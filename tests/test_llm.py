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
    DEFAULT_LOCAL_MAX_OUTPUT_TOKENS,
    DEFAULT_LOCAL_MODEL,
    GroqClient,
    LocalOpenAIClient,
    OpenRouterClient,
    OpenRouterGuardError,
    TruncatedResponseError,
    assert_no_openrouter,
    context_window_for,
    default_model_for,
    get_client,
    max_input_tokens,
    max_output_for,
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
        [
            "OPENAI_BASE_URL",
            "ANTHROPIC_BASE_URL",
            "GROQ_BASE_URL",
            "OPENAI_API_BASE",
            "LOCAL_LLM_BASE_URL",
            "OLLAMA_BASE_URL",
        ],
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
        assert default_model_for("ollama") == DEFAULT_LOCAL_MODEL
        assert default_model_for("lmstudio") == DEFAULT_LOCAL_MODEL
        assert default_model_for("unknown") == DEFAULT_GROQ_MODEL

    def test_local_4k_model_keeps_positive_input_budget(self):
        # ALLaM has a 4k window; naive `window - 16384` would collapse to 1 token.
        # Budgeting must never reserve more than half the window.
        budget = max_input_tokens("iKhalid/ALLaM:7b", backend="ollama")
        assert budget == 4_096 - 2_048  # reserved capped at window // 2

    def test_unknown_local_model_uses_small_local_window(self):
        # Unregistered local tags fall back to the local window, not the 128k cloud one.
        budget = max_input_tokens("some-lmstudio-gguf", backend="lmstudio")
        assert budget == 8_192 - DEFAULT_LOCAL_MAX_OUTPUT_TOKENS

    def test_local_backend_reserves_smaller_output(self):
        assert max_output_for("gemma4:e4b", backend="ollama") == DEFAULT_LOCAL_MAX_OUTPUT_TOKENS
        assert max_output_for("gemma4:e4b") == 16_384  # cloud default when backend unknown

    def test_context_window_lookup(self):
        assert context_window_for("gemma4:e4b") == 8_192
        assert context_window_for("iKhalid/ALLaM:7b") == 4_096
        assert context_window_for("mystery", backend="ollama") == 8_192
        assert context_window_for("mystery") == 128_000

    def test_local_num_ctx_env_override(self, monkeypatch):
        # The env wins for local backends so it matches the loaded context length,
        # regardless of the (user-chosen) model id.
        monkeypatch.setenv("LOCAL_LLM_NUM_CTX", "4096")
        assert context_window_for("gemma4:e4b", backend="lmstudio") == 4_096
        assert context_window_for("any-loaded-id", backend="ollama") == 4_096
        # but it does NOT affect cloud backends
        assert context_window_for("gemma4:e4b") == 8_192

    def test_local_max_output_env_override(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_MAX_OUTPUT_TOKENS", "1536")
        assert max_output_for("anything", backend="ollama") == 1_536
        assert max_output_for("anything") == 16_384  # cloud unaffected


class TestGetClient:
    def test_rejects_unknown_backend(self):
        with pytest.raises(ValueError, match="unknown backend"):
            get_client("gpt5")

    def test_local_backends_construct_client(self):
        assert isinstance(get_client("ollama"), LocalOpenAIClient)
        assert isinstance(get_client("lmstudio"), LocalOpenAIClient)

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


class TestLocalClient:
    """LocalOpenAIClient serves Ollama / LM Studio / llama.cpp — OpenAI chat schema."""

    def test_ollama_default_url_and_no_auth_header(self, monkeypatch):
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(url=url, json=json, headers=headers)
            return _FakeResp("## محضر اجتماع")

        monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
        monkeypatch.setattr(httpx, "post", fake_post)

        client = LocalOpenAIClient(default_base_url="http://localhost:11434/v1")
        out = client.generate("sys", "user", model="iKhalid/ALLaM:7b")

        assert out == "## محضر اجتماع"
        assert captured["url"] == "http://localhost:11434/v1/chat/completions"
        assert captured["json"]["model"] == "iKhalid/ALLaM:7b"
        assert captured["json"]["max_tokens"] == DEFAULT_LOCAL_MAX_OUTPUT_TOKENS
        # No key => no Authorization header (a local server needs none).
        assert "Authorization" not in captured["headers"]

    def test_lmstudio_default_port(self, monkeypatch):
        captured = {}
        monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        monkeypatch.setattr(
            httpx, "post", lambda url, **k: captured.update(url=url) or _FakeResp("ok")
        )
        # The lmstudio backend default is :1234.
        get_client("lmstudio").generate("s", "u", model="local-model")
        assert captured["url"] == "http://localhost:1234/v1/chat/completions"

    def test_env_override_beats_backend_default(self, monkeypatch):
        captured = {}
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://10.0.0.5:1234/v1")
        monkeypatch.setattr(
            httpx, "post", lambda url, **k: captured.update(url=url) or _FakeResp("ok")
        )
        # Even the ollama backend (default :11434) must honor the env override.
        get_client("ollama").generate("s", "u", model="m")
        assert captured["url"] == "http://10.0.0.5:1234/v1/chat/completions"

    def test_api_key_adds_auth_header(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            httpx, "post", lambda url, headers=None, **k: captured.update(headers=headers)
            or _FakeResp("ok"),
        )
        LocalOpenAIClient(api_key="secret").generate("s", "u", model="m")
        assert captured["headers"]["Authorization"] == "Bearer secret"

    def test_truncation_raises(self, monkeypatch):
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp("x", finish_reason="length"))
        with pytest.raises(TruncatedResponseError, match="truncated"):
            LocalOpenAIClient().generate("s", "u", model="m")

    def test_connection_error_gives_helpful_message(self, monkeypatch):
        def boom(*a, **k):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "post", boom)
        with pytest.raises(RuntimeError, match="local.*server running"):
            LocalOpenAIClient(max_retries=0).generate("s", "u", model="m")
