"""Owner 2026-09-21：两份 docx 的切块「检索看得见、文档读不了」。

真因（已查实，GEO 不改权威）：那两份 docx 在知识库里是 ``status=chunked``（未发布）。
检索走的是 **material 层**，契约允许有权限的读者读企业自己的原料，所以切块看得见；
而 ``GET /documents/{id}/chunks`` 对未发布文档额外要求**治理 scope**，GEO 的票只有读
scope，于是那里是 404 ``resource is not available in the caller's view`` —— fail-closed，
权威侧有意为之，不是 bug。

Owner 的指示是「想办法修了，给一条通道……同步知识库的时候就能看得到一并带过来存起来」。
所以 GEO 侧只做两件事，且都不碰权威：
1. 读到的每一段切块正文**落进 GEO 自己的台账**（``kind=chunks``），正本仍在知识库；
2. 按文档取切块时**先走权威的门**，门关着才回落自己存下的快照，并如实标
   ``source=geo_snapshot`` / ``authoritative=False`` / ``authority_document_chunks_denied``。

本文件钉住这两条通道，以及「两边都没有时不伪造空内容」。
"""
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _seed_chunks(document_id: str, chunks: list[tuple[str, str]], *, title: str = "方案.docx") -> None:
    from app.services.knowledge_snapshot import chunk_snapshot_payload, record

    record(
        kind="chunks",
        payload=chunk_snapshot_payload(
            [
                {"document_id": document_id, "document_title": title, "chunk_id": cid, "text": text,
                 "layer": "material"}
                for cid, text in chunks
            ]
        ),
    )


def test_chunks_for_document_prefers_the_chunks_ledger_and_dedupes():
    """按文档取切块：``kind=chunks`` 优先，再用 ``kind=search`` 兜底，同一 chunk_id 只留一次。"""
    from app.services.knowledge_snapshot import chunks_for_document, record

    record(
        kind="search",
        payload={
            "contract": "eios.knowledge_search_result/v2",
            "items": [
                {"document_id": "doc_a", "chunk_id": "chk_1", "text": "检索里存过的第一段"},
                {"document_id": "doc_a", "chunk_id": "chk_9", "text": "只有检索存过的第九段"},
                {"document_id": "doc_other", "chunk_id": "chk_x", "text": "别的文档"},
            ],
        },
    )
    _seed_chunks("doc_a", [("chk_1", "台账里的第一段"), ("chk_2", "台账里的第二段")])

    out = chunks_for_document("doc_a")
    by_id = {c["chunk_id"]: c for c in out}
    assert sorted(by_id) == ["chk_1", "chk_2", "chk_9"]
    assert by_id["chk_1"]["text"] == "台账里的第一段", "chunks 台账优先于检索命中"
    assert by_id["chk_1"]["origin"] == "snapshot:chunks"
    assert by_id["chk_9"]["origin"] == "snapshot:search", "只有检索存过的切块也要取得到"
    assert all(c["source"] == "geo_snapshot" and c["authoritative"] is False for c in out)
    assert all(c["document_id"] == "doc_a" for c in out), "不许把别的文档的切块串进来"

    assert chunks_for_document("doc_missing") == []
    assert chunks_for_document("") == []


def test_documents_with_chunks_counts_distinct_chunks_and_marks_them_snapshot_only():
    """未发布文档也要能被列出（文档列表里没有它），且切块数是「读到过几个不同的」。"""
    from app.services.knowledge_snapshot import documents_with_chunks, record

    _seed_chunks("doc_a", [("chk_1", "第一段"), ("chk_2", "第二段")])
    # 同一段 chk_1 又出现在检索快照里：不许因此把计数涨到 3
    record(
        kind="search",
        payload={
            "contract": "eios.knowledge_search_result/v2",
            "items": [{"document_id": "doc_a", "chunk_id": "chk_1", "text": "第一段",
                       "document_title": "方案.docx"}],
        },
    )

    by_id = {d["document_id"]: d for d in documents_with_chunks()}
    assert by_id["doc_a"]["chunks"] == 2
    assert by_id["doc_a"]["title"] == "方案.docx"
    assert by_id["doc_a"]["snapshot_only"] is True
    assert by_id["doc_a"]["readable_from"] == ["geo_snapshot"]
    assert by_id["doc_a"]["sources"] == ["snapshot:chunks", "snapshot:search"]


def test_search_knowledge_records_every_read_chunk_in_geos_own_ledger(monkeypatch):
    """每次检索读到的切块正文都要落进 GEO 自己的台账（Owner: 读到的都存下来）。"""
    import adapters.eios as eios
    from app.services.knowledge_snapshot import chunks_for_document

    async def _search(method: str, path: str, **_kw):
        assert path == "/api/v1/knowledge/search"
        return {
            "contract": eios.SEARCH_RESULT_CONTRACT,
            "matched": True,
            "hits": [
                {
                    "snippet": "Role: 亚宇臻隆客资截流与转化追踪器",
                    "document_id": "doc_agent",
                    "document_title": "自媒体AI铁军4大Agent职责与Prompt框架.docx",
                    "chunk_id": "chk_agent",
                    "authority": "material",
                    "knowledge_object": {"id": "obj_1", "type": "entity", "canonical_name": "亚宇臻隆"},
                }
            ],
            "warnings": [],
        }

    monkeypatch.setattr(eios, "_request", _search)
    result = _run(eios.search_knowledge("亚宇臻隆科技", top_k=5, include_candidates=True))

    assert result["snapshot_recorded"] is True
    stored = chunks_for_document("doc_agent")
    assert [c["chunk_id"] for c in stored] == ["chk_agent"]
    assert stored[0]["text"] == "Role: 亚宇臻隆客资截流与转化追踪器"
    assert stored[0]["origin"] == "snapshot:chunks"


def test_list_document_chunks_uses_the_authority_gate_when_it_opens(monkeypatch):
    """门开着就用权威的（正本），并顺手落进台账；``source`` 如实标 ``knowledge``。"""
    import adapters.eios as eios
    from app.services.knowledge_snapshot import chunks_for_document

    seen: dict[str, str] = {}

    async def _request(method: str, path: str, **kwargs):
        seen["method"] = method
        seen["path"] = path
        return {"items": [{"id": "chk_1", "ordinal": 0, "content": "权威给的切块原文"}]}

    monkeypatch.setattr(eios, "_request", _request)
    got = _run(eios.list_document_chunks("doc_pub"))

    assert seen == {"method": "GET", "path": "/api/v1/knowledge/documents/doc_pub/chunks"}
    assert got["source"] == "knowledge"
    assert got["warnings"] == []
    assert got["items"][0]["text"] == "权威给的切块原文"
    assert got["items"][0]["authoritative"] is False, "GEO 不冒充权威"

    stored = chunks_for_document("doc_pub")
    assert [c["chunk_id"] for c in stored] == ["chk_1"]
    assert stored[0]["text"] == "权威给的切块原文"


def test_list_document_chunks_falls_back_to_geo_snapshot_when_the_gate_denies(monkeypatch):
    """门关着（未发布文档缺治理 scope）→ 用 GEO 自己存下的快照，并如实标拒绝过。"""
    import adapters.eios as eios

    _seed_chunks("doc_unpublished", [("chk_1", "检索读到过的那一段正文")])

    async def _deny(method: str, path: str, **_kw):
        raise eios.EIOSKnowledgeError(
            "NOT_FOUND", "resource is not available in the caller's view", 404
        )

    monkeypatch.setattr(eios, "_request", _deny)
    got = _run(eios.list_document_chunks("doc_unpublished"))

    assert got["source"] == "geo_snapshot"
    assert got["warnings"][0] == "authority_document_chunks_denied"
    assert "EIOSKnowledgeError" in got["warnings"][1]
    assert "快照" in got["warnings"][1]
    assert [i["chunk_id"] for i in got["items"]] == ["chk_1"]
    assert got["items"][0]["text"] == "检索读到过的那一段正文"
    assert got["items"][0]["authoritative"] is False


def test_list_document_chunks_reraises_when_neither_side_has_it(monkeypatch):
    """两边都没有 → 原样抛权威的错误，不许伪造一个空结果冒充「读到了」。"""
    import adapters.eios as eios

    async def _deny(method: str, path: str, **_kw):
        raise eios.EIOSKnowledgeError(
            "NOT_FOUND", "resource is not available in the caller's view", 404
        )

    monkeypatch.setattr(eios, "_request", _deny)
    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        _run(eios.list_document_chunks("doc_nowhere"))

    assert caught.value.code == "NOT_FOUND"
    assert "resource is not available in the caller's view" in caught.value.message


def test_list_document_chunks_rejects_an_empty_document_id():
    import adapters.eios as eios

    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        _run(eios.list_document_chunks("   "))
    assert caught.value.code == "INVALID_PARAMETER"


def test_list_document_chunks_follows_the_next_cursor_until_it_runs_out(monkeypatch):
    """权威给了 next_cursor 就继续翻 —— 不许把第一页当成「全部切块」。"""
    import adapters.eios as eios

    pages = {
        None: {"items": [{"id": "chk_1", "ordinal": 0, "content": "第一页"}, ], "next_cursor": "c1"},
        "c1": {"items": [{"id": "chk_2", "ordinal": 1, "content": "第二页"}], "next_cursor": None},
    }
    seen: list[Any] = []

    async def _request(method: str, path: str, **kwargs):
        cursor = (kwargs.get("params") or {}).get("cursor")
        seen.append(cursor)
        return pages[cursor]

    monkeypatch.setattr(eios, "_request", _request)
    got = _run(eios.list_document_chunks("doc_paged"))

    assert seen == [None, "c1"]
    assert [i["chunk_id"] for i in got["items"]] == ["chk_1", "chk_2"]
    assert got["truncated"] is False
    assert got["warnings"] == []


def test_list_document_chunks_says_so_when_it_stops_at_the_page_cap(monkeypatch):
    """翻到上限还有下一页：``truncated=True`` + 明确警告，不把一部分说成全部。"""
    import adapters.eios as eios

    async def _always_more(method: str, path: str, **kwargs):
        n = len(getattr(_always_more, "calls", []))
        _always_more.calls = getattr(_always_more, "calls", []) + [1]
        return {"items": [{"id": f"chk_{n}", "ordinal": n, "content": f"第 {n} 页"}], "next_cursor": f"c{n + 1}"}

    monkeypatch.setattr(eios, "_request", _always_more)
    got = _run(eios.list_document_chunks("doc_forever"))

    assert len(got["items"]) == eios._MAX_CHUNK_PAGES
    assert got["truncated"] is True
    assert got["warnings"][0] == "authority_chunks_truncated"
