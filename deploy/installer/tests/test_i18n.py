import ast
import json
import re
from pathlib import Path

import pytest

from installer import i18n, ocm
from installer.backup import BackupPaths
from installer.i18n import _
from installer.messages_en import EN
from installer.prompts import ScriptedPrompter
from installer.runner import FakeRunner, Result
from installer.tests.conftest import NOW
from installer.tests.test_install import ANSWERS, run_main, screen

PACKAGE = Path(__file__).resolve().parents[1]
CYRILLIC = re.compile("[А-Яа-яЁё]")


def translatable_texts() -> set[str]:
    """Все литералы, переданные в `_("…")` в коде установщика."""
    texts: set[str] = set()
    for path in PACKAGE.glob("*.py"):
        if path.name == "messages_en.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                texts.add(node.args[0].value)
    return texts


def test_every_translatable_text_has_an_english_version() -> None:
    missing = sorted(t for t in translatable_texts() if t not in EN)
    assert missing == []


def test_there_are_no_stale_english_entries() -> None:
    stale = sorted(k for k in EN if k not in translatable_texts())
    assert stale == []


def test_translations_keep_the_same_placeholders() -> None:
    names = re.compile(r"\{(\w+)\}")
    broken = [k for k, v in EN.items() if set(names.findall(k)) != set(names.findall(v))]
    assert broken == []


def test_english_texts_contain_no_cyrillic() -> None:
    assert [v for v in EN.values() if CYRILLIC.search(v)] == []


def test_english_is_the_default_language() -> None:
    assert i18n.DEFAULT == "en"


def test_a_missing_translation_falls_back_to_the_source_text() -> None:
    i18n.set_lang("en")
    assert _("нет такого перевода") == "нет такого перевода"


def test_unsupported_language_is_refused() -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        i18n.set_lang("de")


def test_the_wizard_speaks_english_by_default(root: Path) -> None:
    i18n.set_lang("en")
    code, prompter, _runner = run_main(root, ANSWERS)
    assert code == 0
    text = screen(prompter)
    assert "Done. ocmanager is installed." in text
    assert "ssh -L 8080:127.0.0.1:8080 user@" in text
    own = [line for line in text.splitlines() if line != "всё в порядке"]  # ответ заглушки doctor
    assert not CYRILLIC.search("\n".join(own))


def test_lang_ru_switches_the_wizard_to_russian(root: Path) -> None:
    i18n.set_lang("en")
    code, prompter, _runner = run_main(root, ANSWERS, argv=["--lang", "ru"])
    assert code == 0
    assert "Готово. ocmanager установлен." in screen(prompter)


def test_the_language_is_remembered_for_the_next_run(root: Path) -> None:
    i18n.set_lang("en")
    run_main(root, ANSWERS, argv=["--lang=ru"])
    answers = json.loads((root / "deploy" / ".install-state").read_text())["answers"]
    assert answers["lang"] == "ru"
    i18n.set_lang("en")
    code, prompter, _runner = run_main(root, ANSWERS)  # без флага: берётся сохранённый
    assert code == 0
    assert "уже сделано" in screen(prompter)


def test_the_env_variable_selects_the_language(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCM_LANG", "ru")
    i18n.set_lang("en")
    _code, prompter, _runner = run_main(root, ANSWERS, argv=["--dry-run"])
    assert "Это был пробный запуск" in screen(prompter)


def ocm_run(argv: list[str], paths: BackupPaths, answers: list[object]) -> tuple[int, str]:
    said: list[str] = []
    code = ocm.main(
        argv,
        runner=FakeRunner(),
        prompter=ScriptedPrompter(answers),
        paths=paths,
        now=lambda: NOW,
        out=said.append,
    )
    return code, "\n".join(said)


@pytest.fixture
def paths(root: Path, tmp_path: Path) -> BackupPaths:
    return BackupPaths(root=root, backup_dir=tmp_path / "backups", key_file=tmp_path / "key")


def test_ocm_usage_is_in_english_by_default(paths: BackupPaths) -> None:
    i18n.set_lang("en")
    _code, out = ocm_run([], paths, [])
    assert "Usage: ocm <command>" in out
    assert not CYRILLIC.search(out)


def test_ocm_uses_the_language_chosen_at_install_time(paths: BackupPaths) -> None:
    (paths.deploy / ".install-state").write_text(
        json.dumps({"done": [], "answers": {"lang": "ru"}})
    )
    i18n.set_lang("en")
    _code, out = ocm_run([], paths, [])
    assert "Использование: ocm" in out


def test_the_english_confirmation_word_is_yes(paths: BackupPaths) -> None:
    i18n.set_lang("en")
    (paths.deploy / ".previous-rev").write_text(
        json.dumps({"rev": "a" * 40, "branch": "main", "backup": ""})
    )
    code, out = ocm_run(["rollback"], paths, ["no"])
    assert code == 1
    assert "Cancelled." in out
    runner = FakeRunner()
    runner.on("scripts/doctor.sh", Result(0, "OK\n"))
    code = ocm.main(
        ["rollback"],
        runner=runner,
        prompter=ScriptedPrompter(["YES"]),
        paths=paths,
        now=lambda: NOW,
        out=lambda _t: None,
    )
    assert code == 0
