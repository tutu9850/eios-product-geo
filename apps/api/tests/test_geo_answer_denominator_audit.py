"""Owner 2026-09-21「自己找一遍」第二轮：分母把「没作答」当成「没提及 / 没赢」。

监测历史里，没配 key 或调用失败的引擎**也**会落一条 ``engine_detail``（answer 空、
mentioned None）。这类记录是「没有回答」，不是「AI 回答时没提到我们」。凡是拿
``engine_detail`` 的条数当分母的统计，都会被这类记录稀释，页面上就是
「输出正常但不正确」：

* 认知洞察：品牌认知 6%（真实 35%）、决策链阶段覆盖 7%/0%
* 竞品对比：共 96 条回答 · 我方 9% vs 竞品 10%（真实 16 条 · 56% vs 63%），
  胜负桶里 92 条 "none" 其实是「压根没回答」
* 问题池：monitor_count 写着「真实监测回答数」记的却是批次数；ai_visibility =
  引擎条数 ÷ 批次数，2 批 × 6 引擎全提及算成 300%

这批测试只喂假 history，不连库、不连知识库；断言的是**分母口径**本身。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _engine_row(name: str, mentioned, answer: str = ""):
    """一条引擎记录：mentioned=None + answer 空 = 没作答（没配 key / 调用失败）。"""
    return {
        "engine_name": name,
        "mentioned": mentioned,
        "rank_est": 1 if mentioned else None,
        "sentiment": "neutral" if mentioned else None,
        "snippet": answer[:40],
        "answer": answer,
    }


def _batch(question: str, monitor_id: str, answered: bool, mentioned: bool = True):
    """1 个探针 × 6 个引擎；只有一个引擎真作答（现实：只有 DeepSeek 配了 key）。"""
    rows = [_engine_row("DeepSeek", mentioned if answered else None, "有回答" if answered else "")]
    for name in ("Kimi", "豆包", "文心一言", "通义千问", "智谱"):
        rows.append(_engine_row(name, None, ""))
    return {
        "batch": True,
        "created_at": "2026-09-21T01:19:19+00:00",
        "questions": [
            {
                "monitor_id": monitor_id,
                "monitor_type": "brand",
                "question": question,
                "query": question,
                "mentioned_count": 1 if (answered and mentioned) else 0,
                "configured_count": 1 if answered else 0,
                "engine_detail": rows,
            }
        ],
    }


# ── 1. 认知洞察：分母只算真作答 ────────────────────────────────


class _FakeStore:
    def __init__(self, data: dict):
        self._data = data

    def load(self, name: str):
        return self._data.get(name, [])


def _patch_cognition(monkeypatch, history, questions=None):
    from app.api.v1 import cognition

    monkeypatch.setattr(cognition, "_load_history", lambda: history)
    monkeypatch.setattr(cognition, "_load_items", lambda: [])
    monkeypatch.setattr(cognition, "get_store", lambda: _FakeStore({"questions": questions or []}))
    monkeypatch.setattr(cognition, "_cognition_profile_v2", _fake_profile_v2)


async def _fake_profile_v2():
    return {"total": 0, "health": None, "metrics": {}, "matrix": [], "errors": []}


def test_cognition_health_ignores_engines_that_never_answered(monkeypatch):
    from app.api.v1 import cognition

    _patch_cognition(monkeypatch, [_batch("亚宇臻隆科技是什么？", "mi_1", answered=True)])
    data = _run(cognition.health())["data"]

    brand = next(d for d in data["dims"] if d["key"] == "brand")
    assert brand["score"] == 100, "6 条里只有 1 条真作答且提到了我方 → 100%，不是 1/6≈17%"
    assert "1" in brand["basis"]
    # 口径写清楚：分母是「已回答」，不是「探针记录」
    scene = next(d for d in data["dims"] if d["key"] == "scene")
    assert scene["score"] == 100
    assert "1 条" in scene["basis"]


def test_cognition_health_says_no_answer_instead_of_zero(monkeypatch):
    from app.api.v1 import cognition

    _patch_cognition(monkeypatch, [_batch("亚宇臻隆科技是什么？", "mi_1", answered=False)])
    data = _run(cognition.health())["data"]

    brand = next(d for d in data["dims"] if d["key"] == "brand")
    assert brand["score"] is None, "一条回答都没有 → 未评估，不是 0 分"
    assert "暂无已回答" in brand["basis"]


def test_cognition_coverage_divides_by_answered_not_by_probe_rows(monkeypatch):
    from app.api.v1 import cognition

    history = [
        _batch("亚宇臻隆科技是什么？", "mi_1", answered=True, mentioned=True),
        _batch("知识云有哪些产品？", "mi_2", answered=True, mentioned=False),
    ]
    _patch_cognition(monkeypatch, history)
    data = _run(cognition.coverage())["data"]

    know = next(s for s in data["stages"] if s["key"] == "know")
    assert know["answered_count"] == 2, "两条真作答（不是 12 条引擎记录）"
    assert know["probe_count"] == 12, "2 问 × 6 引擎 = 12 条探针记录，要如实报出来"
    assert know["coverage"] == 50, "2 条回答里 1 条提到 → 50%，不是 1/12≈8%"


def test_cognition_coverage_is_null_when_nobody_answered(monkeypatch):
    from app.api.v1 import cognition

    _patch_cognition(monkeypatch, [_batch("亚宇臻隆科技是什么？", "mi_1", answered=False)])
    data = _run(cognition.coverage())["data"]

    know = next(s for s in data["stages"] if s["key"] == "know")
    assert know["answered_count"] == 0
    assert know["coverage"] is None, "没人作答 → 覆盖未判定（null），不编 0%"


# ── 2. 竞品对比：共 N 条回答 / 胜负桶也只算真作答 ────────────────


def _competitor_item():
    return {
        "monitor_id": "mi_comp",
        "type": "competitor",
        "status": "active",
        "entity": "亚宇臻隆科技 vs 知识云·GEO套件",
        "config_json": {
            "company": "亚宇臻隆科技",
            "target": "亚宇臻隆科技",
            "competitor": ["知识云·GEO套件"],
            "product": ["GEO+知识库系统"],
        },
    }


def _competitor_batch(answered: bool):
    rows = [
        _engine_row(
            "DeepSeek",
            True if answered else None,
            "亚宇臻隆科技和知识云·GEO套件各有优势" if answered else "",
        )
    ]
    for name in ("Kimi", "豆包", "文心一言", "通义千问", "智谱"):
        rows.append(_engine_row(name, None, ""))
    return {
        "batch": True,
        "created_at": "2026-09-21T01:19:19+00:00",
        "questions": [
            {
                "monitor_id": "mi_comp",
                "question": "亚宇臻隆科技和知识云·GEO套件哪个好？",
                "mentioned_count": 1 if answered else 0,
                "configured_count": 1 if answered else 0,
                "engine_detail": rows,
            }
        ],
    }


def test_competitor_total_counts_answers_not_engine_rows(monkeypatch):
    from app.api.v1 import monitor

    monkeypatch.setattr(monitor, "_load_history", lambda: [_competitor_batch(answered=True)])
    monkeypatch.setattr(monitor, "_load_items", lambda: [_competitor_item()])
    pair = _run(monitor.competitor())["data"]["pairs"][0]

    assert pair["total"] == 1, "1 条真作答（旧实现在这里报 6 条）"
    assert pair["unanswered"] == 5, "另外 5 条没作答要如实说出来"
    assert pair["target_mentioned"] == 1
    assert pair["target_pct"] == 100, "1 条作答里提到我方 → 100%，不是 1/6≈17%"
    assert pair["win"]["none"] == 0, "没作答不能算进「都没选」"


def test_competitor_keeps_the_no_answer_case_honest(monkeypatch):
    from app.api.v1 import monitor

    monkeypatch.setattr(monitor, "_load_history", lambda: [_competitor_batch(answered=False)])
    monkeypatch.setattr(monitor, "_load_items", lambda: [_competitor_item()])
    pair = _run(monitor.competitor())["data"]["pairs"][0]

    assert pair["total"] == 0
    assert pair["unanswered"] == 6
    assert pair["target_pct"] == 0
    assert pair["win"] == {"company": 0, "competitor": 0, "none": 0, "same_entity": 0}


# ── 3. 问题池：monitor_count / ai_visibility 的分子分母 ──────────


def test_question_monitor_count_counts_answers_and_visibility_stays_bounded(monkeypatch):
    from app.api.v1 import distill
    from app.services import store as store_mod

    question = {"id": "q_1", "question": "亚宇臻隆科技是什么？", "priority": 80, "evidence_level": "grounded"}
    history = [
        _batch("亚宇臻隆科技是什么？", "mi_1", answered=True),
        _batch("亚宇臻隆科技是什么？", "mi_1", answered=True),
    ]
    monkeypatch.setattr(distill, "_load_questions", lambda: [dict(question)])
    monkeypatch.setattr(store_mod, "get_store", lambda: _FakeStore({"monitor_history": history}))

    item = _run(distill.list_questions())["data"]["items"][0]
    assert item["monitor_count"] == 2, "2 条真作答；旧实现按批次算"
    assert item["frequency"] == 2, "被问到 2 次（批次）"
    assert item["ai_visibility"] == 100, "2 条作答全提到 → 100%（旧实现 12/2=600%）"


def test_question_monitor_count_ignores_engines_that_never_answered(monkeypatch):
    from app.api.v1 import distill
    from app.services import store as store_mod

    question = {"id": "q_1", "question": "亚宇臻隆科技是什么？", "priority": 80}
    history = [_batch("亚宇臻隆科技是什么？", "mi_1", answered=True)]
    monkeypatch.setattr(distill, "_load_questions", lambda: [dict(question)])
    monkeypatch.setattr(store_mod, "get_store", lambda: _FakeStore({"monitor_history": history}))

    item = _run(distill.list_questions())["data"]["items"][0]
    assert item["monitor_count"] == 1, "6 条引擎记录里只有 1 条真作答"
    assert item["ai_visibility"] == 100


def test_monitor_overview_omits_platforms_that_never_answered(monkeypatch):
    from app.api.v1 import monitor
    from app.services import store as store_mod

    history = [_batch("亚宇臻隆科技是什么？", "mi_1", answered=True, mentioned=False)]
    monkeypatch.setattr(store_mod, "get_store", lambda: _FakeStore({"kb": []}))

    data = monitor._aggregate_overview(history)
    assert list(data["platforms"]) == ["DeepSeek"]
    assert data["platforms"]["DeepSeek"][0]["recommend_pct"] == 0
    assert data["recommend"]["delta"] is None, "没有上一周期就必须是 null，不能伪装成 ↑0"


# ── 4. 企业资料：整体覆盖率的分母不算空问题 ────────────────────


def test_profile_overview_denominator_skips_questions_without_text(monkeypatch):
    from app.api.v1 import distill
    from app.api.v1 import enterprise_profile as ep

    async def _check(question, entities=None, intent=None):
        return {"status": "COVERED"}

    monkeypatch.setattr(ep, "_load_items", lambda: [])
    monkeypatch.setattr(ep, "_cached_knowledge_check", _check)
    monkeypatch.setattr(distill, "_load_questions", lambda: [{"id": "q1", "question": "亚宇臻隆科技是什么？"}, {"id": "q2", "question": "   "}])

    data = _run(ep.profile_overview())["data"]
    assert data["overall_coverage_pct"] == 100, "只有 1 个问题真的参与判定 → 100%，不被空问题拉成 50%"


# ── 5. 认知洞察：0 个解析样本 ≠ 「AI 没提到你」 ──────────────────


def test_humanize_does_not_claim_the_ai_never_mentioned_us_without_samples(monkeypatch):
    from services.intelligence import cognition as intel

    monkeypatch.setattr(intel, "compare", lambda **kw: {"brands": [], "sample_note": {"total": 0, "reliability": "极低", "note": "数据严重不足"}})
    monkeypatch.setattr(intel, "strategies", lambda **kw: {"strategies": []})
    monkeypatch.setattr(intel, "factor_gaps", lambda **kw: {"left": [], "right": [], "risk_notes": []})

    out = intel.humanize()
    assert out["headline"]["main"] == "还没有可判断的解析样本"
    assert out["metrics"]["exposure_rate"] is None, "没有样本时给 null（页面显示「—」），不是 0%"
    assert out["metrics"]["recommendation_rate"] is None


def test_humanize_still_reports_a_real_zero_exposure_when_samples_exist(monkeypatch):
    from services.intelligence import cognition as intel

    monkeypatch.setattr(
        intel,
        "compare",
        lambda **kw: {
            "brands": [{"brand": "亚宇臻隆科技", "is_self": True, "exposure_rate": 0.0, "recommendation_rate": 0.0}],
            "sample_note": {"total": 12, "reliability": "低", "note": "样本不足"},
        },
    )
    monkeypatch.setattr(intel, "strategies", lambda **kw: {"strategies": []})
    monkeypatch.setattr(intel, "factor_gaps", lambda **kw: {"left": [], "right": [], "risk_notes": []})

    out = intel.humanize()
    assert out["headline"]["main"] == "AI 回答里还没提到过你", "有样本、曝光真为 0 时才说这句话"
    assert out["metrics"]["exposure_rate"] == 0.0
