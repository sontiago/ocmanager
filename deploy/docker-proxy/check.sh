#!/usr/bin/env bash
# Проверка белого списка прокси к Docker. Из корня репозитория:
#   make -C backend ocserv-up && deploy/docker-proxy/check.sh
set -uo pipefail
cd "$(dirname "$0")"

PORT=23750
NAME=ocm-proxy-check
OTHER=$(docker ps --format '{{.Names}}' | grep -v -e '^ocm-ocserv$' -e "^$NAME$" | head -n1)
fails=0

docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --user 0:0 -p "127.0.0.1:$PORT:2375" \
    -v "$PWD/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    haproxy:3.0-alpine >/dev/null || exit 1
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT
sleep 2
export DOCKER_HOST="tcp://127.0.0.1:$PORT"

allow() { if "${@:2}" >/dev/null 2>&1; then echo "  OK   разрешено: $1"; else echo "  FAIL разрешено, но отказано: $1"; fails=$((fails + 1)); fi; }
deny()  { if "${@:2}" >/dev/null 2>&1; then echo "  FAIL запрещено, но прошло: $1"; fails=$((fails + 1)); else echo "  OK   запрещено: $1"; fi; }

allow "inspect ocserv"      docker inspect -f '{{.State.Status}}' ocm-ocserv
allow "exec occtl"          docker exec ocm-ocserv occtl -j show status
allow "logs ocserv"         docker logs --tail 3 ocm-ocserv
allow "restart ocserv"      docker restart ocm-ocserv
deny  "docker ps"           docker ps
deny  "docker images"       docker images
deny  "docker run"          docker run --rm alpine true
deny  "docker info"         docker info
if [ -n "$OTHER" ]; then
    deny "exec в чужой контейнер ($OTHER)" docker exec "$OTHER" id
    deny "inspect чужого контейнера"       docker inspect "$OTHER"
    deny "stop чужого контейнера"          docker stop "$OTHER"
    deny "logs чужого контейнера по имени" docker logs --tail 1 "$OTHER"
fi

[ "$fails" -eq 0 ] && echo "прокси: всё как задумано" || { echo "прокси: ошибок $fails"; exit 1; }
