"""GEO product door — the frozen ``/api/product/geo/*`` API surface.

The door is a path adapter, not a second business implementation.  An
allowlisted product path is rewritten onto the legacy ``/api/v1/*`` route that
already owns that use case, so monitor / distill / cognition / content /
knowledge / onboard semantics, storage and the ``{ok,data,error}`` envelope
stay exactly what the legacy chain serves.

Two things the door deliberately owns itself:

* the ``product.geo_health/v1`` contract that EIOS product-api probes for GEO
  availability — a flat product payload, not the legacy envelope;
* the AuthContext carrier.  EIOS product-api signs ``EIOS-Auth-Context`` while
  GEO's fail-closed session seam reads ``Authorization: Bearer``; the door only
  translates the carrier and never relaxes ``app.product.http_auth``.

The door stays closed unless ``GEO_PRODUCT_DOOR=on``.  Until GEO-03 moves
identity to EIOS, an always-on door would silently give a legacy deployment a
second, unauthenticated namespace, so the switch is explicit and the payload
reports the identity mode it is running in.
"""
from __future__ import annotations

import os
import re
from typing import Any

from fastapi import Request
from starlette.responses import JSONResponse

from app.core.envelope import err
from app.product.http_auth import (
    ProductAuthenticationError,
    auth_context_mode_enabled,
    product_storage_ready,
    resolve_http_product_session,
)

PRODUCT_ID = "geo"
PRODUCT_DOOR_PREFIX = "/api/product/geo"
LEGACY_PREFIX = "/api/v1"
HEALTH_CONTRACT = "product.geo_health/v1"
AUTH_CONTEXT_HEADER = b"eios-auth-context"
IDENTITY_HEADER = b"x-eios-geo-identity"
IDENTITY_HEADER_NAME = "X-EIOS-GEO-Identity"

#: HTTP methods and product-relative paths the product door exposes.  This is the
#: frozen inventory of what the packaged GEO UI actually calls, not a prefix
#: passthrough: anything else is refused with ``GEO_ROUTE_NOT_ALLOWED`` even when
#: the legacy route exists (for example the ``/knowledge/reset`` maintenance door).
_PRODUCT_ROUTES: tuple[tuple[str, str], ...] = (
    # read
    ("GET", r"/monitor/items"),
    ("GET", r"/monitor/tasks"),
    ("GET", r"/monitor/answers"),
    ("GET", r"/monitor/sentiment"),
    ("GET", r"/monitor/citations"),
    ("GET", r"/cognition/competitors"),
    ("GET", r"/cognition/health"),
    ("GET", r"/cognition/portrait"),
    ("GET", r"/cognition/coverage"),
    ("GET", r"/cognition/reasons"),
    ("GET", r"/cognition/sources"),
    ("GET", r"/distill/gaps"),
    ("GET", r"/distill/plans"),
    ("GET", r"/distill/questions"),
    ("GET", r"/distill/cognition/profile"),
    ("GET", r"/intelligence/reports/latest/pdf"),
    ("GET", r"/knowledge/materials"),
    ("GET", r"/knowledge/materials/search"),
    ("GET", r"/knowledge/materials/[^/]+"),
    ("GET", r"/onboard/run-status"),
    ("GET", r"/onboard/status"),
    # write
    # 内测：从企业知识库初始化「本公司资料」（Owner 2026-09-21「单独一个按钮，内测用」）。
    # ``scan`` 只读知识库并把候选交给人点选；``apply`` 才改 GEO 自己那份快照。
    # 知识库对 GEO 仍然是只读的 —— 这两条都不会往知识库写一个字。
    ("POST", r"/kb-init/scan"),
    ("POST", r"/kb-init/apply"),
    ("POST", r"/onboard/auto-config"),
    ("POST", r"/monitor/items"),
    ("POST", r"/monitor/items/preview"),
    ("POST", r"/monitor/items/[^/]+/run"),
    ("POST", r"/monitor/tasks"),
    ("POST", r"/monitor/tasks/[^/]+/run"),
    ("POST", r"/distill/gaps"),
    ("POST", r"/distill/plans/from-gaps"),
    ("POST", r"/distill/content-plan"),
    ("POST", r"/distill/cognition/evaluate"),
    ("POST", r"/content/generate"),
    ("POST", r"/content/score"),
    ("PATCH", r"/monitor/items/[^/]+"),
    ("PATCH", r"/monitor/tasks/[^/]+"),
    ("DELETE", r"/monitor/items/[^/]+"),
    ("DELETE", r"/monitor/tasks/[^/]+"),
    ("DELETE", r"/distill/plans/[^/]+"),
    ("DELETE", r"/distill/questions/[^/]+"),
    ("DELETE", r"/knowledge/materials/[^/]+"),
    ("PUT", r"/knowledge/materials/[^/]+"),
)

_COMPILED_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(pattern)) for method, pattern in _PRODUCT_ROUTES
)


def door_enabled() -> bool:
    """The door is opt-in so a legacy deployment does not grow a new namespace."""
    return os.environ.get("GEO_PRODUCT_DOOR", "off").strip().lower() in {"on", "1", "true"}


def is_door_path(path: str) -> bool:
    return path == PRODUCT_DOOR_PREFIX or path.startswith(PRODUCT_DOOR_PREFIX + "/")


def map_product_path(method: str, product_path: str) -> str | None:
    """Return the legacy path that owns an allowlisted product path, else None."""
    normalized = product_path.rstrip("/") or "/"
    for allowed_method, pattern in _COMPILED_ROUTES:
        if allowed_method == method.upper() and pattern.fullmatch(normalized):
            return LEGACY_PREFIX + normalized
    return None


#: Explicit deployment acknowledgement that this GEO runs product-door requests on
#: legacy tenant identity.  Without it the door reports ``compatibility`` and EIOS
#: keeps the product closed; with it the door may answer ``ok`` while still saying
#: ``identity_mode=legacy``.  It is an acknowledgement, never a migration: GEO-03
#: still has to move identity to EIOS before a real enterprise uses this.
COMPAT_IDENTITY_ACK = "compatibility"


def identity_acknowledged() -> bool:
    return os.environ.get("GEO_PRODUCT_DOOR_IDENTITY_ACK", "").strip().lower() == COMPAT_IDENTITY_ACK


def product_health_payload() -> dict[str, Any]:
    """The ``product.geo_health/v1`` body EIOS product-api probes.

    ``status`` answers one question only: may EIOS expose this door?  It is ``ok``
    when GEO already serves product requests on verified EIOS identity, or when the
    deployment explicitly acknowledged compatibility identity.  Either way the
    payload states which identity and storage mode actually served it.
    """
    identity_mode = "auth_context" if auth_context_mode_enabled() else "legacy"
    storage_mode = "postgres" if product_storage_ready() else "legacy"
    migrated = identity_mode == "auth_context" and storage_mode == "postgres"
    acknowledged = identity_mode == "legacy" and identity_acknowledged()
    return {
        "contract": HEALTH_CONTRACT,
        "status": "ok" if (migrated or acknowledged) else "compatibility",
        "product_id": PRODUCT_ID,
        "identity_mode": identity_mode,
        "identity_acknowledged": acknowledged,
        "storage_mode": storage_mode,
        "door": "path-adapter",
    }


def _with_auth_context_carrier(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Translate the ``EIOS-Auth-Context`` carrier into a bearer token.

    EIOS product-api signs ``EIOS-Auth-Context``; GEO's session seam reads
    ``Authorization: Bearer``.  This only chooses the carrier — whether the token
    is accepted stays entirely with the injected verifier.
    """
    token: bytes | None = None
    has_authorization = False
    for name, value in headers:
        lowered = name.lower()
        if lowered == b"authorization":
            has_authorization = True
        elif lowered == AUTH_CONTEXT_HEADER:
            token = value.strip()
    if token is None or has_authorization or not token:
        return headers
    return [*headers, (b"authorization", b"Bearer " + token)]


class ProductDoorMiddleware:
    """Expose ``/api/product/geo/*`` over the legacy v1 use cases.

    Added last so it is the outermost user middleware: the AuthContext carrier is
    normalized and the path is rewritten before ``_tenant_context``, routing and
    the legacy exception handlers see the request — after the rewrite the request
    travels the legacy chain unchanged.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or not door_enabled() or not is_door_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        scope = dict(scope)
        scope["headers"] = _with_auth_context_carrier(list(scope.get("headers") or []))
        product_path = scope["path"][len(PRODUCT_DOOR_PREFIX):] or "/"

        # Every door response is labelled with the identity mode it actually ran
        # in, so an acceptance run can tell compatibility from migrated GEO.
        identity = "auth_context" if auth_context_mode_enabled() else "compatibility"

        async def marked_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                headers = [h for h in message.get("headers", []) if h[0].lower() != IDENTITY_HEADER]
                message["headers"] = [*headers, (IDENTITY_HEADER, identity.encode())]
            await send(message)

        if product_path.rstrip("/") == "/health":
            # The availability probe is answered by the door itself, because its
            # contract is a product payload rather than the legacy envelope.
            if auth_context_mode_enabled():
                try:
                    await resolve_http_product_session(Request(scope))
                except ProductAuthenticationError as exc:
                    await JSONResponse(status_code=exc.status_code, content=err(exc.code, exc.message))(
                        scope, receive, marked_send
                    )
                    return
            await JSONResponse(content=product_health_payload())(scope, receive, marked_send)
            return

        legacy_path = map_product_path(scope.get("method", "GET"), product_path)
        if legacy_path is None:
            await JSONResponse(
                status_code=404,
                content=err("GEO_ROUTE_NOT_ALLOWED", "GEO product route is not allowed"),
            )(scope, receive, marked_send)
            return

        scope["path"] = legacy_path
        scope["raw_path"] = legacy_path.encode("utf-8")
        await self.app(scope, receive, marked_send)
