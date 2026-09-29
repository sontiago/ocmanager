"""Каждый процесс регистрирует все таблицы.

Модели доменов связаны внешними ключами по имени таблицы (`ForeignKey("plans.id")`),
не импортируя друг друга. Если процесс не загрузил чью-то модель, первый же запрос
падает с NoReferencedTableError — так и было с публичным API, пока хук disconnect.sh
молча получал 500. Проверка идёт в чистом интерпретаторе: в pytest все модели уже
загружены conftest.py и ошибку не увидеть.
"""

import ast
import sys

import pytest

from ocmanager.core import shell

PROBE = """
import importlib
importlib.import_module({module!r})
from ocmanager.core.db import Base
for table in Base.metadata.sorted_tables:
    for fk in table.foreign_keys:
        fk.column  # разрешает внешний ключ; NoReferencedTableError, если таблицы нет
print(sorted(Base.metadata.tables))
"""

EXPECTED = {"clients", "plans", "subscriptions", "devices", "revocations", "nodes", "session_log"}


@pytest.mark.parametrize(
    "module",
    [
        "ocmanager.apps.public_api",
        "ocmanager.apps.admin_api",
        "ocmanager.apps.worker",
        "ocmanager.cli",
    ],
)
async def test_process_knows_every_table(module: str) -> None:
    result = await shell.run([sys.executable, "-c", PROBE.format(module=module)], timeout=60)
    assert set(ast.literal_eval(result.stdout.strip().splitlines()[-1])) >= EXPECTED
