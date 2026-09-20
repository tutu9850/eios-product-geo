"""PostgreSQL-backed black-box acceptance for GEO's P2 monitor slice.

Set GEO_TEST_POSTGRES_URL to run this test.  CI may supply a temporary
PostgreSQL instance; it never uses SQLite or the legacy Store.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.product.runtime.monitor_run import ProviderObservation
from app.product.runtime.monitor_run import IdempotencyInProgress, MonitorRunCommand, ProductMonitorRunService
from app.product.session import ProductSession


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]


class _Context:
    deployment_id = "dep_acceptance"
    enterprise_id = "enterprise_a"
    subject = "human:alice"
    service_id = "eios-geo"


class _Provider:
    binding_id = "geo-test-provider"
    adapter_version = "test-v1"
    calls = 0

    def observe(self, *, query: str, subject_id: str) -> ProviderObservation:
        self.calls += 1
        return ProviderObservation(
            raw_text=f"Provider observation for {subject_id}: {query}",
            source_key=f"test:{subject_id}:{query}",
            provider_request_ref=f"test-request-{self.calls}",
            provider_subject_id=f"native:{subject_id}",
            provider_payload={"test": True},
        )


@pytest.fixture()
def postgres_engine(monkeypatch):
    url = os.environ.get("GEO_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("set GEO_TEST_POSTGRES_URL for PostgreSQL vertical-slice acceptance")
    monkeypatch.setenv("GEO_PRODUCT_DATABASE_URL", url)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**os.environ, "GEO_PRODUCT_DATABASE_URL": url, "PYTHONPATH": str(API_ROOT)},
        check=True,
    )
    engine = create_engine(url)
    with engine.begin() as connection:
        for table in (
            "brand_mentions", "observation_extractions", "observations", "provider_attempts",
            "monitor_runs", "monitor_task_objects", "monitor_tasks", "monitor_objects", "product_tasks", "idempotency_records",
        ):
            connection.execute(text(f"DELETE FROM geo_product.{table}"))
    yield engine
    engine.dispose()


@pytest.fixture()
def strict_client(monkeypatch, postgres_engine):
    monkeypatch.setenv("GEO_RUNTIME_MODE", "baseline")
    monkeypatch.setenv("GEO_AUTH_MODE", "auth_context")
    monkeypatch.setenv("GEO_PRODUCT_STORAGE_MODE", "postgres")
    from app.main import app

    provider = _Provider()
    app.state.auth_context_verifier = lambda token: _Context() if token == "signed" else None
    app.state.product_database_engine = postgres_engine
    app.state.product_operation_policy = lambda session, operation: operation == "geo.monitor.run"
    app.state.geo_monitor_provider = provider
    with TestClient(app) as client:
        yield client, provider, postgres_engine


def _headers(key: str = "run-key") -> dict[str, str]:
    return {"Authorization": "Bearer signed", "Idempotency-Key": key, "X-Tenant-Id": "tenant_corp_01"}


def _payload(query: str = "Which company is recommended?") -> dict:
    return {"subject_namespace": "geo_product", "subject_type": "brand", "subject_id": "brand_acme", "query": query}


def test_monitor_run_vertical_slice_and_idempotency(strict_client):
    client, provider, engine = strict_client
    first = client.post("/api/v2/product/monitor-runs", headers=_headers(), json=_payload())
    assert first.status_code == 200, first.text
    body = first.json()["data"]
    assert body["replayed"] is False
    assert body["trace_ref"]

    replay = client.post("/api/v2/product/monitor-runs", headers=_headers(), json=_payload())
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["replayed"] is True
    assert replay.json()["data"]["run_id"] == body["run_id"]
    assert provider.calls == 1

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM geo_product.product_tasks")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM geo_product.provider_attempts")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM geo_product.observations")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM geo_product.idempotency_records WHERE status = 'succeeded'")).scalar_one() == 1


def test_monitor_run_rejects_idempotency_conflict_and_legacy_identity(strict_client):
    client, provider, engine = strict_client
    assert client.post("/api/v2/product/monitor-runs", headers=_headers("same-key"), json=_payload()).status_code == 200
    conflict = client.post("/api/v2/product/monitor-runs", headers=_headers("same-key"), json=_payload("Different query"))
    assert conflict.status_code == 409
    anonymous = client.post("/api/v2/product/monitor-runs", headers={"X-Tenant-Id": "tenant_corp_01"}, json=_payload())
    assert anonymous.status_code == 401
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM geo_product.observations")).scalar_one() == 1
    assert provider.calls == 1


def test_product_task_cannot_reference_other_enterprise_idempotency(postgres_engine):
    """The database, not just the service, rejects cross-owner task linkage."""
    with postgres_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO geo_product.idempotency_records
              (id, deployment_id, enterprise_id, operation, idempotency_key, request_hash, status)
            VALUES ('idem_a', 'dep_acceptance', 'enterprise_a', 'geo.monitor.run', 'owner-key', 'sha256:test', 'succeeded')
        """))
    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO geo_product.product_tasks
                  (id, deployment_id, enterprise_id, operation, initiating_actor, trace_ref, idempotency_key, request_hash, status)
                VALUES ('task_b', 'dep_acceptance', 'enterprise_b', 'geo.monitor.run', 'human:bob', 'trace_b', 'owner-key', 'sha256:test', 'in_progress')
            """))


def test_same_key_concurrent_execution_calls_provider_once(postgres_engine):
    started = threading.Event()

    class SlowProvider(_Provider):
        def observe(self, *, query: str, subject_id: str) -> ProviderObservation:
            started.set()
            time.sleep(0.2)
            return super().observe(query=query, subject_id=subject_id)

    session = ProductSession("dep_acceptance", "enterprise_a", "human:alice", "human", "eios-geo", "trace_concurrent")
    command = MonitorRunCommand("geo_product", "brand", "brand_acme", "concurrency test", "concurrent-key")
    provider = SlowProvider()
    service = ProductMonitorRunService(engine=postgres_engine, policy=lambda *_: True, provider=provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.execute, session=session, command=command)
        assert started.wait(timeout=2)
        second = pool.submit(service.execute, session=session, command=command)
        assert first.result(timeout=3).replayed is False
        with pytest.raises(IdempotencyInProgress):
            second.result(timeout=3)
    assert provider.calls == 1


def test_recovery_marks_stale_execution_failed(postgres_engine):
    class FailingProvider(_Provider):
        def observe(self, **_kwargs):
            raise AssertionError("provider must not run in recovery test")

    session = ProductSession("dep_acceptance", "enterprise_a", "human:alice", "human", "eios-geo", "trace_recovery")
    command = MonitorRunCommand("geo_product", "brand", "brand_acme", "recovery test", "recovery-key")
    service = ProductMonitorRunService(engine=postgres_engine, policy=lambda *_: True, provider=FailingProvider())
    execution = service._reserve(session, command)
    service._mark_running(session, execution)
    with postgres_engine.begin() as connection:
        connection.execute(text("UPDATE geo_product.provider_attempts SET started_at = now() - interval '2 hours'"))
    assert service.recover_stale(older_than=timedelta(minutes=1)) == 1
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT status FROM geo_product.idempotency_records WHERE idempotency_key = 'recovery-key'")) .scalar_one() == "failed"
