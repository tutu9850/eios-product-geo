"""Owner 2026-09-22：「本公司是谁」和「自动配置」都从 GEO 自己的内容资产来。

三件事：
1. 从内容资产里**猜**公司名（不严格，但只认像名字的，不拿标题硬顶）；
2. 自动配置的候选来自内容资产的文章，**不打知识库**；
3. 删一份内容资产就连它切好的段一起删（都存 GEO 自己库里，删了就是删了）。

以及一条同名同源的边界：没有内容资产时如实说「还没有」，不编造候选。
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest  # noqa: E402

from services.company_identity import (  # noqa: E402
    company_candidates_from_materials,
    is_placeholder_company_name,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def tenant():
    from app.models.geo_models import engine, init_db
    from app.services.store import set_tenant

    init_db()
    try:
        set_tenant(f"tenant_own_{uuid.uuid4().hex[:8]}")
        yield
    finally:
        set_tenant("tenant_corp_01")
        engine.dispose()


# ── 1. 从内容资产猜公司 ────────────────────────────────────

def test_candidates_come_from_titles_and_body_and_ignore_prose():
    materials = [
        {
            "title": "笔革家居整套全屋定制要多久？行业内部流程拆解，看完心里有数",
            "content": "笔革家居是一家做全屋定制的家装公司。笔革家居的工期通常是……" * 3,
        },
        {"title": "亚宇臻隆科技介绍", "content": "亚宇臻隆科技做AI获客。"},
    ]
    got = company_candidates_from_materials(materials)
    assert "笔革家居" in got and "亚宇臻隆科技" in got
    # 「家装公司」「AI获客公司」这种行业泛称不是公司名
    assert not any(c.endswith("公司") and c[:-2] in {"家装", "定制", "全屋定制", "获客", "AI获客"} for c in got)


def test_ranking_prefers_the_name_that_repeats_and_sits_in_a_title():
    repeating = "亚宇臻隆科技是一家公司。" * 8 + "笔革家居是全屋定制公司。" * 2
    got = company_candidates_from_materials([{"title": "公司资料", "content": repeating}])
    assert got[0] == "亚宇臻隆科技", "出现得多的排前面"
    titled = company_candidates_from_materials(
        [
            {"title": "公司资料", "content": "亚宇臻隆科技是一家公司。" * 8},
            {"title": "笔革家居整套全屋定制要多久", "content": "笔革家居的工期。"},
        ]
    )
    assert titled[0] in {"亚宇臻隆科技", "笔革家居"}


def test_prose_fragments_are_not_company_candidates():
    """Owner 2026-09-22：名单里混进句子碎片（「主要来自过往家具」「优先选择上市公司」）。"""
    content = (
        "我们的客户主要来自过往家具行业。合作方优先选择上市公司。"
        "这次梳理围绕三大奢侈品牌设计展开；全面梳理比格家居的增长路径，"
        "阐述笔革家居在成都的做法。品牌定位是设计师家具品牌，儿童房定制柜软装是重点，"
        "公司已超越传统家具卖场模式。"
    )
    got = company_candidates_from_materials([{"title": "笔革家居主理人访谈纪要", "content": content}])
    for bad in (
        "主要来自过往家具",
        "优先选择上市公司",
        "三大奢侈品牌设计",
        "全面梳理比格家居",
        "阐述笔革家居",
        "位为艺术家居品牌",
        "儿童房定制柜软装",
        "司已超越传统家具",
    ):
        assert bad not in got, f"句子碎片不该进公司候选：{bad}"
    assert got[0] == "笔革家居", "标题命中的真名字要排第一"


def test_a_clean_name_beats_the_longer_prose_fragment_that_ends_with_it():
    """后缀收敛不能反过来：长碎片分低时不许吃掉干净短名。"""
    content = "阐述笔革家居的全案定制。笔革家居主理人访谈纪要。" * 2
    got = company_candidates_from_materials([{"title": "笔革家居主理人访谈纪要", "content": content}])
    assert "笔革家居" in got
    assert "阐述笔革家居" not in got


def test_no_materials_means_no_candidate():
    assert company_candidates_from_materials([]) == []
    assert company_candidates_from_materials([{"title": "全屋定制要多久", "content": "定制流程。"}]) == []


def test_question_template_is_never_an_enterprise_candidate():
    materials = [
        {
            "title": "品牌认知调研",
            "content": "请判断哪个品牌更值得推荐。哪个品牌的交付证据更充分？",
        }
    ]
    assert company_candidates_from_materials(materials) == []
    assert is_placeholder_company_name("哪个品牌")
    assert is_placeholder_company_name("沙发哪个品牌")
    assert not is_placeholder_company_name("笔革家居")


def test_finalize_detect_filters_model_placeholder(monkeypatch, tenant):
    from app.api.v1 import onboard

    got = _run(
        onboard._finalize_detect(
            {
                "company": ["哪个品牌", "笔革家居"],
                "products": [],
                "services": [],
                "industry": None,
                "keywords": [],
                "classification_source": "llm",
            },
            biz_fallback=[],
        )
    )
    assert got["company"] == ["笔革家居"]


def test_resolve_self_company_uses_own_materials(monkeypatch, tenant):
    """第 3 档：档案 / 监测对象都没有时，从内容资产猜，来源如实写 ``own_materials``。"""
    from app.services import knowledge_snapshot, store as store_mod

    monkeypatch.setattr(knowledge_snapshot, "list_recent", lambda kind=None, limit=1: [])

    class _Store:
        def load(self, name):
            if name == "kb":
                return [{"title": "笔革家居整套全屋定制要多久", "content": "笔革家居的工期……"}]
            return []

    monkeypatch.setattr(store_mod, "get_store", lambda: _Store())

    import adapters.eios as eios

    async def _must_not_read_knowledge(*_a, **_kw):
        raise AssertionError("本公司识别不该去打知识库")

    monkeypatch.setattr(eios, "get_entities", _must_not_read_knowledge)

    from services.company_identity import resolve_self_company

    got = _run(resolve_self_company())
    assert got == {"name": "笔革家居", "aliases": [], "source": "own_materials"}


def test_file_name_titles_never_become_product_candidates(monkeypatch, tenant):
    """Owner 实测：产品那一行显示的是素材文件名（export_… / 三品牌战略+…）。"""
    from app.api.v1 import onboard
    from app.services.store import get_store

    get_store().save(
        "kb",
        [
            {"id": "m_1", "title": "export_1785221955586", "content": "品牌战略与市场调研材料。", "source_type": "file"},
            {"id": "m_2", "title": "三品牌战略+奢侈品调研-前31页", "content": "行业调研笔记。", "source_type": "file"},
            {"id": "m_3", "title": "笔革家居主理人访谈纪要", "content": "记录了主理人的访谈内容。", "source_type": "file"},
        ],
    )
    import adapters.llm as llm

    async def _no_model(*_a, **_kw):
        raise RuntimeError("这个部署还没有可用的 GEO 模型")

    monkeypatch.setattr(llm, "chat", _no_model)

    got = _run(onboard._step_detect_from_materials())
    assert got["products"] == [], "模型不可用时也不许拿素材标题充产品"
    for p in got["products"]:
        assert not p.startswith("export_")


# ── 2. 自动配置从内容资产来 ────────────────────────────────

def test_auto_config_detect_reads_content_assets_and_never_the_knowledge_base(monkeypatch, tenant):
    from app.api.v1 import onboard
    from app.services.store import get_store

    get_store().save(
        "kb",
        [
            {
                "id": "m_1",
                "title": "笔革家居整套全屋定制要多久",
                "content": "笔革家居是一家做全屋定制的公司，主推全案定制。",
                "source_type": "file",
            }
        ],
    )
    import adapters.eios as eios
    import adapters.llm as llm

    monkeypatch.setattr(eios, "_request", lambda *a, **k: pytest.fail("自动配置不该打知识库"))

    async def _chat(prompt: str, **_kw):
        assert "笔革家居整套全屋定制要多久" in prompt, "候选池要来自内容资产的标题"
        return (
            '{"company": ["笔革家居"], "products": ["全案定制"], "services": [], '
            '"industry": "全屋定制家装", "keywords": ["全屋定制", "家装设计"]}'
        )

    monkeypatch.setattr(llm, "chat", _chat)

    got = _run(onboard._step_detect_from_materials())
    assert got["company"] == ["笔革家居"]
    assert got["products"] == ["全案定制"]
    assert got["industry"] == "全屋定制家装"
    assert got["empty"] is False
    assert got["classification_source"] == "llm"


def test_a_material_title_is_not_offered_as_a_product(monkeypatch, tenant):
    """标题是「这份材料叫什么」，不是「企业在卖什么」——不许混进产品候选。"""
    from app.api.v1 import onboard
    from app.services.store import get_store

    get_store().save(
        "kb",
        [
            {
                "id": "m_1",
                "title": "笔革家居整套全屋定制要多久",
                "content": "笔革家居主推全案定制服务。",
                "source_type": "file",
            }
        ],
    )
    import adapters.llm as llm

    async def _chat(prompt: str, **_kw):
        return (
            '{"company": ["笔革家居"], "products": ["笔革家居整套全屋定制要多久", "全案定制"], '
            '"services": [], "industry": "全屋定制家装", "keywords": []}'
        )

    monkeypatch.setattr(llm, "chat", _chat)

    got = _run(onboard._step_detect_from_materials())
    assert got["products"] == ["全案定制"], "标题不该被当成产品名"


def test_auto_config_detect_says_so_when_there_is_no_content_asset(tenant):
    from app.api.v1 import onboard

    got = _run(onboard._step_detect_from_materials())
    assert got["empty"] is True
    assert got["error"] is None
    assert "内容资产" in (got["hint"] or "")


def test_a_truncated_model_name_is_expanded_to_the_full_candidate(monkeypatch, tenant):
    """实测模型把公司名截短成「笔革」；页面上该显示候选池里的「笔革家居」。"""
    from app.api.v1 import onboard
    from app.services.store import get_store

    get_store().save(
        "kb",
        [
            {
                "id": "m_1",
                "title": "笔革家居主理人访谈纪要",
                "content": "笔革家居主理人访谈纪要。笔革家居主推全案定制。",
                "source_type": "file",
            }
        ],
    )
    import adapters.llm as llm

    async def _chat(prompt: str, **_kw):
        return '{"company": ["笔革"], "products": [], "services": [], "industry": "全屋定制", "keywords": []}'

    monkeypatch.setattr(llm, "chat", _chat)

    got = _run(onboard._step_detect_from_materials())
    assert "笔革家居" in got["company"]
    assert "笔革" not in got["company"]


def test_style_words_are_keywords_not_products(monkeypatch, tenant):
    """实测模型把「意式极简」「奶油风」当成产品；它们是风格，归关键词。"""
    from app.api.v1 import onboard
    from app.services.store import get_store

    get_store().save(
        "kb",
        [
            {
                "id": "m_1",
                "title": "笔革家居主理人访谈纪要",
                "content": "笔革家居畅销产品是琥珀沙发。风格可承接意式极简、奶油风、中古、轻法式。",
                "source_type": "file",
            }
        ],
    )
    import adapters.llm as llm

    async def _chat(prompt: str, **_kw):
        return (
            '{"company": ["笔革家居"], '
            '"products": ["琥珀沙发", "意式极简", "奶油风", "中古", "轻法式"], '
            '"services": [], "industry": "全屋定制", '
            '"keywords": ["意式极简", "奶油风"]}'
        )

    monkeypatch.setattr(llm, "chat", _chat)

    got = _run(onboard._step_detect_from_materials())
    assert got["products"] == ["琥珀沙发"], "风格词不该出现在产品里"
    assert "意式极简" in got["keywords"]


# ── 2.5 产品发现算法（纯规则） ─────────────────────────────

def test_the_product_algorithm_finds_named_products_from_the_body():
    """Owner 2026-09-22：「我要能找到产品的算法」——不调模型也认得出产品名。"""
    from services.product_identity import product_candidates_from_materials

    materials = [
        {
            "title": "笔革家居主理人访谈纪要",
            "content": (
                "畅销产品是「琥珀沙发」，问得最多、卖得也最好。"
                "另外还有按摩功能沙发，定制柜也是主力，季节主题系列卖得不错。"
                "按摩功能沙发主要卖给老人，定制柜按投影面积算，季节主题系列每季换一次。"
                "风格上可以承接意式极简、奶油风、中古、轻法式。"
            ),
        }
    ]
    got = product_candidates_from_materials(materials)
    for want in ("琥珀沙发", "按摩功能沙发", "定制柜", "季节主题系列"):
        assert want in got, f"正文里明明白白的产品没认出来：{want}"
    for bad in ("意式极简", "奶油风", "中古", "轻法式", "笔革家居主理人访谈纪要"):
        assert bad not in got, f"不是产品名的东西不该进候选：{bad}"


def test_the_product_algorithm_ignores_prose_and_file_names():
    from services.product_identity import product_candidates_from_materials

    got = product_candidates_from_materials(
        [
            {"title": "export_1785221955586", "content": "优先选择上市公司合作。主要来自过往家具行业。", "source_type": "file"},
            {"title": "三品牌战略+奢侈品调研-前31页", "content": "本次调研围绕三大奢侈品牌设计展开。", "source_type": "file"},
        ]
    )
    assert got == [], "文件名与句子碎片都不算产品"


def test_a_product_that_only_shows_up_once_without_evidence_is_not_a_candidate():
    """证据闸：只碰巧出现一次、又不在标题/引号里的，不算产品候选。

    实测没有这道闸时，`如松弛感沙发`、`无CRM系统`、`计师共创方案` 这类
    「从长句里切出来的半截话」会一起进候选池。
    """
    from services.product_identity import product_candidates_from_materials

    got = product_candidates_from_materials(
        [{"title": "资料", "content": "顺便提一句异形沙发。另外如松弛感沙发、无CRM系统都很常见。"}]
    )
    assert "异形沙发" not in got
    assert "如松弛感沙发" not in got
    assert "无CRM系统" not in got


def test_a_name_ending_in_fuwu_is_a_service_not_a_product():
    """Owner 2026-09-22：「尾巴含『服务』不在服务里在产品里？这能对吗？」

    第一版把「服务」也当产品尾巴，于是「设计服务」被摆进「产品」那一行。分家只看尾巴，
    不做语义猜测：产品和服务的候选池共用同一套证据规则，只是归到不同的行。
    """
    from services.product_identity import (
        is_service_name,
        product_candidates_from_materials,
        service_candidates_from_materials,
    )

    materials = [
        {
            "title": "笔革家居主理人访谈纪要",
            "content": (
                "畅销产品是「琥珀沙发」，定制柜也是主力。"
                "我们提供设计服务，也做3D建模与打板服务，还有量尺、效果图、安装交付。"
                "设计服务按平米收费，3D建模与打板服务按件收费，定制柜按投影面积算。"
            ),
        }
    ]
    products = product_candidates_from_materials(materials)
    services = service_candidates_from_materials(materials)

    assert "定制柜" in products
    for name in ("设计服务", "打板服务"):
        assert name in services, f"服务候选里应该有：{name}"
        assert name not in products, f"以「服务」收尾的不该出现在产品行：{name}"
    assert "琥珀沙发" in products and "琥珀沙发" not in services
    # 分家只看尾巴，不猜语义
    assert is_service_name("量尺服务") and is_service_name("每周课程")
    assert not is_service_name("琥珀沙发") and not is_service_name("量尺")


def test_the_fallback_pool_is_split_by_tail_too():
    """知识库那一档的池子里混着服务；当兜底用时不能又把服务塞回「产品」行。"""
    from app.api.v1 import onboard

    out = _run(
        onboard._finalize_detect(
            {
                "company": ["亚宇臻隆科技"],
                "products": [],
                "services": [],
                "industry": None,
                "keywords": [],
                "classification_source": "heuristic",
            },
            biz_fallback=["琥珀沙发", "设计服务", "自媒体代运营服务"],
        )
    )
    assert out["products"] == ["琥珀沙发"]
    assert set(out["services"]) == {"设计服务", "自媒体代运营服务"}


def test_merging_a_rule_pool_never_doubles_a_name():
    """规则池的取词有长度上限，会比模型切得短；并进同一行时不能出现两条几乎一样的 chip。"""
    from app.api.v1.onboard import _merge_pool

    assert _merge_pool(["3D建模与打板服务"], ["打板服务"]) == ["3D建模与打板服务"]
    assert _merge_pool(["打板服务"], ["3D建模与打板服务"]) == ["3D建模与打板服务"]
    assert _merge_pool(["琥珀沙发"], ["琥珀沙发", "定制柜"]) == ["琥珀沙发", "定制柜"]


def test_finalize_detect_moves_service_names_out_of_products():
    """模型把服务写进 products 也要挪回来 —— 归类不靠模型自觉。"""
    from app.api.v1 import onboard

    out = _run(
        onboard._finalize_detect(
            {
                "company": ["笔革家居"],
                "products": ["琥珀沙发", "设计服务"],
                "services": [],
                "industry": None,
                "keywords": [],
                "classification_source": "llm",
            },
            biz_fallback=[],
            service_fallback=["3D建模与打板服务"],
        )
    )
    assert out["products"] == ["琥珀沙发"]
    assert "设计服务" in out["services"]
    assert "3D建模与打板服务" in out["services"]


# ── 2.6 勾选的服务要真的建监测对象 ─────────────────────────

def test_selected_services_get_their_own_monitor_objects(monkeypatch, tenant):
    """以前 `_step_create` 算了 services 却从没用过 —— 勾了服务等于没勾。"""
    from app.api.v1 import onboard
    from app.api.v1.monitor import generate_queries

    body = _run(
        onboard._step_create(
            onboard.AutoConfigIn(
                step="create", company="笔革家居", products=["琥珀沙发"], services=["全案定制"]
            )
        )
    )
    created = body["created"]
    by_entity = {c["entity"]: c for c in created}
    assert by_entity["笔革家居"]["type"] == "brand"
    assert by_entity["琥珀沙发"]["type"] == "product"
    assert by_entity["全案定制"]["type"] == "product", "服务也建对象"
    assert by_entity["全案定制"]["config_json"]["kind"] == "service"
    # 服务问法要像服务，不像一件货
    qs = generate_queries(by_entity["全案定制"])
    assert qs == ["全案定制哪家公司做得好？", "全案定制怎么收费？", "全案定制一般包含哪些内容？"]
    assert generate_queries(by_entity["琥珀沙发"])[0] == "琥珀沙发推荐哪些公司？"


def test_the_run_step_runs_the_service_objects_too(monkeypatch, tenant):
    from app.api.v1 import onboard

    body = _run(onboard._step_create(onboard.AutoConfigIn(step="create", company="笔革家居", services=["量尺"])))
    ids = [c["monitor_id"] for c in body["created"]]
    items = onboard._load_items()
    assert [i["monitor_id"] for i in items] == ids
    assert any(i["entity"] == "量尺" for i in items)


# ── 3. 删素材连切块一起删 ──────────────────────────────────

def test_deleting_a_material_removes_its_chunks_too(monkeypatch, tenant):
    from app.api.v1 import knowledge
    from app.services.store import get_store
    import services.embed as embed

    async def _no_vectors(_material_id: str) -> bool:
        return True

    monkeypatch.setattr(embed, "delete_vectors", _no_vectors)

    body = _run(
        knowledge.add_material(
            knowledge.MaterialIn(title="笔革家居整套全屋定制要多久", content=("笔革家居的工期通常是三十到四十五天。" * 20 + "\n\n") * 3)
        )
    )
    item = body["data"]["item"]
    assert item["chunks"] >= 2, "正文够长就该切成多段"
    assert len(get_store().load("kb")) == 1

    deleted = _run(knowledge.delete_material(item["id"]))["data"]
    assert deleted["chunks_removed"] == item["chunks"]
    assert deleted["title"] == "笔革家居整套全屋定制要多久"
    assert get_store().load("kb") == [], "素材行连同它的切块一起没了"


def test_deleting_a_missing_material_is_reported_not_silently_ok(tenant):
    from app.api.v1 import knowledge

    body = _run(knowledge.delete_material("m_not_there"))
    assert body["ok"] is True
    assert body["data"]["error"] == "素材不存在"
