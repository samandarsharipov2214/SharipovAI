#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/vps/apply-nginx-session-fix.sh" >&2
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="$SOURCE_DIR/nginx-sharipovai.conf"
TARGET_FILE="/etc/nginx/sites-available/sharipovai"
ENABLED_FILE="/etc/nginx/sites-enabled/sharipovai"
BACKUP_DIR="/etc/nginx/sharipovai-backups"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [ ! -f "$SOURCE_FILE" ]; then
  echo "Missing $SOURCE_FILE" >&2
  exit 2
fi

install -d -m 700 "$BACKUP_DIR"
if [ -f "$TARGET_FILE" ]; then
  cp -a "$TARGET_FILE" "$BACKUP_DIR/sharipovai.$TIMESTAMP.conf"
fi

install -m 0644 "$SOURCE_FILE" "$TARGET_FILE"
ln -sfn "$TARGET_FILE" "$ENABLED_FILE"

nginx -t
systemctl reload nginx

curl --fail --silent --show-error http://127.0.0.1/health >/dev/null

echo "SharipovAI nginx session fix applied successfully."
echo "Clear the old site cookie once, then sign in again at http://85.137.88.17/login"
