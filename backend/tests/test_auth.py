import asyncio
import os
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch


DB_PATH = os.path.join(tempfile.gettempdir(), f"quiz_auth_{uuid.uuid4().hex}.db")
os.environ.update(
    {
        "APP_ENV": "development",
        "DATABASE_URL": f"sqlite:///{DB_PATH}",
        "SECRET_KEY": "test-secret-key-with-at-least-32-characters",
        "WX_MOCK_LOGIN": "true",
        "WX_MOCK_OPENID": "auth-test-user",
        "DEBUG": "false",
    }
)

from fastapi.testclient import TestClient

from backend.app.database import engine
from backend.app.main import app
from backend.app.routers.auth import _get_wechat_session


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

    def test_non_admin_cannot_use_admin_api(self):
        session = self.login()
        response = self.client.get(
            "/api/banks/all",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
