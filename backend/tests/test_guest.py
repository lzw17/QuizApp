"""游客模式端到端测试：创建游客 → 示例题库 → 练习 → 登录迁移。"""
import os
import tempfile
import unittest
import uuid
from collections import deque

DB_PATH = os.path.join(tempfile.gettempdir(), f"quiz_guest_{uuid.uuid4().hex}.db")
os.environ.update(
    {
        "APP_ENV": "development",
        "DATABASE_URL": f"sqlite:///{DB_PATH}",
        "SECRET_KEY": "test-secret-key-with-at-least-32-characters",
        "WX_MOCK_LOGIN": "true",
        "WX_MOCK_OPENID": "guest-test-user",
        "WX_MOCK_ADMIN": "false",
        "DEBUG": "false",
    }
)

from fastapi.testclient import TestClient

from backend.app.database import SessionLocal, engine
from backend.app.main import app
from backend.app.models.question import Question
from backend.app.models.user import AnswerRecord, User
from backend.app.routers import auth as auth_router
from backend.app.services.demo_bank import DEMO_BANK_NAME


class GuestFlowTest(unittest.TestCase):
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

    def setUp(self):
        # 每个用例独立限流桶，避免相互影响
        auth_router._guest_rate_bucket.clear()

    def _create_guest(self):
        response = self.client.post("/api/auth/guest")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _first_question(self, bank_id):
        """公开题目接口不回传答案，从库里取第一题的 id 与正确答案。"""
        db = SessionLocal()
        try:
            q = (
                db.query(Question)
                .filter(Question.bank_id == bank_id, Question.status == "active")
                .order_by(Question.order_index)
                .first()
            )
            return q.id, q.answer
        finally:
            db.close()

    def test_guest_creation_returns_token_and_demo_bank(self):
        data = self._create_guest()
        self.assertTrue(data["is_new"])
        self.assertTrue(data["user"]["is_guest"])
        self.assertEqual(data["user"]["nickname"], "游客")
        self.assertIn("access_token", data)

        token = data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 游客名下有示例题库，可直接查看题目
        banks = self.client.get(
            "/api/banks?skip=0&limit=20", headers=headers
        ).json()
        demo_banks = [b for b in banks if b["name"] == DEMO_BANK_NAME]
        self.assertEqual(len(demo_banks), 1)
        self.assertEqual(demo_banks[0]["total_count"], 8)

        bank_id = demo_banks[0]["id"]
        detail = self.client.get(
            f"/api/questions?bank_id={bank_id}&limit=100", headers=headers
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(len(detail.json()), 8)

    def test_guest_can_practice_and_records_persist_in_guest_account(self):
        data = self._create_guest()
        token = data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        banks = self.client.get("/api/banks?skip=0&limit=20", headers=headers).json()
        demo = next(b for b in banks if b["name"] == DEMO_BANK_NAME)
        question_id, correct_answer = self._first_question(demo["id"])

        answer = self.client.post(
            "/api/answer",
            json={
                "question_id": question_id,
                "bank_id": demo["id"],
                "user_answer": correct_answer,
                "time_spent": 5,
                "mode": "practice",
            },
            headers=headers,
        )
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertTrue(answer.json()["is_correct"])

        # 记录挂在游客账号下
        db = SessionLocal()
        try:
            guest = db.query(User).filter(User.id == data["user"]["id"]).first()
            self.assertIsNotNone(guest)
            self.assertTrue(guest.is_guest)
            count = (
                db.query(AnswerRecord)
                .filter(AnswerRecord.user_id == guest.id)
                .count()
            )
            self.assertEqual(count, 1)
        finally:
            db.close()

    def test_login_migrates_guest_data_to_real_account(self):
        data = self._create_guest()
        guest_token = data["access_token"]
        guest_headers = {"Authorization": f"Bearer {guest_token}"}
        banks = self.client.get(
            "/api/banks?skip=0&limit=20", headers=guest_headers
        ).json()
        demo = next(b for b in banks if b["name"] == DEMO_BANK_NAME)
        question_id, correct_answer = self._first_question(demo["id"])
        self.client.post(
            "/api/answer",
            json={
                "question_id": question_id,
                "bank_id": demo["id"],
                "user_answer": correct_answer,
                "mode": "practice",
            },
            headers=guest_headers,
        )

        guest_id = data["user"]["id"]
        login = self.client.post(
            "/api/auth/login",
            json={"code": "migrate-code"},
            headers={"Authorization": f"Bearer {guest_token}"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        real = login.json()
        self.assertFalse(real["user"]["is_guest"])
        self.assertNotEqual(real["user"]["id"], guest_id)

        real_headers = {"Authorization": f"Bearer {real['access_token']}"}
        real_banks = self.client.get(
            "/api/banks?skip=0&limit=20", headers=real_headers
        ).json()
        migrated = [b for b in real_banks if b["name"] == DEMO_BANK_NAME]
        self.assertEqual(len(migrated), 1)

        stats = self.client.get("/api/stats", headers=real_headers)
        self.assertEqual(stats.status_code, 200, stats.text)
        self.assertEqual(stats.json()["total_answered"], 1)

        # 游客账号已删除，旧 token 失效
        db = SessionLocal()
        try:
            self.assertIsNone(db.query(User).filter(User.id == guest_id).first())
        finally:
            db.close()
        me = self.client.get("/api/auth/me", headers=guest_headers)
        self.assertEqual(me.status_code, 401)

    def test_guest_cannot_upload_for_generation(self):
        data = self._create_guest()
        headers = {"Authorization": f"Bearer {data['access_token']}"}
        response = self.client.post(
            "/api/upload/url",
            json={"url": "https://example.com/article", "bank_name": "t"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_guest_creation_is_rate_limited_per_ip(self):
        # 先发一次请求让限流桶以真实 client key 建立起来，再灌满窗口
        self.assertEqual(self.client.post("/api/auth/guest").status_code, 200)
        key = next(iter(auth_router._guest_rate_bucket))
        auth_router._guest_rate_bucket[key] = deque([__import__('time').time()] * auth_router.GUEST_RATE_LIMIT_MAX)
        response = self.client.post("/api/auth/guest")
        self.assertEqual(response.status_code, 429)


if __name__ == "__main__":
    unittest.main()
