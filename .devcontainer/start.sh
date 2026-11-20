#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
if [ -z "${APP_PASSWORD:-}" ]; then
  echo "Open ML Studio was not started: create a private .env file with APP_PASSWORD=your-strong-password."
  exit 0
fi
if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  echo "Open ML Studio is already running on port 8000."
  exit 0
fi
PYTHON=python
if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; fi
nohup "$PYTHON" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 >/tmp/open-ml-studio.log 2>&1 </dev/null &
echo "Open ML Studio startup requested. Check the Ports tab for port 8000."
