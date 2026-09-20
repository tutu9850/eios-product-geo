"""ProductSession is the target GEO ownership context.

Legacy tenant headers and request payload values are deliberately absent.  The
initial P1 module only provides a trusted in-process binding seam; authentication
and signed session verification are introduced behind this seam in a later slice.
"""
from __future__ import annotations

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
