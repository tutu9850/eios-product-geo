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
