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
#
# Local (Ollama) entries are the num_ctx we actually run the model with — NOT the
# model's theoretical maximum. Ollama defaults to a stingy 4096 unless a Modelfile
# raises it, and on a shared-memory iGPU the KV cache competes with the weights for
# VRAM, so we keep these modest and match them in the shipped Modelfiles. Arabic
# specialists (ALLaM/Yehia/Fanar) are 4K-native and cannot exceed it.
MODEL_CONTEXT_WINDOWS = {
    "llama-3.3-70b-versatile": 128_000,
    "llama-3.1-70b-versatile": 128_000,
    "llama-3.1-8b-instant": 128_000,
    "anthropic/claude-sonnet-4.6": 200_000,
    "anthropic/claude-sonnet-4.5": 200_000,
    # Local Ollama models (key = the Ollama tag; value = shipped num_ctx).
    "iKhalid/ALLaM:7b": 4_096,
    "yehia7b": 4_096,
    "QCRI/Fanar-1-9B-Instruct": 4_096,
    "gemma4:e4b": 8_192,
    "qwen3:8b": 8_192,
}
DEFAULT_CONTEXT_WINDOW = 128_000

# Backends whose models run locally (Ollama / LM Studio / llama.cpp server). They
# have small real context windows and can't sustain huge outputs, so budgeting
# reserves less for output and falls back to a small window for unregistered tags.
LOCAL_BACKENDS = frozenset({"ollama", "lmstudio"})
DEFAULT_LOCAL_CONTEXT_WINDOW = 8_192

# Reserve room for the model's own output so a near-full input still leaves space
# to write the minutes. Detailed Arabic minutes can be long, so this is generous.
DEFAULT_MAX_OUTPUT_TOKENS = 16_384

# Local models can't reliably sustain a 16k-token answer (small models drift past
# ~4k of structured output), and their context windows are small, so cap output
# lower. Map-reduce assembles long minutes from bounded sections regardless.
DEFAULT_LOCAL_MAX_OUTPUT_TOKENS = 4_096

# Network resilience defaults (Groq SDK retries 429/5xx/connection errors).
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_MAX_RETRIES = 4

# Per-backend default model — resolved when --model is omitted. The local default
# is the best Arabic-writing model that fits a 16GB / ~9GB-VRAM box; override with
# --model after the local benchmark picks a winner. (LM Studio identifies models
# by the loaded GGUF's id, so its default is usually overridden in practice.)
DEFAULT_LOCAL_MODEL = "iKhalid/ALLaM:7b"
DEFAULT_MODELS = {
    "groq": DEFAULT_GROQ_MODEL,
    "openrouter": DEFAULT_OPENROUTER_MODEL,
    "anthropic": "claude-opus-4-8",
    "claude-code": "",  # empty => use whatever model Claude Code is configured with
    "ollama": DEFAULT_LOCAL_MODEL,
    "lmstudio": DEFAULT_LOCAL_MODEL,
}

# Env vars that could silently redirect a client to OpenRouter — including the
# local-server overrides, so a stray LOCAL_LLM_BASE_URL=openrouter.ai is caught
# instead of routing "local" calls through metered OpenRouter.
_BASE_URL_ENV_VARS = (
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "ANTHROPIC_BASE_URL",
    "GROQ_BASE_URL",
    "LOCAL_LLM_BASE_URL",
    "OLLAMA_BASE_URL",
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


def _env_int(name: str, *, minimum: int) -> int | None:
    """Read a positive int env var, or None if unset/invalid."""
    raw = os.environ.get(name, "").strip()
    if raw.isdigit():
        return max(minimum, int(raw))
    return None


def context_window_for(model: str, *, backend: str | None = None) -> int:
    """The context window we run ``model`` with (input + output tokens).

    For local backends, ``LOCAL_LLM_NUM_CTX`` wins so it always matches the context
    length you actually loaded the model with (LM Studio / Ollama num_ctx) — local
    model ids are user-chosen, so an env override is the only reliable source of
    truth. Otherwise a registered window wins; otherwise local falls back to a small
    window (not the 128k cloud default) so map-reduce splits aggressively enough.
    """
    if backend in LOCAL_BACKENDS:
        override = _env_int("LOCAL_LLM_NUM_CTX", minimum=512)
        if override is not None:
            return override
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]
    if backend in LOCAL_BACKENDS:
        return DEFAULT_LOCAL_CONTEXT_WINDOW
    return DEFAULT_CONTEXT_WINDOW


def _local_max_output(explicit: int | None = None) -> int:
    """Resolve a local model's output cap: explicit arg > env > default."""
    if explicit is not None:
        return explicit
    return _env_int("LOCAL_LLM_MAX_OUTPUT_TOKENS", minimum=256) or DEFAULT_LOCAL_MAX_OUTPUT_TOKENS


def max_output_for(model: str, *, backend: str | None = None) -> int:
    """Output-token cap to reserve/allow for ``model`` — smaller for local backends."""
    if backend in LOCAL_BACKENDS:
        return _local_max_output()
    return DEFAULT_MAX_OUTPUT_TOKENS


def max_input_tokens(
    model: str,
    *,
    reserved_output: int | None = None,
    backend: str | None = None,
) -> int:
    """Token budget available for the *input* of one call to ``model``.

    Never reserves more than half the window, so a small-context local model
    (e.g. ALLaM's 4k) still gets a positive, usable input budget instead of
    collapsing to 1 token.
    """
    window = context_window_for(model, backend=backend)
    if reserved_output is None:
        reserved_output = max_output_for(model, backend=backend)
    reserved = min(reserved_output, window // 2)
    return max(1, window - reserved)


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


class AnthropicClient:
    """Anthropic Claude API backend (direct, no intermediary like OpenRouter).

    Calls the official Anthropic Messages API. Metered directly on ANTHROPIC_API_KEY,
    with no routing through OpenRouter or any proxy — fully independent of the
    Tafkeek-reserved OpenRouter key. Useful when you have Claude subscription or
    want dedicated API billing.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("Install anthropic SDK: pip install anthropic") from None
        self._client = Anthropic(api_key=key)
        self._max_output_tokens = max_output_tokens

    def generate(
        self, system: str, user: str, *, model: str = "claude-opus-4-8"
    ) -> str:
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=self._max_output_tokens,
                temperature=0.2,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            choice = response.content[0]
            if getattr(response, "stop_reason", None) == "max_tokens":
                raise TruncatedResponseError(
                    f"Anthropic response hit the {self._max_output_tokens}-token cap "
                    "and was truncated; raise the cap or shorten the input."
                )
            return choice.text or ""
        except Exception as e:
            if "invalid api key" in str(e).lower() or "unauthorized" in str(e).lower():
                raise RuntimeError("ANTHROPIC_API_KEY is invalid or expired") from e
            raise


_DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"
_DEFAULT_LMSTUDIO_URL = "http://localhost:1234/v1"


class LocalOpenAIClient:
    """Local models via an OpenAI-compatible server: Ollama, LM Studio, or
    llama.cpp ``--server`` / vLLM.

    Free and private — nothing leaves the machine. The base URL resolves from
    (in order) the ``base_url`` arg, the ``LOCAL_LLM_BASE_URL`` env var, the
    ``OLLAMA_BASE_URL`` env var, then the per-backend default. No API key is needed
    for a local server, but an optional ``OLLAMA_API_KEY``/``LOCAL_LLM_API_KEY`` is
    sent if set (some proxies want one). Shares the OpenRouter client's
    retry/truncation handling — identical OpenAI chat schema.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        default_base_url: str = _DEFAULT_OLLAMA_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_output_tokens: int | None = None,
    ) -> None:
        # Belt-and-suspenders: guard here too (not just in get_client) so direct
        # construction can't route a "local" call through OpenRouter.
        assert_no_openrouter()
        import httpx

        # Precedence: explicit arg > env override > the backend's default port.
        base = (
            base_url
            or os.environ.get("LOCAL_LLM_BASE_URL")
            or os.environ.get("OLLAMA_BASE_URL")
            or default_base_url
        )
        self._url = f"{base.rstrip('/')}/chat/completions"
        # A local server needs no key; only attach one if explicitly provided.
        self._key = (
            api_key or os.environ.get("LOCAL_LLM_API_KEY") or os.environ.get("OLLAMA_API_KEY", "")
        )
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_output_tokens = _local_max_output(max_output_tokens)
        self._httpx = httpx

    def generate(self, system: str, user: str, *, model: str = DEFAULT_LOCAL_MODEL) -> str:
        payload = {
            "model": model,
            "temperature": 0.2,
            "max_tokens": self._max_output_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._httpx.post(
                    self._url, json=payload, headers=headers, timeout=self._timeout
                )
                if resp.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                    continue
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise TruncatedResponseError(
                        f"Local model response hit the {self._max_output_tokens}-token cap "
                        "and was truncated; lower the input budget (the map-reduce window) or "
                        "raise the model's num_ctx so it has room to finish."
                    )
                return choice["message"]["content"] or ""
            except self._httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    raise RuntimeError(
                        f"Local model request to {self._url} failed: {exc}. Is the local "
                        "server running (Ollama `ollama serve`, or LM Studio's server) and "
                        "the model loaded?"
                    ) from exc
        raise RuntimeError(f"Local model request failed: {last_exc}")


class ClaudeCodeClient:
    """Generate via the local **Claude Code CLI** in headless print mode (``claude -p``).

    Subscription-backed: it uses your Claude Code login, so it's **automatic, $0
    incremental, and never touches a metered API or OpenRouter**. Requires the
    ``claude`` CLI installed and logged in (``npm i -g @anthropic-ai/claude-code``).
    The model is whatever Claude Code is configured to use unless ``model`` overrides
    it. The prompt is piped via stdin so long transcripts don't hit ARG_MAX.
    """

    def __init__(self, *, binary: str | None = None, timeout: float = 600.0) -> None:
        import shutil

        name = binary or os.environ.get("CLAUDE_CODE_BIN", "claude")
        self._path = shutil.which(name)
        if not self._path:
            raise RuntimeError(
                f"Claude Code CLI {name!r} not found on PATH. Install it "
                "(`npm i -g @anthropic-ai/claude-code`) and log in, or set CLAUDE_CODE_BIN."
            )
        self._timeout = timeout

    def generate(self, system: str, user: str, *, model: str = "") -> str:
        import subprocess

        prompt_text = f"{system}\n\n{user}" if system else user
        cmd = [self._path, "-p", "--output-format", "text"]
        if model and model not in ("", "default", "claude-code"):
            cmd += ["--model", model]
        try:
            proc = subprocess.run(
                cmd,
                input=prompt_text,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Claude Code CLI timed out after {self._timeout:.0f}s"
            ) from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"Claude Code CLI failed (exit {proc.returncode}): {detail}")
        out = proc.stdout.strip()
        if not out:
            raise RuntimeError("Claude Code CLI returned empty output")
        return out


# Backend registry: name -> factory(). "ollama" and "lmstudio" are the same
# OpenAI-compatible client with different default ports; either is overridable via
# LOCAL_LLM_BASE_URL. "claude-code" shells out to the local Claude Code CLI.
_BACKENDS: dict[str, Callable[[], LlmClient]] = {
    "groq": lambda: GroqClient(),
    "openrouter": lambda: OpenRouterClient(),
    "anthropic": lambda: AnthropicClient(),
    "claude-code": lambda: ClaudeCodeClient(),
    "ollama": lambda: LocalOpenAIClient(default_base_url=_DEFAULT_OLLAMA_URL),
    "lmstudio": lambda: LocalOpenAIClient(default_base_url=_DEFAULT_LMSTUDIO_URL),
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
