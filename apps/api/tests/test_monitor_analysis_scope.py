"""The six monitor analyses must use the same active brand subject scope."""

import asyncio

from app.api.v1 import monitor


def _run(awaitable):
    return asyncio.run(awaitable)


def _items():
    return [
        {
            "monitor_id": "brand_a",
            "type": "brand",
            "status": "active",
            "config_json": {"company": "甲公司", "industry": "家装"},
        },
        {
            "monitor_id": "brand_b",
            "type": "brand",
            "status": "active",
            "config_json": {"company": "乙公司", "industry": "教育"},
        },
        {
            "monitor_id": "comp_a",
            "type": "competitor",
            "status": "active",
            "config_json": {"company": "甲公司", "target": "甲公司", "competitor": ["竞品甲"]},
        },
        {
            "monitor_id": "comp_b",
            "type": "competitor",
            "status": "active",
            "config_json": {"company": "乙公司", "target": "乙公司", "competitor": ["竞品乙"]},
        },
        {
            "monitor_id": "kw_a",
            "type": "keyword",
            "status": "active",
            "entity": "家装",
            "config_json": {"keyword": "家装"},
        },
        {
            "monitor_id": "kw_b",
            "type": "keyword",
            "status": "active",
            "entity": "教育",
            "config_json": {"keyword": "教育"},
        },
    ]


def _history():
    return [
        {
            "batch": True,
            "created_at": "2026-09-27T00:00:00Z",
            "questions": [
                {
                    "monitor_id": "comp_a",
                    "question": "甲公司和竞品甲哪个好？",
                    "engine_detail": [{
                        "engine_name": "DeepSeek",
                        "answer": "甲公司和竞品甲都提供家装服务。",
                        "mentioned": True,
                        "sentiment": "neutral",
                    }],
                },
                {
                    "monitor_id": "comp_b",
                    "question": "乙公司和竞品乙哪个好？",
                    "engine_detail": [{
                        "engine_name": "DeepSeek",
                        "answer": "乙公司和竞品乙都提供教育服务。",
                        "mentioned": True,
                        "sentiment": "neutral",
                    }],
                },
                {
                    "monitor_id": "kw_a",
                    "question": "家装公司有哪些？",
                    "engine_detail": [{
                        "engine_name": "DeepSeek",
                        "answer": "甲甲有限公司提供家装服务。",
                        "mentioned": True,
                        "sentiment": "neutral",
                    }],
                },
                {
                    "monitor_id": "kw_b",
                    "question": "教育公司有哪些？",
                    "engine_detail": [{
                        "engine_name": "DeepSeek",
                        "answer": "乙有限公司提供教育服务。",
                        "mentioned": True,
                        "sentiment": "neutral",
                    }],
                },
                {
                    "monitor_id": "brand_a",
                    "question": "甲公司怎么样？",
                    "engine_detail": [{
                        "engine_name": "DeepSeek",
                        "answer": "甲公司提供家装服务。",
                        "mentioned": True,
                        "sentiment": "positive",
                    }],
                },
                {
                    "monitor_id": "brand_b",
                    "question": "乙公司怎么样？",
                    "engine_detail": [{
                        "engine_name": "DeepSeek",
                        "answer": "乙公司提供教育服务。",
                        "mentioned": True,
                        "sentiment": "negative",
                    }],
                },
            ],
        },
    ]


def test_competitor_analysis_follows_selected_active_brand(monkeypatch):
    monkeypatch.setattr(monitor, "_load_items", _items)
    monkeypatch.setattr(monitor, "_load_history", _history)

    data = _run(monitor.competitor(monitor_id="brand_a"))["data"]

    assert {row["monitor_id"] for row in data["pairs"]} == {"comp_a"}
    assert data["scope"]["monitor_id"] == "brand_a"
    assert data["scope"]["scope_required"] is False


def test_industry_analysis_matches_selected_brand_industry(monkeypatch):
    monkeypatch.setattr(monitor, "_load_items", _items)
    monkeypatch.setattr(monitor, "_load_history", _history)

    data = _run(monitor.industry(monitor_id="brand_a"))["data"]

    assert data["objects"] == 1
    assert data["total_answers"] == 1
    assert {row["name"] for row in data["players"]} == {"甲甲有限公司"}
    assert data["scope"]["monitor_id"] == "brand_a"


def test_sources_analysis_uses_only_selected_brand_answers(monkeypatch):
    monkeypatch.setattr(monitor, "_load_items", _items)
    monkeypatch.setattr(monitor, "_load_history", _history)

    data = _run(monitor.sources(monitor_id="brand_a"))["data"]

    assert data["sources"] == [{
        "engine": "DeepSeek",
        "total": 1,
        "mentioned": 1,
        "mention_pct": 100,
        "positive": 1,
        "negative": 0,
        "neutral": 0,
    }]
    assert data["scope"]["monitor_id"] == "brand_a"


def test_non_brand_analysis_requires_scope_when_multiple_brands(monkeypatch):
    monkeypatch.setattr(monitor, "_load_items", _items)
    monkeypatch.setattr(monitor, "_load_history", _history)

    for endpoint in (monitor.competitor, monitor.industry, monitor.sources):
        data = _run(endpoint())["data"]
        assert data["scope"]["scope_required"] is True
        assert not data.get("pairs", data.get("players", data.get("sources")))


def test_explicit_all_scope_uses_only_active_brand_answers(monkeypatch):
    items = [
        {"monitor_id": "brand_a", "type": "brand", "status": "active", "config_json": {"company": "甲公司"}},
        {"monitor_id": "brand_paused", "type": "brand", "status": "paused", "config_json": {"company": "旧公司"}},
        {"monitor_id": "product_a", "type": "product", "status": "active", "config_json": {"company": "甲产品"}},
    ]
    history = [{
        "batch": True,
        "created_at": "2026-09-27T00:00:00Z",
        "questions": [
            {"monitor_id": "brand_a", "question": "甲公司怎么样？", "engine_detail": [{"engine_name": "DeepSeek", "answer": "甲公司服务很好。", "mentioned": True, "sentiment": "positive"}]},
            {"monitor_id": "brand_paused", "question": "旧公司怎么样？", "engine_detail": [{"engine_name": "DeepSeek", "answer": "旧公司服务很差。", "mentioned": True, "sentiment": "negative"}]},
            {"monitor_id": "product_a", "question": "甲产品怎么样？", "engine_detail": [{"engine_name": "DeepSeek", "answer": "甲产品质量很差。", "mentioned": True, "sentiment": "negative"}]},
        ],
    }]
    monkeypatch.setattr(monitor, "_load_items", lambda: items)
    monkeypatch.setattr(monitor, "_load_history", lambda: history)

    opinion = _run(monitor.public_opinion(monitor_id="all"))["data"]
    sentiment = _run(monitor.sentiment(monitor_id="all"))["data"]
    overview = _run(monitor.overview(monitor_id="all"))["data"]

    assert opinion["health"]["total"] == 1
    assert sentiment["overview"]["total"] == 1
    assert overview["scope"]["monitor_id"] == "all"
    assert overview["recommend"]["value"] == 100
