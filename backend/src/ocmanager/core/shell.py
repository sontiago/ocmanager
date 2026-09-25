"""Безопасный запуск внешних процессов.

Только список аргументов, без shell. Таймаут на всё. Дочерний процесс
запускается в своей группе и гарантированно убивается — вместе с потомками —
при таймауте, при отмене корутины и при выходе из stream().
Секреты в argv не передаются (видны в ps) — только через input.
"""

import asyncio
import contextlib
import os
import signal
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from subprocess import DEVNULL, PIPE, STDOUT

import structlog

log = structlog.get_logger(__name__)

TERMINATE_GRACE_S = 2.0


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandError(Exception):
    pass


class CommandFailed(CommandError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(
            f"{result.argv[0]} exited with {result.returncode}: {result.stderr.strip()[:500]}"
        )


class CommandTimeout(CommandError):
    def __init__(self, argv: tuple[str, ...], timeout: float) -> None:
        self.argv = argv
        super().__init__(f"{argv[0]} timed out after {timeout}s")


class CommandNotFound(CommandError):
    def __init__(self, argv: tuple[str, ...]) -> None:
        self.argv = argv
        super().__init__(f"executable not found: {argv[0]}")


def _validate(argv: Sequence[str]) -> tuple[str, ...]:
    if isinstance(argv, str | bytes) or not isinstance(argv, list | tuple):
        raise TypeError("argv must be a list or tuple of str, never a shell string")
    if not argv or not all(isinstance(a, str) for a in argv):
        raise TypeError("argv must be a non-empty sequence of str")
    return tuple(argv)


async def _spawn(
    argv: tuple[str, ...], *, stdin: int, stdout: int, stderr: int
) -> asyncio.subprocess.Process:
    try:
        return await asyncio.create_subprocess_exec(
            *argv, stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True
        )
    except FileNotFoundError as exc:
        raise CommandNotFound(argv) from exc


def _signal_group(proc: asyncio.subprocess.Process, sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, sig)


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """SIGTERM всей группе, через TERMINATE_GRACE_S — SIGKILL. Ждёт завершения,
    чтобы не оставлять зомби. Не прерывается отменой."""
    if proc.returncode is None:
        _signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.shield(asyncio.wait_for(proc.wait(), TERMINATE_GRACE_S))
        except TimeoutError:
            _signal_group(proc, signal.SIGKILL)
            await asyncio.shield(proc.wait())


async def run(
    argv: Sequence[str],
    *,
    timeout: float = 10.0,  # noqa: ASYNC109 — таймаут обязан убить процесс, а не только корутину
    input: bytes | None = None,
    check: bool = True,
) -> CommandResult:
    args = _validate(argv)
    started = time.monotonic()
    proc = await _spawn(
        args, stdin=PIPE if input is not None else DEVNULL, stdout=PIPE, stderr=PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(input), timeout)
    except TimeoutError:
        await _terminate(proc)
        log.warning("command_timeout", argv=args, timeout=timeout)
        raise CommandTimeout(args, timeout) from None
    except BaseException:
        await _terminate(proc)
        raise
    assert proc.returncode is not None
    result = CommandResult(
        argv=args,
        returncode=proc.returncode,
        stdout=out.decode(errors="replace"),
        stderr=err.decode(errors="replace"),
    )
    log.debug(
        "command_finished",
        argv=args,
        returncode=result.returncode,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    if check and result.returncode != 0:
        raise CommandFailed(result)
    return result


@asynccontextmanager
async def stream(argv: Sequence[str]) -> AsyncIterator[AsyncIterator[str]]:
    """Построчный поток stdout+stderr долгого процесса (логи для SSE).

        async with shell.stream(["docker", "logs", "-f", name]) as lines:
            async for line in lines:
                ...

    При выходе из блока — нормальном, по break, исключению или отмене —
    процесс и его потомки гарантированно завершены.
    """
    args = _validate(argv)
    proc = await _spawn(args, stdin=DEVNULL, stdout=PIPE, stderr=STDOUT)
    assert proc.stdout is not None
    stdout = proc.stdout

    async def lines() -> AsyncIterator[str]:
        async for raw in stdout:
            yield raw.decode(errors="replace").rstrip("\r\n")

    log.debug("stream_started", argv=args, pid=proc.pid)
    try:
        yield lines()
    finally:
        await _terminate(proc)
        log.debug("stream_closed", argv=args, returncode=proc.returncode)
