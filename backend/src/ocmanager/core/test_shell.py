import asyncio
import os
from pathlib import Path

import pytest

from ocmanager.core import shell


def assert_dead(pid: int) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def wait_for_pid(pidfile: Path) -> int:
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            return int(pidfile.read_text())
        await asyncio.sleep(0.01)
    raise AssertionError("процесс не записал pid")


async def test_run_captures_stdout() -> None:
    r = await shell.run(["printf", "hi"])
    assert (r.argv, r.returncode, r.stdout, r.stderr) == (("printf", "hi"), 0, "hi", "")


async def test_run_passes_input() -> None:
    r = await shell.run(["cat"], input=b"secret-from-stdin")
    assert r.stdout == "secret-from-stdin"


async def test_arguments_are_not_interpreted_by_shell() -> None:
    r = await shell.run(["echo", "$(whoami); rm -rf /"])
    assert r.stdout == "$(whoami); rm -rf /\n"


@pytest.mark.parametrize("bad", ["echo hi", b"echo hi", [], ["echo", 1]])
async def test_run_rejects_non_argv(bad: object) -> None:
    with pytest.raises(TypeError):
        await shell.run(bad)  # type: ignore[arg-type]


async def test_nonzero_raises_when_check() -> None:
    with pytest.raises(shell.CommandFailed) as ei:
        await shell.run(["sh", "-c", "echo err >&2; exit 3"])
    assert ei.value.result.returncode == 3
    assert "err" in ei.value.result.stderr


async def test_nonzero_returned_when_not_check() -> None:
    r = await shell.run(["false"], check=False)
    assert r.returncode == 1


async def test_missing_binary() -> None:
    with pytest.raises(shell.CommandNotFound):
        await shell.run(["definitely-not-a-binary-ocm"])


async def test_timeout_kills_process_group(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    # sh ждёт дочерний sleep: убить надо обоих, а не только sh
    with pytest.raises(shell.CommandTimeout):
        await shell.run(["sh", "-c", f"sleep 30 & echo $! > {pidfile}; wait"], timeout=0.3)
    assert_dead(await wait_for_pid(pidfile))


async def test_cancel_kills_process(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    task = asyncio.create_task(shell.run(["sh", "-c", f"echo $$ > {pidfile}; exec sleep 30"]))
    pid = await wait_for_pid(pidfile)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_dead(pid)


async def test_stream_yields_lines_and_kills_on_break(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    script = f"echo $$ > {pidfile}; i=0; while true; do echo line$i; i=$((i+1)); sleep 0.05; done"
    got: list[str] = []
    async with shell.stream(["sh", "-c", script]) as lines:
        async for line in lines:
            got.append(line)
            if len(got) == 3:
                break
    assert got == ["line0", "line1", "line2"]
    assert_dead(int(pidfile.read_text()))


async def test_stream_merges_stderr() -> None:
    async with shell.stream(["sh", "-c", "echo out; echo err >&2"]) as lines:
        got = [line async for line in lines]
    assert sorted(got) == ["err", "out"]


async def test_stream_killed_on_cancel(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"

    async def consume() -> None:
        async with shell.stream(["sh", "-c", f"echo $$ > {pidfile}; exec sleep 30"]) as lines:
            async for _ in lines:
                pass

    task = asyncio.create_task(consume())
    pid = await wait_for_pid(pidfile)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_dead(pid)
