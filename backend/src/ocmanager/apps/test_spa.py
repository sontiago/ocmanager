from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ocmanager.apps.admin_api import create_app
from ocmanager.core.config import Settings

INDEX = "<!doctype html><title>admin</title>"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("top secret")
    return root


async def fetch(
    settings: Settings, url: str, *, host: str = "localhost:8080"
) -> tuple[int, str, str]:
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        r = await client.get(url, headers={"Host": host})
        return r.status_code, r.headers.get("content-type", ""), r.text


def with_static(settings: Settings, static_dir: Path | None) -> Settings:
    return settings.model_copy(update={"admin_static_dir": static_dir})


async def test_root_serves_index(settings: Settings, static_dir: Path) -> None:
    status, _, body = await fetch(with_static(settings, static_dir), "/")
    assert (status, body) == (200, INDEX)


async def test_asset_served(settings: Settings, static_dir: Path) -> None:
    status, _, body = await fetch(with_static(settings, static_dir), "/assets/app.js")
    assert (status, body) == (200, "console.log(1)")


async def test_unknown_route_falls_back_to_index(settings: Settings, static_dir: Path) -> None:
    status, _, body = await fetch(with_static(settings, static_dir), "/clients/5")
    assert (status, body) == (200, INDEX)


async def test_unknown_admin_path_is_json_404(settings: Settings, static_dir: Path) -> None:
    status, ctype, body = await fetch(with_static(settings, static_dir), "/admin/nope")
    assert status == 404
    assert ctype.startswith("application/json")
    assert '"code": "not_found"' in body or '"code":"not_found"' in body


@pytest.mark.parametrize(
    "url", ["/..%2fsecret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"]
)
async def test_path_traversal_blocked(settings: Settings, static_dir: Path, url: str) -> None:
    _, _, body = await fetch(with_static(settings, static_dir), url)
    assert "top secret" not in body


async def test_without_static_dir_root_is_404(settings: Settings) -> None:
    status, _, _ = await fetch(with_static(settings, None), "/")
    assert status == 404


async def test_missing_static_dir_is_ignored(settings: Settings, tmp_path: Path) -> None:
    status, _, _ = await fetch(with_static(settings, tmp_path / "absent"), "/")
    assert status == 404


async def test_host_guard_still_applies(settings: Settings, static_dir: Path) -> None:
    status, _, _ = await fetch(with_static(settings, static_dir), "/", host="evil.example")
    assert status == 400
