#!/usr/bin/env bash
# Set up the local Arabic-minutes model slate in Ollama.
#
# RUN THIS ON THE TARGET LAPTOP (the Intel-GPU box) — it downloads several GB.
# It does NOT run any model; it just pulls weights and creates context-tuned
# variants so the app's map-reduce fits each model's context window.
#
# Prefer LM Studio for Intel GPU offload (see docs/LOCAL_MODELS.md); use this if
# you want the Ollama CLI path (often CPU-only on Intel, still works).
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install it first:" >&2
  echo "  curl -fsSL https://ollama.com/install.sh | sh" >&2
  exit 1
fi

echo "==> Pulling base models from the Ollama library (this downloads GBs)…"
ollama pull iKhalid/ALLaM:7b      # Arabic-writing leader (4K native context)
ollama pull gemma4:e4b            # generalist, Apache-2.0
ollama pull qwen3:8b              # generalist, Apache-2.0

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Context-tuned variants. ALLaM is 4K-native; generalists get 8192 (KV-cache
# friendly on a ~9GB-VRAM box). Match these with LOCAL_LLM_NUM_CTX when you run.
create_variant() {
  local name="$1" base="$2" ctx="$3"
  printf 'FROM %s\nPARAMETER num_ctx %s\nPARAMETER temperature 0.2\n' "$base" "$ctx" \
    > "$WORK/Modelfile"
  echo "==> Creating $name (num_ctx=$ctx) from $base"
  ollama create "$name" -f "$WORK/Modelfile"
}

create_variant allam-mm  iKhalid/ALLaM:7b 4096
create_variant gemma4-mm gemma4:e4b       8192
create_variant qwen3-mm  qwen3:8b         8192

cat <<'EOF'

==> Done. Yehia-7B and Fanar-1-9B are not in the Ollama library — download a GGUF
    from Hugging Face and create them the same way, e.g.:
      printf 'FROM ./Yehia-7B-preview.Q4_K_M.gguf\nPARAMETER num_ctx 4096\n' > Modelfile
      ollama create yehia-mm -f Modelfile

==> Benchmark the slate (set LOCAL_LLM_NUM_CTX to the smallest context, 4096, so
    every model fits in one pass; or run the 8192 generalists separately):
      ollama serve   # in another terminal
      LOCAL_LLM_NUM_CTX=4096 python scripts/bench_local.py --backend ollama \
        --transcript meeting.json --notes notes.md --reference sonnet_minutes.md \
        --models "allam-mm,gemma4-mm,qwen3-mm"
EOF
