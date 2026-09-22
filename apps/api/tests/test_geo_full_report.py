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
