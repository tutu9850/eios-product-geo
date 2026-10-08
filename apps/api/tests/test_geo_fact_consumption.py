"""Owner 2026-09-21 拍板：Knowledge 里的 active fact 是正式企业事实，GEO 应当消费。

五条原则（本文件钉住其中的可测部分）：
1. 事实原样带出，GEO 不改写；
2. 画像归类**只依据权威 Semantic 关联**（``semantic_object_id`` 前缀），
   **不再用 GEO 自己维护的关键词表**硬分类；
3. 不能可靠归类的不塞进七类，保留在「企业事实」；
4. 内容生成消费的是事实本身（检索片段只作补充）；
5. 不改 Authority / PDP / 权限模型（所以本文件只测读侧行为）。

真实数据背景：本部署 371 条企业可见对象里 ``semantic_object_id`` **全为空**（实测），
因此七类今天必然是空的，29 条事实全部落在「企业事实」。
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

from app.services.company_profile import (  # noqa: E402
    _PROFILE_FIELDS,
    _classify,
    _fact_group,
    build_company_profile,
)
from services.content import _official_fact_lines  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _EmptyStore:
    """本地问题池/内容资产为空的最小 store（这两块与事实消费无关）。"""

    def load(self, _name: str):
        return []


_EMPTY_STORE = _EmptyStore()


def test_group_uses_authority_semantic_prefix_only():
    assert _fact_group({"semantic_object_id": "atr_01ABC"}) == "attribute"
    assert _fact_group({"semantic_object_id": "rel_01ABC"}) == "relation"
    assert _fact_group({"semantic_object_id": "met_01ABC"}) == "metric"
    # 没有权威关联 → 不猜，进「企业事实」
    assert _fact_group({"semantic_object_id": None}) == "enterprise_fact"
    assert _fact_group({}) == "enterprise_fact"
    # 名字里带「负责」也不许因此被分类（旧实现就是这么干的）
    assert _fact_group({"canonical_name": "吴鑫宇 负责人 自媒体运营"}) == "enterprise_fact"


def test_classify_fills_only_from_authority_field():
    unlinked = [{"canonical_name": "销售中心 负责 直客销售与续费"}]
    out = _classify(unlinked)
    assert set(out) == set(_PROFILE_FIELDS)
    assert all(rows == [] for rows in out.values()), "没有权威语义就不许落到七类"

    linked = [{"canonical_name": "X", "profile_field": "customers"}]
    out2 = _classify(linked)
    assert out2["customers"] == linked and out2["people"] == []


def test_official_fact_lines_keeps_fact_text_and_marks_source():
    facts = [{"canonical_name": "吴鑫宇 负责人 自媒体运营"}, {"canonical_name": "  "}]
    with patch("adapters.eios.list_enterprise_facts", return_value=facts):
        lines = _run(_official_fact_lines())
    assert lines == ["- [正式事实] 吴鑫宇 负责人 自媒体运营"]


def test_official_fact_lines_returns_empty_when_unreadable():
    with patch("adapters.eios.list_enterprise_facts", side_effect=RuntimeError("knowledge 503")):
        assert _run(_official_fact_lines()) == []


def test_profile_consumes_facts_and_keeps_them_out_of_the_seven_fields():
    facts = [
        {"canonical_name": "销售中心 负责 直客销售与续费", "object_type": "fact",
         "object_id": "ko_1", "semantic_object_id": None, "authority_level": "governed",
         "object_scope": "enterprise_active", "evidence_ids": ["evi_1"]},
        {"canonical_name": "吴鑫宇 负责人 自媒体运营", "object_type": "fact",
         "object_id": "ko_2", "semantic_object_id": None, "authority_level": "governed",
         "object_scope": "enterprise_active", "evidence_ids": ["evi_2"]},
    ]
    with patch("adapters.eios.list_enterprise_facts", return_value=facts), \
         patch("app.services.company_profile.search_knowledge", side_effect=RuntimeError("no search")), \
         patch("app.services.company_profile.search_relations", return_value=[]), \
         patch("app.services.store.get_store", return_value=_EMPTY_STORE):
        profile = _run(build_company_profile("亚宇臻隆科技"))

    assert [f["canonical_name"] for f in profile["knowledge_facts"]] == [
        "销售中心 负责 直客销售与续费",
        "吴鑫宇 负责人 自媒体运营",
    ]
    # 事实原文不被改写
    assert profile["knowledge_facts"][0]["display"] == "销售中心 负责 直客销售与续费"
    assert profile["fact_groups"] == {"enterprise_fact": 2}
    assert all(rows == [] for rows in profile["classified"].values())
    assert profile["classified_basis"] == "semantic_linkage"
    assert "0 条" in profile["classification_note"]


def test_profile_reports_fact_read_failure_instead_of_pretending_empty():
    with patch("adapters.eios.list_enterprise_facts", side_effect=RuntimeError("knowledge 503")), \
         patch("app.services.company_profile.search_knowledge", return_value={"hits": []}), \
         patch("app.services.company_profile.search_relations", return_value=[]), \
         patch("app.services.store.get_store", return_value=_EMPTY_STORE):
        profile = _run(build_company_profile("亚宇臻隆科技"))
    assert profile["knowledge_facts"] == []
    assert profile["facts_error"] and "503" in profile["facts_error"]


def test_key_facts_basis_tells_the_truth_when_no_fact_has_a_number():
    """浏览器验收发现：29 条真实事实一条数字都没有，前端却写「带数字/时间」。

    排序 ≠ 筛选：没有数字时必须如实说 ``evidence_strength``，不许把排序结果说成筛选结果。
    """
    facts = [
        {"canonical_name": "成都演示间 负责 StoryClaw终端", "object_type": "fact",
         "object_id": "ko_1", "semantic_object_id": None, "evidence_ids": []},
        {"canonical_name": "销售中心 负责 直客销售与续费", "object_type": "fact",
         "object_id": "ko_2", "semantic_object_id": None, "evidence_ids": []},
    ]
    with patch("adapters.eios.list_enterprise_facts", return_value=facts), \
         patch("app.services.company_profile.search_knowledge", return_value={"hits": []}), \
         patch("app.services.company_profile.search_relations", return_value=[]), \
         patch("app.services.store.get_store", return_value=_EMPTY_STORE):
        profile = _run(build_company_profile("亚宇臻隆科技"))
    assert profile["key_facts"], "关键事实仍然要给出（只是来源口径不同）"
    assert profile["key_facts_basis"] == "evidence_strength"


def test_key_facts_basis_reports_number_or_time_when_present():
    facts = [
        {"canonical_name": "2026 年营收目标 2000 万元", "object_type": "fact",
         "object_id": "ko_1", "semantic_object_id": None, "evidence_ids": []},
    ]
    with patch("adapters.eios.list_enterprise_facts", return_value=facts), \
         patch("app.services.company_profile.search_knowledge", return_value={"hits": []}), \
         patch("app.services.company_profile.search_relations", return_value=[]), \
         patch("app.services.store.get_store", return_value=_EMPTY_STORE):
        profile = _run(build_company_profile("亚宇臻隆科技"))
    assert profile["key_facts_basis"] == "number_or_time"


def test_materials_are_document_chunks_plus_entities_not_repeated_slices():
    """Owner 2026-09-21：内容生成消费「知识库文档切块内容 + 实体」。

    实测一条命中 = 一个知识对象 + 它出现的文档切块（snippet 与 /documents/{id}/chunks 的
    content 逐字相同）。同一张表会被检索回多条命中 —— 必须按 chunk_id 去重，
    否则同一段切块被重复喂给模型（旧实现实测重复 8 遍）。
    """
    from services.content import _materials_from_hits

    hits = [
        {"canonical_name": "M-001", "layer": "governed", "chunk_id": "chk_a", "document_title": "11_自媒体账号矩阵",
         "snippet": "工作表: 账号矩阵 M-001 | 抖音 | 亚宇臻隆AI获客"},
        {"canonical_name": "抖音", "layer": "governed", "chunk_id": "chk_a", "document_title": "11_自媒体账号矩阵",
         "snippet": "工作表: 账号矩阵 M-001 | 抖音 | 亚宇臻隆AI获客"},
        {"canonical_name": "M-002", "layer": "governed", "chunk_id": "chk_b", "document_title": "11_自媒体账号矩阵",
         "snippet": "工作表: 账号矩阵 M-002 | 抖音 | 笔革艺术家居"},
    ]
    chunks, entities = _materials_from_hits(hits)
    assert len(chunks) == 2, "同一 chunk_id 只许出现一次"
    assert all("11_自媒体账号矩阵" in c for c in chunks)
    assert entities == ["M-001", "抖音", "M-002"], "实体名去重且保持原顺序"


def test_materials_from_hits_is_empty_without_hits():
    from services.content import _materials_from_hits

    chunks, entities = _materials_from_hits([])
    assert chunks == [] and entities == []
    # 没有切块文本时不产出空壳行
    chunks, entities = _materials_from_hits([{"canonical_name": "某实体", "layer": "governed", "chunk_id": "", "snippet": ""}])
    assert chunks == [] and entities == ["某实体"]
    assert _materials_from_hits([{"canonical_name": "候选事实", "layer": "material", "chunk_id": "chk_c",
                                 "snippet": "候选原文"}]) == ([], [])


def test_build_context_sources_expose_chunks_and_entities_not_the_retired_name():
    """来源面板按新口径给来源，且不再出现退役的旧名字（Owner 2026-09-21 指出）。"""
    from services import content as content_mod

    hits = [{"canonical_name": "M-001", "layer": "governed", "chunk_id": "chk_a", "document_title": "11_自媒体账号矩阵",
             "snippet": "工作表: 账号矩阵"}]

    async def _search(*_a, **_kw):
        return {"hits": hits}

    with patch.object(content_mod, "search_knowledge", _search), \
         patch.object(content_mod, "_official_fact_lines", return_value=["- [正式事实] 销售中心 负责 直客销售与续费"]):
        ctx = _run(content_mod.build_context(question="亚宇臻隆科技是做什么的", company_name="亚宇臻隆科技"))

    kinds = {s["kind"] for s in ctx["context_sources"]}
    assert {"enterprise_fact", "document_chunk", "entity"} <= kinds
    assert "kernel" not in kinds
    chunk_source = next(s for s in ctx["context_sources"] if s["kind"] == "document_chunk")
    assert chunk_source["items"] and "工作表: 账号矩阵" in chunk_source["items"][0]["chunk"]
    assert ctx["materials"][0].startswith("- [正式事实]")
    assert any(m.startswith("- 文档切块") for m in ctx["materials"])


def test_chunk_entries_are_labelled_by_document_not_by_cell_values():
    """文档切块作为数据点来源时，标签是资料名 + 数据点个数，不是表格单元格。"""
    from services.content.fact_checker import LABEL_MAX, score_fact_density

    chunk = {
        "kind": "document_chunk",
        "canonical_name": "11_自媒体账号矩阵",
        "document_title": "11_自媒体账号矩阵",
        "value": "工作表: 账号矩阵 M-001 | 抖音 | 亚宇臻隆AI获客 | 98000 | 吴鑫宇",
    }
    out = score_fact_density("这段内容没有写任何数据", [chunk])
    assert out["missing_facts"], "切块里有数字，应当被当成可注入的数据点"
    label = out["missing_facts"][0]
    assert label.startswith("11_自媒体账号矩阵（")
    assert "数据点" in label
    assert "98000" not in label, "不许把单元格数值列成「企业事实数据」"
    assert len(label) <= LABEL_MAX


def test_score_uses_entity_names_for_coverage_and_chunks_for_density():
    """回归：旧实现把「实体名 + 它所在的那段原文」当事实点，建议里出现
    「M-001（001、98000）」这种把表格单元格当企业事实的假数据点（2026-09-21 实测）。"""
    from services.content.geo_score import score_geo_content

    result = score_geo_content(
        "亚宇臻隆科技是一家做 GEO 全域运营的公司，3 月营业收入 1680000 元。",
        knowledge_facts=[{"canonical_name": "亚宇臻隆AI获客"}, {"canonical_name": "抖音"}],
        data_sources=[
            {"kind": "document_chunk", "canonical_name": "经营月报_亚宇臻隆_2026年3月.xlsx",
             "document_title": "经营月报_亚宇臻隆_2026年3月.xlsx",
             "value": "工作表: 经营月报 营业收入 | 1680000 | 100.0%"},
        ],
        pool_questions=[],
        sections={},
        company_name="亚宇臻隆科技",
    )
    joined = " ".join(result.get("suggestions") or [])
    assert "M-001" not in joined
    assert "（001、" not in joined
    # 切块里的真实数字被正文用上了 → 事实密度不该是 0
    assert result["fact_density"] > 0
