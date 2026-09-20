def test_baseline_mode_is_explicit(monkeypatch):
    from app.runtime.mode import is_baseline_mode

    monkeypatch.setenv("GEO_RUNTIME_MODE", "baseline")
    assert is_baseline_mode() is True
    monkeypatch.setenv("GEO_RUNTIME_MODE", "production")
    assert is_baseline_mode() is False


def test_baseline_mode_does_not_start_background_runtime(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    import services.scheduler as scheduler

    calls = []
    monkeypatch.setenv("GEO_RUNTIME_MODE", "baseline")
    monkeypatch.setattr(scheduler, "start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr(scheduler, "shutdown_scheduler", lambda: calls.append("shutdown"))

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200

    assert calls == []


def test_baseline_mode_blocks_primary_external_adapters(monkeypatch):
    import asyncio
    import pytest

    from adapters.eios import _request
    from adapters.llm import chat
    from app.runtime.mode import OutboundNetworkBlocked

    monkeypatch.setenv("GEO_RUNTIME_MODE", "baseline")
    with pytest.raises(OutboundNetworkBlocked, match="legacy_kernel"):
        asyncio.run(_request("GET", "/never"))
    with pytest.raises(OutboundNetworkBlocked, match="llm"):
        asyncio.run(chat("never"))
