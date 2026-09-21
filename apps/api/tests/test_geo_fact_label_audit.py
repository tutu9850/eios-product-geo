"""Owner 2026-09-21：知识库命中里的 ``value`` 是**原文片段**，不是事实值。

实测（``GET :8091/api/v1/content/score``）：内容评分返回的建议里出现被截断的表格原文
「M-001 工作表: 账号矩阵 账号编号 | 平台 | 账号名 | 内容方向 | 粉丝数 | 负责人 …」，
企业画像卡同样把这段 502 字的表按 20 条「事实」重复打印。

根因（两处，均非用户输入）：
1. ``adapters/eios._map_hit`` 把命中所在的 **snippet** 放进 ``value``，``predicate`` 恒为 None
   （知识库对这家企业只产出 ``type=entity`` 对象，没有任何 fact 对象）；
2. ``score_fact_density`` / 前端 ``factLine`` 直接 ``canonical_name + value`` 拼标签。

本文件钉住修复后的口径：用户可见标签只允许「实体名 + 数字锚点」或后端给的 display，
永不回吐多行原文；同一份原文带出的重复标签要去重。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

from services.content.fact_checker import LABEL_MAX, score_fact_density  # noqa: E402

#: 实测样本：一张账号矩阵表就是命中的 snippet（502 字，多行表格）
_RAW_SHEET = (
    "工作表: 账号矩阵\n\n账号编号 | 平台 | 账号名 | 内容方向 | 粉丝数 | 负责人\n\n"
    "M-001 | 抖音 | 亚宇臻隆AI获客 | 家居AI获客干货 | 98000 | 吴鑫宇\n\n"
    "M-002 | 抖音 | 笔革艺术家居 | 案例展示 | 12000 | 李沅洪"
)


def _hit(name: str) -> dict:
    """知识库命中形态：canonical_name=实体名，value=它所在的整段原文。"""
    return {
        "canonical_name": name,
        "predicate": None,
        "value": _RAW_SHEET,
        "text": _RAW_SHEET[:200],
        "object_type": "entity",
        "document_title": "账号矩阵",
    }


def test_missing_label_never_dumps_raw_text():
    out = score_fact_density("这段内容没有写任何数据", [_hit("抖音")])
    assert out["needs_rewrite"] is True
    for item in out["missing_facts"]:
        assert "工作表" not in item, item
        assert "|" not in item, item
        assert "\n" not in item, item
        assert len(item) <= LABEL_MAX, item
    assert "抖音" in out["suggestion"]
    assert "工作表" not in out["suggestion"]


def test_label_is_name_plus_number_anchor_from_own_row():
    """锚点只取该实体自己那一行：整段表里别人的数字不算这条对象的。"""
    out = score_fact_density("内容里提到了抖音账号但没给数", [_hit("抖音")])
    assert out["missing_facts"] == ["抖音（001、98000）"]

    out2 = score_fact_density("本文只谈笔革艺术家居", [_hit("笔革艺术家居")])
    assert out2["missing_facts"] == ["笔革艺术家居（002、12000）"]


def test_repeated_same_entity_is_deduped():
    """同一份表带出 20 个实体时，同名同时只报一次。"""
    facts = [_hit("抖音"), _hit("抖音"), _hit("抖音")]
    out = score_fact_density("没有命中任何数据", facts)
    assert out["missing_facts"] == ["抖音（001、98000）"]


def test_label_without_name_uses_source_not_raw_text():
    """没有实体名时不许拿表格原文当标签——退回出处资料名。"""
    fact = {"canonical_name": "", "predicate": None, "value": _RAW_SHEET, "document_title": "账号矩阵"}
    out = score_fact_density("没有命中", [fact])
    assert out["missing_facts"] == ["账号矩阵"]

    # 连出处也没有 → 丢弃该标签（不吐原文），退回通用建议
    bare = {"canonical_name": "", "predicate": None, "value": _RAW_SHEET, "document_title": ""}
    out2 = score_fact_density("没有命中", [bare])
    assert out2["missing_facts"] == []
    assert "补充更多带数字/时间的企业数据" in out2["suggestion"]


def test_hit_label_also_sanitized():
    """命中（正文里写了数据）时也不能把原文标签吐给用户。"""
    out = score_fact_density(f"抖音账号现有 98000 粉丝（来源：{_RAW_SHEET[:10]}）", [_hit("抖音")])
    for item in out["hit_facts"]:
        assert "工作表" not in item and "\n" not in item


def test_fact_display_prefers_name_and_source_for_entities():
    from app.services.company_profile import _fact_display

    line = _fact_display(_hit("抖音"))
    assert line == "抖音 · 来自《账号矩阵》"
    assert "\n" not in line


def test_fact_display_keeps_real_fact_single_line_and_capped():
    from app.services.company_profile import _fact_display

    line = _fact_display(
        {"canonical_name": "亚宇臻隆科技", "predicate": "成立时间", "value": "2021 年成立", "document_title": "公司简介"}
    )
    assert line == "亚宇臻隆科技：2021 年成立"

    long_line = _fact_display({"canonical_name": "X", "predicate": "备注", "value": _RAW_SHEET, "document_title": ""})
    assert "\n" not in long_line
    assert len(long_line) <= 120


def test_entity_cores_skip_serial_codes():
    """实体覆盖不该要求正文写「M-001」这类表格编号。"""
    from services.content.geo_score import _entity_cores

    facts = [
        {"canonical_name": "M-001"},
        {"canonical_name": "M-002"},
        {"canonical_name": "A12"},
        {"canonical_name": "2024"},
        {"canonical_name": "抖音"},
        {"canonical_name": "亚宇臻隆科技"},
    ]
    cores = _entity_cores(facts, "亚宇臻隆科技")
    assert "M-001" not in cores and "M-002" not in cores
    assert "A12" not in cores and "2024" not in cores
    assert "抖音" in cores
    assert "亚宇臻隆科技" not in cores  # 自身企业名不算要补的实体


def test_own_row_anchors_do_not_cross_match_other_rows():
    """正文写了 A 行的数字，不该算成 B 行实体被写进去了。"""
    facts = [_hit("抖音"), _hit("笔革艺术家居")]
    out = score_fact_density("笔革艺术家居在抖音做内容，粉丝 12000。", facts)
    assert "笔革艺术家居（002、12000）" in out["hit_facts"]
    assert "抖音（001、98000）" in out["missing_facts"]
