#!/usr/bin/env bash
set -euo pipefail

# SQLite WAL-safe backup script
# Usage: ./deploy/backup_db.sh [output_dir]
# Uses sqlite3 .backup (safe with WAL mode, handles concurrent writers)

DB_PATH="${DATABASE_PATH:-$(cd "$(dirname "$0")/.." && pwd)/data/stock_analysis.db}"
OUTPUT_DIR="${1:-$(dirname "$DB_PATH")/backups}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "[ERROR] Database not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$OUTPUT_DIR/hivelogic_${TIMESTAMP}.db"

if command -v sqlite3 &>/dev/null; then
  sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
else
  cp "$DB_PATH" "$BACKUP_FILE"
  cp "${DB_PATH}-wal" "${BACKUP_FILE}-wal" 2>/dev/null || true
  cp "${DB_PATH}-shm" "${BACKUP_FILE}-shm" 2>/dev/null || true
fi

gzip -f "$BACKUP_FILE"
echo "[backup] Created: ${BACKUP_FILE}.gz"

# Retention: keep last 30 backups
cd "$OUTPUT_DIR"
ls -t hivelogic_*.db.gz | tail -n +31 | xargs rm -f 2>/dev/null || true
echo "[backup] Retention: keeping last 30 backups in $OUTPUT_DIR"
