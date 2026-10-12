"""Tenant boundaries for the in-process Intelligence queue.

The queue is deliberately small and process-local, so these tests exercise the
ContextVar hand-off directly instead of starting a real LLM or the supervisor.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.store import current_tenant, set_tenant  # noqa: E402
from services.intelligence import queue  # noqa: E402


@pytest.fixture
def isolated_queue():
    """Save queue globals so a focused test cannot leak jobs into another test."""
    saved = {
        "queue": queue._queue,
        "worker": queue._worker_task,
        "deferred": queue._deferred,
        "loop": queue._main_loop,
        "since": queue._succeeded_since_report,
        "reports": queue._report_running,
    }
    queue._queue = None
    queue._worker_task = None
    queue._deferred = []
    queue._main_loop = None
    queue._succeeded_since_report = {}
    queue._report_running = set()
    try:
        yield
    finally:
        queue._queue = saved["queue"]
        queue._worker_task = saved["worker"]
        queue._deferred = saved["deferred"]
        queue._main_loop = saved["loop"]
        queue._succeeded_since_report = saved["since"]
        queue._report_running = saved["reports"]


def test_enqueue_captures_tenant_in_deferred_job(isolated_queue):
    set_tenant("tenant_alice")
    queue.enqueue("ev-alice")

    # The worker may run later under another request's ContextVar.  The queued
    # item must retain the cabinet that created it.
    set_tenant("tenant_bob")
    queue.enqueue("ev-explicit", tenant_id="tenant_explicit")

    assert queue._deferred == [
        ("tenant_alice", "ev-alice"),
        ("tenant_explicit", "ev-explicit"),
    ]


def test_worker_sets_and_restores_tenant_around_extractor(monkeypatch, isolated_queue):
    from services.intelligence import extractor

    seen: list[tuple[str, str]] = []

    async def fake_analyze(evidence_id: str):
        seen.append((evidence_id, current_tenant()))
        return {"status": "failed"}

    monkeypatch.setattr(extractor, "analyze_evidence", fake_analyze)

    async def run_worker_once():
        set_tenant("tenant_request")
        queue._queue = asyncio.Queue()
        queue._queue.put_nowait(("tenant_alice", "ev-alice"))
        task = asyncio.create_task(queue._worker())
        await queue._queue.join()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return current_tenant()

    restored = asyncio.run(run_worker_once())

    assert seen == [("ev-alice", "tenant_alice")]
    assert restored == "tenant_request"


def test_auto_report_receives_tenant_and_restores_context(monkeypatch, isolated_queue):
    from services.intelligence import reasoning

    seen: list[tuple[str | None, str]] = []

    async def fake_generate_report(**kwargs):
        seen.append((kwargs.get("tenant"), current_tenant()))
        return {"gap_matrix": [], "actions": []}

    monkeypatch.setattr(reasoning, "generate_report", fake_generate_report)

    async def run_report():
        set_tenant("tenant_request")
        await queue._auto_report("tenant_alice")
        return current_tenant()

    restored = asyncio.run(run_report())

    assert seen == [("tenant_alice", "tenant_alice")]
    assert restored == "tenant_request"
    assert "tenant_alice" not in queue._report_running


def test_recover_pending_scopes_tenant_and_monitor(monkeypatch, isolated_queue):
    from services.intelligence import repo

    requested: list[tuple[str | None, str | None]] = []
    enqueued: list[tuple[str, str | None]] = []

    pending = [
        {"id": "ev-one", "tenant_id": "tenant_alice", "context_json": '{"monitor_id":"m-one"}'},
        {"id": "ev-two", "tenant_id": "tenant_alice", "context_json": '{"monitor_id":"m-two"}'},
    ]

    monkeypatch.setattr(queue, "flush_deferred", lambda tenant_id=None: 0)

    def fake_pending(tenant_id=None, monitor_id=None):
        requested.append((tenant_id, monitor_id))
        return pending

    monkeypatch.setattr(repo, "list_evidence_pending", fake_pending)
    monkeypatch.setattr(queue, "enqueue", lambda evidence_id, tenant_id=None: enqueued.append((evidence_id, tenant_id)))

    set_tenant("tenant_alice")
    recovered = asyncio.run(queue.recover_pending(monitor_id="m-one"))

    assert recovered == 1
    assert requested == [("tenant_alice", "m-one")]
    assert enqueued == [("ev-one", "tenant_alice")]


def test_recover_sample_caps_jobs_and_disables_auto_report(monkeypatch, isolated_queue):
    from services.intelligence import extractor, repo

    pending = [
        {"id": f"ev-{index}", "tenant_id": "tenant_alice", "context_json": '{"monitor_id":"m-one"}'}
        for index in range(40)
    ]
    monkeypatch.setattr(repo, "list_evidence_pending", lambda *_args: pending)
    monkeypatch.setattr(queue, "flush_deferred", lambda *_args: pytest.fail("bounded recovery flushed unrelated deferred jobs"))
    monkeypatch.setattr(queue, "ensure_worker", lambda: queue._queue)
    queue._deferred = [("tenant_alice", "ev-unrelated")]

    async def fake_analyze(_evidence_id):
        return {"status": "succeeded"}

    async def forbidden_report(_tenant_id):
        pytest.fail("sample extraction generated an automatic report")

    monkeypatch.setattr(extractor, "analyze_evidence", fake_analyze)
    monkeypatch.setattr(queue, "_auto_report", forbidden_report)

    async def run_sample():
        set_tenant("tenant_alice")
        queue._queue = asyncio.Queue()
        count = await queue.recover_pending(monitor_id="m-one", limit=30, auto_report=False)
        task = asyncio.create_task(queue._worker())
        await queue._queue.join()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return count

    assert asyncio.run(run_sample()) == 30
    assert queue._deferred == [("tenant_alice", "ev-unrelated")]
    assert queue._succeeded_since_report == {}


def test_snapshot_defaults_to_current_tenant(isolated_queue):
    from datetime import datetime, timezone

    from app.models.geo_models import GeoExtraction, SessionLocal, init_db

    init_db()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add_all(
            [
                GeoExtraction(
                    id="ex-alice",
                    evidence_id="ev-alice",
                    status="succeeded",
                    version=1,
                    tenant_id="tenant_alice",
                    created_at=now,
                    updated_at=now,
                ),
                GeoExtraction(
                    id="ex-bob",
                    evidence_id="ev-bob",
                    status="failed",
                    version=1,
                    tenant_id="tenant_bob",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.commit()

    async def read_snapshot():
        set_tenant("tenant_alice")
        queue._queue = asyncio.Queue()
        queue._queue.put_nowait(("tenant_alice", "ev-pending"))
        queue._queue.put_nowait(("tenant_bob", "ev-other"))
        return await queue.snapshot()

    stats = asyncio.run(read_snapshot())

    assert stats["succeeded"] == 1
    assert stats["failed"] == 0
    assert stats["total"] == 1
    assert stats["queue_size"] == 1
