#!/usr/bin/env bash
# Установка ocmanager одной командой: sudo ./install.sh
# Логика мастера — deploy/installer (Python, только стандартная библиотека).
set -euo pipefail

cd "$(dirname "$0")"

if [ "$(id -u)" -ne 0 ]; then
    echo "Запустите установщик от root: sudo ./install.sh" >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Нужен python3 (3.10 или новее). Установите: apt-get install -y python3" >&2
    exit 1
fi

PYTHONPATH="$PWD/deploy" exec python3 -m installer.install "$@"
