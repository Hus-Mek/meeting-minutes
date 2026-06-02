"""Unit tests for backend selection, the OpenRouter guardrail, and budgeting.

No real network client is ever constructed here — `groq` is faked in sys.modules.
"""

from __future__ import annotations

import sys
import types

import pytest

import httpx

from meeting_minutes.llm import (
    DEFAULT_GROQ_MODEL,
    GroqClient,
    OpenRouterClient,
    OpenRouterGuardError,
    TruncatedResponseError,
    assert_no_openrouter,
    default_model_for,
    get_client,
    max_input_tokens,
)


def _install_fake_groq(monkeypatch, captured, *, finish_reason="stop"):
    """Inject a fake `groq` module so GroqClient never hits the network."""

    class FakeMessage:
        content = "## Topic\nDone."

    class FakeChoice:
        message = FakeMessage()

    FakeChoice.finish_reason = finish_reason

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeCompletion()

    class FakeChat:
        completions = FakeCompletions()

    class FakeGroq:
        def __init__(self, api_key=None, **kwargs):
            captured["api_key"] = api_key
            captured["init_kwargs"] = kwargs
            self.chat = FakeChat()

    module = types.ModuleType("groq")
    module.Groq = FakeGroq
    monkeypatch.setitem(sys.modules, "groq", module)


class TestOpenRouterGuard:
    def test_passes_when_no_base_url_set(self):
        assert_no_openrouter(env={})

    def test_passes_for_non_openrouter_base_url(self):
        assert_no_openrouter(env={"OPENAI_BASE_URL": "https://api.groq.com/openai/v1"})

    @pytest.mark.parametrize(
        "var",
        ["OPENAI_BASE_URL", "ANTHROPIC_BASE_URL", "GROQ_BASE_URL", "OPENAI_API_BASE"],
    )
    def test_raises_for_base_url_openrouter(self, var):
        with pytest.raises(OpenRouterGuardError, match="reserved for Tafkeek"):
            assert_no_openrouter(env={var: "https://openrouter.ai/api/v1"})

    @pytest.mark.parametrize("var", ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "https_proxy"])
    def test_raises_for_proxy_openrouter(self, var):
        with pytest.raises(OpenRouterGuardError, match="reserved for Tafkeek"):
            assert_no_openrouter(env={var: "https://openrouter.ai"})

    def test_is_case_insensitive(self):
        with pytest.raises(OpenRouterGuardError):
            assert_no_openrouter(env={"ANTHROPIC_BASE_URL": "HTTPS://OpenRouter.AI"})


class TestBudgeting:
    def test_known_model_reserves_output_room(self):
        # 128k window minus 16384 reserved output.
        assert max_input_tokens("llama-3.3-70b-versatile") == 128_000 - 16_384

    def test_unknown_model_uses_conservative_fallback(self):
        assert max_input_tokens("some-future-model") == 128_000 - 16_384

    def test_default_model_per_backend(self):
        assert default_model_for("groq") == DEFAULT_GROQ_MODEL
        assert default_model_for("openrouter").startswith("anthropic/")
        assert default_model_for("unknown") == DEFAULT_GROQ_MODEL


class TestGetClient:
    def test_rejects_unknown_backend(self):
        with pytest.raises(ValueError, match="unknown backend"):
            get_client("gpt5")

    def test_ollama_backend_is_stubbed(self):
        with pytest.raises(NotImplementedError, match="Ollama backend"):
            get_client("ollama")

    def test_openrouter_requires_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            get_client("openrouter")

    def test_guard_runs_before_construction(self, monkeypatch):
        monkeypatch.setenv("GROQ_BASE_URL", "https://openrouter.ai/x")
        with pytest.raises(OpenRouterGuardError):
            get_client("groq")


class TestGroqClient:
    def test_requires_api_key(self, monkeypatch):
        captured = {}
        _install_fake_groq(monkeypatch, captured)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            GroqClient()

    def test_generate_sets_output_cap_and_returns_content(self, monkeypatch):
        captured = {}
        _install_fake_groq(monkeypatch, captured)
        client = GroqClient(api_key="test-key")
        result = client.generate("sys", "user", model=DEFAULT_GROQ_MODEL)
        assert result == "## Topic\nDone."
        assert captured["api_key"] == "test-key"
        assert captured["model"] == DEFAULT_GROQ_MODEL
        assert captured["max_tokens"] == 16_384
        assert captured["messages"][0]["role"] == "system"
        # SDK constructed with retries + a trust_env=False http client (proxy-proof)
        assert captured["init_kwargs"]["max_retries"] >= 1
        assert "http_client" in captured["init_kwargs"]

    def test_truncated_response_raises(self, monkeypatch):
        captured = {}
        _install_fake_groq(monkeypatch, captured, finish_reason="length")
        client = GroqClient(api_key="k")
        with pytest.raises(TruncatedResponseError, match="truncated"):
            client.generate("sys", "user", model=DEFAULT_GROQ_MODEL)

    def test_get_client_groq_constructs_real_class(self, monkeypatch):
        captured = {}
        _install_fake_groq(monkeypatch, captured)
        monkeypatch.setenv("GROQ_API_KEY", "k")
        assert isinstance(get_client("groq"), GroqClient)


class _FakeResp:
    def __init__(self, content, finish_reason="stop", status=200):
        self.status_code = status
        self._content = content
        self._finish = finish_reason

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"finish_reason": self._finish, "message": {"content": self._content}}]}


class TestOpenRouterClient:
    def test_requires_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            OpenRouterClient()

    def test_generate_posts_and_returns_content(self, monkeypatch):
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(url=url, json=json, headers=headers)
            return _FakeResp("## محضر اجتماع")

        monkeypatch.setattr(httpx, "post", fake_post)
        client = OpenRouterClient(api_key="or-key")
        out = client.generate("sys", "user", model="anthropic/claude-sonnet-4.6")
        assert out == "## محضر اجتماع"
        assert captured["url"].endswith("/chat/completions")
        assert captured["json"]["model"] == "anthropic/claude-sonnet-4.6"
        assert captured["headers"]["Authorization"] == "Bearer or-key"

    def test_truncation_raises(self, monkeypatch):
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp("x", finish_reason="length"))
        with pytest.raises(TruncatedResponseError):
            OpenRouterClient(api_key="k").generate("s", "u")
