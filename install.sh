#!/usr/bin/env bash
# Установка ocmanager одной командой: sudo ./install.sh
# Логика мастера — deploy/installer (Python, только стандартная библиотека).
set -euo pipefail

cd "$(dirname "$0")"

# Язык сообщений этого скрипта: английский, русский — по OCM_LANG=ru или --lang ru.
lang="${OCM_LANG:-en}"
prev=""
for arg in "$@"; do
    if [ "$arg" = "--lang=ru" ] || { [ "$prev" = "--lang" ] && [ "$arg" = "ru" ]; }; then lang=ru; fi
    prev="$arg"
done
say() { if [ "$lang" = ru ]; then echo "$1" >&2; else echo "$2" >&2; fi; }

if [ "$(id -u)" -ne 0 ]; then
    say "Запустите установщик от root: sudo ./install.sh" "Run the installer as root: sudo ./install.sh"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    say "Нужен python3 (3.10 или новее). Установите: apt-get install -y python3" \
        "python3 (3.10 or newer) is required. Install it: apt-get install -y python3"
    exit 1
fi

# -I: интерпретатор не берёт модули из текущего каталога и из PYTHONPATH — мы root.
# (the interpreter ignores the current directory and PYTHONPATH: we run as root)
exec python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); from installer.install import main; sys.exit(main(sys.argv[2:]))' "$PWD/deploy" "$@"
