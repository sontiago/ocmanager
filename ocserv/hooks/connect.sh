#!/bin/sh
# connect.sh — ocserv вызывает на каждое подключение; ненулевой код = отказ.
# Никаких сетевых вызовов: VPN должен работать при лежащей панели.
# -x — строка целиком (c1-d1 не совпадёт с c1-d10), -F — без регулярок.
. "${OCM_HOOKS_ENV:-/etc/ocmanager/hooks.env}" 2>/dev/null || exit 1
[ -n "${USERNAME:-}" ] || exit 1
[ -r "${ALLOWLIST:-}" ] || exit 1
exec grep -qxF -- "$USERNAME" "$ALLOWLIST"
