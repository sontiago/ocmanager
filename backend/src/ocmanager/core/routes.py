"""Адреса, которые клиенты VPN должны открывать напрямую, мимо туннеля (`no-route` в ocserv)."""

import ipaddress

MAX_ROUTES = 200


def normalize_route(raw: str) -> str:
    """`1.2.3.4` → `1.2.3.4/32`; `10.0.0.5/8` → `10.0.0.0/8`. Только IPv4: ocserv раздаёт клиентам
    IPv4-подсеть. Маршрут по умолчанию и служебные диапазоны отвергаются: они ломают туннель
    или не имеют смысла."""
    text = raw.strip()
    try:
        net = ipaddress.IPv4Network(text, strict=False)
    except ValueError:
        raise ValueError(
            f"{raw!r}: ожидается IPv4-адрес или подсеть вида 1.2.3.4 или 1.2.3.0/24"
        ) from None
    if net.prefixlen == 0:
        raise ValueError("0.0.0.0/0 отвергнут: это весь интернет, туннель потерял бы смысл")
    if net.is_loopback or net.is_multicast or net.is_unspecified or net.is_link_local:
        raise ValueError(f"{raw!r}: служебный диапазон")
    return str(net)


def normalize_routes(raw: list[str]) -> list[str]:
    """Без повторов, отсортировано по адресу."""
    nets = {ipaddress.IPv4Network(normalize_route(r)) for r in raw}
    return [str(n) for n in sorted(nets)]
