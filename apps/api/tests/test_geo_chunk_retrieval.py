"""Owner 2026-09-21 拍板要做的那两件：**让切块真被用上**。

1. 检索命中定位到具体那一段（`/knowledge/materials/search` 返回命中段与段号）；
2. 内容生成注入**最相关的那几段**（而不是整篇开头固定 150 字）；
   顺带补上既存缺口：上传的文件（`source_type=file`）以前根本进不了生成上下文。

不变量：
- 没切块的老素材一律按整篇处理，**不许假装有块**（`chunk_ordinal` 是 None）；
- 正文命中按「最贴的那一段」算，不再按整篇累加（避免「长 = 相关」）；
- 这里全是本地确定性打分，不调模型、不联网。
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

from services.chunking import chunk_material  # noqa: E402
from services.content import build_context  # noqa: E402
from services.embed import best_chunk, hybrid_search, n_gram_scores  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


#: 够长到切出多段；**命中的内容刻意放在最后一段**，这样「定位」才是有意义的
LONG = (
    "第一段只讲公司沿革与工商登记信息，与渠道和成交无关。" * 12
    + "\n\n"
    + "第二段讲售后与续费政策，同样与渠道无关。" * 12
    + "\n\n"
    + "第三段讲成都、重庆、无锡三地演示间的成交路径与复购。" * 10
)


def _material(mid: str, title: str, content: str) -> dict:
    return chunk_material({"id": mid, "title": title, "content": content})


def test_best_chunk_finds_the_segment_that_actually_matches():
    mat = _material("m_1", "公司资料", LONG)
    assert len(mat["text_chunks"]) >= 2, "这份资料应当被切成多段"
    hit = best_chunk("无锡演示间", mat)
    assert hit is not None
    assert "无锡" in hit["text"], "命中的必须是含「无锡」的那一段"
    assert hit["ordinal"] == mat["chunks"] - 1, "命中的是最后一段（开头两段与无锡无关）"
    assert hit["id"] == f"m_1#{hit['ordinal']}"


def test_ranking_does_not_change_just_because_a_material_was_chunked():
    """排序口径**故意不变**：切块前后同一篇资料得分一样。

    核心词是集合，长度不会抬高分数；「命中定位到哪一段」是另一件事（``best_chunk``），
    不掺进 n_gram 数值 —— 否则素材页的分数会因为「切了块」而莫名跳动。
    """
    material = _material("m_1", "公司资料", LONG)
    plain = {"id": "m_1", "title": "公司资料", "content": LONG}
    assert n_gram_scores("无锡演示间", [material]) == n_gram_scores("无锡演示间", [plain])


def test_material_search_returns_the_matched_segment():
    """检索结果要给出「命中在第几段 + 那一段的片段」。"""
    mats = [_material("m_1", "公司资料", LONG)]

    async def _no_vectors(_texts):
        return None

    with patch("services.embed._load_materials", return_value=mats), \
         patch("services.embed._qdrant_alive", return_value=False), \
         patch("services.embed._load_mem_index", return_value={}), \
         patch("services.embed.embed_texts", _no_vectors):
        hits = _run(hybrid_search("无锡演示间", top_k=3))

    assert hits, "应当命中这份素材"
    top = hits[0]
    assert top["chunk_id"] and top["chunk_ordinal"] is not None
    assert top["chunk_ordinal"] == len(mats[0]["text_chunks"]) - 1, "要指向真正命中的那一段"
    assert "无锡" in (top["snippet"] or ""), "片段应当是含命中词的那一段"


def test_material_search_still_works_for_old_materials_without_chunks():
    mats = [{"id": "m_old", "title": "老素材", "content": "成都、重庆、无锡三地演示间。"}]

    async def _no_vectors(_texts):
        return None

    with patch("services.embed._load_materials", return_value=mats), \
         patch("services.embed._qdrant_alive", return_value=False), \
         patch("services.embed._load_mem_index", return_value={}), \
         patch("services.embed.embed_texts", _no_vectors):
        hits = _run(hybrid_search("无锡", top_k=3))

    assert hits
    assert hits[0]["chunk_id"] is None and hits[0]["chunk_ordinal"] is None, "没切块就不许假装有段"
    assert "无锡" in (hits[0]["snippet"] or "")


class _Store:
    def __init__(self, items: list[dict]):
        self._items = items

    def load(self, name: str):
        return list(self._items) if name == "kb" else []


def _context(question: str, assets: list[dict]) -> dict:
    async def _search(*_a, **_kw):
        return {"hits": []}

    with patch("app.services.store.get_store", return_value=_Store(assets)), \
         patch("services.content.search_knowledge", _search), \
         patch("services.content._official_fact_lines", return_value=[]):
        return _run(build_context(question=question, company_name="亚宇臻隆科技"))


def test_uploaded_file_now_reaches_content_generation():
    """既存缺口：上传件是 source_type=file，原来被「历史素材」排除在外 → 生成时用不上。"""
    assets = [_material("m_up", "渠道复盘.txt", LONG) | {"source_type": "file"}]
    ctx = _context("无锡演示间怎么成交", assets)
    titles = [a["title"] for a in ctx["other_assets"]]
    assert "渠道复盘.txt" in titles, "上传的文件必须进入生成上下文"


def test_generation_injects_the_matched_segment_not_the_opening_150_chars():
    assets = [_material("m_up", "渠道复盘.txt", LONG) | {"source_type": "file"}]
    ctx = _context("无锡演示间怎么成交", assets)
    src = next(s for s in ctx["context_sources"] if s["kind"] == "asset")
    item = src["items"][0]
    assert item["content"] and "无锡" in item["content"], "注入的应当是命中那一段"
    assert item["chunk_ordinal"] is not None and item["chunk_id"].startswith("m_up#")


def test_generation_prefers_the_last_segment_when_that_is_the_one_that_matches():
    """命中在最后一段时，注入的必须是最后一段 —— 这才叫「最相关的几段」。"""
    assets = [_material("m_up", "渠道复盘.txt", LONG) | {"source_type": "file"}]
    ctx = _context("无锡演示间怎么成交", assets)
    src = next(s for s in ctx["context_sources"] if s["kind"] == "asset")
    item = src["items"][0]
    assert item["chunk_ordinal"] == len(assets[0]["text_chunks"]) - 1
    assert item["content"].startswith("第三段讲成都、重庆、无锡"), "注入的是那一段本身，不是整篇开头"


def test_old_material_without_chunks_still_injects_its_opening_text():
    assets = [{"id": "m_old", "title": "老素材", "source_type": "file", "content": "无锡演示间" * 60}]
    ctx = _context("无锡演示间", assets)
    src = next(s for s in ctx["context_sources"] if s["kind"] == "asset")
    item = src["items"][0]
    assert item["chunk_ordinal"] is None, "没切块就不许报段号"
    assert item["content"] == ("无锡演示间" * 60)[:150]
