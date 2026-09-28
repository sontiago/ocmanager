"""Хуки ocserv (ocserv/hooks/*.sh), запущенные на хосте через sh.

Окружение чистое (`env -i`), как у ocserv: скрипт видит только то, что
передали явно. hooks.env подменяется через OCM_HOOKS_ENV.
"""

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from ocmanager.core import shell

HOOKS = Path(__file__).parents[3] / "ocserv" / "hooks"


@dataclass
class Stand:
    dir: Path
    allowlist: Path
    hooks_env: Path
    token_file: Path

    def write_env(self, url: str = "http://127.0.0.1:9/") -> None:
        self.hooks_env.write_text(
            f"ALLOWLIST='{self.allowlist}'\n"
            f"SESSION_END_URL='{url}'\n"
            f"INTERNAL_TOKEN_FILE='{self.token_file}'\n"
        )


@pytest.fixture
def stand(tmp_path: Path) -> Stand:
    s = Stand(tmp_path, tmp_path / "allowed.list", tmp_path / "hooks.env", tmp_path / "token")
    s.allowlist.write_text("c1-d10\nc2-d1\n")
    s.token_file.write_text("tok-123")
    s.write_env()
    return s


async def run_hook(name: str, stand: Stand, **env: str) -> int:
    argv = ["env", "-i", "PATH=/usr/bin:/bin", f"OCM_HOOKS_ENV={stand.hooks_env}"]
    argv += [f"{k}={v}" for k, v in env.items()]
    result = await shell.run([*argv, "sh", str(HOOKS / name)], check=False, timeout=10)
    return result.returncode


async def test_connect_allows_listed_user(stand: Stand) -> None:
    assert await run_hook("connect.sh", stand, USERNAME="c2-d1") == 0


@pytest.mark.parametrize("username", ["c9-d9", "", "c1-d1", ".*", "c2-d"])
async def test_connect_refuses(stand: Stand, username: str) -> None:
    assert await run_hook("connect.sh", stand, USERNAME=username) != 0


async def test_connect_refuses_without_username(stand: Stand) -> None:
    assert await run_hook("connect.sh", stand) != 0


async def test_connect_refuses_when_list_missing(stand: Stand) -> None:
    stand.allowlist.unlink()
    assert await run_hook("connect.sh", stand, USERNAME="c2-d1") != 0


async def test_connect_refuses_when_hooks_env_missing(stand: Stand) -> None:
    stand.hooks_env.unlink()
    assert await run_hook("connect.sh", stand, USERNAME="c2-d1") != 0


async def test_connect_empty_list_refuses_everyone(stand: Stand) -> None:
    stand.allowlist.write_text("")
    assert await run_hook("connect.sh", stand, USERNAME="c2-d1") != 0


@dataclass
class Captured:
    requests: list[dict[str, Any]] = field(default_factory=list)


@pytest.fixture
def server() -> Iterator[tuple[str, Captured]]:
    captured = Captured()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            captured.requests.append(
                {
                    "path": self.path,
                    "token": self.headers["X-Internal-Token"],
                    "type": self.headers["Content-Type"],
                    "json": json.loads(body),
                }
            )
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_: Any) -> None:
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/internal/session-end", captured
    httpd.shutdown()
    httpd.server_close()


async def test_disconnect_posts_final_counters(stand: Stand, server: tuple[str, Captured]) -> None:
    url, captured = server
    stand.write_env(url)
    code = await run_hook(
        "disconnect.sh",
        stand,
        USERNAME="c2-d1",
        ID="17",
        STATS_BYTES_IN="1000",
        STATS_BYTES_OUT="2000",
        STATS_DURATION="60",
        IP_REAL="203.0.113.5",
    )
    assert code == 0
    [req] = captured.requests
    assert req["path"] == "/internal/session-end"
    assert req["token"] == "tok-123"
    assert req["type"] == "application/json"
    assert req["json"] == {
        "username": "c2-d1",
        "session_id": "17",
        "bytes_in": 1000,
        "bytes_out": 2000,
        "duration_sec": 60,
        "remote_ip": "203.0.113.5",
    }


async def test_disconnect_non_numeric_counters_become_zero(
    stand: Stand, server: tuple[str, Captured]
) -> None:
    url, captured = server
    stand.write_env(url)
    await run_hook("disconnect.sh", stand, USERNAME="c2-d1", STATS_BYTES_IN="1;rm")
    assert captured.requests[0]["json"]["bytes_in"] == 0


async def test_disconnect_exits_zero_when_panel_is_down(stand: Stand) -> None:
    started = time.monotonic()
    assert await run_hook("disconnect.sh", stand, USERNAME="c2-d1") == 0
    assert time.monotonic() - started < 4


async def test_disconnect_exits_zero_without_token(stand: Stand) -> None:
    stand.token_file.unlink()
    assert await run_hook("disconnect.sh", stand, USERNAME="c2-d1") == 0
