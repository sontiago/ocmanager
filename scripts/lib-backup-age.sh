#!/usr/bin/env bash
# Свежесть резервной копии. Подключается из doctor.sh и из теста.
# backup_is_fresh <файл-метки> <сейчас, epoch-секунды> [макс. часов, по умолчанию 36]
# Метка — строка ISO-времени последней успешной копии (пишет ocm backup).
backup_is_fresh() {
    local marker=$1 now=$2 max_hours=${3:-36} stamp then
    [ -r "$marker" ] || return 1
    stamp=$(head -n 1 "$marker")
    then=$(date -d "$stamp" +%s 2>/dev/null) || return 1
    [ $((now - then)) -le $((max_hours * 3600)) ]
}
