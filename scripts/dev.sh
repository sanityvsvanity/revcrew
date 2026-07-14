#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Ensure .env exists
if [ ! -f .env ]; then
    echo "[dev] No .env found — copying .env.example"
    cp .env.example .env
fi

echo "[dev] Starting RevCrew on http://localhost:8000 ..."
exec .venv/bin/uvicorn main:app --reload --port 8000