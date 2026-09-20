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
        ("POST", "/knowledge/reset"),
        ("POST", "/knowledge/materials"),
        ("POST", "/knowledge/materials/upload"),
        ("POST", "/monitor/batch"),
        ("GET", "/stats/overview"),
        ("DELETE", "/distill/questions"),
    ],
)
def test_routes_outside_the_frozen_inventory_are_refused(product_door, method, path):
    response = product_door.request(method, f"{PRODUCT_DOOR_PREFIX}{path}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GEO_ROUTE_NOT_ALLOWED"


def test_every_allowlisted_route_maps_onto_a_real_legacy_route():
    """The door may not invent endpoints: each product path must own a v1 route."""
    methods = {"get", "post", "put", "patch", "delete"}
    spec = app.openapi()
    legacy = {
        (m.upper(), _normalized(p))
        for p, ops in spec["paths"].items()
        for m in ops
        if m.lower() in methods
    }
    unmapped = [
        (method, pattern)
        for method, pattern in _product_route_patterns()
        if (method, _normalized("/api/v1" + pattern)) not in legacy
    ]
    assert unmapped == []


def _normalized(path: str) -> str:
    return re.sub(r"\{[^}]+\}|\[[^\]]+\][+*?]?", "{}", path)


def _product_route_patterns() -> list[tuple[str, str]]:
    from app.product import door

    return list(door._PRODUCT_ROUTES)


def test_report_pdf_route_is_admitted_and_owned_by_the_legacy_use_case(product_door):
    """周期报告 PDF（Owner 2026-09-21 拍板加入白名单）。

    老 v1 的 PDF handler 在「暂无报告」时回 **HTTP 200 + JSON**，不是文件。产品门只做
    路径适配，所以「有没有报告」这件事由老 handler 如实说，门不替它编一个空 PDF。
    """
    assert (
        map_product_path("GET", "/intelligence/reports/latest/pdf")
        == "/api/v1/intelligence/reports/latest/pdf"
    )
    # 老 handler 直连 SQLAlchemy 读报告表，不等同于建表（线上库一直有表）。测试库是空的，
    # 这里先建表，才是在验「门放行了这条路由」，而不是在验空库上的 500。
    from app.models.geo_models import init_db

    init_db()
    legacy = product_door.get("/api/v1/intelligence/reports/latest/pdf")
    through_door = product_door.get(f"{PRODUCT_DOOR_PREFIX}/intelligence/reports/latest/pdf")
    assert through_door.status_code == legacy.status_code
    if legacy.headers.get("content-type", "").startswith("application/pdf"):
        assert through_door.headers["content-type"].startswith("application/pdf")
        assert through_door.content[:4] == b"%PDF"
    else:
        # 「暂无报告」时老 handler 回 200 + JSON envelope；request_id 每次不同，逐字段比。
        assert through_door.json()["ok"] is False
        assert through_door.json()["error"] == legacy.json()["error"]


def test_path_mapping_is_a_prefix_adapter():
    assert map_product_path("GET", "/monitor/items") == "/api/v1/monitor/items"
    assert map_product_path("post", "/distill/gaps") == "/api/v1/distill/gaps"
    assert map_product_path("PUT", "/knowledge/materials/kb_1") == "/api/v1/knowledge/materials/kb_1"
    assert map_product_path("GET", "/knowledge/reset") is None
    assert map_product_path("POST", "/monitor/items") == "/api/v1/monitor/items"
