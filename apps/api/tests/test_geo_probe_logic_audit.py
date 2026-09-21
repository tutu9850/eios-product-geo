"""Owner 2026-09-21「自己找一遍」：三条被点名的「输出正常但不正确」。

1. 监测探针问出「使用{公司}需要注意什么？」—— 公司不是能「使用」的东西，
   这句话本身不成立，模型只能替我们编一份「注意事项」（实测被计入负面情绪）。
2. 事实核验里那条 `best < 0.5` 是老 Kernel 的**归一化分**阈值，而 EIOS 知识库的 `n`
   是**无界 rank 分**（契约只有 minimum），于是条件恒不成立 = 所有断言都算有依据：
   凭空编的「成立于 2005 年，注册资本 1 亿元」也被判成 grounded。
3. 知识缺口判定只认「实体名出现在命中片段里」，而企业知识库几乎每张表都写着公司名
   → 这一条恒为真，无关问题（「今天天气怎么样？」）也被报成 PARTIAL/COVERED。

这些测试不连真实知识库：`search_knowledge` 是在函数体里 import 的，patch
`adapters.eios.search_knowledge` 即可，断言的是**判定逻辑**本身。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest  # noqa: E402

import adapters.eios as eios  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── 1. 探针不再问不成立的问题 ──────────────────────────────────


def test_brand_probe_never_asks_how_to_use_a_company():
    from app.api.v1.monitor import generate_brand_queries

    cfg = {"company": "亚宇臻隆科技", "product": ["知识云·GEO套件"], "industry": "家装设计", "tier": "deep"}
    queries = generate_brand_queries(cfg, "deep")["queries"]

    assert "使用亚宇臻隆科技需要注意什么？" not in queries
    assert not any("需要注意什么" in q for q in queries)
    # 替换上来的是一句真实用户会搜的话（问 AI 有没有说我们坏话）
    assert "亚宇臻隆科技有什么负面评价？" in queries


def test_brand_probe_risk_branch_keeps_its_sentences_for_a_deep_tier():
    from app.api.v1.monitor import generate_brand_queries

    cats = generate_brand_queries({"company": "亚宇臻隆科技"}, "deep")["categories"]
    assert cats["risk"] == [
        "亚宇臻隆科技有哪些缺点？",
        "亚宇臻隆科技有什么负面评价？",
        "亚宇臻隆科技适合哪些企业？",
        "亚宇臻隆科技不适合哪些企业？",
    ]


def test_product_probe_has_an_object():
    from app.api.v1.monitor import generate_queries

    queries = generate_queries({"type": "product", "config_json": {"product": "知识云·GEO套件"}})
    assert "知识云·GEO套件推荐？" not in queries
    assert "知识云·GEO套件推荐哪些公司？" in queries


def test_competitor_probe_does_not_hardcode_another_industry():
    from app.api.v1.monitor import generate_queries

    queries = generate_queries(
        {
            "type": "competitor",
            "config_json": {"company": "亚宇臻隆科技", "competitor": "知识云", "industry": "家装设计", "product": "全案定制"},
        }
    )
    # 家装公司不该被问「企业知识管理」，那是写死的、跟生意无关的行业词
    assert not any("企业知识管理" in q for q in queries)
    assert "家装设计领域，知识云和亚宇臻隆科技谁更适合？" in queries


def test_probe_lists_are_deduplicated_and_stripped():
    from app.api.v1.monitor import generate_queries

    # 竞品分支里「行业存在时」曾与上一句完全重复；这里直接给重复输入验去重保序
    item = {
        "type": "competitor",
        "config_json": {"company": "亚宇臻隆科技", "competitor": "知识云", "industry": "家装设计"},
    }
    queries = generate_queries(item)
    assert len(queries) == len(set(queries))
    assert all(q == q.strip() and q for q in queries)


# ── 2. 事实核验：数字必须出现在证据里 ──────────────────────────


def _fake_search(hits: list[dict]):
    async def _search(query: str, **kwargs):  # noqa: ARG001
        return {"hits": hits}

    return _search


def test_a_fabricated_year_is_not_grounded_even_when_evidence_looks_similar(monkeypatch):
    """高分命中 + 4 字窗口命中，但年份/金额不在证据里 → 仍要报「缺少依据」。

    这就是 `best < 0.5` 那个 bug 的回归：score 给 12.0（EIOS 的真实量级），
    老代码会判 grounded；新代码看的是数字在不在证据文本里。
    """
    from app.api.v1 import monitor

    monkeypatch.setattr(
        eios,
        "search_knowledge",
        _fake_search([{"canonical_name": "亚宇臻隆科技", "predicate": None, "value": "亚宇臻隆科技 成立于 性质 民营", "score": 12.0}]),
    )
    res = _run(
        monitor._check_answer_facts(
            "亚宇臻隆科技",
            "亚宇臻隆科技成立于 2005 年，注册资本 1 亿元，员工 800 人。",
            "亚宇臻隆科技是什么？",
        )
    )
    assert res["abnormal"] is True
    assert res["main_type"] == "缺少依据"


def test_a_claim_whose_numbers_are_in_the_evidence_is_grounded(monkeypatch):
    from app.api.v1 import monitor

    monkeypatch.setattr(
        eios,
        "search_knowledge",
        _fake_search(
            [{"canonical_name": "亚宇臻隆科技", "predicate": None, "value": "亚宇臻隆科技 成立于 2005 年 注册资本 1 亿元", "score": 12.0}]
        ),
    )
    res = _run(
        monitor._check_answer_facts(
            "亚宇臻隆科技",
            "亚宇臻隆科技成立于 2005 年，注册资本 1 亿元。",
            "亚宇臻隆科技是什么？",
        )
    )
    assert res["abnormal"] is False
    assert res["reason"] == "断言均有知识库依据"


def test_a_price_sentence_is_now_treated_as_a_claim(monkeypatch):
    """「价格 9800 元」原来既没锚点也没数字检测 → 直接「无事实断言」放过。"""
    from app.api.v1 import monitor

    monkeypatch.setattr(eios, "search_knowledge", _fake_search([]))
    res = _run(
        monitor._check_answer_facts(
            "亚宇臻隆科技",
            "亚宇臻隆科技的知识云·GEO套件价格 9800 元。",
            "知识云·GEO套件价格多少？",
        )
    )
    assert res["reason"] != "无事实断言"
    assert res["abnormal"] is True


def test_without_a_company_name_there_is_nothing_to_check():
    from app.api.v1 import monitor

    res = _run(monitor._check_answer_facts("", "亚宇臻隆科技成立于 2005 年。", "q"))
    assert res["checked"] is False


# ── 3. 知识缺口：相关性按内容二元组判，不按「公司名出现过」 ────


def test_content_bigrams_drop_question_words():
    from app.api.v1.distill import _content_bigrams

    grams = _content_bigrams("全案定制在成都都有哪些公司在做？")
    assert "哪些" not in "".join(grams)
    # 去疑问词后剩下的实词仍在（成都 / 全案 / 定制 / 公司在 等二元组）
    assert any(g.startswith("成都") or g.endswith("成都") for g in grams)
    # 纯疑问句去掉疑问词后不足两个内容字 → 空集（不会凭空命中）
    assert _content_bigrams("怎么样？") == set()


def test_an_unrelated_question_is_not_reported_as_covered(monkeypatch):
    """旧逻辑：企业知识库每张表都有公司名 → related 恒真 → 无关问题也 PARTIAL/COVERED。"""
    from app.api.v1 import distill

    monkeypatch.setattr(
        eios,
        "search_knowledge",
        _fake_search(
            [
                {
                    "canonical_name": "亚宇臻隆科技",
                    "predicate": None,
                    "value": "亚宇臻隆科技 企业简介 主营 软件与信息技术服务",
                    "score": 11.0,
                }
            ]
        ),
    )
    res = _run(distill._knowledge_check("今天天气怎么样？", ["亚宇臻隆科技"]))
    assert res["status"] not in ("COVERED", "PARTIAL")
    assert res["has_knowledge"] is False
    assert res["judge_basis"] == "document_text"


def test_a_question_about_the_hits_is_covered_basis_document_text(monkeypatch):
    from app.api.v1 import distill

    monkeypatch.setattr(
        eios,
        "search_knowledge",
        _fake_search(
            [
                {
                    "canonical_name": "亚宇臻隆科技",
                    "predicate": None,
                    "value": "亚宇臻隆科技 成立于 2016 年 主营 全案定制 家装设计 产品介绍",
                    "score": 11.0,
                }
            ]
        ),
    )
    res = _run(distill._knowledge_check("亚宇臻隆科技的主营产品和全案定制介绍是什么？"))
    assert res["judge_basis"] == "document_text"
    assert res["matched_terms"], "判定命中的内容词要能复盘"
    assert res["has_knowledge"] is True


def test_hits_with_fact_triples_are_labelled_fact_triple(monkeypatch):
    from app.api.v1 import distill

    monkeypatch.setattr(
        eios,
        "search_knowledge",
        _fake_search(
            [
                {
                    "canonical_name": "亚宇臻隆科技",
                    "predicate": "主营产品",
                    "value": "全案定制",
                    "score": 9.0,
                }
            ]
        ),
    )
    res = _run(distill._knowledge_check("亚宇臻隆科技主营产品是什么？"))
    assert res["judge_basis"] == "fact_triple"


# ── 4. 事实核验页的两个计数（「知识库命中」曾把没断言的回答算进去） ──


def test_fact_check_kpis_do_not_count_answers_without_claims(monkeypatch):
    """`hit_kb` 原来是「跑过检查且没判异常」——「无事实断言」的回答也满足，
    于是「模型只说请查工商信息」这种回答被算成「知识库命中」。
    `total_checked` 同理，原来算的是送检条数（超时/无文本也算）。"""
    from app.api.v1 import monitor

    base = {
        "company_name": "亚宇臻隆科技",
        "records": [
            {"question": "q1", "platform": "DeepSeek", "snippet": "a", "ts": "2026-09-21T00:00:00Z"},
            {"question": "q2", "platform": "Kimi", "snippet": "b", "ts": "2026-09-21T00:01:00Z"},
            {"question": "q3", "platform": "Doubao", "snippet": "", "ts": "2026-09-21T00:02:00Z"},
        ],
    }
    monkeypatch.setattr(monitor, "_aggregate_fact_check", lambda items, company_name=None: base)
    monkeypatch.setattr(monitor, "_load_history", lambda: [])

    async def fake_check(company_name, snippet, question):  # noqa: ARG001
        if question == "q1":  # 有断言，但知识库对不上 → 失真
            return {"checked": True, "abnormal": True, "main_type": "缺少依据", "claims": ["经营范围不明"]}
        if question == "q2":  # 有回答，但没有任何可核验断言
            return {"checked": True, "abnormal": False, "reason": "无事实断言"}
        return {"checked": False, "abnormal": False, "reason": "无文本"}  # 没跑完检查

    monkeypatch.setattr(monitor, "_check_answer_facts", fake_check)

    truth = _run(monitor.fact_check())["data"]["truth"]
    assert truth["candidate_total"] == 3
    assert truth["total_checked"] == 2      # 没跑完检查的不算
    assert truth["no_claim_count"] == 1     # 单独如实报出来
    assert truth["hit_kb"] == 0             # 没断言的回答不算「知识库命中」
    assert truth["abnormal_count"] == 1


def test_fact_check_hit_kb_only_counts_grounded_claims(monkeypatch):
    from app.api.v1 import monitor

    base = {
        "company_name": "亚宇臻隆科技",
        "records": [
            {"question": "q1", "platform": "DeepSeek", "snippet": "a", "ts": "2026-09-21T00:00:00Z"},
        ],
    }
    monkeypatch.setattr(monitor, "_aggregate_fact_check", lambda items, company_name=None: base)
    monkeypatch.setattr(monitor, "_load_history", lambda: [])

    async def fake_check(company_name, snippet, question):  # noqa: ARG001
        return {"checked": True, "abnormal": False, "reason": "断言均有知识库依据", "kernel_ok": True}

    monkeypatch.setattr(monitor, "_check_answer_facts", fake_check)

    truth = _run(monitor.fact_check())["data"]["truth"]
    assert truth["total_checked"] == 1
    assert truth["hit_kb"] == 1
    assert truth["no_claim_count"] == 0
