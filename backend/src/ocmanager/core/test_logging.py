import json
import logging

import pytest
import structlog

from ocmanager.core.logging import configure_logging


def last_json_line(out: str) -> dict[str, object]:
    return json.loads(out.strip().splitlines()[-1])  # type: ignore[no-any-return]


def test_structlog_renders_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", fmt="json")
    structlog.get_logger("t").info("hello", client_id=42)
    line = last_json_line(capsys.readouterr().out)
    assert line["event"] == "hello"
    assert line["client_id"] == 42
    assert line["level"] == "info"
    assert str(line["timestamp"]).endswith("Z")


@pytest.mark.parametrize(
    "key",
    [
        "token",
        "password",
        "p12_password",
        "init_data",
        "authorization",
        "bot_token",
        "secret_key",
    ],
)
def test_secrets_redacted(capsys: pytest.CaptureFixture[str], key: str) -> None:
    configure_logging("INFO", fmt="json")
    structlog.get_logger().info("x", **{key: "hunter2"})
    out = capsys.readouterr().out
    assert "hunter2" not in out
    assert last_json_line(out)[key] == "***"


def test_nested_secrets_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", fmt="json")
    structlog.get_logger().info("x", headers={"Authorization": "tma abc", "Host": "h"})
    line = last_json_line(capsys.readouterr().out)
    assert line["headers"] == {"Authorization": "***", "Host": "h"}


def test_stdlib_logs_go_through_same_renderer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", fmt="json")
    logging.getLogger("uvicorn.error").info("started")
    line = last_json_line(capsys.readouterr().out)
    assert (line["event"], line["logger"]) == ("started", "uvicorn.error")


def test_level_filters(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", fmt="json")
    structlog.get_logger().info("quiet")
    assert capsys.readouterr().out == ""
