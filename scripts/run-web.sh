#!/usr/bin/env bash
# Phase 2: asyncio.Lock job mutex requires --workers 1 (D-12). The runner's
# lock is process-local, so multiple uvicorn workers would each accept
# concurrent jobs and race on scripts/jx.sh. `python -m qlsv` calls
# `uvicorn.run(app, ...)` which is single-process by construction (one
# worker, never multi-process); this script keeps the constraint visible
# in the launcher so the Phase 4 systemd unit (which CAN multi-worker) is
# forced to pin --workers 1 explicitly.
#
# Dev launcher cho qlsv-web. Vietnamese (no diacritics) per bash convention.
#
# Cho admin: dung ../start.sh o repo root thay vi script nay — start.sh tu
# bootstrap venv + config. Script nay danh cho dev / khi venv da co san.
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
if [ -x "$VENV/bin/python" ]; then
  PYTHON="$VENV/bin/python"
else
  PYTHON="python3"
fi

echo "Khoi dong qlsv-web (--workers 1 enforced by python -m qlsv entrypoint)..."
exec "$PYTHON" -m qlsv
