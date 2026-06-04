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
import re
import threading
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
    # Claude Code tier aliases (Opus preferred, Sonnet fallback — see
    # ClaudeCodeClient) and the current 4.x ids. Opus/Sonnet 4.x are 200k-context, so
    # the budget is the same whichever tier the CLI ends up running.
    "opus": 200_000,
    "sonnet": 200_000,
    "claude-opus-4-8": 200_000,
    "claude-sonnet-4-6": 200_000,
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
    # Claude Code runs only an Opus or Sonnet model — nothing else. "opus" is the
    # preferred tier; ClaudeCodeClient falls back to "sonnet" if the account lacks
    # Opus access. (CLI tier aliases auto-resolve to the latest model in each tier.)
    "claude-code": "opus",
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
    The model is always an Opus model, falling back to a Sonnet model when the account
    lacks Opus access — nothing else (an explicit ``model`` only chooses which of those
    two tiers to try first). The prompt is piped via stdin so long transcripts don't
    hit ARG_MAX.
    """

    # ---- CLI-version robustness (keyed by resolved binary path) -----------------
    # Older `claude` CLIs predate some flags we pass (e.g. --setting-sources,
    # --strict-mcp-config). An unrecognised flag makes the CLI exit 1 with
    # "unknown option '--…'", which previously broke generation outright on any
    # machine whose installed claude was older than the bundled one. We defend two
    # ways: (1) probe `claude --help` once and skip flags it doesn't advertise;
    # (2) a runtime safety net that strips any flag the CLI still rejects and
    # retries. Both results are cached per binary so we pay the cost at most once
    # per process. (The cache key is the binary path; if the user upgrades the same
    # claude in place mid-session it stays stale until restart — perf-only, and the
    # retry net still keeps generation working.)
    _help_cache: dict[str, str] = {}
    _unsupported_flags: dict[str, set[str]] = {}
    _cache_lock = threading.Lock()  # guards _help_cache populate-on-miss across threads
    # commander.js emits e.g.  error: unknown option '--setting-sources'. Tolerate the
    # quote dialects ' " ` , an optional ':' separator, and case — the retry net is our
    # backstop, so it must recognise every "unknown option" wording an old CLI emits.
    _UNKNOWN_OPT_RE = re.compile(
        r"""unknown option[:\s]*['"`]?(--[A-Za-z0-9][A-Za-z0-9-]*)""",
        re.IGNORECASE,
    )

    # ---- Model policy: an Opus model, else a Sonnet model, nothing else ----------
    # CLI tier aliases — they auto-resolve to the latest model in each tier on the
    # user's plan, so we never have to pin (or chase) a specific 4.x id.
    _OPUS = "opus"
    _SONNET = "sonnet"
    # The CLI's "model not on your plan" wording, e.g. "There's an issue with the
    # selected model (X). It may not exist or you may not have access to it." Used to
    # fall Opus → Sonnet when the account can't run the preferred tier. Anchored on
    # model-specific phrasing so a generic auth/MCP/org "no access" error does NOT
    # masquerade as a model problem and trigger a wrong tier switch.
    _MODEL_UNAVAILABLE_RE = re.compile(
        r"selected model"  # CLI's exact phrasing
        r"|may not have access to it"  # its trailing, model-specific clause
        r"|model[\s\S]{0,40}?(?:not (?:exist|found|available)|no access)",
        re.IGNORECASE,
    )

    # Common install locations, checked after PATH so it "just works" even when the
    # app is launched from a shell/process without the CLI on PATH. Not hardcoded
    # user paths — `~` expands per-user (to %USERPROFILE% on Windows), staying
    # portable across machines and OSes.
    _FALLBACK_PATHS = (
        # Unix / macOS
        "~/.local/bin/claude",
        "~/.claude/local/claude",
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
        # Windows — npm global shim (.cmd) + native installer (.exe)
        "~/AppData/Roaming/npm/claude.cmd",
        "~/AppData/Roaming/npm/claude.exe",
        "~/.local/bin/claude.exe",
        "~/AppData/Local/Programs/claude/claude.exe",
    )

    def __init__(self, *, binary: str | None = None, timeout: float = 600.0) -> None:
        path = self._resolve_binary(binary)
        if not path:
            # Plain-language guidance for non-technical users: the GUI detects this
            # error and shows an illustrated setup guide, but keep the full steps here
            # too as a fallback (and for CLI users). Lead with the no-setup option.
            # Must keep the words "not found" — tests match on that substring.
            raise RuntimeError(
                "Claude Code was not found on this computer.\n"
                "Quick option — no setup: in the 'Model backend' menu, switch to 'Cowork' to "
                "copy the prompt into Claude yourself.\n"
                "To use Claude Code automatically: (1) install Node.js from https://nodejs.org "
                "(2) open Command Prompt and run:  npm install -g @anthropic-ai/claude-code  "
                "(3) run:  claude  and log in with your Claude account  (4) reopen Meeting Minutes.\n"
                "(Advanced: set CLAUDE_CODE_BIN to the claude binary's path.)"
            )
        self._path: str = path  # narrowed: non-None past the guard above
        self._timeout = timeout

    @classmethod
    def _resolve_binary(cls, binary: str | None) -> str | None:
        """Resolve the claude CLI: explicit arg/env > PATH > known install dirs."""
        import shutil

        explicit = binary or os.environ.get("CLAUDE_CODE_BIN")
        if explicit:  # may be a bare name or a full path
            p = os.path.expanduser(explicit)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
            return shutil.which(explicit)
        found = shutil.which("claude")
        if found:
            return found
        for candidate in cls._FALLBACK_PATHS:
            p = os.path.expanduser(candidate)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return None

    @classmethod
    def _cli_help(cls, path: str) -> str:
        """Return (cached) ``claude --help`` text for *path*, or ``""`` if unreadable.

        Used to detect which optional flags the installed CLI version understands so
        we never hand an older CLI a flag it would reject. Probed at most once per
        binary per process — ``--help`` is a cheap, LLM-free call. Double-checked
        locking keeps concurrent first-callers (FastAPI runs generation in a thread
        pool) from each spawning their own probe.
        """
        cached = cls._help_cache.get(path)
        if cached is not None:
            return cached
        with cls._cache_lock:
            cached = cls._help_cache.get(path)
            if cached is not None:  # another thread won the race while we waited
                return cached
            import subprocess

            try:
                proc = subprocess.run(
                    [path, "--help"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                help_text = (proc.stdout or "") + (proc.stderr or "")
            except Exception:
                # Help unreadable → cache "" so _supports() trusts the flag and lets
                # the runtime retry net strip it if the CLI truly rejects it (and we
                # don't re-probe a binary whose --help keeps failing).
                help_text = ""
            cls._help_cache[path] = help_text
            return help_text

    def _supports(self, flag: str) -> bool:
        """Whether the resolved CLI advertises *flag* (and hasn't rejected it before).

        When ``--help`` could not be read we return ``True`` (don't pre-emptively drop
        a flag we can't verify) and rely on the retry safety net in ``generate``.
        """
        if flag in self._unsupported_flags.get(self._path, frozenset()):
            return False
        help_text = self._cli_help(self._path)
        if not help_text:
            return True
        # Count the flag as advertised only when it appears as an actual option entry:
        # at the start of an indented help line (optionally after a short alias like
        # "-p, "), not merely inside another option's description (the real
        # --strict-mcp-config help text contains the prose "from --mcp-config") nor as
        # a prefix of a longer flag (--model within --fallback-model). A bare substring
        # test gives false positives that waste a failing CLI spawn before the retry.
        return (
            re.search(rf"(?m)^\s+(?:-\w, )?{re.escape(flag)}(?=$|[\s=\[<,])", help_text)
            is not None
        )

    @classmethod
    def _model_attempts(cls, model: str) -> list[str]:
        """The Opus→Sonnet attempt order for *model*.

        Claude Code may run only an Opus or a Sonnet model — nothing else — so any
        request collapses onto a tier: an explicit Sonnet ask is tried first (then
        Opus); everything else (Opus, an empty/``default`` value, or an unrelated id
        like a Groq/Haiku name) prefers Opus and falls back to Sonnet.
        """
        if "sonnet" in (model or "").lower():
            return [cls._SONNET, cls._OPUS]
        return [cls._OPUS, cls._SONNET]

    def generate(self, system: str, user: str, *, model: str = "") -> str:
        import subprocess
        import tempfile

        prompt_text = f"{system}\n\n{user}" if system else user
        # Core flags every supported CLI understands; required for headless text out.
        base = [self._path, "-p", "--output-format", "text"]
        # Optional hardening flags — each newer than the core set. Lean invocation:
        # this is plain text generation, not an agent task, so skip the heavy startup:
        # no MCP servers (--strict-mcp-config + empty --mcp-config), and no user-level
        # hooks/rules (--setting-sources project,local — the SessionStart hook alone
        # makes its own LLM call on every invocation). Running in an empty cwd avoids
        # loading any project CLAUDE.md/hooks. Auth is unaffected — it lives in
        # ~/.claude/.credentials.json, not in settings.
        #
        # Each flag is OPTIONAL by design: an older CLI that predates one just reverts
        # to its default (heavier startup) and still generates correctly. We include a
        # flag only if --help advertises it, and the retry loop below strips any the
        # CLI rejects, so an unrecognised flag can never break generation. (A CLI old
        # enough to lack these flags falls back to loading user-level hooks/MCP —
        # generation still succeeds, just with the heavier startup these flags avoid.)
        optional = [
            ["--strict-mcp-config"],
            ["--mcp-config", '{"mcpServers":{}}'],
            ["--setting-sources", "project,local"],
        ]
        optional = [frag for frag in optional if self._supports(frag[0])]

        # Model policy: an Opus model, else a Sonnet model, nothing else. Always pass
        # an explicit tier (so we never inherit whatever the CLI happens to default
        # to), trying Opus first and falling back to Sonnet if the account can't run
        # it. `use_model` only drops to False on a CLI so old it lacks --model.
        attempts = self._model_attempts(model)
        model_idx = 0
        use_model = self._supports("--model")

        while True:
            cmd = list(base)
            for frag in optional:
                cmd += frag
            if use_model:
                cmd += ["--model", attempts[model_idx]]
            try:
                with tempfile.TemporaryDirectory() as workdir:
                    proc = subprocess.run(
                        cmd,
                        input=prompt_text,
                        capture_output=True,
                        text=True,
                        # Force UTF-8 so Arabic prompts/output aren't mangled by
                        # Windows' default cp1252 ('charmap') encoding on the child's
                        # stdin/stdout (else an Arabic prompt raises 'charmap codec
                        # can't encode').
                        encoding="utf-8",
                        errors="replace",
                        timeout=self._timeout,
                        cwd=workdir,
                        # On Windows, suppress the console window that would otherwise
                        # flash for each CLI call when launched from a windowed
                        # (no-console) app. getattr keeps this 0/inert on POSIX where
                        # the flag does not exist.
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Claude Code CLI timed out after {self._timeout:.0f}s"
                ) from exc
            if proc.returncode == 0:
                break
            stderr = proc.stderr or ""
            detail = (proc.stderr or proc.stdout or "").strip()
            # (1) An older CLI rejected a flag we passed? Scan only stderr — commander
            # writes its diagnostics there, so a transcript or model reply that echoes
            # "unknown option …" in stdout can't trigger a spurious strip.
            rejected = self._UNKNOWN_OPT_RE.search(stderr)
            if rejected:
                name = rejected.group(1)
                if name == "--model":
                    # CLI too old to even know --model: drop tier enforcement and
                    # retry (it uses its own default model — unavoidable on such a CLI).
                    self._unsupported_flags.setdefault(self._path, set()).add("--model")
                    use_model = False
                    continue
                idx = next(
                    (i for i, frag in enumerate(optional) if frag[0] == name), None
                )
                if idx is not None:
                    # Remember it (so future calls skip it) and retry the slimmer cmd.
                    self._unsupported_flags.setdefault(self._path, set()).add(
                        optional.pop(idx)[0]
                    )
                    continue
                # An "unknown option" we didn't inject (a core flag, or something a
                # future change added): can't strip it → surface, never fall through to
                # the model-tier check (keeps unknown-option strictly terminal here).
                raise RuntimeError(
                    f"Claude Code CLI failed (exit {proc.returncode}): {detail}"
                )
            # (2) Preferred tier not available on this account → fall to the next tier
            # (Opus → Sonnet). Only when --model is in play and a tier remains.
            if (
                use_model
                and model_idx + 1 < len(attempts)
                and self._MODEL_UNAVAILABLE_RE.search(stderr)
            ):
                model_idx += 1
                continue
            # Anything else (not logged in, both tiers unavailable, …) → surface as-is.
            raise RuntimeError(
                f"Claude Code CLI failed (exit {proc.returncode}): {detail}"
            )
        out = proc.stdout.strip()
        if not out:
            raise RuntimeError("Claude Code CLI returned empty output")
        return out


def launch_claude_login(binary: str | None = None) -> None:
    """Open an interactive Claude Code session so the user can complete the one-time
    browser login.

    Resolves the CLI the same way ``ClaudeCodeClient`` does (explicit arg, then
    ``CLAUDE_CODE_BIN``, then PATH / known install locations — including the bundled
    copy the desktop launcher wires up). Shared by the tray "Log in to Claude" item
    and the in-app button so both behave identically. Raises ``RuntimeError`` when no
    ``claude`` can be found.
    """
    import subprocess
    import sys

    claude = binary or os.environ.get("CLAUDE_CODE_BIN") or ClaudeCodeClient._resolve_binary(None)
    if not claude:
        raise RuntimeError("Claude Code was not found, so there is nothing to log in to.")
    if sys.platform == "win32":
        # 'start "title" "program"' opens a visible console running claude
        # interactively; it walks the user through logging in via the browser.
        subprocess.Popen(f'start "Claude Code login" "{claude}"', shell=True)  # noqa: S602
    else:
        subprocess.Popen([claude])  # noqa: S603


def claude_code_available(timeout: float = 10.0) -> tuple[bool, str | None]:
    """Startup check: is a *working* Claude Code CLI present?

    Resolves the binary (CLAUDE_CODE_BIN / PATH / known locations / the bundled copy)
    and runs ``claude --version``. Returns ``(ok, path)`` where ``ok`` is True only if
    the CLI both resolves AND runs. Does NOT check login — that surfaces at generate
    time. UTF-8 + no-console-window flags match how generation invokes the CLI.
    """
    import subprocess

    path = ClaudeCodeClient._resolve_binary(None)
    if not path:
        return (False, None)
    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (proc.returncode == 0, path)
    except Exception:
        return (False, path)


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
