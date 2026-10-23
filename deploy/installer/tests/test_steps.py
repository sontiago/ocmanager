import hashlib
from pathlib import Path

import pytest

from installer import steps
from installer.config import generate_secrets, write_env
from installer.runner import CommandError, FakeNet, FakeRunner, Result

VALUES = {
    "DOMAIN_APP": "app.example.com",
    "DOMAIN_VPN": "vpn.example.com",
    "ACME_EMAIL": "me@example.com",
    **generate_secrets(),
    "OCM_BOT_TOKEN": "123456789:AAH-abcdefghijklmnopqrstuvwxyz_01",
    "OCM_BOT_USERNAME": "ocbot",
    "OCM_TRIBUTE_API_KEY": "",
}
PASSWORD = "correct-horse-battery"


class Clock:
    """Время, которое идёт только от sleep: тест не ждёт по-настоящему."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def make_ctx(root: Path, runner: FakeRunner, **over) -> steps.Context:  # type: ignore[no-untyped-def]
    clock = over.pop("clock", Clock())
    ctx = steps.Context(
        runner=runner,
        net=FakeNet(public_ip="203.0.113.10"),
        root=root,
        values=dict(VALUES),
        admin_user="owner",
        admin_password=PASSWORD,
        state=steps.State(root / "deploy" / ".install-state"),
        sleep=clock.sleep,
        clock=clock.monotonic,
        out=lambda _text: None,
        swapfile=root / "swapfile",
        fstab=root / "fstab",
        **over,
    )
    ctx.clock_obj = clock  # type: ignore[attr-defined]
    return ctx


def tls_ok(runner: FakeRunner) -> FakeRunner:
    runner.on("s_client", Result(0, "Verify return code: 0 (ok)\n"))
    runner.on("doctor.sh", Result(0, "всё в порядке\n"))
    return runner


def env_hash(root: Path) -> str:
    return hashlib.sha256((root / "deploy" / ".env").read_bytes()).hexdigest()


def test_the_step_names_and_order() -> None:
    assert [s.name for s in steps.build_steps()] == [
        "env",
        "swap",
        "docker",
        "build",
        "infra",
        "pki",
        "admin",
        "stack",
        "certs",
        "doctor",
    ]


def test_a_full_run_issues_the_commands_in_the_order_of_the_readme(root: Path) -> None:
    runner = tls_ok(FakeRunner())
    ctx = make_ctx(root, runner)
    steps.run_steps(ctx, steps.build_steps())
    assert [c for c in runner.joined() if c.startswith("docker compose")] == [
        "docker compose build",
        "docker compose up -d postgres redis volume-init",
        "docker compose run --rm cli pki init",
        "docker compose run --rm cli admin create owner --password-stdin",
        "docker compose up -d",
    ]
    assert any("s_client" in c and "app.example.com" in c for c in runner.joined())
    assert any("s_client" in c and "vpn.example.com" in c for c in runner.joined())
    assert runner.joined()[-1].endswith("doctor.sh")
    assert (root / "deploy" / ".env").exists()


def test_compose_commands_run_in_the_deploy_directory(root: Path) -> None:
    seen: list[Path | None] = []

    class Spy(FakeRunner):
        def run(self, cmd, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(kwargs.get("cwd"))
            return super().run(cmd, **kwargs)

    steps.run_steps(make_ctx(root, tls_ok(Spy())), steps.build_steps())
    compose_cwds = {cwd for cwd in seen if cwd == root / "deploy"}
    assert compose_cwds == {root / "deploy"}


def test_the_env_file_is_written_with_the_values(root: Path) -> None:
    ctx = make_ctx(root, tls_ok(FakeRunner()))
    steps.run_steps(ctx, steps.build_steps())
    text = (root / "deploy" / ".env").read_text()
    assert "DOMAIN_APP=app.example.com" in text
    assert f"OCM_SECRET_KEY={VALUES['OCM_SECRET_KEY']}" in text


def test_a_failure_stops_the_run_and_the_next_one_resumes(root: Path) -> None:
    broken = tls_ok(FakeRunner())
    broken.on("pki init", Result(1, "", "boom"))
    ctx = make_ctx(root, broken)
    with pytest.raises(steps.StepError) as err:
        steps.run_steps(ctx, steps.build_steps())
    assert "pki" in str(err.value)
    assert ctx.state.done() == ["env", "build", "infra"]
    before = env_hash(root)

    fixed = tls_ok(FakeRunner())
    ctx2 = make_ctx(root, fixed)
    steps.run_steps(ctx2, steps.build_steps())
    calls = fixed.joined()
    assert not any(c == "docker compose build" for c in calls)  # сделанное не повторяется
    assert not any("postgres redis" in c for c in calls)
    assert any("pki init" in c for c in calls)
    assert env_hash(root) == before  # секреты и .env не пересозданы


def test_the_state_is_saved_after_every_step(root: Path) -> None:
    broken = tls_ok(FakeRunner())
    broken.on("up -d", Result(1, "", "boom"))  # падает уже на infra
    ctx = make_ctx(root, broken)
    with pytest.raises(steps.StepError):
        steps.run_steps(ctx, steps.build_steps())
    reread = steps.State(root / "deploy" / ".install-state")
    assert reread.done() == ["env", "build"]


@pytest.mark.parametrize(
    ("step_cmd", "stderr"),
    [
        ("pki init", "CA уже существует в /var/lib/ocmanager-pki."),
        ("admin create", "conflict: admin 'owner' already exists"),
    ],
)
def test_an_already_existing_ca_or_admin_is_not_an_error(
    root: Path, step_cmd: str, stderr: str
) -> None:
    runner = tls_ok(FakeRunner())
    runner.on(step_cmd, Result(1, "", stderr))
    ctx = make_ctx(root, runner)
    steps.run_steps(ctx, steps.build_steps())
    assert "stack" in ctx.state.done()


def test_the_admin_password_goes_through_stdin_never_through_arguments(root: Path) -> None:
    runner = tls_ok(FakeRunner())
    steps.run_steps(make_ctx(root, runner), steps.build_steps())
    index = next(i for i, c in enumerate(runner.joined()) if "admin create" in c)
    assert runner.inputs[index] == PASSWORD + "\n"
    assert not any(PASSWORD in c for c in runner.joined())


def test_the_state_file_never_contains_secrets(root: Path) -> None:
    ctx = make_ctx(root, tls_ok(FakeRunner()))
    steps.run_steps(ctx, steps.build_steps())
    text = (root / "deploy" / ".install-state").read_text()
    assert PASSWORD not in text
    assert VALUES["OCM_SECRET_KEY"] not in text
    assert VALUES["POSTGRES_PASSWORD"] not in text


class Sequenced(FakeRunner):
    """openssl отвечает «не готово» заданное число раз, затем «готово»."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.on("doctor.sh", Result(0, ""))

    def run(self, cmd, **kwargs):  # type: ignore[no-untyped-def]
        if "s_client" in cmd:
            self.calls.append(list(cmd))
            self.inputs.append(kwargs.get("input"))
            if self.failures > 0:
                self.failures -= 1
                return Result(0, "Verify return code: 21 (unable to verify the first certificate)")
            return Result(0, "Verify return code: 0 (ok)")
        return super().run(cmd, **kwargs)


def test_certificate_polling_waits_until_both_domains_are_ready(root: Path) -> None:
    runner = Sequenced(failures=2)
    ctx = make_ctx(root, runner)
    steps.run_steps(ctx, steps.build_steps())
    assert len(ctx.clock_obj.sleeps) == 2  # type: ignore[attr-defined]
    assert all(s == 10 for s in ctx.clock_obj.sleeps)  # type: ignore[attr-defined]


def test_certificate_polling_gives_up_with_a_useful_hint(root: Path) -> None:
    runner = Sequenced(failures=10_000)
    ctx = make_ctx(root, runner)
    with pytest.raises(steps.StepError) as err:
        steps.run_steps(ctx, steps.build_steps())
    message = str(err.value)
    assert "app.example.com" in message
    assert "80" in message and "docker compose logs caddy" in message
    assert ctx.clock_obj.now <= 310  # type: ignore[attr-defined]


def test_a_red_doctor_warns_but_does_not_stop_the_install(root: Path) -> None:
    runner = FakeRunner()
    runner.on(
        "doctor.sh", Result(2, "FAIL reconcile\n")
    )  # раньше общего правила: первое выигрывает
    tls_ok(runner)
    warnings: list[str] = []
    ctx = make_ctx(root, runner)
    ctx.warn = warnings.append
    steps.run_steps(ctx, steps.build_steps())
    assert "doctor" in ctx.state.done()
    assert any("doctor" in w or "проверк" in w for w in warnings)


def test_dry_run_runs_nothing_and_writes_nothing(root: Path) -> None:
    runner = tls_ok(FakeRunner())
    ctx = make_ctx(root, runner, dry_run=True)
    steps.run_steps(ctx, steps.build_steps())
    assert runner.calls == []
    assert not (root / "deploy" / ".env").exists()
    assert not (root / "deploy" / ".install-state").exists()


def test_swap_is_created_once_and_recorded_in_fstab(root: Path) -> None:
    runner = tls_ok(FakeRunner())
    ctx = make_ctx(root, runner, want_swap=True)
    steps.run_steps(ctx, steps.build_steps())
    joined = runner.joined()
    swap_calls = [c for c in joined if "swap" in c or "fallocate" in c or "mkswap" in c]
    assert any(f"fallocate -l 2G {root / 'swapfile'}" in c for c in swap_calls)
    assert any(c.startswith("chmod 600") for c in joined)
    assert any("mkswap" in c for c in joined)
    assert any("swapon" in c for c in joined)
    fstab = (root / "fstab").read_text()
    assert fstab.count("swap sw 0 0") == 1

    # повтор: файл уже есть — ничего не делаем и fstab не дублируем
    (root / "swapfile").write_text("x")
    again = tls_ok(FakeRunner())
    ctx2 = make_ctx(root, again, want_swap=True)
    ctx2.state.reset()
    steps.run_steps(ctx2, steps.build_steps())
    assert not any("fallocate" in c for c in again.joined())
    assert (root / "fstab").read_text().count("swap sw 0 0") == 1


def test_swap_is_skipped_without_consent(root: Path) -> None:
    runner = tls_ok(FakeRunner())
    steps.run_steps(make_ctx(root, runner, want_swap=False), steps.build_steps())
    assert not any("fallocate" in c for c in runner.joined())


def test_docker_is_installed_only_with_consent(root: Path) -> None:
    runner = tls_ok(FakeRunner())
    steps.run_steps(make_ctx(root, runner, want_docker=True), steps.build_steps())
    joined = runner.joined()
    assert "apt-get update" in joined
    assert "apt-get install -y docker.io docker-compose-v2" in joined
    assert any("systemctl enable --now docker" in c for c in joined)


def test_docker_is_not_touched_by_default(root: Path) -> None:
    runner = tls_ok(FakeRunner())
    steps.run_steps(make_ctx(root, runner), steps.build_steps())
    assert "apt-get update" not in runner.joined()


def test_a_corrupted_state_file_is_treated_as_empty(root: Path) -> None:
    path = root / "deploy" / ".install-state"
    path.write_text("{not json")
    state = steps.State(path)
    assert state.done() == []
    state.mark("env")
    assert steps.State(path).done() == ["env"]


def test_command_errors_become_step_errors_with_the_failed_command(root: Path) -> None:
    runner = tls_ok(FakeRunner())
    runner.on("compose build", CommandError(["docker", "compose", "build"], 1, "no space left"))
    with pytest.raises(steps.StepError) as err:
        steps.run_steps(make_ctx(root, runner), steps.build_steps())
    assert "no space left" in str(err.value)


def test_existing_env_is_left_alone_when_reuse_is_chosen(root: Path) -> None:
    write_env(root / "deploy" / ".env", "KEEP=1\n")
    before = env_hash(root)
    ctx = make_ctx(root, tls_ok(FakeRunner()), reuse_env=True)
    steps.run_steps(ctx, steps.build_steps())
    assert env_hash(root) == before
