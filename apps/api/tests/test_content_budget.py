"""Isolated checks for GEO's existing content-call wait budget."""
import asyncio
import time
import uuid

import pytest


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def tenant():
    from app.models.geo_models import engine, init_db
    from app.services.store import set_tenant

    init_db()
    set_tenant(f"tenant_budget_{uuid.uuid4().hex[:8]}")
    try:
        yield
    finally:
        set_tenant("tenant_corp_01")
        engine.dispose()


def test_bounded_call_stops_waiting_when_deadline_expires(monkeypatch):
    import adapters.llm as llm

    monkeypatch.setattr(llm, "_CONTENT_CALL_BUDGET_SECONDS", 0.02)
    cancelled = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(1)
            return "too late"
        finally:
            cancelled.set()

    with pytest.raises(llm.LLMError) as caught:
        _run(llm.bounded_content_call(work))
    assert caught.value.code == "CONTENT_DEADLINE_EXCEEDED"
    assert cancelled.is_set()


def test_task_cancellation_stops_wait_and_cancels_async_work(monkeypatch):
    import adapters.llm as llm

    monkeypatch.setattr(llm, "_CONTENT_CALL_BUDGET_SECONDS", 1)
    cancelled = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.set()

    async def cancel_call():
        task = asyncio.create_task(llm.bounded_content_call(work))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(cancel_call())
    assert cancelled.is_set()


def test_improve_source_check_is_inside_the_same_budget(monkeypatch):
    import adapters.llm as llm
    import app.api.v1.content as api

    monkeypatch.setattr(llm, "_CONTENT_CALL_BUDGET_SECONDS", 0.01)
    invoked_model = False

    async def slow_source_check(_req):
        await asyncio.sleep(0.03)
        return [], []

    async def model_call(**_kwargs):
        nonlocal invoked_model
        invoked_model = True
        return {"content": "改稿"}

    monkeypatch.setattr(api, "_validate_saved_sources", slow_source_check)
    import services.content as service
    monkeypatch.setattr(service, "improve", model_call)

    result = _run(api.improve(api.ImproveIn(
        content="原稿", instruction="缩短", context_sources=[],
    )))
    assert result["error"]["code"] == "CONTENT_DEADLINE_EXCEEDED"
    assert invoked_model is False


def test_late_sync_model_reply_is_not_returned_as_success(monkeypatch):
    import adapters.llm as llm

    monkeypatch.setattr(llm, "require_outbound_network", lambda _name: None)
    monkeypatch.setattr(llm, "_invoke_sync", lambda *_args: (time.sleep(0.06), "late success")[1])

    async def call():
        with llm.call_budget(0.01):
            return await llm.chat("prompt")

    with pytest.raises(llm.LLMError) as caught:
        _run(call())
    assert caught.value.code == "CONTENT_DEADLINE_EXCEEDED"
    # The synchronous worker may finish in its thread, but its result is discarded.
    time.sleep(0.08)


def test_transient_retry_exhaustion_obeys_deadline(monkeypatch, tenant):
    import adapters.llm as llm
    import services.content as content

    monkeypatch.setattr(llm, "_CONTENT_CALL_BUDGET_SECONDS", 0.01)
    calls = 0

    async def context(**_kwargs):
        return {
            "company_name": "示例公司", "materials": [], "context_sources": [],
            "source_material_ids": [], "knowledge_status": "ready", "warnings": [],
            "faq_assets": [], "other_assets": [], "pool_questions": [], "signals": {},
            "uploaded_sources": [],
        }

    async def fact_gate(_question):
        return {"unverified": []}

    async def transient_chat(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        raise llm.LLMError("RATE_LIMITED", "busy")

    async def no_delay(_seconds):
        return None

    monkeypatch.setattr(content, "build_context", context)
    monkeypatch.setattr(content, "_fact_gate", fact_gate)
    monkeypatch.setattr(content, "chat", transient_chat)
    monkeypatch.setattr(asyncio, "sleep", no_delay)

    with llm.call_budget(0.01), pytest.raises(llm.LLMError) as caught:
        _run(content.generate(question="介绍示例公司"))
    assert caught.value.code == "CONTENT_DEADLINE_EXCEEDED"
    assert calls == 1
