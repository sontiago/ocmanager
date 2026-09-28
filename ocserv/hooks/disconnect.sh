#!/bin/sh
# disconnect.sh — финальные счётчики сессии в панель. Сбой отправки не должен
# влиять на ocserv, поэтому всегда exit 0; потерю закроет сбор трафика.
. "${OCM_HOOKS_ENV:-/etc/ocmanager/hooks.env}" 2>/dev/null || exit 0
TOKEN=$(cat "${INTERNAL_TOKEN_FILE:-/nonexistent}" 2>/dev/null) || exit 0
num() { case "$1" in '' | *[!0-9]*) echo 0 ;; *) echo "$1" ;; esac; }
BODY=$(printf '{"username":"%s","session_id":"%s","bytes_in":%s,"bytes_out":%s,"duration_sec":%s,"remote_ip":"%s"}' \
  "${USERNAME:-}" "${ID:-}" "$(num "${STATS_BYTES_IN:-}")" "$(num "${STATS_BYTES_OUT:-}")" \
  "$(num "${STATS_DURATION:-}")" "${IP_REAL:-}")
curl -fsS -m 3 -X POST "$SESSION_END_URL" \
  -H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json" \
  --data "$BODY" >/dev/null 2>&1
exit 0
