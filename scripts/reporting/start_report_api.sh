#!/usr/bin/env bash
# Start / restart Delhivery report API (used by n8n daily workflow)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${REPORT_API_LOG:-/tmp/delhivery_report_api.log}"
PID_FILE="${REPORT_API_PID:-/tmp/delhivery_report_api.pid}"

export TB_URL="${TB_URL:-http://127.0.0.1:9091}"
export REPORT_API_PORT="${REPORT_API_PORT:-5060}"
export REPORT_OUTPUT_DIR="${REPORT_OUTPUT_DIR:-/var/tmp/delhivery-reports}"
export REPORT_TZ="${REPORT_TZ:-Asia/Kolkata}"
# Reachable from n8n container (docker bridge / host IP)
export REPORT_PUBLIC_BASE="${REPORT_PUBLIC_BASE:-http://172.31.16.106:5060}"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Stopping existing report API pid $(cat "$PID_FILE")"
  kill "$(cat "$PID_FILE")" || true
  sleep 1
fi

cd "$DIR"
nohup python3 report_server.py >>"$LOG" 2>&1 &
echo $! >"$PID_FILE"
echo "Started report API pid=$(cat "$PID_FILE") port=$REPORT_API_PORT log=$LOG"
sleep 1
curl -sf "http://127.0.0.1:${REPORT_API_PORT}/health" && echo
