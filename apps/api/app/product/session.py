"""ProductSession is the target GEO ownership context.

Legacy tenant headers and request payload values are deliberately absent.  The
initial P1 module only provides a trusted in-process binding seam; authentication
and signed session verification are introduced behind this seam in a later slice.
"""
from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Protocol


@dataclass(frozen=True, slots=True)
class ProductSession:
    deployment_id: str
    enterprise_id: str
    principal_id: str
    actor_type: str
    service_id: str
    trace_ref: str | None = None


class VerifiedAuthContext(Protocol):
    """The verified subset of Foundation ``eios.auth_context/v1`` GEO consumes."""

    deployment_id: str
    enterprise_id: str
    subject: str
    service_id: str


def product_session_from_verified_auth_context(
    context: VerifiedAuthContext, *, trace_ref: str | None = None
) -> ProductSession:
    """Translate an already-verified Foundation AuthContext into product scope.

    Verification and trust-store selection intentionally remain outside GEO's
    product model.  This seam refuses malformed subjects rather than inventing
    a principal or falling back to legacy tenant data.
    """
    deployment_id = context.deployment_id.strip()
    enterprise_id = context.enterprise_id.strip()
    subject = context.subject.strip()
    service_id = context.service_id.strip()
    actor_type, separator, principal_id = subject.partition(":")
    if not deployment_id or not enterprise_id or not service_id:
        raise ValueError("verified AuthContext must include deployment, enterprise, and service")
    if separator != ":" or actor_type not in {"human", "agent", "system"} or not principal_id:
        raise ValueError("verified AuthContext subject must be human, agent, or system")
    return ProductSession(
        deployment_id=deployment_id,
        enterprise_id=enterprise_id,
        principal_id=subject,
        actor_type=actor_type,
        service_id=service_id,
        trace_ref=trace_ref,
    )


_current: ContextVar[ProductSession | None] = ContextVar("geo_product_session", default=None)


def current_product_session() -> ProductSession | None:
    """Return the trusted server-bound session, if the caller established one."""
    return _current.get()


@contextmanager
def bind_product_session(session: ProductSession) -> Iterator[ProductSession]:
    """Bind a session for a request, worker, or sealed test fixture.

    This function is intentionally not an HTTP-header parser: accepting caller
    supplied deployment/enterprise values here would recreate legacy authority.
    """
    token = _current.set(session)
    try:
        yield session
    finally:
        _current.reset(token)


# ── 账号分柜（Owner 2026-09-22 拍板）─────────────────────────────────────────
#
# 「这个产品注册一个人就开一份存储空间」—— Owner 原话。一个人做亚宇臻隆的 GEO 内容，
# 另一个人只做笔革家居的，两个人的资料不许互相看见、不许串。
#
# 柜号从**已验证会话**的 principal 推出来，不从 HTTP 头推 —— 头是调用方给的，
# 那等于让调用方自己挑柜子。本部署是单企业部署（``EIOS_ENTERPRISE_ID`` 一个值），
# 所以柜号只用 principal；**若以后一个 GEO 部署服务多企业，柜号必须把 enterprise 加进去**，
# 否则两个企业里同名的 ``alice`` 会落进同一个柜。
CABINET_PREFIX = "acct_"
#: 柜号会被写进 ``tenant_id`` 列，必须落在旧约束 ``^[A-Za-z0-9_-]{1,64}$`` 内。
_CABINET_SAFE = re.compile(r"[^A-Za-z0-9_-]+")
_CABINET_MAX_SLUG = 48


def cabinet_for_session(session: ProductSession) -> str:
    """这个账号的柜号（稳定、可读、只由已验证主体决定）。

    ``human:alice`` → ``acct_human_alice``。主体里没有可用的 ASCII 片段时
    （纯中文、符号、空）退化成哈希，**不回落默认柜** —— 回落等于把「分不清是谁」
    变成「大家一起用」。
    """
    raw = (session.principal_id or "").strip()
    slug = _CABINET_SAFE.sub("_", raw).strip("_")[:_CABINET_MAX_SLUG]
    if slug:
        return f"{CABINET_PREFIX}{slug}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{CABINET_PREFIX}{digest}"
