"""Pluggable LLM backend with a hard OpenRouter guardrail.

Default backend is Groq (Llama 3.3 70B) — already in the wider stack, cheap, and
good enough for summarisation. The Claude and Ollama adapters are stubs documented
for later; only Groq is implemented now.

HARD RULE: this tool must NEVER route through OpenRouter (reserved for Tafkeek).
``assert_no_openrouter`` enforces that in code — covering both ``*_BASE_URL`` and
proxy env vars — and the Groq client is built with ``trust_env=False`` so proxy
variables cannot silently tunnel traffic through OpenRouter.
"""

from __future__ import annotations

import os
from typing import Callable, Protocol

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

# Default Sonnet model id on OpenRouter (overridable via --model / the GUI).
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"

# Per-model context windows (input + output tokens). Used to size single-pass vs
# map-reduce. Conservative fallback for unknown models.
MODEL_CONTEXT_WINDOWS = {
    "llama-3.3-70b-versatile": 128_000,
    "llama-3.1-70b-versatile": 128_000,
    "llama-3.1-8b-instant": 128_000,
    "anthropic/claude-sonnet-4.6": 200_000,
    "anthropic/claude-sonnet-4.5": 200_000,
}
DEFAULT_CONTEXT_WINDOW = 128_000

# Reserve room for the model's own output so a near-full input still leaves space
# to write the minutes. Detailed Arabic minutes can be long, so this is generous.
DEFAULT_MAX_OUTPUT_TOKENS = 16_384

# Network resilience defaults (Groq SDK retries 429/5xx/connection errors).
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_MAX_RETRIES = 4

# Per-backend default model — resolved when --model is omitted.
DEFAULT_MODELS = {
    "groq": DEFAULT_GROQ_MODEL,
    "openrouter": DEFAULT_OPENROUTER_MODEL,
    "ollama": "llama3.1",
}

# Env vars that could silently redirect a client to OpenRouter.
_BASE_URL_ENV_VARS = (
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "ANTHROPIC_BASE_URL",
    "GROQ_BASE_URL",
)
_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


class OpenRouterGuardError(RuntimeError):
    """Raised when configuration would route a call through OpenRouter."""


def assert_no_openrouter(env: dict[str, str] | None = None) -> None:
    """Fail loudly if any base-URL or proxy env var points at OpenRouter."""
    environ = env if env is not None else os.environ
    for var in (*_BASE_URL_ENV_VARS, *_PROXY_ENV_VARS):
        value = environ.get(var, "")
        if "openrouter" in value.lower():
            raise OpenRouterGuardError(
                f"{var}={value!r} points at OpenRouter, which is reserved for Tafkeek. "
                "Unset it before running the minutes generator."
            )


def default_model_for(backend: str) -> str:
    """The default model id for a backend (used when --model is omitted)."""
    return DEFAULT_MODELS.get(backend, DEFAULT_GROQ_MODEL)


def max_input_tokens(model: str, *, reserved_output: int = DEFAULT_MAX_OUTPUT_TOKENS) -> int:
    """Token budget available for the *input* of one call to ``model``."""
    window = MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)
    return max(1, window - reserved_output)


class LlmClient(Protocol):
    """A backend is anything that turns (system, user, model) into Markdown."""

    def generate(self, system: str, user: str, *, model: str) -> str: ...


class TruncatedResponseError(RuntimeError):
    """Raised when the model stopped because it hit the output-token cap."""


class GroqClient:
    """Groq backend using the official SDK. Constructed lazily so tests never hit it."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        assert_no_openrouter()
        import httpx  # Groq SDK dependency
        from groq import Groq  # imported here so the dep is optional until used

        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set")
        # trust_env=False => ignore HTTP(S)_PROXY/ALL_PROXY so traffic can't be
        # tunnelled through OpenRouter even if those vars are set.
        self._client = Groq(
            api_key=key,
            timeout=timeout,
            max_retries=max_retries,
            http_client=httpx.Client(trust_env=False, timeout=timeout),
        )
        self._max_output_tokens = max_output_tokens

    def generate(self, system: str, user: str, *, model: str = DEFAULT_GROQ_MODEL) -> str:
        response = self._client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=self._max_output_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            raise TruncatedResponseError(
                f"Groq response hit the {self._max_output_tokens}-token output cap and was "
                "truncated; the meeting is too large for a single call (raise the cap or "
                "lower the input budget so map-reduce splits it further)."
            )
        return choice.message.content or ""


_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class OpenRouterClient:
    """Sonnet (and other) models via OpenRouter's OpenAI-compatible REST API.

    DELIBERATE, user-authorized exception to the usual OpenRouter ban for this app:
    it uses a dedicated ``OPENROUTER_API_KEY`` and is selected only when the user
    explicitly chooses ``--backend openrouter``. The env-var OpenRouter guardrail
    still protects the Groq path from accidental proxy/base-url tunnelling.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        import httpx

        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self._key = key
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        self._httpx = httpx

    def generate(self, system: str, user: str, *, model: str = DEFAULT_OPENROUTER_MODEL) -> str:
        payload = {
            "model": model,
            "temperature": 0.2,
            "max_tokens": self._max_output_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._httpx.post(
                    _OPENROUTER_URL, json=payload, headers=headers, timeout=self._timeout
                )
                if resp.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                    continue
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise TruncatedResponseError(
                        f"OpenRouter response hit the {self._max_output_tokens}-token cap "
                        "and was truncated; raise the cap or shorten the input."
                    )
                return choice["message"]["content"] or ""
            except self._httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    raise RuntimeError(f"OpenRouter request failed: {exc}") from exc
        raise RuntimeError(f"OpenRouter request failed: {last_exc}")


def _ollama_stub(*_args, **_kwargs):
    raise NotImplementedError(
        "Ollama backend not implemented yet. It would POST to a local Ollama server "
        "for a fully free, private run. Use --backend groq for now."
    )


# Backend registry: name -> factory().
_BACKENDS: dict[str, Callable[[], LlmClient]] = {
    "groq": lambda: GroqClient(),
    "openrouter": lambda: OpenRouterClient(),
    "ollama": _ollama_stub,
}


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
