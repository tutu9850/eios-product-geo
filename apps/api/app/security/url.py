"""Outbound URL validation for user supplied URLs.

This is deliberately strict: GEO only fetches public HTTP(S) pages and must
never be used to reach loopback, link-local, private, or cloud metadata hosts.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse


class UnsafeURL(ValueError):
    """The URL is not safe for an outbound fetch."""


def _public_host(host: str) -> None:
    if not host:
        raise UnsafeURL("URL 缺少主机名")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]
        except OSError as exc:
            raise UnsafeURL("无法解析目标主机") from exc
    if not addresses:
        raise UnsafeURL("无法解析目标主机")
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise UnsafeURL("禁止访问内网、环回或保留地址")


def validate_public_url(url: str) -> str:
    """Validate and normalize one public HTTP(S) URL."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeURL("仅允许 HTTP(S) URL")
    if parsed.username or parsed.password:
        raise UnsafeURL("URL 不允许携带用户凭据")
    if parsed.port not in (None, 80, 443):
        raise UnsafeURL("禁止访问非标准 HTTP(S) 端口")
    _public_host(parsed.hostname or "")
    return parsed.geturl()


def redirect_url(base: str, location: str) -> str:
    """Resolve and validate a redirect target against the previous URL."""
    return validate_public_url(urljoin(base, location))

