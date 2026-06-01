"""Pluggable LLM backend with a hard OpenRouter guardrail.

Default backend is Groq (Llama 3.3 70B) — already in the wider stack, cheap, and
good enough for summarisation. The Claude and Ollama adapters are stubs documented
for later; only Groq is implemented now.

HARD RULE: this tool must NEVER route through OpenRouter (reserved for Tafkeek).
``assert_no_openrouter`` enforces that in code, regardless of backend, before any
network client is constructed.
"""

from __future__ import annotations

import os
from typing import Callable, Protocol

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

# Env vars that could silently redirect a client to OpenRouter.
_BASE_URL_ENV_VARS = (
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "ANTHROPIC_BASE_URL",
    "GROQ_BASE_URL",
)


class OpenRouterGuardError(RuntimeError):
    """Raised when configuration would route a call through OpenRouter."""


def assert_no_openrouter(env: dict[str, str] | None = None) -> None:
    """Fail loudly if any base-URL env var points at OpenRouter."""
    environ = env if env is not None else os.environ
    for var in _BASE_URL_ENV_VARS:
        value = environ.get(var, "")
        if "openrouter" in value.lower():
            raise OpenRouterGuardError(
                f"{var}={value!r} points at OpenRouter, which is reserved for Tafkeek. "
                "Unset it before running the minutes generator."
            )


class LlmClient(Protocol):
    """A backend is anything that turns (system, user, model) into Markdown."""

    def generate(self, system: str, user: str, *, model: str) -> str: ...


class GroqClient:
    """Groq backend using the official SDK. Constructed lazily so tests never hit it."""

    def __init__(self, api_key: str | None = None) -> None:
        assert_no_openrouter()
        from groq import Groq  # imported here so the dep is optional until used

        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self._client = Groq(api_key=key)

    def generate(self, system: str, user: str, *, model: str = DEFAULT_GROQ_MODEL) -> str:
        response = self._client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


def _claude_stub(*_args, **_kwargs):
    raise NotImplementedError(
        "Claude backend not implemented yet. It would use the `anthropic` SDK with "
        "prompt caching once Anthropic API access is available (Enterprise seat does "
        "not grant it automatically)."
    )


def _ollama_stub(*_args, **_kwargs):
    raise NotImplementedError(
        "Ollama backend not implemented yet. It would POST to a local Ollama server "
        "for a fully free, private run."
    )


# Backend registry: name -> factory(). Only Groq is live.
_BACKENDS: dict[str, Callable[[], LlmClient]] = {
    "groq": lambda: GroqClient(),
    "claude": _claude_stub,
    "ollama": _ollama_stub,
}

DEFAULT_MODELS = {"groq": DEFAULT_GROQ_MODEL}


def get_client(backend: str = "groq") -> LlmClient:
    """Construct the LLM client for the named backend (default Groq)."""
    assert_no_openrouter()
    try:
        factory = _BACKENDS[backend]
    except KeyError:
        raise ValueError(
            f"unknown backend {backend!r}; choose from {sorted(_BACKENDS)}"
        ) from None
    return factory()
