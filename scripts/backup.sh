#!/bin/sh
# Scheduled PostgreSQL backup — runs inside the `backup` compose service
# (postgres:15-alpine image, so pg_dump is available).
#
# Env: DATABASE_URL (postgres://...), BACKUP_DIR (default /backups),
#      BACKUP_KEEP (default 14), BACKUP_INTERVAL_SECONDS (default 86400)
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

mkdir -p "$BACKUP_DIR"

echo "[backup] Starting scheduled backups every ${INTERVAL}s (keep ${BACKUP_KEEP})"

while true; do
  STAMP="$(date -u +%Y%m%d-%H%M%S)"
  DEST="${BACKUP_DIR}/backup-${STAMP}.sql.gz"
  echo "[backup] ${STAMP} — dumping to ${DEST}"
  if pg_dump --no-owner "${DATABASE_URL}" | gzip -6 > "${DEST}"; then
    echo "[backup] OK ($(du -h "${DEST}" | cut -f1))"
  else
    echo "[backup] FAILED — removing partial file" >&2
    rm -f "${DEST}"
  fi

  # Retention: keep the newest $BACKUP_KEEP files
  ls -1t "${BACKUP_DIR}"/backup-*.sql.gz 2>/dev/null | tail -n "+$((BACKUP_KEEP + 1))" | while read -r OLD; do
    echo "[backup] rotating out ${OLD}"
    rm -f "${OLD}"
  done

  sleep "${INTERVAL}"
done
