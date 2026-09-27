"""Проверка границ модулей (дизайн §4.1, Global Constraints).

Доменные модули импортируют только себя, ocmanager.core и ocmanager.events.
core и events не импортируют ничего, кроме друг друга. Склейка доменов —
в flows/, tma/, admin/, apps/, cli/ — не ограничена.

    uv run python scripts/check_boundaries.py [src/ocmanager]
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

DOMAINS = frozenset({"billing", "subscriptions", "provisioning", "nodes", "notifications", "audit"})
INFRA = frozenset({"core", "events"})


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    importer: str
    imported: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: ocmanager.{self.importer} imports {self.imported}"


def _imported_modules(tree: ast.Module, package: list[str]) -> list[tuple[int, str]]:
    """Абсолютные имена модулей, которые импортирует файл; относительные
    импорты разрешаются относительно пакета файла."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                found.append((node.lineno, node.module or ""))
                continue
            base = package[: len(package) - (node.level - 1)]
            if node.module:
                found.append((node.lineno, ".".join([*base, node.module])))
            else:
                found += [(node.lineno, ".".join([*base, a.name])) for a in node.names]
    return found


def _allowed(importer: str, imported: str) -> bool:
    parts = imported.split(".")
    if parts[0] != "ocmanager":
        return True
    if len(parts) == 1:
        return False  # `import ocmanager` тянет всё подряд
    target = parts[1]
    if importer in INFRA:
        return target in INFRA
    return target == importer or target in INFRA


def find_violations(root: Path) -> list[Violation]:
    """root — каталог пакета ocmanager (src/ocmanager)."""
    violations: list[Violation] = []
    for owner in sorted(DOMAINS | INFRA):
        owner_dir = root / owner
        if not owner_dir.is_dir():
            continue
        for path in sorted(owner_dir.rglob("*.py")):
            rel = path.relative_to(root.parent).with_suffix("")
            package = list(rel.parts[:-1])  # для __init__.py это сам пакет — так и нужно
            tree = ast.parse(path.read_text(), filename=str(path))
            for line, imported in _imported_modules(tree, package):
                if not _allowed(owner, imported):
                    violations.append(Violation(path, line, owner, imported))
    return violations


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).parent.parent / "src" / "ocmanager"
    violations = find_violations(root)
    for v in violations:
        print(v)
    if violations:
        print(f"\n{len(violations)} нарушений границ модулей", file=sys.stderr)
        return 1
    print("границы модулей в порядке")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
