"""CLI plan без БД: невалидный ввод отсекается до похода в базу.
Создание и список проверены flows/test_plans.py и вручную (Задача 2.1, шаг 6)."""

import pytest
from typer.testing import CliRunner

from ocmanager.cli import app

runner = CliRunner()

GOOD = [
    "plan", "create", "--code", "m1", "--name-ru", "Месяц", "--name-en", "Month",
    "--days", "30", "--devices", "3", "--price", "19900",
]  # fmt: skip


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        (["--code", "M1"], "code"),
        (["--price", "-5"], "price_amount"),
        (["--currency", "RU"], "currency"),
        (["--name-en", " "], "name_i18n"),
        (["--days", "0"], "duration_days"),
    ],
)
def test_invalid_plan_is_refused_before_touching_the_database(
    override: list[str], expected: str
) -> None:
    result = runner.invoke(app, [*GOOD, *override])
    assert result.exit_code == 1
    assert expected in result.output
