"""Network address helpers."""

from __future__ import annotations

import socket


def list_bind_addresses() -> list[str]:
    """Return common bind addresses plus local interface IPs (IPv4/IPv6)."""
    addresses = ["127.0.0.1", "::1", "0.0.0.0", "::"]
    seen = set(addresses)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, type=socket.SOCK_STREAM):
            ip = info[4][0]
            if "%" in ip:
                ip = ip.split("%", 1)[0]
            if ip not in seen:
                seen.add(ip)
                addresses.append(ip)
    except OSError:
        pass
    return addresses


def normalize_host(host: str) -> str:
    text = host.strip()
    if not text:
        raise ValueError("IP アドレスを設定してください")
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        socket.inet_pton(socket.AF_INET, text)
        return text
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, text)
        return text
    except OSError as exc:
        raise ValueError(f"無効な IP アドレスです: {host}") from exc
