"""Owner 2026-09-23：两处「看起来有数、其实读不出东西」的修复。

1. 监测主体：总览/舆情/评价/事实四页各自猜主体（或直接停机），改成同一处选择，
   `all` = 全选汇总；账号里一个企业品牌对象都没有时不算「需要选择」。
2. 负面高频词：碎片（消费/费者/的负/面评）来自 2-4 字滑窗各算一次，
   改成最长优先、不重叠切分，只列重复出现过的词。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

from app.api.v1 import monitor  # noqa: E402


def _patch_items(monkeypatch, items):
    monkeypatch.setattr(monitor, "_load_items", lambda: items)


def test_scope_all_means_every_object_and_needs_no_selection(monkeypatch):
    _patch_items(monkeypatch, [
        {"monitor_id": "mi_1", "type": "brand", "status": "active"},
        {"monitor_id": "mi_2", "type": "brand", "status": "active"},
    ])
    assert monitor._resolve_subject_scope("all") == (None, False)


def test_scope_keeps_a_picked_object_and_refuses_an_unknown_one(monkeypatch):
    _patch_items(monkeypatch, [
        {"monitor_id": "mi_1", "type": "brand", "status": "active"},
        {"monitor_id": "mi_2", "type": "brand", "status": "active"},
    ])
    assert monitor._resolve_subject_scope("mi_2") == ("mi_2", False)
    # 多个品牌对象时不许猜第一个
    assert monitor._resolve_subject_scope(None) == (None, True)
    assert monitor._resolve_subject_scope("mi_not_mine") == (None, True)


def test_scope_with_no_brand_object_is_not_a_pending_choice(monkeypatch):
    _patch_items(monkeypatch, [{"monitor_id": "mi_9", "type": "keyword", "status": "active"}])
    # 没有企业品牌对象 = 没什么可选，也没得统计；但不该输出「请选择监测主体」
    assert monitor._resolve_subject_scope(None) == (None, False)


def test_negative_top_words_are_words_not_sliding_window_fragments(monkeypatch):
    _patch_items(monkeypatch, [{"monitor_id": "mi_1", "type": "brand", "status": "active",
                                "config_json": {"company": "笔革家居"}}])
    records = [
        {"sentiment": "negative", "snippet": "消费者抱怨交付太慢，消费者还提到增项"},
        {"sentiment": "negative", "snippet": "消费者说交付慢，售后推诿"},
        {"sentiment": "positive", "snippet": "消费者很满意"},  # 正面不参与统计
    ]
    words = [w["word"] for w in monitor._negative_top_words(records, "mi_1")]
    assert "消费者" in words
    assert "消费" not in words, "最长优先：切出「消费者」后不再产「消费」"
    assert "费者" not in words, "滑窗碎片不能再出现"
    assert "交付" in words


def test_negative_top_words_drop_one_off_noise(monkeypatch):
    _patch_items(monkeypatch, [{"monitor_id": "mi_1", "type": "brand", "status": "active",
                                "config_json": {"company": "笔革家居"}}])
    records = [{"sentiment": "negative", "snippet": "只出现一次的词比如增项条款"}]
    assert monitor._negative_top_words(records, "mi_1") == []
