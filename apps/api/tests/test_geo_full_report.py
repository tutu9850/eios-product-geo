from app.api.v1.monitor import _analyze_answer
from app.api.v1 import report
from app.services.report_pdf import render_live_report_html


def test_explicit_non_recognition_is_not_counted_as_a_mention():
    result = _analyze_answer(
        "笔革家居",
        "笔革家居并不是一个广为人知的品牌，可能是输入法打字错误。",
    )
    assert result["mentioned"] is False
    assert result["recognition"] == "not_recognised"
    assert result["rank_est"] is None
    assert result["sentiment"] is None


def test_real_recognition_keeps_sentence_index_but_does_not_call_it_rank():
    result = _analyze_answer("笔革家居", "笔革家居位于成都，提供全案家居服务。")
    assert result["mentioned"] is True
    assert result["recognition"] == "recognised"
    assert result["rank_est"] == 1
    assert result["rank_est_kind"] == "sentence_index"


def test_ambiguous_canonical_name_does_not_become_a_company_fact():
    result = _analyze_answer(
        "比格家居",
        "比格家居（通常指Beegle比格或类似名称的互联网整装/定制家居品牌）在市场上主打性价比。"
        "根据大量用户反馈和行业观察，这类品牌常见品控与售后问题。",
    )
    assert result["recognition"] == "not_recognised"
    assert result["mentioned"] is False
    assert result["sentiment"] is None
    assert result["sentiment_status"] == "unknown"


def test_typo_or_similar_brand_claim_does_not_become_a_company_fact():
    result = _analyze_answer(
        "笔革家居",
        "你提到的“笔革家居”，大概率是“佰怡家”的笔误，或者是某个区域性品牌。"
        "我主要拿它和索菲亚这个行业头部品牌来做个对比。",
    )
    assert result["recognition"] == "not_recognised"
    assert result["mentioned"] is False
    assert result["sentiment"] is None


def test_stored_snippet_is_reassessed_when_full_answer_is_missing():
    from app.api.v1.monitor import _reassess_history_engine

    result = _reassess_history_engine(
        "brand_1",
        {
            "snippet": "你提到的“笔革家居”，大概率是“佰怡家”的笔误，或者是某个区域性品牌。",
            "mentioned": True,
            "recognition": "recognised",
            "sentiment": "positive",
        },
        {"brand_1": {"type": "brand", "config_json": {"company": "笔革家居"}}},
    )
    assert result["recognition"] == "not_recognised"
    assert result["mentioned"] is False
    assert result["sentiment"] is None


def test_competitor_monitor_reassesses_against_target_brand():
    from app.api.v1.monitor import _reassess_history_engine

    result = _reassess_history_engine(
        "pair_1",
        {
            "snippet": "你提到的“笔革家居”，大概率是“佰怡家”的笔误，或者是某个区域性品牌。",
            "mentioned": True,
            "recognition": "recognised",
            "sentiment": "positive",
        },
        {"pair_1": {"type": "competitor", "entity": "笔革家居 vs 索菲亚", "config_json": {"target": "笔革家居"}}},
    )
    assert result["recognition"] == "not_recognised"
    assert result["mentioned"] is False
    assert result["sentiment"] is None


def test_answers_reassesses_competitor_rows_instead_of_reusing_stale_flags(monkeypatch):
    import asyncio
    from app.api.v1 import monitor

    monkeypatch.setattr(monitor, "_load_history", lambda: [{
        "id": "batch-competitor", "created_at": "2026-09-27T00:00:00Z",
        "questions": [{"monitor_id": "pair-1", "question": "笔革家居还是索菲亚？", "engine_detail": [{
            "engine_name": "DeepSeek",
            "answer": "你提到的‘笔革家居’，大概率是‘佰怡家’的笔误，或者是某个区域性品牌。",
            "mentioned": True,
            "sentiment": "positive",
        }]}],
    }])
    monkeypatch.setattr(monitor, "_load_items", lambda: [{
        "monitor_id": "pair-1", "type": "competitor", "entity": "笔革家居 vs 索菲亚",
        "status": "active", "config_json": {"company": "笔革家居", "target": "笔革家居"},
    }])

    data = asyncio.run(monitor.answers(page=1, page_size=10, monitor_id="pair-1"))["data"]
    row = data["answers"][0]
    assert row["recognition"] == "not_recognised"
    assert row["mentioned"] is False
    assert row["sentiment"] is None
    assert row["sentiment_status"] == "unknown"


def test_quick_check_uses_the_explicit_brand_monitor(monkeypatch):
    import asyncio
    from app.api.v1 import monitor

    monkeypatch.setattr(
        monitor,
        "_load_items",
        lambda: [{
            "monitor_id": "brand_1",
            "type": "brand",
            "status": "active",
            "entity": "展示名",
            "config_json": {"company": "真实企业", "aliases": ["真实品牌"]},
        }],
    )
    seen = {}

    async def fake_run(question, company_name, engines=None, full=False, aliases=None, **kwargs):
        seen.update(question=question, company_name=company_name, aliases=aliases)
        return [{"engine_name": "DeepSeek", "configured": True, "mentioned": True, "rank_est": 1, "sentiment": "neutral", "snippet": "真实企业"}]

    monkeypatch.setattr(monitor, "_run_check", fake_run)
    monkeypatch.setattr(monitor, "_append_history", lambda item: seen.update(history=item))
    response = asyncio.run(monitor.check(monitor.MonitorCheckIn(question="真实企业怎么样？", monitor_id="brand_1")))

    assert response["ok"] is True
    assert response["data"]["company_name"] == "真实企业"
    assert response["data"]["monitor_id"] == "brand_1"
    assert seen["company_name"] == "真实企业"
    assert seen["aliases"] == ["真实品牌"]
    assert seen["history"]["questions"][0]["monitor_id"] == "brand_1"


def test_paused_brands_are_not_available_as_analysis_subjects(monkeypatch):
    from app.api.v1 import monitor

    monkeypatch.setattr(
        monitor,
        "_load_items",
        lambda: [
            {"monitor_id": "active", "type": "brand", "status": "active", "config_json": {"company": "甲"}},
            {"monitor_id": "paused", "type": "brand", "status": "paused", "config_json": {"company": "乙"}},
            {"monitor_id": "product", "type": "product", "status": "active", "config_json": {"company": "甲"}},
        ],
    )
    assert [row["monitor_id"] for row in monitor._brand_scope_options()] == ["active"]
    assert [row["monitor_id"] for row in monitor._active_brands()] == ["active"]


def test_live_report_contains_the_trust_and_comparison_sections():
    html = render_live_report_html({
        "company": "笔革家居",
        "generated_at": "2026/09/22 16:00:00",
        "health": {
            "total": 35,
            "dims": [{"label": "品牌认知", "score": 35, "basis": "真实回答提及率"}],
            "sample": {
                "question_total": 62,
                "engine_total": 6,
                "engine_effective": 4,
                "silent_engines": ["Kimi", "通义千问"],
                "engines": [],
            },
        },
        "competitors": {
            "groups": [],
            "matrix": {"columns": ["我", "竞品A"], "rows": [{"label": "正面描述率", "values": ["35%", "49%"]}]},
        },
    })
    assert "有效引擎 4/6" in html
    assert "本期未返回：Kimi、通义千问" in html
    assert "对象对比矩阵" in html
    assert "正面描述率" in html
    assert "规则建议" in html


def test_report_identity_does_not_split_a_string_product_into_characters(monkeypatch):
    class Store:
        def load(self, key):
            assert key == "monitor_items"
            return [{
                "type": "brand",
                "entity": "笔革家居",
                "config_json": {"industry": "家居", "product": "全屋定制"},
            }]

    monkeypatch.setattr(report, "get_store", lambda: Store())
    monkeypatch.setattr(report.cognition, "_brand_name_and_aliases", lambda: ("笔革家居", []))
    company, industry, products = report._identity()
    assert company == "笔革家居"
    assert industry == "家居"
    assert products == ["全屋定制"]
