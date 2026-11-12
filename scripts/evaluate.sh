#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --frozen --extra dev
uv run --frozen python scripts/prepare_embeddings.py
HF_HUB_OFFLINE=1 uv run --frozen soc-triage offline
HF_HUB_OFFLINE=1 uv run --frozen python scripts/run_inspect.py
