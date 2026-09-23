import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro):
    return asyncio.run(coro)


def test_answers_paginates_complete_groups_and_reports_full_totals(monkeypatch):
    from app.api.v1 import monitor

    def batch(batch_id, mid, query):
        return {
            "id": batch_id, "batch": True, "created_at": f"2026-09-2{batch_id[-1]}T00:00:00Z",
            "questions": [{"monitor_id": mid, "query": query, "engine_detail": [
                {"engine_name": f"engine-{i}", "answer": f"answer-{i}", "mentioned": True}
                for i in range(6)
            ]}],
        }

    monkeypatch.setattr(monitor, "_load_history", lambda: [
        batch("b1", "brand-1", "same question"), batch("b2", "brand-2", "same question")
    ])
    monkeypatch.setattr(monitor, "_load_items", lambda: [
        {"monitor_id": "brand-1", "type": "brand"}, {"monitor_id": "brand-2", "type": "brand"}
    ])

    result = _run(monitor.answers(page=1, page_size=1, monitor_id="brand-1"))["data"]
    assert result["group_total"] == 1
    assert result["total"] == 6
    assert len(result["answers"]) == 6
    assert len(result["groups"][0]["answers"]) == 6
    assert {answer["monitor_id"] for answer in result["answers"]} == {"brand-1"}


def test_public_opinion_filters_monitor_and_time(monkeypatch):
    from app.api.v1 import monitor

    records = [
        {"monitor_id": "a", "question": "q", "engine_detail": [
            {"engine_name": "DeepSeek", "sentiment": "negative"}]},
        {"monitor_id": "b", "question": "q", "engine_detail": [
            {"engine_name": "DeepSeek", "sentiment": "positive"}]},
    ]
    history = [
        {"batch": True, "created_at": "2026-09-10T00:00:00Z", "questions": records},
        {"batch": True, "created_at": "2026-09-20T00:00:00Z", "questions": [
            {"monitor_id": "a", "question": "q2", "engine_detail": [
                {"engine_name": "DeepSeek", "sentiment": "positive"}]}
        ]},
    ]
    result = monitor._aggregate_public_opinion(history, monitor_id="a", start_at="2026-09-15")
    assert result["metrics"]["check_records"] == 1
    assert result["metrics"]["positive"] == 1
    assert result["scope"]["monitor_id"] == "a"


def test_sentiment_filters_monitor_and_time():
    from app.api.v1 import monitor

    history = [
        {"batch": True, "created_at": "2026-09-10T00:00:00Z", "questions": [
            {"monitor_id": "a", "question": "old", "engine_detail": [
                {"engine_name": "DeepSeek", "sentiment": "negative", "snippet": "old negative"}]},
            {"monitor_id": "b", "question": "other", "engine_detail": [
                {"engine_name": "DeepSeek", "sentiment": "negative", "snippet": "other negative"}]},
        ]},
        {"batch": True, "created_at": "2026-09-20T00:00:00Z", "questions": [
            {"monitor_id": "a", "question": "new", "engine_detail": [
                {"engine_name": "DeepSeek", "sentiment": "positive", "snippet": "new positive"}]},
        ]},
    ]
    result = monitor._aggregate_sentiment(history, monitor_id="a", start_at="2026-09-15")
    assert result["overview"] == {"total": 1, "positive": 1, "negative": 0, "neutral": 0,
                                  "pos_pct": 100, "neg_pct": 0, "neu_pct": 0}
    assert result["questions"][0]["question"] == "new"


def test_uncertain_brand_identity_is_not_a_negative_review():
    from app.api.v1.monitor import _analyze_answer

    answer = (
        "笔革家居靠谱吗？我无法给出一个绝对的是或否的结论，因为这取决于具体交易场景、个人体验，"
        "以及该品牌当前的经营状况。笔革家居可能是一个线上品牌、区域性的实体店，或者是某个平台的店铺名称。"
        "建议先确认它的官方渠道、公司主体和联系方式。"
    )
    result = _analyze_answer("笔革家居", answer)
    assert result["recognition"] == "not_recognised"
    assert result["mentioned"] is False
    assert result["sentiment"] is None
    assert result["sentiment_status"] == "unknown"


def test_quoted_yes_no_disclaimer_with_generic_risk_checklist_is_unknown():
    from app.api.v1.monitor import _analyze_answer

    answer = (
        "关于‘笔革家居’是否靠谱，我无法给出一个绝对的‘是’或‘否’的结论，"
        "因为这取决于具体交易场景。笔革家居可能是一个区域性品牌。"
        "判断这类商家时要查看投诉记录，规避不靠谱的店铺，谨防质量问题。"
    )
    result = _analyze_answer("笔革家居", answer)
    assert result["recognition"] == "not_recognised"
    assert result["sentiment"] is None


def test_uncertainty_rules_preserve_a_concrete_negative_review():
    from app.api.v1.monitor import _analyze_answer

    result = _analyze_answer(
        "笔革家居",
        "笔革家居多次被投诉质量差，售后问题严重，不建议购买。",
    )
    assert result["recognition"] == "recognised"
    assert result["mentioned"] is True
    assert result["sentiment"] == "negative"
    assert result["sentiment_status"] == "classified"


def test_uncertain_yes_or_no_wording_does_not_trigger_negative_keyword():
    from app.api.v1.monitor import _analyze_answer

    result = _analyze_answer("笔革家居", "笔革家居靠谱吗？很难说靠谱还是不靠谱，缺少可核实信息。")
    assert result["recognition"] == "not_recognised"
    assert result["sentiment"] is None
    assert result["sentiment_status"] == "unknown"


def test_full_historical_answer_is_reassessed_and_excluded_from_sentiment_totals(monkeypatch):
    from app.api.v1 import monitor

    answer = (
        "笔革家居靠谱吗？我无法给出一个绝对的是或否的结论。笔革家居可能是一个线上品牌、区域性的实体店，"
        "或者是某个平台的店铺名称。"
    )
    history = [{
        "batch": True, "created_at": "2026-09-22T00:00:00Z", "questions": [{
            "monitor_id": "brand-a", "question": "笔革家居靠谱吗？", "engine_detail": [{
                "engine_name": "DeepSeek", "answer": answer, "snippet": answer[:240],
                "mentioned": True, "recognition": "recognised", "sentiment": "negative",
            }],
        }],
    }]
    monkeypatch.setattr(monitor, "_load_items", lambda: [{
        "monitor_id": "brand-a", "type": "brand", "status": "active",
        "config_json": {"company": "笔革家居"},
    }])

    sentiment = monitor._aggregate_sentiment(history, monitor_id="brand-a")
    opinion = monitor._aggregate_public_opinion(history, monitor_id="brand-a")
    assert sentiment["overview"]["total"] == 0
    assert sentiment["unknown_count"] == 1
    assert opinion["health"]["total"] == 0
    assert opinion["health"]["score"] is None
    assert opinion["unknown_count"] == 1


def test_answers_returns_reassessed_recognition_and_unknown_status(monkeypatch):
    from app.api.v1 import monitor

    answer = "笔革家居靠谱吗？我无法给出一个绝对的是或否的结论。笔革家居可能是线上品牌或店铺名称。"
    monkeypatch.setattr(monitor, "_load_history", lambda: [{
        "id": "batch-1", "batch": True, "created_at": "2026-09-22T00:00:00Z",
        "questions": [{"monitor_id": "brand-a", "question": "笔革家居靠谱吗？", "engine_detail": [{
            "engine_name": "DeepSeek", "answer": answer, "mentioned": True, "sentiment": "negative",
        }]}],
    }])
    monkeypatch.setattr(monitor, "_load_items", lambda: [{
        "monitor_id": "brand-a", "type": "brand", "config_json": {"company": "笔革家居"},
    }])

    rows = _run(monitor.answers(page=1, page_size=10, monitor_id="brand-a"))["data"]["answers"]
    assert len(rows) == 1
    assert rows[0]["recognition"] == "not_recognised"
    assert rows[0]["mentioned"] is False
    assert rows[0]["sentiment"] is None
    assert rows[0]["sentiment_status"] == "unknown"


def test_overview_filters_to_selected_brand_and_recomputes_answer_metrics(monkeypatch):
    from app.api.v1 import monitor

    uncertain = "笔革家居靠谱吗？我无法给出一个绝对的是或否的结论。笔革家居可能是线上品牌或店铺名称。"
    history = [{
        "batch": True, "created_at": "2026-09-22T00:00:00Z",
        "questions": [
            {"monitor_id": "brand-a", "question": "笔革家居情况？", "engine_detail": [
                {"engine_name": "DeepSeek", "answer": "笔革家居是本地家具品牌，售后评价很好，值得推荐。",
                 "mentioned": False, "rank_est": None, "sentiment": "negative"}]},
            {"monitor_id": "brand-a", "question": "笔革家居靠谱吗？", "engine_detail": [
                {"engine_name": "Kimi", "answer": uncertain, "mentioned": True, "rank_est": 1,
                 "sentiment": "negative"}]},
            {"monitor_id": "brand-b", "question": "比格家居情况？", "engine_detail": [
                {"engine_name": "豆包", "answer": "比格家居推荐度很好。", "mentioned": True,
                 "rank_est": 1, "sentiment": "positive"}]},
        ],
    }]
    monkeypatch.setattr(monitor, "_load_history", lambda: history)
    monkeypatch.setattr(monitor, "_load_items", lambda: [
        {"monitor_id": "brand-a", "type": "brand", "status": "active", "config_json": {"company": "笔革家居"}},
        {"monitor_id": "brand-b", "type": "brand", "status": "active", "config_json": {"company": "比格家居"}},
    ])

    data = _run(monitor.overview(monitor_id="brand-a"))["data"]
    assert data["scope"]["monitor_id"] == "brand-a"
    assert data["recommend"]["value"] == 50  # unknown answer remains an answer, but is not a mention
    assert data["rank"]["value"] == 1
    assert set(data["platforms"]) == {"DeepSeek", "Kimi"}
    assert "豆包" not in data["platforms"]
    assert data["platforms"]["Kimi"][0]["mentioned"] == 0


def test_overview_requires_brand_selection_when_multiple_brands_exist(monkeypatch):
    from app.api.v1 import monitor

    monkeypatch.setattr(monitor, "_load_history", lambda: [])
    monkeypatch.setattr(monitor, "_load_items", lambda: [
        {"monitor_id": "brand-a", "type": "brand", "status": "active", "config_json": {"company": "笔革家居"}},
        {"monitor_id": "brand-b", "type": "brand", "status": "active", "config_json": {"company": "比格家居"}},
    ])
    data = _run(monitor.overview())["data"]
    assert data["scope"]["scope_required"] is True
    assert data["recommend"]["value"] is None
    assert data["rank"]["value"] is None
    assert data["platforms"] == {}
    assert {b["monitor_id"] for b in data["scope"]["brands"]} == {"brand-a", "brand-b"}


def test_overview_does_not_show_unanswered_platform_as_zero(monkeypatch):
    from app.api.v1 import monitor

    monkeypatch.setattr(monitor, "_load_history", lambda: [{
        "batch": True, "created_at": "2026-09-22T00:00:00Z", "questions": [{
            "monitor_id": "brand-a", "question": "笔革家居是什么？", "engine_detail": [
                {"engine_name": "DeepSeek", "answer": "笔革家居是家具品牌。", "mentioned": True},
                {"engine_name": "Kimi", "answer": "", "snippet": "", "mentioned": None},
            ],
        }],
    }])
    monkeypatch.setattr(monitor, "_load_items", lambda: [{
        "monitor_id": "brand-a", "type": "brand", "status": "active",
        "config_json": {"company": "笔革家居"},
    }])

    data = _run(monitor.overview(monitor_id="brand-a"))["data"]
    assert data["recommend"]["value"] == 100
    assert set(data["platforms"]) == {"DeepSeek"}


def test_fact_check_missing_evidence_is_not_a_distortion_or_hit(monkeypatch):
    from app.api.v1 import monitor

    base = {"company_name": "Brand A", "records": [
        {"monitor_id": "a", "question": "q", "platform": "DeepSeek",
         "snippet": "Brand A成立于2005年。", "ts": "2026-09-22T00:00:00Z"}
    ]}
    monkeypatch.setattr(monitor, "_aggregate_fact_check", lambda items, company_name=None: base)
    monkeypatch.setattr(monitor, "_load_history", lambda: [])
    monkeypatch.setattr(monitor, "_load_items", lambda: [
        {"monitor_id": "a", "type": "brand", "config_json": {"company": "Brand A"}}
    ])

    async def unsupported(*args):
        return {"checked": True, "abnormal": False, "unsupported": True,
                "main_type": "缺少依据", "reason": "知识库未覆盖", "knowledge_ok": True}

    monkeypatch.setattr(monitor, "_check_answer_facts", unsupported)
    data = _run(monitor.fact_check())["data"]
    assert data["truth"]["hit_kb"] == 0
    assert data["truth"]["abnormal_count"] == 0
    assert data["truth"]["unsupported_count"] == 1


def test_fact_check_knowledge_failure_is_not_counted_as_checked_or_hit(monkeypatch):
    from app.api.v1 import monitor

    base = {"company_name": "Brand A", "records": [
        {"monitor_id": "a", "question": "q", "platform": "DeepSeek",
         "snippet": "Brand A成立于2005年。", "ts": "2026-09-22T00:00:00Z"}
    ]}
    monkeypatch.setattr(monitor, "_aggregate_fact_check", lambda items, company_name=None: base)
    monkeypatch.setattr(monitor, "_load_history", lambda: [])
    monkeypatch.setattr(monitor, "_load_items", lambda: [
        {"monitor_id": "a", "type": "brand", "config_json": {"company": "Brand A"}}
    ])

    async def unavailable(*args):
        return {"checked": False, "abnormal": False, "reason": "知识库不可用", "knowledge_ok": False}

    monkeypatch.setattr(monitor, "_check_answer_facts", unavailable)
    truth = _run(monitor.fact_check())["data"]["truth"]
    assert truth["total_checked"] == 0
    assert truth["hit_kb"] == 0
    assert truth["knowledge_ok"] is False


def test_competitor_mentions_do_not_produce_winner_from_sentence_order(monkeypatch):
    from app.api.v1 import monitor

    monkeypatch.setattr(monitor, "_load_items", lambda: [{
        "monitor_id": "pair-1", "type": "competitor", "status": "active",
        "config_json": {"company": "Brand A", "competitor": "Brand B"},
    }])
    monkeypatch.setattr(monitor, "_load_history", lambda: [{
        "batch": True, "created_at": "2026-09-22T00:00:00Z",
        "questions": [{"monitor_id": "pair-1", "question": "Which is better?",
                       "engine_detail": [{"answer": "Brand A and Brand B are options.",
                                          "subjects": {
                                              "company": {"mentioned": True, "rank_est": 1},
                                              "competitor": {"mentioned": True, "rank_est": 2},
                                          }}]}],
    }])
    data = _run(monitor.competitor())["data"]
    assert data["pairs"][0]["win"]["company"] == 0
    assert data["pairs"][0]["win"]["competitor"] == 0
    assert data["pairs"][0]["win"]["none"] == 1
