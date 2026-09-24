"""Fail-closed HTTP entry seam for a verified Foundation AuthContext."""
from __future__ import annotations

import inspect
import os
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from fastapi import Request

from app.product.session import ProductSession, product_session_from_verified_auth_context


AUTH_CONTEXT_MODE = "auth_context"


class AuthContextVerifier(Protocol):
    def __call__(self, token: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class ProductAuthenticationError(Exception):
    code: str
    message: str
    status_code: int


class AuthContextInvalid(ValueError):
    """A configured verifier rejected a bearer token."""


class AuthContextVerifierUnavailable(RuntimeError):
    """A configured verifier cannot currently establish token validity."""


def auth_mode() -> str:
    # Keep the legacy default for local compatibility. Production deployments
    # must set GEO_AUTH_MODE=auth_context; destructive operations are guarded
    # independently and never accept the legacy header shim.
    return os.environ.get("GEO_AUTH_MODE", "legacy").strip().lower() or "legacy"


#: 宿主（product-api）签给 GEO 的票的 audience。product-api 的 ``_probe_geo_available``
#: 与产品面转发都用这个值签名，GEO 只认它。
DEFAULT_HOST_AUDIENCE = "eios-geo"


def host_audience() -> str:
    return os.environ.get("EIOS_GEO_HOST_AUDIENCE", DEFAULT_HOST_AUDIENCE).strip() or DEFAULT_HOST_AUDIENCE


def cabinet_mode() -> str:
    """GEO 自己的库按什么分柜（``account`` = 每个登录账号一份，``none`` = 旧行为）。

    ``account`` 只在会话真被验过签时成立 —— 没验签就分不出「这个账号是谁」，
    那时候报 ``none``，不许把「没验」说成「按账号分了」。
    """
    return "account" if auth_context_mode_enabled() else "none"


def _host_trust_keys() -> dict[str, str]:
    """宿主票的信任钥：``kid=path`` 逗号分隔；单钥部署直接给部署公钥。"""
    explicit = os.environ.get("EIOS_GEO_HOST_TRUST_KEYS", "").strip()
    keys: dict[str, str] = {}
    if explicit:
        for item in explicit.split(","):
            kid, _, path = item.partition("=")
            if kid.strip() and path.strip():
                keys[kid.strip()] = path.strip()
        return keys
    single = os.environ.get("EIOS_AUTH_PUBLIC_KEY_PATH", "").strip()
    kid = os.environ.get("EIOS_AUTH_KID", "").strip()
    if single and kid:
        keys[kid] = single
    return keys


def default_auth_context_verifier() -> Callable[[str], Any]:
    """本部署装到 ``app.state.auth_context_verifier`` 的验签器。

    与 ``app.product.consumer_auth`` 同一套信任模型（都只认服务端验过的 AuthContext），
    但信任钥与 audience 是宿主那一条，各配各的。配置缺失 / 钥文件不在 / 基座库不在
    一律抛 ``ProductAuthenticationError``，**不降级成放行**。
    """

    def verify(token: str) -> Any:
        keys = _host_trust_keys()
        if not keys:
            raise ProductAuthenticationError(
                "AUTH_CONTEXT_UNAVAILABLE",
                "GEO 未配置宿主信任钥（EIOS_GEO_HOST_TRUST_KEYS 或 EIOS_AUTH_PUBLIC_KEY_PATH）",
                503,
            )
        issuer = os.environ.get("EIOS_AUTH_ISSUER", "").strip()
        if not issuer:
            raise ProductAuthenticationError(
                "AUTH_CONTEXT_UNAVAILABLE", "GEO 未配置 EIOS_AUTH_ISSUER", 503
            )
        from pathlib import Path

        missing = [kid for kid, path in keys.items() if not Path(path).is_file()]
        if missing:
            raise ProductAuthenticationError(
                "AUTH_CONTEXT_UNAVAILABLE",
                f"宿主信任钥文件不存在：{', '.join(sorted(missing))}",
                503,
            )
        try:
            from eios_auth import AuthContextError, TrustStore, verify_auth_context
        except ImportError as exc:
            raise ProductAuthenticationError(
                "AUTH_CONTEXT_UNAVAILABLE", f"eios_auth 不可用：{exc}", 503
            ) from exc
        try:
            return verify_auth_context(
                token,
                trust_store=TrustStore.from_pem_files(keys),
                expected_issuer=issuer,
                expected_audience=host_audience(),
            )
        except AuthContextError as exc:
            raise ProductAuthenticationError(
                exc.code or "AUTH_CONTEXT_INVALID", exc.message, exc.http_status or 401
            ) from exc

    return verify



def auth_context_mode_enabled() -> bool:
    return auth_mode() == AUTH_CONTEXT_MODE


def product_storage_ready() -> bool:
    """True only after P2 has installed product-owned PostgreSQL persistence."""
    return os.environ.get("GEO_PRODUCT_STORAGE_MODE", "legacy").strip().lower() == "postgres"


async def resolve_http_product_session(request: Request) -> ProductSession:
    """Resolve only a bearer token that a trusted server verifier has verified.

    The verifier is injected by process setup (or a sealed test), never chosen by
    an HTTP caller. GEO deliberately does not parse unverified claims itself.
    """
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ProductAuthenticationError("AUTH_CONTEXT_REQUIRED", "verified AuthContext is required", 401)
    verifier: Callable[[str], Any] | None = getattr(request.app.state, "auth_context_verifier", None)
    if verifier is None:
        raise ProductAuthenticationError("AUTH_CONTEXT_UNAVAILABLE", "AuthContext verifier is not configured", 503)
    try:
        context = verifier(token.strip())
        if inspect.isawaitable(context):
            context = await context
    except (AuthContextVerifierUnavailable, ConnectionError, TimeoutError) as exc:
        raise ProductAuthenticationError("AUTH_CONTEXT_UNAVAILABLE", "AuthContext verifier is unavailable", 503) from exc
    except (AuthContextInvalid, ValueError, PermissionError) as exc:
        raise ProductAuthenticationError("AUTH_CONTEXT_INVALID", "AuthContext token is invalid", 401) from exc
    try:
        return product_session_from_verified_auth_context(
            context, trace_ref=request.headers.get("X-Trace-Id") or f"geo_trace_{uuid.uuid4().hex}"
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProductAuthenticationError("AUTH_CONTEXT_INVALID", str(exc), 401) from exc
