from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path, Query
from pydantic import BaseModel

MAX_LIMIT = 200
MAX_ID = 2**63 - 1  # BIGINT: id больше этого asyncpg отвергает ошибкой, то есть ответом 500

# Идентификатор в пути. Без границ `/clients/99999999999999999999` доходит до БД.
BigId = Annotated[int, Path(ge=1, le=MAX_ID)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0, le=10**9)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


PageDep = Annotated[PageParams, Depends(page_params)]


def page_of[T](items: list[T], total: int, params: PageParams) -> Page[T]:
    return Page[T](items=items, total=total, limit=params.limit, offset=params.offset)
