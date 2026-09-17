import unittest
from unittest.mock import patch

from backend.app.config import Settings
from backend.app.services import ai_engine


class LlmConfigTest(unittest.TestCase):
    def production_settings(self, **overrides):
        values = {
            "_env_file": None,
            "APP_ENV": "production",
            "DEBUG": False,
            "SECRET_KEY": "a-random-production-secret-key-that-is-long-enough",
            "DATABASE_URL": "mysql+pymysql://quizapp:password@127.0.0.1/quizapp",
            "WX_APPID": "wxaec3bef13eea7842",
            "WX_SECRET": "a" * 32,
            "WX_MOCK_LOGIN": False,
            "PUBLIC_BASE_URL": "https://api.example.com",
            "ALLOWED_ORIGINS": "https://servicewechat.com",
            "LLM_API_KEY": "sk-valid-production-key",
            "LLM_BASE_URL": "https://models.example.com/v1",
            "LLM_MODEL": "custom-model",
        }
        values.update(overrides)
        return Settings(**values)

    def test_llm_settings_override_legacy_deepseek_settings(self):
        config = Settings(
            _env_file=None,
            LLM_API_KEY="custom-key",
            LLM_BASE_URL="https://models.example.com/v1",
            LLM_MODEL="custom-model",
            DEEPSEEK_API_KEY="legacy-key",
            DEEPSEEK_BASE_URL="https://api.deepseek.com",
            DEEPSEEK_MODEL="deepseek-chat",
        )

        self.assertEqual(config.llm_api_key, "custom-key")
        self.assertEqual(config.llm_base_url, "https://models.example.com/v1")
        self.assertEqual(config.llm_model, "custom-model")

    def test_chat_completions_url_is_normalized_to_api_base(self):
        config = Settings(
            _env_file=None,
            LLM_BASE_URL="https://models.example.com/v1/chat/completions/",
        )

        self.assertEqual(config.llm_base_url, "https://models.example.com/v1")

    def test_production_rejects_plain_http_llm_endpoint(self):
        config = self.production_settings(
            LLM_BASE_URL="http://models.example.com/v1",
        )

        with self.assertRaisesRegex(RuntimeError, "must use HTTPS"):
            config.validate_runtime_security()

    def test_partial_llm_override_is_rejected(self):
        config = Settings(
            _env_file=None,
            LLM_API_KEY="custom-key",
            LLM_BASE_URL="",
            LLM_MODEL="",
        )

        with self.assertRaisesRegex(RuntimeError, "must be configured together"):
            config.validate_runtime_security()

    def test_production_rejects_placeholder_credentials(self):
        cases = (
            ({"WX_SECRET": "<你的AppSecret>"}, "WX_APPID and WX_SECRET"),
            ({"LLM_API_KEY": "<CHANGE_ME_LLM_KEY>"}, "LLM_API_KEY"),
            ({"SECRET_KEY": "<CHANGE_ME_RANDOM_SECRET_VALUE_123456789>"}, "SECRET_KEY"),
            (
                {"DATABASE_URL": "mysql+pymysql://quizapp:<CHANGE_ME_DB_PASSWORD>@127.0.0.1/quizapp"},
                "DATABASE_URL",
            ),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(RuntimeError, message):
                    self.production_settings(**overrides).validate_runtime_security()

    def test_llm_parse_logs_do_not_include_model_output(self):
        sensitive_output = "private-document-fragment-without-json"
        with self.assertLogs(ai_engine.logger, level="WARNING") as captured:
            self.assertEqual(ai_engine._parse_llm_output(sensitive_output), [])
        self.assertNotIn(sensitive_output, "\n".join(captured.output))

    def test_get_llm_passes_custom_client_settings(self):
        overrides = {
            "LLM_API_KEY": "custom-key",
            "LLM_BASE_URL": "https://models.example.com/v1/chat/completions",
            "LLM_MODEL": "custom-model",
            "LLM_TIMEOUT_SECONDS": 45.0,
            "LLM_MAX_RETRIES": 3,
            "LLM_MAX_TOKENS": 2048,
        }
        patches = [patch.object(ai_engine.settings, name, value) for name, value in overrides.items()]

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
            "backend.app.services.ai_engine.ChatOpenAI"
        ) as chat_openai:
            ai_engine.get_llm(temperature=0.25)

        chat_openai.assert_called_once_with(
            model="custom-model",
            openai_api_key="custom-key",
            openai_api_base="https://models.example.com/v1",
            temperature=0.25,
            max_tokens=2048,
            timeout=45.0,
            max_retries=3,
        )


if __name__ == "__main__":
    unittest.main()
