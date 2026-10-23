from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient, Response

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


async def fetch_response(settings: Settings, url: str) -> Response:
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        return await client.get(url, headers={"Host": "localhost:8080"})


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


async def test_a_missing_asset_is_a_real_404_not_the_app_shell(
    settings: Settings, static_dir: Path
) -> None:
    """После выкладки закэшированный index.html ссылается на старый хэшированный файл: ответ
    index.html с кодом 200 дал бы белый экран и загадочную ошибку про тип содержимого."""
    for url in ("/assets/gone.js", "/assets/nested/gone.css"):
        status, ctype, body = await fetch(with_static(settings, static_dir), url)
        assert status == 404, url
        assert INDEX not in body
        assert "text/html" not in ctype


async def test_the_app_shell_is_never_cached(settings: Settings, static_dir: Path) -> None:
    """index.html — единственный файл без хэша в имени: пока он в кэше, браузер не узнает
    о новой версии."""
    for url in ("/", "/clients/5", "/index.html"):
        r = await fetch_response(with_static(settings, static_dir), url)
        assert r.status_code == 200, url
        assert r.headers["cache-control"] == "no-cache", url


async def test_hashed_assets_are_left_cacheable(settings: Settings, static_dir: Path) -> None:
    r = await fetch_response(with_static(settings, static_dir), "/assets/app.js")
    assert r.headers.get("cache-control") != "no-cache"
