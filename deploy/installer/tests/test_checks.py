import pytest

from installer import checks
from installer.runner import CommandError, FakeNet, FakeRunner, Result

GIB = 1024**3

UBUNTU_2204 = 'ID=ubuntu\nVERSION_ID="22.04"\nPRETTY_NAME="Ubuntu 22.04.4 LTS"\n'
UBUNTU_2404 = 'ID=ubuntu\nVERSION_ID="24.04"\n'
UBUNTU_2004 = 'ID=ubuntu\nVERSION_ID="20.04"\n'
DEBIAN_12 = 'ID=debian\nVERSION_ID="12"\n'
DEBIAN_11 = 'ID=debian\nVERSION_ID="11"\n'
ALPINE = "ID=alpine\nVERSION_ID=3.19.1\n"


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        (UBUNTU_2204, True),
        (UBUNTU_2404, True),
        (DEBIAN_12, True),
        (DEBIAN_11, False),
        (UBUNTU_2004, False),
        (ALPINE, False),
        ("", False),
    ],
)
def test_check_os(text: str, ok: bool) -> None:
    finding = checks.check_os(text)
    assert finding.ok is ok
    if not ok:
        assert finding.blocking is True
        assert "Debian 12" in finding.hint and "Ubuntu 22.04" in finding.hint


def test_check_root() -> None:
    assert checks.check_root(0).ok
    finding = checks.check_root(1000)
    assert not finding.ok and finding.blocking
    assert "sudo" in finding.hint


def test_check_python() -> None:
    assert checks.check_python((3, 10, 12)).ok
    assert checks.check_python((3, 12, 0)).ok
    assert not checks.check_python((3, 9, 18)).ok


def meminfo(mem_gib: float, swap_gib: float) -> str:
    return (
        f"MemTotal:       {int(mem_gib * GIB / 1024)} kB\n"
        "MemFree:        100 kB\n"
        f"SwapTotal:      {int(swap_gib * GIB / 1024)} kB\n"
    )


@pytest.mark.parametrize(
    ("mem", "swap", "needs"),
    [(1, 0, True), (1, 2, False), (0.9, 0.5, False), (4, 0, False), (2, 0, False), (1.9, 0, True)],
)
def test_needs_swap(mem: float, swap: float, needs: bool) -> None:
    assert checks.needs_swap(meminfo(mem, swap)) is needs


def test_check_memory_warns_but_never_blocks() -> None:
    low = checks.check_memory(meminfo(1, 0))
    assert not low.ok and not low.blocking
    assert "swap" in low.hint.lower()
    assert checks.check_memory(meminfo(4, 0)).ok
    assert checks.check_memory(meminfo(1, 2)).ok


SS_FREE = ""
SS_TCP_80 = 'LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=812,fd=6))\n'
SS_TCP_443 = 'LISTEN 0 4096 [::]:443 [::]:* users:(("docker-proxy",pid=99,fd=4))\n'
SS_UDP_443 = 'UNCONN 0 0 0.0.0.0:443 0.0.0.0:* users:(("ocserv",pid=77,fd=3))\n'
SS_OTHER_PORT = "LISTEN 0 128 0.0.0.0:8080 0.0.0.0:*\nLISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n"


def ports_runner(tcp: str, udp: str) -> FakeRunner:
    fake = FakeRunner()
    fake.on("-ltn", Result(0, tcp))
    fake.on("-lun", Result(0, udp))
    return fake


def test_free_ports_are_fine() -> None:
    findings = checks.check_ports(ports_runner(SS_OTHER_PORT, SS_FREE))
    assert [f.ok for f in findings] == [True, True, True]
    assert [f.title for f in findings] == [
        "Порт 80/tcp свободен",
        "Порт 443/tcp свободен",
        "Порт 443/udp свободен",
    ]


def test_a_busy_port_blocks_and_names_the_process() -> None:
    findings = checks.check_ports(ports_runner(SS_TCP_80 + SS_TCP_443, SS_UDP_443))
    busy = [f for f in findings if not f.ok]
    assert len(busy) == 3
    assert all(f.blocking for f in busy)
    assert "nginx" in busy[0].hint and "80" in busy[0].title


def test_a_port_in_use_by_our_own_stack_is_not_a_problem() -> None:
    """Повторный запуск установщика: порты держат наши же контейнеры."""
    ours = 'LISTEN 0 4096 0.0.0.0:443 0.0.0.0:* users:(("docker-proxy",pid=1,fd=4))\n'
    fake = ports_runner(ours, "")
    fake.on("docker ps", Result(0, "ocm-caddy\nocm-ocserv\n"))
    findings = checks.check_ports(fake, our_containers_running=True)
    assert all(f.ok for f in findings)


def test_ss_missing_is_a_warning_not_a_crash() -> None:
    fake = FakeRunner()
    fake.on("ss ", CommandError(["ss"], 127, "not found"))
    findings = checks.check_ports(fake)
    assert findings and all(not f.blocking for f in findings)


def docker_runner(server: str = "27.1.1", compose: str = "2.29.1") -> FakeRunner:
    fake = FakeRunner()
    fake.on("docker version", Result(0, server + "\n"))
    fake.on("docker compose version", Result(0, compose + "\n"))
    return fake


def test_a_modern_docker_is_fine() -> None:
    finding = checks.check_docker(docker_runner())
    assert finding.ok and finding.code == "docker_ok"


def test_an_old_docker_blocks() -> None:
    finding = checks.check_docker(docker_runner(server="23.0.6"))
    assert not finding.ok and finding.blocking and finding.code == "docker_old"
    assert "24" in finding.hint


def test_compose_v1_blocks() -> None:
    fake = FakeRunner()
    fake.on("docker version", Result(0, "27.1.1\n"))
    fake.on("docker compose version", Result(125, "", "docker: 'compose' is not a docker command"))
    finding = checks.check_docker(fake)
    assert not finding.ok and finding.code == "compose_missing"


def test_no_docker_is_installable_not_blocking() -> None:
    fake = FakeRunner()
    fake.on("docker", Result(127, "", "docker: command not found"))
    finding = checks.check_docker(fake)
    assert not finding.ok and finding.code == "docker_missing"
    assert finding.blocking is False
    assert "установ" in finding.hint.lower()


def test_check_disk() -> None:
    assert checks.check_disk(20 * GIB).ok
    low = checks.check_disk(5 * GIB)
    assert not low.ok and low.blocking
    assert "8" in low.hint


def test_dns_matching_the_public_ip_is_fine() -> None:
    net = FakeNet(public_ip="203.0.113.10", a_records={"app.example.com": ["203.0.113.10"]})
    assert checks.check_dns(net, "app.example.com", "203.0.113.10").ok


def test_dns_pointing_elsewhere_blocks_and_shows_both_addresses() -> None:
    net = FakeNet(public_ip="203.0.113.10", a_records={"app.example.com": ["198.51.100.7"]})
    finding = checks.check_dns(net, "app.example.com", "203.0.113.10")
    assert not finding.ok and finding.blocking
    assert "198.51.100.7" in finding.hint and "203.0.113.10" in finding.hint


def test_no_a_record_blocks_with_a_hint() -> None:
    finding = checks.check_dns(FakeNet(public_ip="203.0.113.10"), "app.example.com", "203.0.113.10")
    assert not finding.ok and finding.blocking
    assert "A-запис" in finding.hint


def test_unknown_public_ip_warns_without_blocking() -> None:
    net = FakeNet(public_ip=None, a_records={"app.example.com": ["198.51.100.7"]})
    finding = checks.check_dns(net, "app.example.com", None)
    assert not finding.ok and finding.blocking is False


def test_dns_with_several_records_is_fine_if_ours_is_among_them() -> None:
    net = FakeNet(a_records={"a.example.com": ["1.1.1.1", "203.0.113.10"]})
    assert checks.check_dns(net, "a.example.com", "203.0.113.10").ok


def test_blocking_findings_filter() -> None:
    items = [
        checks.Finding(True, "a", "", True, "x"),
        checks.Finding(False, "b", "h", True, "y"),
        checks.Finding(False, "c", "h", False, "z"),
    ]
    assert [f.title for f in checks.blockers(items)] == ["b"]
