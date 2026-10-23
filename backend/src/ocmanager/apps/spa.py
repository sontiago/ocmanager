"""SPA: неизвестный путь отдаёт index.html, чтобы работал клиентский роутер."""

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# Эти префиксы — не страницы приложения: промах там должен быть настоящим 404, а не оболочкой.
# /admin — API (JSON-ошибка), /assets — хэшированные файлы сборки: после выкладки закэшированный
# index.html ссылается на старый файл, и ответ index.html с кодом 200 дал бы белый экран.
NOT_A_PAGE = ("admin", "assets")


def _is_under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or any(_is_under(path, p) for p in NOT_A_PAGE):
                raise
            response = await super().get_response("index.html", scope)
        # index.html — единственный файл без хэша в имени: в кэше он прятал бы новую версию.
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response
