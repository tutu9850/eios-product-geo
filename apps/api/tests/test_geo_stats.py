"""总览统计的可解释性边界。"""

import asyncio


def test_stats_never_reports_more_answered_models_than_current_catalog(monkeypatch):
    from app.api.v1 import stats

    monkeypatch.setattr(stats, "_load_materials", lambda: [])
    monkeypatch.setattr(stats, "_load_links", lambda: [])
    monkeypatch.setattr(
        stats,
        "_load_history",
        lambda: [{"batch": True, "summary": {}, "questions": [{"configured_count": 1}]}],
    )

    import adapters.engines as engines
    import adapters.eios as eios

    async def no_engines():
        return []

    async def no_entities():
        return []

    monkeypatch.setattr(engines, "list_engines", no_engines)
    monkeypatch.setattr(eios, "get_entities", no_entities)

    result = asyncio.run(stats.overview())
    assert result["data"]["engines"] == {"total": 0, "answered": 0}
