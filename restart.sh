#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/server.log"
PORT=8000

# 既存プロセスを停止
PID=$(lsof -ti:$PORT 2>/dev/null || true)
if [ -n "$PID" ]; then
  echo "Stopping PID $PID on port $PORT..."
  kill "$PID"
  sleep 1
fi

# 起動
echo "Starting server (log: $LOG)..."
cd "$SCRIPT_DIR"
uv run uvicorn app.main:app --host 127.0.0.1 --port $PORT >> "$LOG" 2>&1 &
NEW_PID=$!

# 起動確認
sleep 3
if kill -0 "$NEW_PID" 2>/dev/null; then
  echo "Server running — PID $NEW_PID  http://127.0.0.1:$PORT"
else
  echo "Server failed to start. Last log:"
  tail -20 "$LOG"
  exit 1
fi
