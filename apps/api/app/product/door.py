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
    cabinet_mode,
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

#: The frozen product surface: every legacy ``/api/v1`` route the GEO product serves,
#: named one at a time. 2026-09-21 Owner ruling ("把 GEO 全部功能都连起来，通了他们")
#: opened the whole legacy v1 surface instead of only the 37 routes the packaged UI
#: happened to call -- 135 of the 139 legacy routes are here.
#:
#: Deliberately absent: ``geo/consumer/*``, the Advisor hand-off face. It verifies its
#: own signature and the Advisor calls it directly, so this door must never hand it a
#: product session. Also absent: ``health``, which the middleware answers above.
#:
#: Every path here still has to own a real v1 route:
#: ``test_every_allowlisted_route_maps_onto_a_real_legacy_route`` fails if the door
#: invents an endpoint, and the scope comment on each row matches the same route in
#: ``eios-product-api``'s ``_GEO_ACTIONS``.
_PRODUCT_ROUTES: tuple[tuple[str, str], ...] = (
    # ── GET ──
    ("GET", r"/analyze/reports/[^/]+"),  # read
    ("GET", r"/cognition/competitors"),  # read
    ("GET", r"/cognition/coverage"),  # read
    ("GET", r"/cognition/health"),  # read
    ("GET", r"/cognition/portrait"),  # read
    ("GET", r"/cognition/reasons"),  # read
    ("GET", r"/cognition/sources"),  # read
    ("GET", r"/content/company"),  # read
    ("GET", r"/distill/cognition-map"),  # read
    ("GET", r"/distill/cognition-profile"),  # read
    ("GET", r"/distill/cognition/profile"),  # read
    ("GET", r"/distill/gaps"),  # read
    ("GET", r"/distill/overview"),  # read
    ("GET", r"/distill/plans"),  # read
    ("GET", r"/distill/questions"),  # read
    ("GET", r"/distill/questions/[^/]+/platforms"),  # read
    ("GET", r"/eios/export/knowledge-index"),  # read
    ("GET", r"/enterprise-profile/categories"),  # read
    ("GET", r"/enterprise-profile/export"),  # read
    ("GET", r"/enterprise-profile/items/[^/]+"),  # read
    ("GET", r"/enterprise-profile/overview"),  # read
    ("GET", r"/intelligence/analyses"),  # read
    ("GET", r"/intelligence/compare"),  # read
    ("GET", r"/intelligence/evidence"),  # read
    ("GET", r"/intelligence/factor-gaps"),  # read
    ("GET", r"/intelligence/gap-analysis"),  # read
    ("GET", r"/intelligence/harvest/runs/[^/]+"),  # read
    ("GET", r"/intelligence/humanize"),  # read
    ("GET", r"/intelligence/keywords"),  # read
    ("GET", r"/intelligence/matrix"),  # read
    ("GET", r"/intelligence/overview"),  # read
    ("GET", r"/intelligence/perception"),  # read
    ("GET", r"/intelligence/reports/latest"),  # read
    ("GET", r"/intelligence/reports/latest/pdf"),  # read
    ("GET", r"/intelligence/sov"),  # read
    ("GET", r"/intelligence/stats"),  # read
    ("GET", r"/intelligence/strategies"),  # read
    ("GET", r"/intelligence/trend-delta"),  # read
    ("GET", r"/knowledge/materials"),  # read
    ("GET", r"/knowledge/materials/[^/]+"),  # read
    ("GET", r"/knowledge/materials/search"),  # read
    ("GET", r"/knowledge/media/[^/]+"),  # read
    ("GET", r"/knowledge/profile"),  # read
    ("GET", r"/links"),  # read
    ("GET", r"/market/signals"),  # read
    ("GET", r"/market/watchlist"),  # read
    ("GET", r"/meta/engines"),  # read
    ("GET", r"/monitor/answers"),  # read
    ("GET", r"/monitor/citations"),  # read
    ("GET", r"/monitor/competitor"),  # read
    ("GET", r"/monitor/effects"),  # read
    ("GET", r"/monitor/export"),  # read
    ("GET", r"/monitor/fact-check"),  # read
    ("GET", r"/monitor/history"),  # read
    ("GET", r"/monitor/industry"),  # read
    ("GET", r"/monitor/items"),  # read
    ("GET", r"/monitor/items/[^/]+/trend"),  # read
    ("GET", r"/monitor/overview"),  # read
    ("GET", r"/monitor/pool"),  # read
    ("GET", r"/monitor/public-opinion"),  # read
    ("GET", r"/monitor/rank-sentiment"),  # read
    ("GET", r"/monitor/sentiment"),  # read
    ("GET", r"/monitor/sources"),  # read
    ("GET", r"/monitor/tasks"),  # read
    ("GET", r"/monitor/tasks/[^/]+/overview"),  # read
    ("GET", r"/onboard/run-status"),  # read
    ("GET", r"/onboard/status"),  # read
    ("GET", r"/stats/overview"),  # read
    # ── POST ──
    ("POST", r"/analyze/diagnose"),  # run
    ("POST", r"/battle"),  # run
    ("POST", r"/collect/crawl"),  # run
    ("POST", r"/content/generate"),  # manage
    ("POST", r"/content/parse"),  # read
    ("POST", r"/content/improve"),  # manage
    ("POST", r"/content/quality"),  # read
    ("POST", r"/content/save"),  # manage
    ("POST", r"/content/score"),  # read
    ("POST", r"/diagnose"),  # run
    ("POST", r"/distill/analyze"),  # manage
    ("POST", r"/distill/cognition/evaluate"),  # run
    ("POST", r"/distill/content-plan"),  # manage
    ("POST", r"/distill/content-publish"),  # manage
    ("POST", r"/distill/content-recheck"),  # manage
    ("POST", r"/distill/faq"),  # read
    ("POST", r"/distill/faq/upgraded"),  # read
    ("POST", r"/distill/gaps"),  # manage
    ("POST", r"/distill/loop/run"),  # run
    ("POST", r"/distill/opportunities"),  # manage
    ("POST", r"/distill/plans"),  # manage
    ("POST", r"/distill/plans/customer-gap"),  # manage
    ("POST", r"/distill/plans/from-gaps"),  # manage
    ("POST", r"/distill/plans/manual"),  # manage
    ("POST", r"/distill/questions"),  # manage
    ("POST", r"/enterprise-profile/items/[^/]+/plans"),  # manage
    ("POST", r"/enterprise-profile/refresh"),  # manage
    ("POST", r"/intelligence/analyze"),  # run
    ("POST", r"/intelligence/harvest/search"),  # run
    ("POST", r"/intelligence/recover"),  # run
    ("POST", r"/intelligence/reports/run"),  # run
    ("POST", r"/kb-init/apply"),  # manage
    ("POST", r"/kb-init/scan"),  # read
    ("POST", r"/keywords/expand"),  # run
    ("POST", r"/knowledge/materials"),  # manage
    ("POST", r"/knowledge/materials/upload"),  # manage
    ("POST", r"/knowledge/materials/vectorize"),  # run
    ("POST", r"/knowledge/media/upload"),  # manage
    ("POST", r"/knowledge/reset"),  # manage
    ("POST", r"/links"),  # manage
    ("POST", r"/links/check"),  # manage
    ("POST", r"/links/check-all"),  # manage
    ("POST", r"/market/collect"),  # run
    ("POST", r"/market/signals/[^/]+/confirm"),  # read
    ("POST", r"/market/signals/[^/]+/extract"),  # manage
    ("POST", r"/market/signals/[^/]+/ignore"),  # manage
    ("POST", r"/market/signals/[^/]+/to-plan"),  # manage
    ("POST", r"/market/watchlist"),  # manage
    ("POST", r"/meta/engines/[^/]+/ping"),  # run
    ("POST", r"/monitor/batch"),  # run
    ("POST", r"/monitor/check"),  # run
    ("POST", r"/monitor/generate-questions"),  # run
    ("POST", r"/monitor/items"),  # manage
    ("POST", r"/monitor/items/[^/]+/run"),  # run
    ("POST", r"/monitor/items/preview"),  # read
    ("POST", r"/monitor/pool"),  # manage
    ("POST", r"/monitor/tasks"),  # manage
    ("POST", r"/monitor/tasks/[^/]+/run"),  # run
    ("POST", r"/onboard/auto-config"),  # run
    # ── PUT ──
    ("PUT", r"/knowledge/materials/[^/]+"),  # manage
    # ── PATCH ──
    ("PATCH", r"/monitor/items/[^/]+"),  # manage
    ("PATCH", r"/monitor/tasks/[^/]+"),  # manage
    # ── DELETE ──
    ("DELETE", r"/distill/plans/[^/]+"),  # manage
    ("DELETE", r"/distill/questions/[^/]+"),  # manage
    ("DELETE", r"/knowledge/materials/[^/]+"),  # manage
    ("DELETE", r"/links/[^/]+"),  # manage
    ("DELETE", r"/market/watchlist/[^/]+"),  # manage
    ("DELETE", r"/monitor/items/[^/]+"),  # manage
    ("DELETE", r"/monitor/tasks/[^/]+"),  # manage
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
    #: 数据按什么分柜。``account`` = 每个登录账号一份（Owner 2026-09-22），
    #: 只在身份真被验过签时才成立 —— 没验签就分不出「这个账号是谁」。
    cabinets = cabinet_mode()
    migrated = identity_mode == "auth_context" and storage_mode == "postgres"
    acknowledged = identity_mode == "legacy" and identity_acknowledged()
    # Owner 2026-09-22：「先把 GEO 自己的柜做对」——身份已验证 + 按账号分柜时，
    # 产品面就真的在服务「这个账号自己的数据」，即使底层仍是 GEO 自己的 SQLite
    # （``storage_mode=legacy``）。所以可用性看的是那两件事，不再要求 postgres。
    served_on_verified_account = identity_mode == "auth_context" and cabinets == "account"
    return {
        "contract": HEALTH_CONTRACT,
        "status": "ok" if (served_on_verified_account or migrated or acknowledged) else "compatibility",
        "product_id": PRODUCT_ID,
        "identity_mode": identity_mode,
        "identity_acknowledged": acknowledged,
        "storage_mode": storage_mode,
        "cabinet_mode": cabinets,
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
