import asyncio
import os
import tempfile
import time
import unittest
import uuid
import zipfile
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch


DB_PATH = os.path.join(tempfile.gettempdir(), f"quiz_auth_{uuid.uuid4().hex}.db")
os.environ.update(
    {
        "APP_ENV": "development",
        "DATABASE_URL": f"sqlite:///{DB_PATH}",
        "SECRET_KEY": "test-secret-key-with-at-least-32-characters",
        "WX_MOCK_LOGIN": "true",
        "WX_MOCK_OPENID": "auth-test-user",
        "WX_MOCK_ADMIN": "false",
        "DEBUG": "false",
    }
)

from fastapi.testclient import TestClient
from fastapi import HTTPException

from backend.app.database import SessionLocal, _engine_options, engine
from backend.app.config import settings
from backend.app.main import app
from backend.app.models.question import (
    ExamSubmission,
    GenerateTask,
    GenerationBatch,
    Question,
    QuestionBank,
)
from backend.app.models.user import AnswerRecord, User, UserProgress
from backend.app.routers.auth import _get_wechat_session
from backend.app.routers.upload import _build_bank_data, _ensure_generation_capacity
from backend.app.schemas.question import QuestionCreate
from backend.app.services.question_service import (
    get_user_stats,
    recover_interrupted_tasks,
    run_generate_task,
)
from backend.app.services.doc_parser import _limit_extracted_text, validate_document_file


class AuthFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        engine.dispose()
        if os.path.exists(DB_PATH):
            os.unlink(DB_PATH)

    def login(self):
        response = self.client.post("/api/auth/login", json={"code": "test-code"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_mysql_engine_checks_and_recycles_pooled_connections(self):
        options = _engine_options("mysql+pymysql://user:password@db/quizapp")
        self.assertTrue(options["pool_pre_ping"])
        self.assertEqual(options["pool_recycle"], 1800)
        self.assertNotIn("pool_pre_ping", _engine_options("sqlite:///quiz.db"))

    def create_bank(self, created_by="mock_auth-test-user"):
        db = SessionLocal()
        try:
            bank = QuestionBank(
                name=f"delete-test-{uuid.uuid4().hex[:8]}",
                description="",
                category="test",
                total_count=1,
                status="ready",
                created_by=created_by,
            )
            db.add(bank)
            db.flush()
            question = Question(
                bank_id=bank.id,
                type="single",
                content="test question",
                options=[{"key": "A", "text": "answer"}],
                answer="A",
                order_index=1,
            )
            db.add(question)
            db.commit()
            return bank.id, question.id
        finally:
            db.close()

    def test_bank_owner_can_soft_delete_bank(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()

        db = SessionLocal()
        try:
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(
                id=task_id,
                bank_id=bank_id,
                status="running",
                message="generating",
            ))
            db.add(GenerationBatch(
                task_id=task_id,
                bank_id=bank_id,
                batch_index=0,
                status="running",
                source_text="private source text",
            ))
            db.add(UserProgress(
                user_id=session["user"]["id"],
                bank_id=bank_id,
                total_answered=1,
                correct_count=1,
                starred_ids=[question_id],
            ))
            db.add(AnswerRecord(
                user_id=session["user"]["id"],
                question_id=question_id,
                bank_id=bank_id,
                user_answer="A",
                is_correct=True,
            ))
            db.commit()
        finally:
            db.close()

        banks = self.client.get("/api/banks", headers=headers)
        self.assertEqual(banks.status_code, 200, banks.text)
        item = next(bank for bank in banks.json() if bank["id"] == bank_id)
        self.assertTrue(item["can_delete"])

        response = self.client.delete(f"/api/banks/{bank_id}", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deleted_questions"], 1)
        self.assertEqual(
            self.client.get(f"/api/banks/{bank_id}", headers=headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/api/questions?bank_id={bank_id}", headers=headers).status_code,
            404,
        )

        db = SessionLocal()
        try:
            self.assertEqual(db.get(QuestionBank, bank_id).status, "deleted")
            self.assertEqual(db.get(Question, question_id).status, "deleted")
            self.assertEqual(
                db.query(AnswerRecord).filter(AnswerRecord.bank_id == bank_id).count(),
                1,
            )
            self.assertEqual(
                db.query(UserProgress).filter(UserProgress.bank_id == bank_id).count(),
                1,
            )
            task = db.query(GenerateTask).filter(GenerateTask.bank_id == bank_id).one()
            self.assertEqual(task.status, "failed")
            self.assertEqual(task.message, "题库已删除，生成已停止")
            batch = db.query(GenerationBatch).filter(GenerationBatch.task_id == task.id).one()
            self.assertEqual(batch.status, "failed")
            self.assertIsNone(batch.source_text)
        finally:
            db.close()

    def test_non_owner_cannot_delete_bank(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, _ = self.create_bank(created_by="another-user")

        response = self.client.delete(f"/api/banks/{bank_id}", headers=headers)
        self.assertEqual(response.status_code, 403, response.text)

        db = SessionLocal()
        try:
            self.assertEqual(db.get(QuestionBank, bank_id).status, "ready")
            db.get(QuestionBank, bank_id).status = "deleted"
            db.commit()
        finally:
            db.close()

    def test_admin_can_delete_another_users_bank(self):
        with patch("backend.app.auth.settings.ADMIN_OPENIDS", "mock_auth-test-user"):
            session = self.login()
            headers = {"Authorization": f"Bearer {session['access_token']}"}
            bank_id, _ = self.create_bank(created_by="another-user")
            response = self.client.delete(f"/api/banks/{bank_id}", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)

    def test_login_and_restore_session(self):
        session = self.login()
        self.assertEqual(session["token_type"], "Bearer")
        self.assertGreater(session["expires_in"], 0)
        self.assertNotIn("openid", session["user"])

        response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], session["user"]["id"])

    def test_code2session_collects_server_side_identity(self):
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "openid": "wx-openid",
                    "session_key": "wx-session-key",
                    "unionid": "wx-unionid",
                }

        class FakeClient:
            def __init__(self, timeout):
                captured["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            async def get(self, url, params):
                captured["url"] = url
                captured["params"] = params
                return FakeResponse()

        with (
            patch("backend.app.routers.auth.settings.WX_MOCK_LOGIN", False),
            patch("backend.app.routers.auth.settings.WX_APPID", "test-appid"),
            patch("backend.app.routers.auth.settings.WX_SECRET", "test-secret"),
            patch("backend.app.routers.auth.httpx.AsyncClient", FakeClient),
        ):
            wechat_session = asyncio.run(_get_wechat_session("one-time-code"))

        self.assertEqual(wechat_session.openid, "wx-openid")
        self.assertEqual(wechat_session.unionid, "wx-unionid")
        self.assertEqual(wechat_session.session_key, "wx-session-key")
        self.assertEqual(captured["params"]["js_code"], "one-time-code")
        self.assertEqual(captured["params"]["grant_type"], "authorization_code")

    def test_protected_routes_reject_missing_and_tampered_tokens(self):
        self.assertEqual(self.client.get("/api/banks").status_code, 401)
        self.assertEqual(self.client.get("/api/stats").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/upload/url",
                json={"url": "https://example.com", "bank_name": "unauthorized"},
            ).status_code,
            401,
        )
        response = self.client.get(
            "/api/auth/me", headers={"Authorization": "Bearer invalid.token.value"}
        )
        self.assertEqual(response.status_code, 401)

    def test_upload_validation_rejects_bad_documents_and_private_urls(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bad_file = self.client.post(
            "/api/upload",
            headers=headers,
            files={"file": ("notes.pdf", b"not-a-pdf", "application/pdf")},
            data={"bank_name": "invalid upload"},
        )
        self.assertEqual(bad_file.status_code, 400, bad_file.text)

        private_url = self.client.post(
            "/api/upload/url",
            headers=headers,
            json={"url": "http://127.0.0.1:8000/internal"},
        )
        self.assertEqual(private_url.status_code, 400, private_url.text)

    def test_upload_rejects_when_user_reaches_generation_capacity(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        db = SessionLocal()
        try:
            bank_ids = []
            for index in range(2):
                bank = QuestionBank(
                    name=f"active-generation-{index}-{uuid.uuid4().hex[:8]}",
                    status="pending",
                    created_by="mock_auth-test-user",
                )
                db.add(bank)
                db.flush()
                bank_ids.append(bank.id)
                db.add(GenerateTask(
                    id=uuid.uuid4().hex,
                    bank_id=bank.id,
                    status="running" if index else "pending",
                ))
            db.commit()
        finally:
            db.close()

        response = self.client.post(
            "/api/upload/url",
            headers=headers,
            json={"url": "https://example.com/source", "bank_name": "over-limit"},
        )
        self.assertEqual(response.status_code, 429, response.text)

        db = SessionLocal()
        try:
            db.query(GenerateTask).filter(GenerateTask.bank_id.in_(bank_ids)).update(
                {GenerateTask.status: "failed"},
                synchronize_session=False,
            )
            db.query(QuestionBank).filter(QuestionBank.id.in_(bank_ids)).update(
                {QuestionBank.status: "deleted"},
                synchronize_session=False,
            )
            db.commit()
        finally:
            db.close()

    def test_expired_token_is_rejected(self):
        session = self.login()
        future = time.time() + session["expires_in"] + 1
        with patch("backend.app.auth.time.time", return_value=future):
            response = self.client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {session['access_token']}"},
            )
        self.assertEqual(response.status_code, 401)

    def test_profile_and_user_data_are_bound_to_token(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        response = self.client.put(
            "/api/auth/profile",
            headers=headers,
            json={"user_id": 999999, "nickname": "测试用户", "avatar": ""},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], session["user"]["id"])
        self.assertEqual(response.json()["nickname"], "测试用户")
        self.assertEqual(self.client.get("/api/stats", headers=headers).status_code, 200)

    def test_profile_rejects_external_avatar_url(self):
        session = self.login()
        response = self.client.put(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={"nickname": "测试用户", "avatar": "https://example.com/avatar.png"},
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_avatar_rejects_mismatched_file_signature(self):
        session = self.login()
        response = self.client.post(
            "/api/auth/avatar",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            files={"file": ("avatar.png", b"not-a-png", "image/png")},
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_non_admin_cannot_use_admin_api(self):
        session = self.login()
        response = self.client.get(
            "/api/banks/all",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_question_crud_returns_answers_only_to_admin(self):
        with patch("backend.app.routers.auth.settings.ADMIN_OPENIDS", "mock_auth-test-user"):
            session = self.login()
            headers = {"Authorization": f"Bearer {session['access_token']}"}
            bank_id, question_id = self.create_bank()

            listed = self.client.get(
                f"/api/admin/questions?bank_id={bank_id}", headers=headers
            )
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(listed.json()[0]["answer"], "A")

            updated = self.client.put(
                f"/api/questions/{question_id}",
                headers=headers,
                json={
                    "bank_id": bank_id,
                    "type": "single",
                    "content": "updated question",
                    "options": [{"key": "A", "text": "answer"}],
                    "answer": "A",
                    "explanation": "updated",
                    "tags": ["admin"],
                    "difficulty": 3,
                },
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()["content"], "updated question")

            deleted = self.client.delete(
                f"/api/questions/{question_id}", headers=headers
            )
            self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_practice_payload_cannot_cross_question_banks(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()
        other_bank_id, _ = self.create_bank()

        answer = self.client.post(
            "/api/answer",
            headers=headers,
            json={
                "bank_id": other_bank_id,
                "question_id": question_id,
                "user_answer": "A",
            },
        )
        self.assertEqual(answer.status_code, 400, answer.text)

        star = self.client.post(
            "/api/star",
            headers=headers,
            json={"bank_id": other_bank_id, "question_id": question_id},
        )
        self.assertEqual(star.status_code, 400, star.text)

    def test_public_questions_hide_answers_and_duplicate_answers_are_rejected(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()

        response = self.client.get(
            f"/api/questions?bank_id={bank_id}&limit=10", headers=headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("answer", response.json()[0])

        duplicate = self.client.post(
            "/api/answer",
            headers=headers,
            json={
                "bank_id": bank_id,
                "question_id": question_id,
                "user_answer": "AA",
            },
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.text)

        invalid_mode = self.client.get(
            f"/api/questions?bank_id={bank_id}&mode=unsupported", headers=headers
        )
        self.assertEqual(invalid_mode.status_code, 400, invalid_mode.text)

    def test_exam_session_requires_complete_unique_submission(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()

        started = self.client.post(
            "/api/exam/start",
            headers=headers,
            json={"bank_id": bank_id, "question_count": 1},
        )
        self.assertEqual(started.status_code, 200, started.text)
        payload = started.json()
        self.assertEqual(len(payload["questions"]), 1)
        self.assertNotIn("answer", payload["questions"][0])

        incomplete = self.client.post(
            "/api/exam/submit",
            headers=headers,
            json={"session_id": payload["session_id"], "bank_id": bank_id, "answers": []},
        )
        self.assertEqual(incomplete.status_code, 422)

        submitted = self.client.post(
            "/api/exam/submit",
            headers=headers,
            json={
                "session_id": payload["session_id"],
                "bank_id": bank_id,
                "answers": [{"question_id": question_id, "user_answer": "A"}],
            },
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        first_result = submitted.json()
        again = self.client.post(
            "/api/exam/submit",
            headers=headers,
            json={
                "session_id": payload["session_id"],
                "bank_id": bank_id,
                "answers": [{"question_id": question_id, "user_answer": "A"}],
            },
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json(), first_result)
        db = SessionLocal()
        try:
            self.assertEqual(
                db.query(AnswerRecord).filter(
                    AnswerRecord.user_id == session["user"]["id"],
                    AnswerRecord.bank_id == bank_id,
                    AnswerRecord.mode == "exam",
                ).count(),
                1,
            )
            persisted = db.get(ExamSubmission, payload["session_id"])
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.result, first_result)
        finally:
            db.close()

    def test_exam_accepts_unanswered_questions_as_wrong(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()

        started = self.client.post(
            "/api/exam/start",
            headers=headers,
            json={"bank_id": bank_id, "question_count": 1},
        )
        self.assertEqual(started.status_code, 200, started.text)
        payload = started.json()
        self.assertGreaterEqual(payload["duration_seconds"], 600)
        submitted = self.client.post(
            "/api/exam/submit",
            headers=headers,
            json={
                "session_id": payload["session_id"],
                "bank_id": bank_id,
                "answers": [{"question_id": question_id, "user_answer": ""}],
            },
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["wrong"], 1)
        self.assertEqual(submitted.json()["results"][0]["user_answer"], "")
        db = SessionLocal()
        try:
            db.query(AnswerRecord).filter(
                AnswerRecord.user_id == session["user"]["id"],
                AnswerRecord.bank_id == bank_id,
            ).delete(synchronize_session=False)
            db.query(UserProgress).filter(
                UserProgress.user_id == session["user"]["id"],
                UserProgress.bank_id == bank_id,
            ).delete(synchronize_session=False)
            db.get(QuestionBank, bank_id).status = "deleted"
            db.commit()
        finally:
            db.close()

    def test_bank_tags_require_authentication(self):
        bank_id, _ = self.create_bank()
        response = self.client.get(f"/api/banks/{bank_id}/tags")
        self.assertEqual(response.status_code, 401)

    def test_logout_revokes_existing_token(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)

    def test_account_deletion_anonymizes_user_and_revokes_token(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()
        source_path = os.path.join(settings.UPLOAD_DIR, f"{uuid.uuid4()}.pdf")
        with open(source_path, "wb") as source:
            source.write(b"%PDF-1.4 test source")
        self.addCleanup(
            lambda: os.path.exists(source_path) and os.remove(source_path)
        )
        db = SessionLocal()
        try:
            bank = db.get(QuestionBank, bank_id)
            bank.source_file = source_path
            bank.source_type = "pdf"
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(
                id=task_id,
                bank_id=bank_id,
                status="running",
            ))
            db.add(GenerationBatch(
                task_id=task_id,
                bank_id=bank_id,
                batch_index=0,
                status="running",
                source_text="private account source",
            ))
            db.add(UserProgress(
                user_id=session["user"]["id"],
                bank_id=bank_id,
                total_answered=1,
                starred_ids=[question_id],
            ))
            db.add(AnswerRecord(
                user_id=session["user"]["id"],
                question_id=question_id,
                bank_id=bank_id,
                user_answer="A",
                is_correct=True,
            ))
            db.commit()
        finally:
            db.close()

        response = self.client.delete("/api/auth/account", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(os.path.exists(source_path))
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)
        db = SessionLocal()
        try:
            user = db.get(User, session["user"]["id"])
            self.assertFalse(user.is_active)
            self.assertEqual(user.nickname, "")
            self.assertEqual(db.query(AnswerRecord).filter(AnswerRecord.user_id == user.id).count(), 0)
            self.assertEqual(db.query(UserProgress).filter(UserProgress.user_id == user.id).count(), 0)
            deleted_bank = db.get(QuestionBank, bank_id)
            self.assertEqual(deleted_bank.status, "deleted")
            self.assertEqual(deleted_bank.name, "已删除题库")
            self.assertEqual(deleted_bank.description, "")
            self.assertEqual(deleted_bank.category, "")
            self.assertEqual(deleted_bank.source_file, "")
            self.assertEqual(deleted_bank.source_type, "")
            self.assertEqual(deleted_bank.total_count, 0)
            deleted_question = db.get(Question, question_id)
            self.assertEqual(deleted_question.status, "deleted")
            self.assertEqual(deleted_question.content, "")
            self.assertEqual(deleted_question.options, [])
            deleted_batch = db.query(GenerationBatch).filter(
                GenerationBatch.task_id == task_id,
            ).one()
            self.assertEqual(deleted_batch.status, "failed")
            self.assertIsNone(deleted_batch.source_text)
            self.assertEqual(deleted_question.answer, "")
            self.assertEqual(deleted_question.explanation, "")
            self.assertEqual(deleted_question.tags, [])
        finally:
            db.close()

    def test_admin_configuration_can_be_revoked(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        with patch("backend.app.auth.settings.ADMIN_OPENIDS", "mock_auth-test-user"):
            self.assertTrue(self.client.get("/api/auth/me", headers=headers).json()["is_admin"])
            self.assertEqual(self.client.get("/api/banks/all", headers=headers).status_code, 200)
        with patch("backend.app.auth.settings.ADMIN_OPENIDS", ""):
            self.assertFalse(self.client.get("/api/auth/me", headers=headers).json()["is_admin"])
            self.assertEqual(self.client.get("/api/banks/all", headers=headers).status_code, 403)

    def test_ready_banks_are_private_to_owner_but_visible_to_admin(self):
        owner = self.login()
        owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
        bank_id, question_id = self.create_bank()
        db = SessionLocal()
        try:
            db.get(QuestionBank, bank_id).category = f"private-{uuid.uuid4().hex}"
            private_category = db.get(QuestionBank, bank_id).category
            db.commit()
        finally:
            db.close()

        with patch("backend.app.routers.auth.settings.WX_MOCK_OPENID", "other-user"):
            other = self.login()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}

        listed = self.client.get("/api/banks?limit=100", headers=other_headers)
        self.assertNotIn(bank_id, {item["id"] for item in listed.json()})
        categories = self.client.get("/api/banks/categories", headers=other_headers)
        self.assertNotIn(private_category, categories.json())
        self.assertEqual(self.client.get(f"/api/banks/{bank_id}", headers=other_headers).status_code, 404)
        self.assertEqual(self.client.get(f"/api/questions?bank_id={bank_id}", headers=other_headers).status_code, 404)
        self.assertEqual(self.client.get(f"/api/questions/{question_id}", headers=other_headers).status_code, 404)
        self.assertEqual(
            self.client.post(
                "/api/exam/start",
                headers=other_headers,
                json={"bank_id": bank_id, "question_count": 1},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/api/answer",
                headers=other_headers,
                json={"bank_id": bank_id, "question_id": question_id, "user_answer": "A"},
            ).status_code,
            400,
        )

        with patch("backend.app.auth.settings.ADMIN_OPENIDS", "mock_other-user"):
            self.assertEqual(self.client.get(f"/api/banks/{bank_id}", headers=other_headers).status_code, 200)

        self.assertEqual(self.client.delete(f"/api/banks/{bank_id}", headers=owner_headers).status_code, 200)

    def test_document_structure_limits_reject_archive_bombs_and_long_pdfs(self):
        docx_path = os.path.join(tempfile.gettempdir(), f"bomb-{uuid.uuid4().hex}.docx")
        pdf_path = os.path.join(tempfile.gettempdir(), f"pages-{uuid.uuid4().hex}.pdf")
        self.addCleanup(lambda: os.path.exists(docx_path) and os.remove(docx_path))
        self.addCleanup(lambda: os.path.exists(pdf_path) and os.remove(pdf_path))

        with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "A" * (2 * 1024 * 1024))
        with self.assertRaisesRegex(ValueError, "压缩比异常"):
            validate_document_file(docx_path, "word")

        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_blank_page(width=100, height=100)
        with open(pdf_path, "wb") as target:
            writer.write(target)
        with patch("backend.app.services.doc_parser.settings.MAX_PDF_PAGES", 1):
            with self.assertRaisesRegex(ValueError, "页数不能超过"):
                validate_document_file(pdf_path, "pdf")

    def test_upload_metadata_and_extracted_text_limits(self):
        bank_data = _build_bank_data("   ", "fallback name", " description ", " category ")
        self.assertEqual(bank_data.name, "fallback name")
        self.assertEqual(bank_data.description, "description")
        self.assertEqual(bank_data.category, "category")

        with self.assertRaises(HTTPException) as metadata_error:
            _build_bank_data("x" * 201, "fallback", "", "")
        self.assertEqual(metadata_error.exception.status_code, 400)

        with patch("backend.app.services.doc_parser.settings.MAX_EXTRACTED_TEXT_CHARS", 10):
            self.assertEqual(_limit_extracted_text("1234567890"), "1234567890")
            with self.assertRaisesRegex(ValueError, "文本超过处理上限"):
                _limit_extracted_text("12345678901")

    def test_progress_cannot_move_backwards_without_explicit_reset(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, _ = self.create_bank()
        for position in (10, 3):
            response = self.client.post(
                "/api/progress",
                headers=headers,
                json={"bank_id": bank_id, "position": position},
            )
            self.assertEqual(response.status_code, 200, response.text)
        progress = self.client.get(f"/api/progress/{bank_id}", headers=headers)
        self.assertEqual(progress.json()["last_position"], 10)

        reset = self.client.post(
            "/api/progress",
            headers=headers,
            json={"bank_id": bank_id, "position": 0, "reset": True},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        progress = self.client.get(f"/api/progress/{bank_id}", headers=headers)
        self.assertEqual(progress.json()["last_position"], 0)
        self.client.delete(f"/api/banks/{bank_id}", headers=headers)

    def test_profile_cannot_claim_another_server_avatar(self):
        session = self.login()
        response = self.client.put(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={
                "nickname": "测试用户",
                "avatar": f"/uploads/avatars/{uuid.uuid4().hex}.png",
            },
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_restart_recovery_fails_recent_tasks_and_hides_pending_bank(self):
        db = SessionLocal()
        try:
            bank = QuestionBank(name="interrupted", status="pending", created_by="owner")
            db.add(bank)
            db.flush()
            task = GenerateTask(id=uuid.uuid4().hex, bank_id=bank.id, status="pending")
            db.add(task)
            db.commit()
            task_id = task.id
            bank_id = bank.id
            recovered = recover_interrupted_tasks(db)
            self.assertEqual(recovered, [])
            self.assertEqual(db.get(GenerateTask, task_id).status, "failed")
            self.assertEqual(db.get(QuestionBank, bank_id).status, "deleted")
        finally:
            db.close()

    def test_pending_bank_is_hidden_from_regular_users(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        db = SessionLocal()
        try:
            bank = QuestionBank(name="pending", status="pending", created_by="another-user")
            db.add(bank)
            db.flush()
            question = Question(
                bank_id=bank.id,
                type="single",
                content="pending question",
                options=[{"key": "A", "text": "answer"}],
                answer="A",
            )
            db.add(question)
            db.commit()
            bank_id, question_id = bank.id, question.id
        finally:
            db.close()

        self.assertEqual(self.client.get(f"/api/banks/{bank_id}", headers=headers).status_code, 404)
        self.assertEqual(self.client.get(f"/api/banks/{bank_id}/tags", headers=headers).status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/questions?bank_id={bank_id}", headers=headers).status_code,
            404,
        )
        self.assertEqual(self.client.get(f"/api/questions/{question_id}", headers=headers).status_code, 404)
        self.assertEqual(
            self.client.post(
                "/api/answer",
                headers=headers,
                json={"bank_id": bank_id, "question_id": question_id, "user_answer": "A"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/progress",
                headers=headers,
                json={"bank_id": bank_id, "position": 0},
            ).status_code,
            400,
        )

    def test_question_create_validates_answer_and_type(self):
        with self.assertRaises(ValueError):
            QuestionCreate(
                bank_id=1,
                type="unsupported",
                content="question",
                options=[{"key": "A", "text": "answer"}],
                answer="A",
            )
        with self.assertRaises(ValueError):
            QuestionCreate(
                bank_id=1,
                type="single",
                content="question",
                options=[{"key": "A", "text": "answer"}],
                answer="B",
            )

    def test_latest_wrong_attempt_is_resolved_by_correct_retry(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()
        db = SessionLocal()
        try:
            question = db.get(Question, question_id)
            question.options = [
                {"key": "A", "text": "correct"},
                {"key": "B", "text": "wrong"},
            ]
            question.tags = ["retry"]
            db.commit()
        finally:
            db.close()

        wrong = self.client.post(
            "/api/answer",
            headers=headers,
            json={"bank_id": bank_id, "question_id": question_id, "user_answer": "B"},
        )
        self.assertEqual(wrong.status_code, 200, wrong.text)
        self.assertEqual(len(self.client.get("/api/wrong-questions", headers=headers).json()), 1)
        review = self.client.get(
            f"/api/review-questions?bank_id={bank_id}&source=wrong",
            headers=headers,
        )
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(review.json()[0]["answer"], "A")

        correct = self.client.post(
            "/api/answer",
            headers=headers,
            json={"bank_id": bank_id, "question_id": question_id, "user_answer": "A"},
        )
        self.assertEqual(correct.status_code, 200, correct.text)
        self.assertEqual(self.client.get("/api/wrong-questions", headers=headers).json(), [])
        self.assertEqual(
            self.client.get(f"/api/questions/count?bank_id={bank_id}&mode=wrong", headers=headers).json()["total"],
            0,
        )

    def test_wrong_question_cursor_does_not_skip_after_resolution(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, first_id = self.create_bank()
        db = SessionLocal()
        try:
            first = db.get(Question, first_id)
            first.options = [
                {"key": "A", "text": "correct"},
                {"key": "B", "text": "wrong"},
            ]
            for index in range(2):
                db.add(Question(
                    bank_id=bank_id,
                    type="single",
                    content=f"cursor question {index}",
                    options=[
                        {"key": "A", "text": "correct"},
                        {"key": "B", "text": "wrong"},
                    ],
                    answer="A",
                    order_index=index + 2,
                ))
            db.commit()
            question_ids = [
                question_id for (question_id,) in db.query(Question.id).filter(
                    Question.bank_id == bank_id,
                ).order_by(Question.id).all()
            ]
        finally:
            db.close()

        for question_id in question_ids:
            response = self.client.post(
                "/api/answer",
                headers=headers,
                json={"bank_id": bank_id, "question_id": question_id, "user_answer": "B"},
            )
            self.assertEqual(response.status_code, 200, response.text)

        first_page = self.client.get(
            f"/api/questions?bank_id={bank_id}&mode=wrong&limit=1",
            headers=headers,
        )
        self.assertEqual(first_page.status_code, 200, first_page.text)
        cursor_id = first_page.json()[0]["id"]
        self.assertEqual(cursor_id, question_ids[0])

        resolved = self.client.post(
            "/api/answer",
            headers=headers,
            json={"bank_id": bank_id, "question_id": cursor_id, "user_answer": "A"},
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)

        next_page = self.client.get(
            f"/api/questions?bank_id={bank_id}&mode=wrong&after_id={cursor_id}&limit=1",
            headers=headers,
        )
        self.assertEqual(next_page.status_code, 200, next_page.text)
        self.assertEqual([item["id"] for item in next_page.json()], [question_ids[1]])

    def test_deleted_bank_is_excluded_from_current_review_stats(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()
        db = SessionLocal()
        try:
            question = db.get(Question, question_id)
            question.options = [
                {"key": "A", "text": "correct"},
                {"key": "B", "text": "wrong"},
            ]
            db.commit()
        finally:
            db.close()

        self.assertEqual(self.client.post(
            "/api/answer",
            headers=headers,
            json={"bank_id": bank_id, "question_id": question_id, "user_answer": "B"},
        ).status_code, 200)
        self.assertEqual(self.client.post(
            "/api/star",
            headers=headers,
            json={"bank_id": bank_id, "question_id": question_id},
        ).status_code, 200)
        before = self.client.get("/api/stats", headers=headers).json()

        deleted = self.client.delete(f"/api/banks/{bank_id}", headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        after = self.client.get("/api/stats", headers=headers).json()
        self.assertEqual(after["wrong_count"], before["wrong_count"] - 1)
        self.assertEqual(after["starred_count"], before["starred_count"] - 1)

    def test_cross_bank_wrong_and_review_queries_include_every_bank(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        baseline = self.client.get(
            "/api/questions/count?mode=wrong",
            headers=headers,
        ).json()["total"]
        pairs = [self.create_bank(), self.create_bank()]
        db = SessionLocal()
        try:
            for _, question_id in pairs:
                question = db.get(Question, question_id)
                question.options = [
                    {"key": "A", "text": "correct"},
                    {"key": "B", "text": "wrong"},
                ]
            db.commit()
        finally:
            db.close()

        for bank_id, question_id in pairs:
            response = self.client.post(
                "/api/answer",
                headers=headers,
                json={"bank_id": bank_id, "question_id": question_id, "user_answer": "B"},
            )
            self.assertEqual(response.status_code, 200, response.text)

        questions = self.client.get(
            "/api/questions?mode=wrong&limit=100",
            headers=headers,
        )
        self.assertEqual(questions.status_code, 200, questions.text)
        by_id = {item["id"]: item for item in questions.json()}
        for bank_id, question_id in pairs:
            self.assertEqual(by_id[question_id]["bank_id"], bank_id)
            self.assertNotIn("answer", by_id[question_id])
        self.assertEqual(
            self.client.get("/api/questions/count?mode=wrong", headers=headers).json()["total"],
            baseline + 2,
        )

        review = self.client.get(
            "/api/review-questions?source=wrong",
            headers=headers,
        )
        self.assertEqual(review.status_code, 200, review.text)
        review_by_id = {item["id"]: item for item in review.json()}
        for _, question_id in pairs:
            self.assertEqual(review_by_id[question_id]["answer"], "A")
        first_review_page = self.client.get(
            "/api/review-questions?source=wrong&skip=0&limit=1",
            headers=headers,
        )
        second_review_page = self.client.get(
            "/api/review-questions?source=wrong&skip=1&limit=1",
            headers=headers,
        )
        self.assertEqual(first_review_page.status_code, 200, first_review_page.text)
        self.assertEqual(second_review_page.status_code, 200, second_review_page.text)
        self.assertEqual(len(first_review_page.json()), 1)
        self.assertEqual(len(second_review_page.json()), 1)
        self.assertNotEqual(first_review_page.json()[0]["id"], second_review_page.json()[0]["id"])

        for bank_id, question_id in pairs:
            starred = self.client.post(
                "/api/star",
                headers=headers,
                json={"bank_id": bank_id, "question_id": question_id},
            )
            self.assertEqual(starred.status_code, 200, starred.text)
            self.assertTrue(starred.json()["is_starred"])

        starred_questions = self.client.get(
            "/api/questions?mode=starred&limit=100",
            headers=headers,
        )
        self.assertEqual(starred_questions.status_code, 200, starred_questions.text)
        starred_by_id = {item["id"]: item for item in starred_questions.json()}
        for bank_id, question_id in pairs:
            self.assertEqual(starred_by_id[question_id]["bank_id"], bank_id)
            self.assertNotIn("answer", starred_by_id[question_id])

        starred_review = self.client.get(
            "/api/review-questions?source=starred",
            headers=headers,
        )
        self.assertEqual(starred_review.status_code, 200, starred_review.text)
        starred_review_by_id = {item["id"]: item for item in starred_review.json()}
        for _, question_id in pairs:
            self.assertEqual(starred_review_by_id[question_id]["answer"], "A")

        ordered_pairs = sorted(pairs, key=lambda pair: pair[1])
        cursor_bank_id, cursor_question_id = ordered_pairs[0]
        _, remaining_question_id = ordered_pairs[1]
        unstarred = self.client.post(
            "/api/star",
            headers=headers,
            json={"bank_id": cursor_bank_id, "question_id": cursor_question_id},
        )
        self.assertEqual(unstarred.status_code, 200, unstarred.text)
        self.assertFalse(unstarred.json()["is_starred"])
        cursor_page = self.client.get(
            f"/api/review-questions?source=starred&after_id={cursor_question_id}&limit=1",
            headers=headers,
        )
        self.assertEqual(cursor_page.status_code, 200, cursor_page.text)
        self.assertEqual(
            [item["id"] for item in cursor_page.json()],
            [remaining_question_id],
        )

        no_bank = self.client.get("/api/questions?mode=sequential", headers=headers)
        self.assertEqual(no_bank.status_code, 400, no_bank.text)

        for bank_id, question_id in pairs:
            self.client.post(
                "/api/answer",
                headers=headers,
                json={"bank_id": bank_id, "question_id": question_id, "user_answer": "A"},
            )
        db = SessionLocal()
        try:
            for bank_id, _ in pairs:
                db.get(QuestionBank, bank_id).status = "deleted"
            db.commit()
        finally:
            db.close()

    def test_random_seed_pagination_is_stable_without_duplicates(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        db = SessionLocal()
        try:
            bank = QuestionBank(
                name=f"random-{uuid.uuid4().hex[:8]}",
                status="ready",
                created_by="mock_auth-test-user",
            )
            db.add(bank)
            db.flush()
            db.add_all([
                Question(
                    bank_id=bank.id,
                    type="single",
                    content=f"random question {index}",
                    options=[{"key": "A", "text": "answer"}],
                    answer="A",
                    order_index=index,
                )
                for index in range(150)
            ])
            db.commit()
            bank_id = bank.id
        finally:
            db.close()

        first = self.client.get(
            "/api/questions",
            params={"bank_id": bank_id, "mode": "random", "skip": 0, "limit": 100, "seed": 42},
            headers=headers,
        )
        second = self.client.get(
            "/api/questions",
            params={"bank_id": bank_id, "mode": "random", "skip": 100, "limit": 100, "seed": 42},
            headers=headers,
        )
        repeat = self.client.get(
            "/api/questions",
            params={"bank_id": bank_id, "mode": "random", "skip": 0, "limit": 100, "seed": 42},
            headers=headers,
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(repeat.status_code, 200, repeat.text)
        first_ids = [item["id"] for item in first.json()]
        second_ids = [item["id"] for item in second.json()]
        self.assertEqual(len(first_ids), 100)
        self.assertEqual(len(second_ids), 50)
        self.assertEqual(len(set(first_ids + second_ids)), 150)
        self.assertEqual(first_ids, [item["id"] for item in repeat.json()])

    def test_daily_question_and_study_report_hide_answer(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()
        db = SessionLocal()
        try:
            db.get(Question, question_id).tags = ["report-tag"]
            db.commit()
        finally:
            db.close()

        daily = self.client.get(f"/api/daily-question?bank_id={bank_id}", headers=headers)
        self.assertEqual(daily.status_code, 200, daily.text)
        self.assertEqual(daily.json()["bank_id"], bank_id)
        self.assertNotIn("answer", daily.json()["question"])

        answer = self.client.post(
            "/api/answer",
            headers=headers,
            json={"bank_id": bank_id, "question_id": question_id, "user_answer": "B"},
        )
        self.assertEqual(answer.status_code, 400)
        report = self.client.get("/api/study-report?days=7", headers=headers)
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(len(report.json()["daily"]), 7)
        self.assertIn("weak_tags", report.json())

    def test_exam_start_accepts_tag_and_difficulty_filters(self):
        session = self.login()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        bank_id, question_id = self.create_bank()
        db = SessionLocal()
        try:
            question = db.get(Question, question_id)
            question.tags = ["chapter_1"]
            question.difficulty = 4
            db.add(Question(
                bank_id=bank_id,
                type="single",
                content="tag wildcard control",
                options=[{"key": "A", "text": "answer"}],
                answer="A",
                tags=["chapterA1"],
                difficulty=4,
                order_index=2,
            ))
            db.commit()
        finally:
            db.close()
        filtered = self.client.get(
            f"/api/questions?bank_id={bank_id}&tag=chapter_1&limit=100",
            headers=headers,
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual([item["id"] for item in filtered.json()], [question_id])
        count = self.client.get(
            f"/api/questions/count?bank_id={bank_id}&tag=chapter_1",
            headers=headers,
        )
        self.assertEqual(count.status_code, 200, count.text)
        self.assertEqual(count.json()["total"], 1)
        response = self.client.post(
            "/api/exam/start",
            headers=headers,
            json={"bank_id": bank_id, "question_count": 1, "tag": "chapter_1", "difficulty": 4},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()["questions"]], [question_id])

    def test_stats_streak_and_stale_task_recovery(self):
        db = SessionLocal()
        try:
            user = User(openid=f"stats-{uuid.uuid4().hex}")
            db.add(user)
            db.flush()
            now = datetime.utcnow()
            db.add_all([
                AnswerRecord(
                    user_id=user.id,
                    question_id=1,
                    bank_id=1,
                    user_answer="A",
                    is_correct=True,
                    answered_at=now,
                ),
                AnswerRecord(
                    user_id=user.id,
                    question_id=2,
                    bank_id=1,
                    user_answer="A",
                    is_correct=False,
                    answered_at=now - timedelta(days=1),
                ),
            ])
            stale = GenerateTask(
                id=uuid.uuid4().hex,
                status="running",
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
            )
            db.add(stale)
            db.commit()
            self.assertEqual(get_user_stats(db, user.id)["streak_days"], 2)
            self.assertEqual(recover_interrupted_tasks(db), [])
            db.refresh(stale)
            self.assertEqual(stale.status, "failed")
        finally:
            db.close()

    def test_user_progress_unique_constraint_is_declared(self):
        constraints = UserProgress.__table__.constraints
        self.assertIn("uq_user_progress_user_bank", {c.name for c in constraints})

    def test_generation_with_no_valid_questions_is_failed_and_hidden(self):
        session = self.login()
        bank_id, _ = self.create_bank(created_by="mock_auth-test-user")
        db = SessionLocal()
        try:
            bank = db.get(QuestionBank, bank_id)
            bank.status = "pending"
            db.query(Question).filter(Question.bank_id == bank_id).delete(
                synchronize_session=False
            )
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(
                id=task_id,
                bank_id=bank_id,
                status="pending",
                message="queued",
            ))
            db.commit()
        finally:
            db.close()

        async def parsed_document(*args, **kwargs):
            return "This document has enough text to be split into a valid source chunk."

        with (
            patch(
                "backend.app.services.generation_service.parse_document",
                new=parsed_document,
            ),
            patch(
                "backend.app.services.generation_service.generate_from_chunk",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "backend.app.services.generation_service.settings.GENERATION_BATCH_MAX_RETRIES",
                0,
            ),
        ):
            asyncio.run(
                run_generate_task(
                    task_id=task_id,
                    bank_id=bank_id,
                    file_path="https://example.com/source",
                    source_type="url",
                    db_factory=SessionLocal,
                )
            )

        db = SessionLocal()
        try:
            task = db.get(GenerateTask, task_id)
            bank = db.get(QuestionBank, bank_id)
            self.assertEqual(task.status, "failed")
            self.assertEqual(task.error, "生成失败，请更换资料或稍后重试")
            self.assertEqual(bank.status, "deleted")
        finally:
            db.close()

    def test_generation_frequency_and_daily_limits_are_persistent(self):
        db = SessionLocal()
        try:
            user = User(openid=f"quota-{uuid.uuid4().hex}")
            db.add(user)
            db.flush()
            for index in range(2):
                bank = QuestionBank(
                    name=f"quota-{index}",
                    status="deleted",
                    created_by=user.openid,
                )
                db.add(bank)
                db.flush()
                db.add(GenerateTask(
                    id=uuid.uuid4().hex,
                    bank_id=bank.id,
                    status="done",
                    created_at=datetime.utcnow(),
                ))
            db.commit()

            with (
                patch("backend.app.routers.upload.settings.MAX_DAILY_GENERATION_TASKS", 2),
                patch("backend.app.routers.upload.settings.MIN_GENERATION_INTERVAL_SECONDS", 0),
                self.assertRaises(HTTPException) as daily_error,
            ):
                _ensure_generation_capacity(db, user)
            self.assertEqual(daily_error.exception.status_code, 429)

            with (
                patch("backend.app.routers.upload.settings.MAX_DAILY_GENERATION_TASKS", 100),
                patch("backend.app.routers.upload.settings.MIN_GENERATION_INTERVAL_SECONDS", 60),
                self.assertRaises(HTTPException) as frequency_error,
            ):
                _ensure_generation_capacity(db, user)
            self.assertEqual(frequency_error.exception.status_code, 429)
        finally:
            db.close()

    def test_generation_success_marks_pending_bank_ready(self):
        db = SessionLocal()
        try:
            bank = QuestionBank(
                name=f"generation-success-{uuid.uuid4().hex[:8]}",
                status="pending",
                created_by="mock_auth-test-user",
                total_count=0,
            )
            db.add(bank)
            db.flush()
            bank_id = bank.id
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(
                id=task_id,
                bank_id=bank_id,
                status="pending",
                message="queued",
            ))
            db.commit()
        finally:
            db.close()

        generated = [{
            "bank_id": bank_id,
            "type": "single",
            "content": "generated question",
            "options": [{"key": "A", "text": "answer"}],
            "answer": "A",
            "explanation": "generated explanation",
            "tags": ["generated"],
            "difficulty": 2,
        }]

        async def parsed_document(*args, **kwargs):
            return "source text"

        async def generated_questions(*args, **kwargs):
            callback = kwargs.get("progress_callback")
            if callback:
                await callback(1, 1, 1, "generating")
            return generated

        with (
            patch(
                "backend.app.services.generation_service.parse_document",
                new=parsed_document,
            ),
            patch(
                "backend.app.services.generation_service.split_text_into_chunks",
                return_value=["source text"],
            ),
            patch(
                "backend.app.services.generation_service.generate_from_chunk",
                new=AsyncMock(return_value=generated),
            ),
            patch(
                "backend.app.services.generation_service.classify_questions_tags",
                new=AsyncMock(side_effect=lambda questions: questions),
            ),
        ):
            asyncio.run(
                run_generate_task(
                    task_id=task_id,
                    bank_id=bank_id,
                    file_path="https://example.com/source",
                    source_type="url",
                    db_factory=SessionLocal,
                )
            )

        db = SessionLocal()
        try:
            task = db.get(GenerateTask, task_id)
            bank = db.get(QuestionBank, bank_id)
            self.assertEqual(task.status, "done")
            self.assertEqual(task.progress, 100)
            self.assertEqual(bank.status, "ready")
            self.assertEqual(bank.total_count, 1)
            self.assertEqual(
                db.query(Question).filter(Question.bank_id == bank_id).count(),
                1,
            )
            batch = db.query(GenerationBatch).filter(
                GenerationBatch.task_id == task_id,
            ).one()
            self.assertEqual(batch.status, "done")
            self.assertEqual(batch.generated_count, 1)
            self.assertIsNone(batch.source_text)
            bank.status = "deleted"
            db.commit()
        finally:
            db.close()

    def test_generation_timeout_marks_task_failed(self):
        db = SessionLocal()
        try:
            bank = QuestionBank(
                name=f"generation-timeout-{uuid.uuid4().hex[:8]}",
                status="pending",
                created_by="mock_auth-test-user",
            )
            db.add(bank)
            db.flush()
            bank_id = bank.id
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(id=task_id, bank_id=bank_id, status="pending"))
            db.commit()
        finally:
            db.close()

        async def slow_document(*args, **kwargs):
            await asyncio.sleep(0.05)
            return "source text"

        with (
            patch(
                "backend.app.services.generation_service.parse_document",
                new=slow_document,
            ),
            patch(
                "backend.app.services.generation_service.settings.GENERATION_TIMEOUT_SECONDS",
                0.01,
            ),
        ):
            asyncio.run(
                run_generate_task(
                    task_id=task_id,
                    bank_id=bank_id,
                    file_path="https://example.com/source",
                    source_type="url",
                    db_factory=SessionLocal,
                )
            )

        db = SessionLocal()
        try:
            task = db.get(GenerateTask, task_id)
            bank = db.get(QuestionBank, bank_id)
            self.assertEqual(task.status, "failed")
            self.assertEqual(task.error, "生成失败，请更换资料或稍后重试")
            self.assertEqual(task.message, "出题达到时间上限")
            self.assertEqual(bank.status, "deleted")
        finally:
            db.close()

    def test_generation_batch_unique_constraint_is_declared(self):
        constraints = GenerationBatch.__table__.constraints
        self.assertIn(
            "uq_generation_batches_task_index",
            {constraint.name for constraint in constraints},
        )

    def test_running_generation_batch_is_recovered_for_requeue(self):
        db = SessionLocal()
        try:
            bank = QuestionBank(
                name=f"recoverable-{uuid.uuid4().hex[:8]}",
                status="pending",
                source_file="https://example.com/source",
                source_type="url",
                created_by="recover-owner",
            )
            db.add(bank)
            db.flush()
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(
                id=task_id,
                bank_id=bank.id,
                status="running",
                total_chunks=1,
            ))
            db.add(GenerationBatch(
                task_id=task_id,
                bank_id=bank.id,
                batch_index=0,
                status="running",
                source_text="recoverable text",
            ))
            db.commit()

            self.assertEqual(recover_interrupted_tasks(db), [task_id])
            task = db.get(GenerateTask, task_id)
            batch = db.query(GenerationBatch).filter(
                GenerationBatch.task_id == task_id,
            ).one()
            self.assertEqual(task.status, "running")
            self.assertEqual(batch.status, "running")
            self.assertEqual(batch.source_text, "recoverable text")

            task.status = "failed"
            bank.status = "deleted"
            batch.status = "failed"
            batch.source_text = None
            db.commit()
        finally:
            db.close()

    def test_generation_partial_success_keeps_incremental_questions(self):
        db = SessionLocal()
        try:
            bank = QuestionBank(
                name=f"partial-{uuid.uuid4().hex[:8]}",
                status="pending",
                source_file="https://example.com/source",
                source_type="url",
                created_by="partial-owner",
            )
            db.add(bank)
            db.flush()
            bank_id = bank.id
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(id=task_id, bank_id=bank_id, status="pending"))
            db.commit()
        finally:
            db.close()

        generated = [{
            "type": "single",
            "content": "incrementally persisted question",
            "options": [{"key": "A", "text": "answer"}],
            "answer": "A",
            "explanation": "explanation",
            "tags": ["tag"],
            "difficulty": 2,
        }]

        async def parsed_document(*args, **kwargs):
            return "source text"

        async def generate_by_chunk(chunk, **kwargs):
            return generated if chunk == "good chunk" else []

        with (
            patch(
                "backend.app.services.generation_service.parse_document",
                new=parsed_document,
            ),
            patch(
                "backend.app.services.generation_service.split_text_into_chunks",
                return_value=["good chunk", "bad chunk"],
            ),
            patch(
                "backend.app.services.generation_service.generate_from_chunk",
                new=generate_by_chunk,
            ),
            patch(
                "backend.app.services.generation_service.classify_questions_tags",
                new=AsyncMock(side_effect=lambda questions: questions),
            ),
            patch(
                "backend.app.services.generation_service.settings.GENERATION_BATCH_MAX_RETRIES",
                0,
            ),
            patch(
                "backend.app.services.generation_service.settings.GENERATION_CHUNK_CONCURRENCY",
                1,
            ),
            patch(
                "backend.app.services.generation_service.settings.MIN_PARTIAL_GENERATED_QUESTIONS",
                1,
            ),
        ):
            asyncio.run(run_generate_task(task_id=task_id, db_factory=SessionLocal))

        db = SessionLocal()
        try:
            task = db.get(GenerateTask, task_id)
            bank = db.get(QuestionBank, bank_id)
            batches = db.query(GenerationBatch).filter(
                GenerationBatch.task_id == task_id,
            ).order_by(GenerationBatch.batch_index).all()
            self.assertEqual(task.status, "done")
            self.assertTrue(task.partial_success)
            self.assertEqual(task.failed_chunks, 1)
            self.assertEqual(task.generated_count, 1)
            self.assertEqual(bank.status, "ready")
            self.assertEqual([batch.status for batch in batches], ["done", "failed"])
            self.assertTrue(all(batch.source_text is None for batch in batches))
            bank.status = "deleted"
            db.commit()
        finally:
            db.close()

    def test_completed_generation_is_idempotent_on_redelivery(self):
        db = SessionLocal()
        try:
            bank = QuestionBank(
                name=f"redelivery-{uuid.uuid4().hex[:8]}",
                status="ready",
                total_count=1,
                created_by="redelivery-owner",
            )
            db.add(bank)
            db.flush()
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(
                id=task_id,
                bank_id=bank.id,
                status="done",
                total_chunks=1,
                processed_chunks=1,
                generated_count=1,
            ))
            db.add(GenerationBatch(
                task_id=task_id,
                bank_id=bank.id,
                batch_index=0,
                status="done",
                source_text=None,
                generated_count=1,
            ))
            db.commit()
            bank_id = bank.id
        finally:
            db.close()

        generate = AsyncMock(return_value=[])
        with patch(
            "backend.app.services.generation_service.generate_from_chunk",
            new=generate,
        ):
            asyncio.run(run_generate_task(task_id=task_id, db_factory=SessionLocal))
        generate.assert_not_awaited()

        db = SessionLocal()
        try:
            self.assertEqual(db.get(GenerateTask, task_id).status, "done")
            db.get(QuestionBank, bank_id).status = "deleted"
            db.commit()
        finally:
            db.close()

    def test_partial_result_below_threshold_is_hidden(self):
        from backend.app.services.generation_service import _finalize_generation

        db = SessionLocal()
        try:
            bank = QuestionBank(
                name=f"below-threshold-{uuid.uuid4().hex[:8]}",
                status="pending",
                created_by="threshold-owner",
            )
            db.add(bank)
            db.flush()
            bank_id = bank.id
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(
                id=task_id,
                bank_id=bank_id,
                status="running",
                total_chunks=2,
            ))
            db.add_all([
                GenerationBatch(
                    task_id=task_id,
                    bank_id=bank_id,
                    batch_index=0,
                    status="done",
                    generated_count=1,
                ),
                GenerationBatch(
                    task_id=task_id,
                    bank_id=bank_id,
                    batch_index=1,
                    status="failed",
                    generated_count=0,
                ),
                Question(
                    bank_id=bank_id,
                    type="single",
                    content="insufficient partial question",
                    options=[{"key": "A", "text": "answer"}],
                    answer="A",
                ),
            ])
            db.commit()
        finally:
            db.close()

        with patch(
            "backend.app.services.generation_service.settings.MIN_PARTIAL_GENERATED_QUESTIONS",
            2,
        ):
            _finalize_generation(SessionLocal, task_id, bank_id)

        db = SessionLocal()
        try:
            task = db.get(GenerateTask, task_id)
            question = db.query(Question).filter(Question.bank_id == bank_id).one()
            self.assertEqual(task.status, "failed")
            self.assertFalse(task.partial_success)
            self.assertEqual(db.get(QuestionBank, bank_id).status, "deleted")
            self.assertEqual(question.status, "deleted")
        finally:
            db.close()

    def test_batch_and_questions_rollback_together(self):
        from backend.app.services.generation_service import _persist_batch_questions

        db = SessionLocal()
        try:
            bank = QuestionBank(
                name=f"atomic-{uuid.uuid4().hex[:8]}",
                status="pending",
                created_by="atomic-owner",
            )
            db.add(bank)
            db.flush()
            bank_id = bank.id
            task_id = uuid.uuid4().hex
            db.add(GenerateTask(
                id=task_id,
                bank_id=bank_id,
                status="running",
                total_chunks=1,
            ))
            db.add(GenerationBatch(
                task_id=task_id,
                bank_id=bank_id,
                batch_index=0,
                status="running",
                source_text="atomic source",
            ))
            db.commit()
            batch_id = db.query(GenerationBatch.id).filter(
                GenerationBatch.task_id == task_id,
            ).scalar()
        finally:
            db.close()

        question = [{
            "type": "single",
            "content": "must roll back",
            "options": [{"key": "A", "text": "answer"}],
            "answer": "A",
            "explanation": "",
            "tags": [],
            "difficulty": 1,
        }]
        with (
            patch(
                "backend.app.services.generation_service._update_task_aggregate",
                side_effect=RuntimeError("forced rollback"),
            ),
            self.assertRaises(RuntimeError),
        ):
            _persist_batch_questions(
                SessionLocal,
                task_id,
                bank_id,
                batch_id,
                question,
            )

        db = SessionLocal()
        try:
            batch = db.get(GenerationBatch, batch_id)
            self.assertEqual(batch.status, "running")
            self.assertEqual(batch.source_text, "atomic source")
            self.assertEqual(
                db.query(Question).filter(Question.bank_id == bank_id).count(),
                0,
            )
            batch.status = "failed"
            batch.source_text = None
            db.get(GenerateTask, task_id).status = "failed"
            db.get(QuestionBank, bank_id).status = "deleted"
            db.commit()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
