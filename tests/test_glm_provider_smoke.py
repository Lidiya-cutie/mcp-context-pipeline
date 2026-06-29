import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from secure_middleware import SecureLLMMiddleware, create_secure_middleware


def test_secure_middleware_uses_anthropic_base_url_and_token_fallback(monkeypatch):
    captured = {}

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_module = types.ModuleType("anthropic")
    fake_module.AsyncAnthropic = FakeAsyncAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "glm-token-123")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "glm-4.7")
    monkeypatch.setenv("HTTP_PROXY", "")
    monkeypatch.setenv("HTTPS_PROXY", "")
    monkeypatch.setenv("ALL_PROXY", "")

    middleware = create_secure_middleware(provider="anthropic", api_key=None, model=None)

    assert isinstance(middleware, SecureLLMMiddleware)
    assert middleware.client is not None
    assert middleware.model == "glm-4.7"
    assert captured.get("api_key") == "glm-token-123"
    assert captured.get("base_url") == "https://api.z.ai/api/anthropic"


def test_secure_middleware_prefers_anthropic_api_key_over_auth_token(monkeypatch):
    captured = {}

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_module = types.ModuleType("anthropic")
    fake_module.AsyncAnthropic = FakeAsyncAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "primary-api-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fallback-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "glm-4.7")
    monkeypatch.setenv("HTTP_PROXY", "")
    monkeypatch.setenv("HTTPS_PROXY", "")
    monkeypatch.setenv("ALL_PROXY", "")

    middleware = create_secure_middleware(provider="anthropic", api_key=None, model=None)

    assert isinstance(middleware, SecureLLMMiddleware)
    assert middleware.client is not None
    assert captured.get("api_key") == "primary-api-key"
    assert captured.get("base_url") == "https://api.z.ai/api/anthropic"
