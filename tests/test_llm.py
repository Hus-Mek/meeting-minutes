"""Unit tests for the LLM backend selection and OpenRouter guardrail.

No real network client is ever constructed here.
"""

from __future__ import annotations

import sys
import types

import pytest

from meeting_minutes.llm import (
    DEFAULT_GROQ_MODEL,
    GroqClient,
    OpenRouterGuardError,
    assert_no_openrouter,
    get_client,
)


def _install_fake_groq(monkeypatch, captured):
    """Inject a fake `groq` module so GroqClient never hits the network."""

    class FakeMessage:
        content = "## Topic\nDone."

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeCompletion()

    class FakeChat:
        completions = FakeCompletions()

    class FakeGroq:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.chat = FakeChat()

    module = types.ModuleType("groq")
    module.Groq = FakeGroq
    monkeypatch.setitem(sys.modules, "groq", module)


class TestOpenRouterGuard:
    def test_passes_when_no_base_url_set(self):
        assert_no_openrouter(env={})  # does not raise

    def test_passes_for_non_openrouter_base_url(self):
        assert_no_openrouter(env={"OPENAI_BASE_URL": "https://api.groq.com/openai/v1"})

    @pytest.mark.parametrize(
        "var",
        ["OPENAI_BASE_URL", "ANTHROPIC_BASE_URL", "GROQ_BASE_URL", "OPENAI_API_BASE"],
    )
    def test_raises_when_pointed_at_openrouter(self, var):
        with pytest.raises(OpenRouterGuardError, match="reserved for Tafkeek"):
            assert_no_openrouter(env={var: "https://openrouter.ai/api/v1"})

    def test_is_case_insensitive(self):
        with pytest.raises(OpenRouterGuardError):
            assert_no_openrouter(env={"ANTHROPIC_BASE_URL": "HTTPS://OpenRouter.AI"})


class TestGetClient:
    def test_rejects_unknown_backend(self):
        with pytest.raises(ValueError, match="unknown backend"):
            get_client("gpt5")

    def test_claude_backend_is_stubbed(self):
        with pytest.raises(NotImplementedError, match="Claude backend"):
            get_client("claude")

    def test_ollama_backend_is_stubbed(self):
        with pytest.raises(NotImplementedError, match="Ollama backend"):
            get_client("ollama")

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

    def test_generate_calls_sdk_and_returns_content(self, monkeypatch):
        captured = {}
        _install_fake_groq(monkeypatch, captured)
        client = GroqClient(api_key="test-key")

        result = client.generate("sys", "user", model=DEFAULT_GROQ_MODEL)

        assert result == "## Topic\nDone."
        assert captured["api_key"] == "test-key"
        assert captured["model"] == DEFAULT_GROQ_MODEL
        assert captured["messages"][0]["role"] == "system"
        assert captured["messages"][1]["content"] == "user"

    def test_get_client_groq_constructs_real_class(self, monkeypatch):
        captured = {}
        _install_fake_groq(monkeypatch, captured)
        monkeypatch.setenv("GROQ_API_KEY", "k")
        client = get_client("groq")
        assert isinstance(client, GroqClient)
