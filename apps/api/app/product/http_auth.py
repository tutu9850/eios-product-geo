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
    return os.environ.get("GEO_AUTH_MODE", "legacy").strip().lower() or "legacy"


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
