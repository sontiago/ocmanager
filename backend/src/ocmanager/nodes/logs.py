"""Server-Sent Events из построчного потока логов."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress


def _frame(line: str) -> bytes:
    """Одно событие. `\\r` и `\\n` внутри строки не могут начать новое поле протокола
    (`event:`, `id:`), поэтому строка режется на отдельные `data:`."""
    parts = line.splitlines() or [""]
    return ("".join(f"data: {part}\n" for part in parts) + "\n").encode()


async def sse_lines(
    lines: AsyncIterator[str], *, heartbeat_s: float = 15.0
) -> AsyncIterator[bytes]:
    """`data: <строка>\\n\\n` на каждую строку; при тишине дольше `heartbeat_s` — комментарий
    `: ping`, чтобы прокси не оборвал молчащее соединение.

    Ожидание следующей строки не отменяется по таймауту (`wait_for` закрыл бы источник
    вместе с процессом `docker logs`): задача живёт, пока строка не придёт. Отмена
    и закрытие генератора отменяют её — источник получает CancelledError и завершается."""
    pending = asyncio.ensure_future(anext(lines))
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_s)
            if not done:
                yield b": ping\n\n"
                continue
            try:
                line = pending.result()
            except StopAsyncIteration:
                return
            yield _frame(line)
            pending = asyncio.ensure_future(anext(lines))
    finally:
        pending.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending
