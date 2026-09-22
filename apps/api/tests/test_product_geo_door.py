"""Product door acceptance: the frozen /api/product/geo/* surface (GEO-01B).

The door must serve the legacy use cases unchanged, refuse everything that is
not in the frozen inventory, and never be mistaken for the migrated identity.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.product.door import PRODUCT_DOOR_PREFIX, map_product_path


class _Context:
    deployment_id = "dep_door"
    enterprise_id = "enterprise_door"
    subject = "human:alice"
    service_id = "eios-geo"


@pytest.fixture()
def product_door(monkeypatch):
    monkeypatch.setenv("GEO_PRODUCT_DOOR", "on")
    monkeypatch.delenv("GEO_AUTH_MODE", raising=False)
    monkeypatch.delenv("GEO_PRODUCT_STORAGE_MODE", raising=False)
    monkeypatch.delenv("GEO_RUNTIME_MODE", raising=False)
    return TestClient(app)


def test_door_is_closed_until_a_deployment_opts_in(monkeypatch):
    monkeypatch.delenv("GEO_PRODUCT_DOOR", raising=False)
    monkeypatch.delenv("GEO_RUNTIME_MODE", raising=False)
    with TestClient(app) as client:
        assert client.get(f"{PRODUCT_DOOR_PREFIX}/health").status_code == 404


def test_health_contract_reports_the_mode_it_actually_runs_in(product_door):
    response = product_door.get(f"{PRODUCT_DOOR_PREFIX}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["contract"] == "product.geo_health/v1"
    assert body["product_id"] == "geo"
    # Unmigrated and unacknowledged GEO must not answer "ok": EIOS availability
    # would go green on legacy tenant identity without anyone saying so.
    assert body["status"] == "compatibility"
    assert body["identity_mode"] == "legacy"
    assert body["identity_acknowledged"] is False
    assert body["storage_mode"] == "legacy"
    assert response.headers["x-eios-geo-identity"] == "compatibility"


def test_compatibility_identity_is_exposed_only_after_an_explicit_acknowledgement(monkeypatch):
    monkeypatch.setenv("GEO_PRODUCT_DOOR", "on")
    monkeypatch.delenv("GEO_AUTH_MODE", raising=False)
    monkeypatch.delenv("GEO_PRODUCT_STORAGE_MODE", raising=False)
    monkeypatch.delenv("GEO_RUNTIME_MODE", raising=False)
    monkeypatch.setenv("GEO_PRODUCT_DOOR_IDENTITY_ACK", "compatibility")
    client = TestClient(app)
    body = client.get(f"{PRODUCT_DOOR_PREFIX}/health").json()
    assert body["status"] == "ok"
    # The acknowledgement never hides what actually served the request.
    assert body["identity_mode"] == "legacy"
    assert body["identity_acknowledged"] is True
    monkeypatch.setenv("GEO_PRODUCT_DOOR_IDENTITY_ACK", "0")
    assert client.get(f"{PRODUCT_DOOR_PREFIX}/health").json()["status"] == "compatibility"


def test_health_contract_is_ok_only_when_identity_and_storage_are_migrated(monkeypatch):
    monkeypatch.setenv("GEO_PRODUCT_DOOR", "on")
    monkeypatch.setenv("GEO_AUTH_MODE", "auth_context")
    monkeypatch.setenv("GEO_PRODUCT_STORAGE_MODE", "postgres")
    monkeypatch.delenv("GEO_RUNTIME_MODE", raising=False)
    app.state.auth_context_verifier = lambda token: _Context() if token == "signed" else None
    try:
        # No lifespan: strict product startup needs a PostgreSQL URL this card does not own.
        client = TestClient(app)
        unauthenticated = client.get(f"{PRODUCT_DOOR_PREFIX}/health")
        authorized = client.get(f"{PRODUCT_DOOR_PREFIX}/health", headers={"EIOS-Auth-Context": "signed"})
    finally:
        del app.state.auth_context_verifier
    assert unauthenticated.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["status"] == "ok"
    assert authorized.headers["x-eios-geo-identity"] == "auth_context"


def test_eios_auth_context_carrier_never_replaces_the_verified_session(monkeypatch):
    """A tenant header is not an identity, even next to a valid product carrier."""
    monkeypatch.setenv("GEO_PRODUCT_DOOR", "on")
    monkeypatch.setenv("GEO_AUTH_MODE", "auth_context")
    monkeypatch.setenv("GEO_PRODUCT_STORAGE_MODE", "postgres")
    monkeypatch.delenv("GEO_RUNTIME_MODE", raising=False)
    app.state.auth_context_verifier = lambda token: _Context() if token == "signed" else None
    try:
        client = TestClient(app)
        tenant_only = client.get(
            f"{PRODUCT_DOOR_PREFIX}/health", headers={"X-Tenant-Id": "tenant_corp_01"}
        )
        carried = client.get(
            f"{PRODUCT_DOOR_PREFIX}/health",
            headers={"EIOS-Auth-Context": "signed", "X-Tenant-Id": "tenant_attacker"},
        )
    finally:
        del app.state.auth_context_verifier
    assert tenant_only.status_code == 401
    assert tenant_only.json()["error"]["code"] == "AUTH_CONTEXT_REQUIRED"
    assert carried.status_code == 200


def test_allowlisted_path_is_served_by_the_legacy_use_case(product_door):
    legacy = product_door.get("/api/v1/monitor/items")
    through_door = product_door.get(f"{PRODUCT_DOOR_PREFIX}/monitor/items")
    assert through_door.status_code == legacy.status_code
    assert through_door.json()["ok"] == legacy.json()["ok"]
    assert through_door.headers["x-eios-geo-identity"] == "compatibility"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        # The Advisor hand-off face verifies its own signature and the Advisor calls
        # it directly. 2026-09-21 opened the whole legacy v1 surface; these three are
        # what stayed shut, because they are not the product door's to sign.
        ("GET", "/geo/consumer/knowledge"),
        ("GET", "/geo/consumer/snapshots"),
        ("GET", "/geo/consumer/summary"),
        # Retired P1 observation names: they never owned a legacy route.
        ("POST", "/monitor/objects"),
        ("GET", "/observation/overview"),
        ("POST", "/capability/question-generate"),
        ("POST", "/setup/draft"),
        # A method the owning legacy route does not have, and a name it never had.
        ("PUT", "/monitor/items/mi_1"),
        ("POST", "/knowledge/unknown"),
        ("DELETE", "/distill/questions"),
    ],
)
def test_routes_outside_the_frozen_inventory_are_refused(product_door, method, path):
    response = product_door.request(method, f"{PRODUCT_DOOR_PREFIX}{path}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GEO_ROUTE_NOT_ALLOWED"


def test_every_allowlisted_route_maps_onto_a_real_legacy_route():
    """The door may not invent endpoints: each product path must own a v1 route."""
    legacy = _legacy_inventory()
    unmapped = [
        (method, pattern)
        for method, pattern in _product_route_patterns()
        if (method, _normalized("/api/v1" + pattern)) not in legacy
    ]
    assert unmapped == []


def test_the_opened_surface_is_the_legacy_v1_surface_minus_the_advisor_handoff():
    """Owner 2026-09-21「把 GEO 全部功能都连起来，通了他们」：老 v1 面整面接上。

    This pins the ruling, not a habit: of the 139 legacy routes, 135 are served by this
    door. The only four it does not serve are the three ``geo/consumer/*`` routes --
    the Advisor hand-off face, which the Advisor calls directly on its own verified
    signature -- and ``health``, which the middleware answers itself. A future change
    that quietly closes a shipped route, or quietly opens a hand-off route, fails here.
    """
    allowlisted = {
        (method, _normalized("/api/v1" + pattern))
        for method, pattern in _product_route_patterns()
    }
    assert _legacy_inventory() - allowlisted == {
        ("GET", "/api/v1/geo/consumer/knowledge"),
        ("GET", "/api/v1/geo/consumer/snapshots"),
        ("GET", "/api/v1/geo/consumer/summary"),
        ("GET", "/api/v1/health"),
    }
    assert allowlisted - _legacy_inventory() == set()


def _normalized(path: str) -> str:
    return re.sub(r"\{[^}]+\}|\[[^\]]+\][+*?]?", "{}", path)


def _legacy_inventory() -> set[tuple[str, str]]:
    """Every real ``/api/v1`` route the app serves, as (METHOD, normalized path)."""
    methods = {"get", "post", "put", "patch", "delete"}
    return {
        (m.upper(), _normalized(p))
        for p, ops in app.openapi()["paths"].items()
        for m in ops
        if m.lower() in methods and p.startswith("/api/v1/")
    }


def _product_route_patterns() -> list[tuple[str, str]]:
    from app.product import door

    return list(door._PRODUCT_ROUTES)


def test_report_pdf_route_is_admitted_and_owned_by_the_legacy_use_case(product_door, monkeypatch):
    """冻结的历史 PDF 路径继续是对外文档门，内容改为实时聚合报告。"""
    assert (
        map_product_path("GET", "/intelligence/reports/latest/pdf")
        == "/api/v1/intelligence/reports/latest/pdf"
    )
    # 这里验路由所有权与文档响应；WeasyPrint/Pango 的真渲染在 PDF 专项验收中覆盖。
    monkeypatch.setattr("app.api.v1.report.render_live_report_pdf", lambda data: b"%PDF-1.7\n")
    legacy = product_door.get("/api/v1/intelligence/reports/latest/pdf")
    through_door = product_door.get(f"{PRODUCT_DOOR_PREFIX}/intelligence/reports/latest/pdf")
    assert through_door.status_code == legacy.status_code
    assert legacy.headers["content-type"].startswith("application/pdf")
    assert through_door.headers["content-type"].startswith("application/pdf")
    assert through_door.content[:4] == b"%PDF"


def test_kb_init_routes_are_admitted_and_owned_by_the_legacy_use_cases(product_door):
    """内测「知识库初始化」两条路由：门只做路径适配，语义归老 v1 的 use case。"""
    assert map_product_path("POST", "/kb-init/scan") == "/api/v1/kb-init/scan"
    assert map_product_path("POST", "/kb-init/apply") == "/api/v1/kb-init/apply"
    # 没进名单的邻居仍然被拒（放行是逐条的，不是前缀透传）
    assert map_product_path("GET", "/kb-init/scan") is None
    assert map_product_path("POST", "/kb-init/anything-else") is None


def test_path_mapping_is_a_prefix_adapter():
    assert map_product_path("GET", "/monitor/items") == "/api/v1/monitor/items"
    assert map_product_path("post", "/distill/gaps") == "/api/v1/distill/gaps"
    assert map_product_path("PUT", "/knowledge/materials/kb_1") == "/api/v1/knowledge/materials/kb_1"
    assert map_product_path("GET", "/knowledge/reset") is None
    assert map_product_path("POST", "/monitor/items") == "/api/v1/monitor/items"
