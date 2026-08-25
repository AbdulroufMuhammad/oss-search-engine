"""Blocks fetching internal/private targets from user-supplied URLs (SSRF guard).

Used by anything that fetches a caller-supplied URL (e.g. /v1/extract) — without
this, an authenticated caller could use the fetcher to reach internal services
(SearXNG on 127.0.0.1:8081, cloud metadata endpoints, etc.) that are otherwise
not externally reachable.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeUrlError(Exception):
    pass


def assert_safe_url(url: str) -> None:
    parts = urlsplit(url)

    if parts.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"scheme must be http or https, got {parts.scheme!r}")

    hostname = parts.hostname
    if not hostname:
        raise UnsafeUrlError("URL has no hostname")

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve hostname: {exc}") from exc

    for family, _, _, _, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise UnsafeUrlError(f"{hostname} resolves to a non-public address ({ip}); refusing to fetch")
