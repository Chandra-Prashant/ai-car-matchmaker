#!/usr/bin/env bash
# Start every local service. Logs in /tmp; stop with ./dev.sh stop
set -e
cd "$(dirname "$0")"

if [ "$1" = "stop" ]; then
  pkill -f "uvicorn app.main" || true
  pkill -f "http.server 3001" || true
  pkill -f "next dev" || true
  echo "stopped"
  exit 0
fi

pkill -f "uvicorn app.main" 2>/dev/null || true
pkill -f "http.server 3001" 2>/dev/null || true

(cd backend && nohup uv run uvicorn app.main:app --port 8000 > /tmp/api.log 2>&1 &)
nohup python3 -m http.server 3001 --directory sandbox > /tmp/sandbox.log 2>&1 &
(cd frontend && nohup npm run dev > /tmp/web.log 2>&1 &)

sleep 5
printf "api      %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/health)"
printf "sandbox  %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3001)"
printf "frontend %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000)"
