import json

import pytest

from scripts.dump_openapi import build_schema, main


def test_the_admin_schema_lists_the_admin_api() -> None:
    schema = build_schema("admin")
    assert "/admin/promo-codes" in schema["paths"]
    assert "/admin/stats/traffic" in schema["paths"]
    assert "PromoOut" in schema["components"]["schemas"]


def test_the_public_schema_lists_the_mini_app_api() -> None:
    schema = build_schema("public")
    assert "/api/tma/referral" in schema["paths"]
    assert "ReferralOut" in schema["components"]["schemas"]


def test_the_output_is_stable_between_runs() -> None:
    """Сверка типов в CI сравнивает файлы: порядок ключей не должен плавать."""
    first = json.dumps(build_schema("admin"), sort_keys=True)
    second = json.dumps(build_schema("admin"), sort_keys=True)
    assert first == second


def test_an_unknown_target_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["nothing"])


def test_main_prints_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    main(["admin"])
    assert json.loads(capsys.readouterr().out)["info"]["title"] == "ocmanager admin api"
