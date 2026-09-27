from pathlib import Path

import pytest

from scripts.check_boundaries import find_violations, main


def make_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "ocmanager"
    for rel, source in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return root


def imported(root: Path) -> list[str]:
    return [v.imported for v in find_violations(root)]


def test_real_source_tree_is_clean() -> None:
    root = Path(__file__).parent.parent / "src" / "ocmanager"
    assert find_violations(root) == []


def test_domain_may_import_itself_core_events_and_stdlib(tmp_path: Path) -> None:
    root = make_tree(
        tmp_path,
        {
            "nodes/service.py": (
                "import json\n"
                "from sqlalchemy import select\n"
                "from ocmanager.core.db import Base\n"
                "from ocmanager.events import bus\n"
                "from ocmanager.nodes.models import Node\n"
                "from .models import Node\n"
            ),
        },
    )
    assert imported(root) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from ocmanager.provisioning.pki import ca\n", "ocmanager.provisioning.pki"),
        ("import ocmanager.subscriptions.state\n", "ocmanager.subscriptions.state"),
        ("from ocmanager.flows import access\n", "ocmanager.flows"),
        ("from ocmanager.tma.schemas import X\n", "ocmanager.tma.schemas"),
        ("from ocmanager import provisioning\n", "ocmanager"),
        ("from ...provisioning import service\n", "ocmanager.provisioning"),
        ("from ... import admin\n", "ocmanager.admin"),
    ],
)
def test_domain_importing_other_layer_is_violation(
    tmp_path: Path, source: str, expected: str
) -> None:
    root = make_tree(tmp_path, {"billing/providers/tribute.py": source})
    [violation] = find_violations(root)
    assert violation.imported == expected
    assert violation.importer == "billing"
    assert violation.path.name == "tribute.py"
    assert violation.line == 1


def test_import_inside_function_is_found(tmp_path: Path) -> None:
    root = make_tree(
        tmp_path, {"nodes/x.py": "def f():\n    from ocmanager.billing import plans\n"}
    )
    assert [(v.line, v.imported) for v in find_violations(root)] == [(2, "ocmanager.billing")]


def test_core_and_events_must_not_import_domains(tmp_path: Path) -> None:
    root = make_tree(
        tmp_path,
        {
            "core/x.py": "from ocmanager.audit.service import record\n",
            "events/y.py": "from ocmanager.core.db import Base\n",
        },
    )
    assert imported(root) == ["ocmanager.audit.service"]


def test_glue_layers_are_not_restricted(tmp_path: Path) -> None:
    root = make_tree(
        tmp_path,
        {
            "flows/access.py": (
                "from ocmanager.nodes import service\nfrom ocmanager.subscriptions import state\n"
            ),
            "apps/worker.py": "from ocmanager.flows import access\n",
        },
    )
    assert imported(root) == []


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dirty = make_tree(tmp_path / "a", {"nodes/x.py": "from ocmanager.billing import plans\n"})
    clean = make_tree(tmp_path / "b", {"nodes/x.py": "from ocmanager.core import db\n"})
    assert main(["prog", str(dirty)]) == 1
    assert "nodes/x.py:1: ocmanager.nodes imports ocmanager.billing" in capsys.readouterr().out
    assert main(["prog", str(clean)]) == 0
