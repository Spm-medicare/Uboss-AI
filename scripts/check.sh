#!/usr/bin/env bash
# Everything CI will run, in the order that fails fastest.
#
# Run this before pushing. It is the same set of checks the pipeline uses (1.6.4), so a green
# run here means a green run there — the point of having one command is that nobody has to
# remember which six to run.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "── backend ────────────────────────────────────────────────────"
( cd backend && uv run ruff check . )
( cd backend && uv run mypy src )

echo "── frontend ───────────────────────────────────────────────────"
( cd frontend && npm run lint --silent )
( cd frontend && npx tsc --noEmit )

echo "── tests ──────────────────────────────────────────────────────"
# Builds a throwaway database from the migrations and drops it afterwards. It never touches
# the development database.
set -a; source backend/.env; set +a
backend/.venv/Scripts/python.exe -m pytest tests/ || uv run --directory backend python -m pytest ../tests

echo
echo "All checks passed."
