#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ ! -x ".venv/bin/python" ]]; then
  osascript -e 'display dialog "Сначала установите зависимости проекта в .venv." buttons {"OK"} with title "Directum Log Analyzer"'
  exit 1
fi
.venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port 8000 --reload &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
sleep 2
open "http://127.0.0.1:8000/"
wait "$server_pid"
