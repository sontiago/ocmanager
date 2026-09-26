"""Реестр ORM-моделей полный.

Проверка идёт в отдельном процессе. В процессе pytest модели уже импортированы
через conftest.py и тесты, поэтому забытый импорт в ocmanager/models.py здесь
не виден. Alembic из командной строки видит только то, что импортирует реестр.
"""

import json
import sys
from pathlib import Path

import ocmanager
from ocmanager.core import shell
from ocmanager.models import metadata

PACKAGE_ROOT = Path(ocmanager.__file__).parent

PROBE = """
import json, sys
import ocmanager.models as registry
print(json.dumps({
    "modules": sorted(
        n for n in sys.modules
        if n.startswith("ocmanager.") and n.endswith(".models") and n != "ocmanager.models"
    ),
    "tables": sorted(registry.metadata.tables),
}))
"""


async def fresh_registry() -> dict[str, list[str]]:
    result = await shell.run([sys.executable, "-c", PROBE], timeout=60)
    loaded: dict[str, list[str]] = json.loads(result.stdout)
    return loaded


async def test_every_models_module_is_registered() -> None:
    expected = {
        "ocmanager." + ".".join(p.relative_to(PACKAGE_ROOT).with_suffix("").parts)
        for p in PACKAGE_ROOT.rglob("models.py")
        if p.parent != PACKAGE_ROOT
    }
    missing = sorted(expected - set((await fresh_registry())["modules"]))
    assert missing == [], f"добавьте импорт в ocmanager/models.py: {missing}"


async def test_registry_sees_every_table_known_to_tests() -> None:
    """Таблица, объявленная вне models.py или импортированная только тестом,
    тоже не видна Alembic."""
    missing = sorted(set(metadata.tables) - set((await fresh_registry())["tables"]))
    assert missing == [], f"таблицы не видны через ocmanager/models.py: {missing}"
