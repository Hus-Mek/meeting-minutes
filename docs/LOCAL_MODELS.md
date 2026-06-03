# Running minutes generation on a local model (free, private, offline)

The app can generate the Arabic minutes (محضر اجتماع) with a **local** model instead
of Groq/OpenRouter. Local runs are free and never leave the machine. You point the
app at any **OpenAI‑compatible local server** — **LM Studio** (recommended for an
Intel GPU) or **Ollama** — and select `--backend lmstudio` or `--backend ollama`.

> **Where to run this:** the laptop with the Intel GPU. These steps download several
> GB of model weights — do them **on that machine**, not in this dev checkout.

## What to expect (read this first)

- **No open model ≤ ~9B matches Sonnet 4.6** on formal Arabic. Local is a cost/privacy
  win, not a quality match. The goal is the *closest acceptable* model — pick it by
  **benchmarking** (below), not by spec sheets.
- Best **Arabic writers** that fit your box: **ALLaM‑7B** and **Yehia‑7B** (Apache‑2.0).
  They lead the Arabic *grammar/writing* and *generation* leaderboards (AraLingBench,
  AraGen), which predict minute‑writing better than MCQ leaderboards. Their native
  context is only **4K tokens**, so the app's map‑reduce splits the transcript
  automatically — that's expected, not a bug.
- **Gemma 4 E4B** and **Qwen3‑8B** are strong *generalists* (Apache‑2.0, big context)
  but only "adequate" at formal Arabic — benchmark them, don't assume they win.

## Target hardware: 16 GB RAM, ~9 GB VRAM (Intel iGPU, Vulkan)

- Stick to **7–9B models at Q4_K_M** (~4.5–6 GB). They fit fully in ~9 GB VRAM with
  room for the KV cache, so you get **full GPU offload**.
- **Skip** the 26B/30B MoEs (Gemma 4 26B‑A4B ≈ 17 GB Q4, Qwen3‑30B‑A3B ≈ 18.6 GB) —
  they don't fit 9 GB VRAM at a usable quant.
- Keep an eye on **context length**: a big context inflates the KV cache and can
  overflow VRAM. Use the per‑model values below.

---

## Option A — LM Studio (recommended for Intel + Vulkan)

LM Studio has a GUI for downloading GGUFs, a **Vulkan llama.cpp** runtime that works on
Intel GPUs, and a built‑in OpenAI‑compatible server. Refs:
[Vulkan runtime for Intel](https://lmstudio.ai/docs/app/system-requirements),
[OpenAI‑compat server](https://lmstudio.ai/docs/developer/openai-compat).

1. **Install** LM Studio and, on first run, make sure the **GPU/runtime** is set to
   **"Vulkan llama.cpp"** (Settings → Runtimes / the runtime selector). Prereqs for
   Intel Vulkan: recent GPU driver exposing **Vulkan 1.3** and the
   [LunarG Vulkan runtime](https://vulkan.lunarg.com/); verify with
   `vulkaninfo | grep apiVersion`.
2. **Download models** (search tab → paste a GGUF repo; pick a **Q4_K_M** quant):
   | Model | HF GGUF repo to search (verify exact name) | Role |
   |---|---|---|
   | ALLaM‑7B‑Instruct | `Omartificial-Intelligence-Space/ALLaM-7B-Instruct-preview-Q4_K_M-GGUF` (or `eltay89/ALLaM-7B-Instruct-GGUF`) | Arabic‑writing leader |
   | Yehia‑7B‑preview | search `Yehia-7B-preview GGUF` (Navid‑AI; community quant) | Arabic generation leader |
   | **Qwen3.5‑9B** | `unsloth/Qwen3.5-9B-GGUF` | **strongest generalist** — 201 langs incl. Arabic, 262K ctx. **LM Studio only** (Qwen3.5 GGUFs don't load in Ollama yet); run text‑only. |
   | Gemma 4 E4B | `unsloth/gemma-4-E4B-it-GGUF` or `ggml-org/gemma-4-E4B-it-GGUF` | generalist, lighter |
   | Qwen3‑8B | `Qwen/Qwen3-8B-GGUF` or `bartowski/Qwen_Qwen3-8B-GGUF` | generalist (older; Qwen3.5‑9B supersedes if it fits) |
   | Fanar‑1‑9B | search `Fanar-1-9B-Instruct GGUF` (skip if none published) | knowledge generalist |
3. **Load a model** and in the loader set:
   - **GPU Offload / GPU Layers → max** (the slider's recommended max for your VRAM).
   - **Context length**: ALLaM/Yehia/Fanar → **4096** (their hard limit); Gemma 4 E4B /
     Qwen3‑8B → **8192** (watch the "estimated memory" readout stays under ~9 GB).
   - If offered, set **KV cache type = q8_0** to halve KV memory.

   **Important — tell the app the context you chose.** The app sizes its map‑reduce to
   fit the model's context. Set `LOCAL_LLM_NUM_CTX` to the **context length you loaded**
   (the env wins over built‑in defaults, and is the only reliable signal because LM
   Studio model ids are arbitrary). E.g. `export LOCAL_LLM_NUM_CTX=4096` for ALLaM, or
   `8192` for the generalists. If you forget, the known Ollama tags still have correct
   built‑in defaults; arbitrary LM Studio ids fall back to a safe 8192.
4. **Start the server**: Developer tab → toggle **Status → ON** (or `lms server start`).
   It serves at **`http://localhost:1234/v1`** — which is the `lmstudio` backend's
   default, so no extra config is needed.
5. **The model id** LM Studio reports (Developer tab, or `GET /v1/models`) is what you
   pass as `--model` to the app/benchmark.

Troubleshooting Intel Vulkan: if a model fails to load with multiple GPUs present, use
the Vulkan SDK's `vkconfig` to *force a single physical device*
([known issue #1393](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1393)).

---

## Option B — Ollama (simplest; may run CPU‑only on Intel)

Ollama is one‑line to install but its Intel‑GPU offload is limited — on this hardware
it often runs **CPU‑only** (still fine, just slower: ~7–14 tok/s for a 7B). Prefer LM
Studio if you want the GPU. To use Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve            # in one terminal
bash scripts/setup_ollama_models.sh   # pulls the slate + sets num_ctx via Modelfiles
```

`scripts/setup_ollama_models.sh` pulls the library models (`iKhalid/ALLaM:7b`,
`gemma4:e4b`, `qwen3:8b`) and builds num_ctx‑tuned variants. Ollama serves at
`http://localhost:11434/v1` — the `ollama` backend's default.

---

## Run the benchmark, then pick the winner

With the server up and the slate downloaded, run each model on a **real transcript**
and compare against your **known‑good Sonnet output**:

```bash
# LM Studio: pass the exact model ids you loaded.
# Set LOCAL_LLM_NUM_CTX to the SMALLEST context in your slate (4096 if ALLaM/Yehia
# are included) so every model fits; or benchmark specialists and generalists in
# two passes with their own num_ctx.
LOCAL_LLM_NUM_CTX=4096 python scripts/bench_local.py --backend lmstudio \
    --transcript meeting.json --notes notes.md --reference sonnet_minutes.md \
    --models "allam-7b-instruct,yehia-7b,gemma-4-e4b-it,qwen3-8b"

# Ollama: default slate
python scripts/bench_local.py --backend ollama \
    --transcript meeting.json --notes notes.md --reference sonnet_minutes.md
```

It writes each model's minutes to `bench_out/<model>.md` plus a timing table, and
copies your Sonnet reference to `bench_out/_reference.md`. **Open them side by side and
judge the Arabic** (grammar, gender agreement, names kept verbatim, table fidelity).

The benchmark **only ever talks to your local server** — it refuses cloud backends, so
it can't spend money.

## Use the winner

```bash
# CLI
python -m meeting_minutes.cli --transcript meeting.json --notes notes.md \
    --out minutes.md --backend lmstudio --model <winning-model-id>

# Web UI: start the app, choose the lmstudio/ollama backend, set the model id.
```

### Env knobs (all optional)

| Var | Purpose |
|---|---|
| `LOCAL_LLM_BASE_URL` | Override the server URL for either backend (e.g. a box on the LAN). |
| `LOCAL_LLM_API_KEY` | Auth header, if your server requires one. |
| `LOCAL_LLM_NUM_CTX` | Context length to size map‑reduce against — **set to the value you loaded the model with.** |
| `LOCAL_LLM_MAX_OUTPUT_TOKENS` | Cap on generated tokens per call (default 4096). Lower it for 4K‑context models. |

To make a local model the default when `--model` is omitted, edit `DEFAULT_LOCAL_MODEL`
in `meeting_minutes/llm.py`.
