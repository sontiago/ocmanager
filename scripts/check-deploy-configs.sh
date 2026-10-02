#!/usr/bin/env bash
# Проверка конфигов деплоя без запуска стека. Из корня репозитория: scripts/check-deploy-configs.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export DOMAIN_APP=app.example.com DOMAIN_VPN=vpn.example.com ACME_EMAIL=admin@example.com

echo "== caddy"
docker run --rm -e DOMAIN_APP -e DOMAIN_VPN -e ACME_EMAIL \
    -v "$PWD/deploy/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
    caddy:2.8-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

echo "== nginx"
docker run --rm -e DOMAIN_VPN \
    -v "$PWD/deploy/nginx/nginx.conf.template:/t:ro" \
    nginx:1.27-alpine sh -c "envsubst '\${DOMAIN_VPN}' </t >/etc/nginx/nginx.conf && nginx -t"

echo "== haproxy"
docker run --rm \
    -v "$PWD/deploy/docker-proxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" \
    haproxy:3.0-alpine haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg

if [ -f deploy/docker-compose.yml ]; then
    echo "== compose"
    docker compose -f deploy/docker-compose.yml --env-file deploy/.env.example config -q
fi
echo "конфиги валидны"
