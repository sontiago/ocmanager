#!/bin/sh
# Любой HTTP-ответ (даже страница камуфляжа) = TLS-слушатель жив.
proxy=""
[ "${OCSERV_PROXY_PROTOCOL:-false}" = "true" ] && proxy="--haproxy-protocol"
# shellcheck disable=SC2086 — $proxy пуст или один флаг
exec curl -ks $proxy -o /dev/null https://localhost:443/
