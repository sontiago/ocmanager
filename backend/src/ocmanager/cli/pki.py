from pathlib import Path
from typing import Annotated

import typer
from cryptography.hazmat.primitives import serialization

from ocmanager.cli._common import fail, refuse_in_production, settings, write_file
from ocmanager.core.clock import utcnow
from ocmanager.provisioning.pki import ca as ca_mod
from ocmanager.provisioning.pki.certs import issue_client_cert, issue_server_cert
from ocmanager.provisioning.pki.crl import build_crl
from ocmanager.provisioning.pki.p12 import generate_password, pack_p12

app = typer.Typer(no_args_is_help=True)

CA_COMMON_NAME = "ocmanager CA"


@app.command()
def init() -> None:
    """Создаёт CA, пустой CRL и пустой allowed.list. Существующий CA не трогает.

    ocserv видит только ocserv_state_dir: туда кладётся копия ca.crt, а ca.key
    остаётся в pki_dir, который в контейнер ноды не монтируется."""
    s = settings()
    if (s.pki_dir / ca_mod.CA_KEY_FILE).exists() or (s.pki_dir / ca_mod.CA_CERT_FILE).exists():
        raise fail(
            f"CA уже существует в {s.pki_dir}. Перезапись уничтожит все выданные ключи — "
            "удалите каталог вручную, если действительно это нужно."
        )
    now = utcnow()
    ca = ca_mod.create_ca(CA_COMMON_NAME, now)
    ca_mod.save_ca(ca, s.pki_dir)
    state = s.ocserv_state_dir
    write_file(state / "ca.crt", ca.cert.public_bytes(serialization.Encoding.PEM), 0o644)
    # Новый CA — старый CRL недействителен, поэтому перезаписываем.
    write_file(state / "crl.pem", build_crl(ca, [], now), 0o644)
    allowlist = state / "allowed.list"
    if not allowlist.exists():
        write_file(allowlist, b"", 0o644)  # пустой список = всем отказ
    typer.echo(f"CA создан: {s.pki_dir / ca_mod.CA_CERT_FILE}")


@app.command("dev-server-cert")
def dev_server_cert(
    host: Annotated[list[str], typer.Option("--host", help="DNS-имя или IP, можно несколько")],
) -> None:
    """Серверный сертификат ocserv от нашего CA (только dev) — в каталог состояния ноды."""
    s = settings()
    refuse_in_production(s)
    ca = ca_mod.load_ca(s.pki_dir)
    issued = issue_server_cert(ca, host, utcnow())
    key_pem = issued.key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    state = s.ocserv_state_dir
    write_file(state / "server.key", key_pem, 0o600)
    write_file(
        state / "server.crt",
        issued.cert.public_bytes(serialization.Encoding.PEM),
        0o644,
    )
    typer.echo(f"server.crt для {', '.join(host)}")


@app.command("issue-test-cert")
def issue_test_cert(
    cn: Annotated[str, typer.Argument(help="ocserv-username, например c9001-d1")],
    out: Annotated[Path, typer.Option("--out", help="куда записать .p12")],
) -> None:
    """Клиентский .p12 для ручной проверки (только dev). Печатает пароль и серийный номер."""
    s = settings()
    refuse_in_production(s)
    ca = ca_mod.load_ca(s.pki_dir)
    try:
        issued = issue_client_cert(ca, cn, utcnow())
    except ValueError as exc:
        raise fail(str(exc)) from None
    password = generate_password()
    write_file(out, pack_p12(issued, ca.cert, password, friendly_name=cn), 0o600)
    typer.echo(f"password: {password}")
    typer.echo(f"serial:   {issued.serial}")
