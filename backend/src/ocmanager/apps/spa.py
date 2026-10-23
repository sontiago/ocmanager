"""SPA: неизвестный путь отдаёт index.html, чтобы работал клиентский роутер."""

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # Несуществующий API-путь остаётся JSON-404, а не страницей приложения.
            if exc.status_code != 404 or path == "admin" or path.startswith("admin/"):
                raise
            return await super().get_response("index.html", scope)
