#!/usr/bin/env bash
set -euo pipefail

# HiveLogic 服务端启动脚本
# 用法: ./deploy/run_server.sh [--port 8100] [--host 0.0.0.0]
# 依赖: uv (https://docs.astral.sh/uv/)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$REPO_ROOT/server"

PORT="${HIVELOGIC_PORT:-8100}"
HOST="${HIVELOGIC_HOST:-0.0.0.0}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --port)  PORT="$2";  shift 2 ;;
    --host)  HOST="$2";  shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ ! -d "$SERVER_DIR" ]]; then
  echo "[ERROR] server/ directory not found at: $SERVER_DIR" >&2
  exit 1
fi

if ! command -v uv &>/dev/null; then
  echo "[ERROR] uv is not installed. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

export DATABASE_PATH="${DATABASE_PATH:-$REPO_ROOT/data/stock_analysis.db}"
export LOG_DIR="${LOG_DIR:-$REPO_ROOT/logs}"

mkdir -p "$(dirname "$DATABASE_PATH")" "$LOG_DIR"

echo "[run_server] SERVER_DIR=$SERVER_DIR"
echo "[run_server] HOST=$HOST  PORT=$PORT"
echo "[run_server] DATABASE_PATH=$DATABASE_PATH"
echo "[run_server] LOG_DIR=$LOG_DIR"

cd "$SERVER_DIR"
exec uv run python main.py --serve-only --host "$HOST" --port "$PORT"
