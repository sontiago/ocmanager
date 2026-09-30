import asyncio
from collections.abc import AsyncIterator

from ocmanager.nodes.logs import sse_lines


async def source(
    *lines: str, delay: float = 0.0, closed: asyncio.Event | None = None
) -> AsyncIterator[str]:
    try:
        for line in lines:
            await asyncio.sleep(delay)
            yield line
    finally:
        if closed is not None:
            closed.set()


async def collect(stream: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in stream]


async def test_every_line_is_one_event() -> None:
    assert await collect(sse_lines(source("one", "two"))) == [b"data: one\n\n", b"data: two\n\n"]


async def test_an_empty_line_is_still_an_event() -> None:
    assert await collect(sse_lines(source(""))) == [b"data: \n\n"]


async def test_line_breaks_inside_a_line_cannot_inject_fields() -> None:
    (chunk,) = await collect(sse_lines(source("ok\r\nevent: evil\rid: 1")))
    assert chunk == b"data: ok\ndata: event: evil\ndata: id: 1\n\n"
    assert b"\nevent:" not in chunk  # ни одной строки, начинающейся с поля протокола


async def test_silence_produces_pings_without_losing_the_line() -> None:
    chunks = await collect(sse_lines(source("late", delay=0.2), heartbeat_s=0.05))
    assert chunks[0] == b": ping\n\n"
    assert chunks.count(b": ping\n\n") >= 2
    assert chunks[-1] == b"data: late\n\n"  # пинги источник не убили


async def test_an_empty_source_ends_the_stream() -> None:
    assert await collect(sse_lines(source())) == []


async def test_closing_the_stream_closes_the_source() -> None:
    closed = asyncio.Event()
    stream = sse_lines(source("a", "b", "c", closed=closed))
    assert await anext(stream) == b"data: a\n\n"
    await stream.aclose()  # type: ignore[attr-defined]
    await asyncio.wait_for(closed.wait(), timeout=1)


async def test_cancelling_a_silent_stream_closes_the_source() -> None:
    closed = asyncio.Event()
    task = asyncio.ensure_future(
        collect(sse_lines(source("never", delay=30, closed=closed), heartbeat_s=0.05))
    )
    await asyncio.sleep(0.15)
    task.cancel()
    await asyncio.wait_for(closed.wait(), timeout=1)
