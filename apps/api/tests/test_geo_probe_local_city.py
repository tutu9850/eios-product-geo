"""Owner 2026-09-23：「监测这里，行业还是国内，不是成都，不是根据自动配置的行业问的，修一下，问的时候要加本地」。

实测到的坏问句（monitor_history.summary.weak_questions 里能直接看到）：

    国内家居家具行业，主营沙发、软床及定制家具的设计、生产与销售平台有哪些？

两个病根：
1. 「国内」是**写死**的 —— 所在地在自动配置第 1 步填过，只喂给了竞品发现，
   `POST /onboard/auto-config step=create` 建对象时根本没把 city 写进 config_json，
   探针自然只能问全国；
2. 自动配置 detect 出来的行业是**一句话**（用于展示），整句套进探针模板就成了上面那句。

这些测试不连模型、不连知识库，断言的是**探针文本**与**自动配置落库的 config**。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

from app.api.v1 import onboard  # noqa: E402
from app.api.v1.monitor import _probe_term, generate_brand_queries, generate_queries  # noqa: E402
from app.services.region import clean_city, extract_city  # noqa: E402

#: 自动配置真实 detect 出来的行业（一句话，实测值）
_LONG_INDUSTRY = "家居家具行业，主营沙发、软床及定制家具的设计、生产与销售"


def _run(coro):
    return asyncio.run(coro)


# ── 1. 行业长句截短 ────────────────────────────────────────────


def test_long_industry_is_shortened_for_probes():
    assert _probe_term(_LONG_INDUSTRY) == "家居家具"
    # 短词不误伤（原本就是行业名/产品名的原样返回）
    assert _probe_term("家装设计") == "家装设计"
    assert _probe_term("AI数字员工与自媒体获客服务") == "AI数字员工与自媒体获客服务"
    assert _probe_term("") == ""
    assert _probe_term("   ") == ""


def test_city_is_normalised():
    assert clean_city("成都市") == "成都"
    assert clean_city(" 成都 ") == "成都"
    assert clean_city("") == ""
    assert clean_city("眉山市") == "眉山"      # 词表外的小城市去「市」
    assert extract_city("笔革家居") == ""       # 名字里没城市，抠不出来就是抠不出来


# ── 2. 探针按所在地问「本地」，不再问「国内」 ──────────────────


def test_brand_probe_asks_local_not_nationwide():
    cfg = {"company": "笔革家居", "product": ["琥珀沙发"], "industry": _LONG_INDUSTRY, "city": "成都", "tier": "lite"}
    queries = generate_brand_queries(cfg, "lite")["queries"]
    assert "成都本地的家居家具公司有哪些？" in queries
    assert "成都的琥珀沙发推荐哪些公司？" in queries
    assert not any("国内" in q for q in queries)
    assert not any(_LONG_INDUSTRY in q for q in queries)  # 整句行业不再进探针


def test_brand_probe_without_a_city_does_not_invent_one():
    """没填所在地 → 退回通用问法；既不许写死「国内」，也不许编一个城市出来。"""
    cfg = {"company": "笔革家居", "product": ["琥珀沙发"], "industry": _LONG_INDUSTRY, "tier": "lite"}
    queries = generate_brand_queries(cfg, "lite")["queries"]
    assert "家居家具公司有哪些？" in queries
    assert "琥珀沙发推荐哪些公司？" in queries
    assert not any("国内" in q for q in queries)
    assert not any("成都" in q for q in queries)


def test_product_probe_carries_the_city_but_falls_back_for_old_objects():
    with_city = generate_queries({"type": "product", "config_json": {"product": "琥珀沙发", "city": "成都"}})
    assert with_city[0] == "成都的琥珀沙发推荐哪些公司？"
    # 老对象（还没写 city）问法原样，不因为改造而变
    legacy = generate_queries({"type": "product", "config_json": {"product": "琥珀沙发"}})
    assert legacy[0] == "琥珀沙发推荐哪些公司？"


def test_service_probe_is_local_too():
    queries = generate_queries({"type": "product", "config_json": {"product": "全案定制", "kind": "service", "city": "成都市"}})
    assert queries[0] == "成都的全案定制哪家公司做得好？"


def test_keyword_probe_is_shortened_and_local():
    queries = generate_queries({"type": "keyword", "config_json": {"keyword": _LONG_INDUSTRY, "city": "成都"}})
    assert queries[0] == "成都的家居家具哪个好？"
    assert not any(_LONG_INDUSTRY in q for q in queries)


def test_competitor_probe_uses_the_short_industry():
    queries = generate_queries(
        {
            "type": "competitor",
            "config_json": {"company": "笔革家居", "competitor": "欧派", "industry": _LONG_INDUSTRY, "city": "成都"},
        }
    )
    assert "家居家具领域，欧派和笔革家居谁更适合？" in queries
    assert not any(_LONG_INDUSTRY in q for q in queries)


# ── 3. 自动配置建对象时把所在地写进去 ──────────────────────────


def test_auto_config_create_persists_the_city_on_every_object():
    res = _run(
        onboard._step_create(
            onboard.AutoConfigIn(
                step="create",
                company="笔革家居",
                products=["琥珀沙发"],
                services=["全案定制"],
                industry=_LONG_INDUSTRY,
                city="成都市",
                competitors=[{"name": "欧派"}],
            )
        )
    )
    created = res["created"]
    assert created, "自动配置至少要建出对象"
    assert all(i["config_json"].get("city") == "成都" for i in created), created

    brand = next(i for i in created if i["type"] == "brand")
    queries = generate_queries(brand)
    assert "成都本地的家居家具公司有哪些？" in queries


def test_auto_config_without_a_city_does_not_write_the_key():
    res = _run(onboard._step_create(onboard.AutoConfigIn(step="create", company="笔革家居", products=["琥珀沙发"], industry="家装设计")))
    assert all("city" not in i["config_json"] for i in res["created"])
    brand = next(i for i in res["created"] if i["type"] == "brand")
    assert not any("国内" in q for q in generate_queries(brand))
