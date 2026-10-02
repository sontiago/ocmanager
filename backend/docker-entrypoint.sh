#!/bin/sh
# Роли одного образа: docker run <image> <роль> [аргументы]. exec — чтобы сигналы
# (SIGTERM от docker stop) доходили до процесса, а не до оболочки.
set -eu

role="${1:-}"
[ "$#" -gt 0 ] && shift

case "$role" in
    api-public)
        # За Caddy адрес клиента приходит в X-Forwarded-For (решение П7-10).
        exec uvicorn ocmanager.apps.public_api:create_app --factory \
            --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' "$@"
        ;;
    api-admin)
        # Все интерфейсы контейнера; наружу порт публикуется только на 127.0.0.1 хоста.
        exec uvicorn ocmanager.apps.admin_api:create_app --factory \
            --host 0.0.0.0 --port 8080 "$@"
        ;;
    worker) exec python -m ocmanager.apps.worker "$@" ;;
    bot) exec python -m ocmanager.apps.bot "$@" ;;
    migrate) exec alembic upgrade head "$@" ;;
    cli) exec ocmanager "$@" ;;
    *)
        echo "роль: api-public | api-admin | worker | bot | migrate | cli <команда>" >&2
        exit 64
        ;;
esac
