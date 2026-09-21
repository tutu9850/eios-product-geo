"""Owner 2026-09-21：「geo 上传资料这里也要切块存，只切块就行了」。

这个文件只钉「切块存」这一件事，并且钉住**后面那些没做**：
- 存的是 GEO 自己的素材行（不是知识库）；
- 每块 text 是正文的**逐字切片**（不许重排/改写，否则引用对不上原文）；
- 块数写进 `chunks`（这个字段以前恒为 0，是个空壳）；
- 正文改了要重切（切块和正文对不上等于骗人）；
- 不调模型、不向量化、不抽实体、不写知识库。
"""
import asyncio
import io
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest  # noqa: E402

from services.chunking import CHUNK_MAX, chunk_material, chunk_text  # noqa: E402


@pytest.fixture()
def tenant():
    """每个测试一个自己的租户柜（素材存在 GEO 自己的 store 里，按 tenant 分区）。"""
    from app.models.geo_models import engine, init_db
    from app.services.store import set_tenant

    init_db()
    try:
        set_tenant(f"tenant_chunk_{uuid.uuid4().hex[:8]}")
        yield
    finally:
        set_tenant("tenant_corp_01")
        engine.dispose()


LONG = ("第一段讲了产品定位与目标客户。\n\n") + ("第二段" + "内容很长。" * 120 + "\n\n") + "短尾。"


def test_chunk_text_is_a_verbatim_slice_of_the_source():
    chunks = chunk_text(LONG)
    assert len(chunks) >= 2
    for i, c in enumerate(chunks):
        assert c["ordinal"] == i
        assert c["start"] < c["end"]
        assert c["chars"] == len(c["text"])
        assert LONG[c["start"]:c["end"]] == c["text"], "块必须是正文的逐字切片"
        assert c["text"].strip(), "不许产出空块"
        assert c["chars"] <= CHUNK_MAX


def test_chunk_text_handles_short_and_empty_text():
    assert len(chunk_text("就一句话。")) == 1
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []
    material = chunk_material({"content": "   "})
    assert material["chunks"] == 0 and material["text_chunks"] == []


def test_chunk_text_splits_one_overlong_paragraph():
    """一整段没有空行、又远超上限：必须按句子/硬切切开，不能当成一块塞给模型。"""
    one = "这是一句很长的话。" * 300
    chunks = chunk_text(one)
    assert len(chunks) > 1
    assert all(c["chars"] <= CHUNK_MAX for c in chunks)
    assert all(one[c["start"]:c["end"]] == c["text"] for c in chunks)


def test_chunk_material_records_the_count_and_the_time():
    item = chunk_material({"content": LONG})
    assert item["chunks"] == len(item["text_chunks"]) >= 2
    assert item["chunk_chars"] == len(LONG)
    assert item["chunked_at"]


def _upload(name: str, raw: bytes):
    from starlette.datastructures import UploadFile

    from app.api.v1 import knowledge

    return asyncio.run(knowledge.upload_material(UploadFile(file=io.BytesIO(raw), filename=name)))


def test_uploaded_file_is_stored_with_its_chunks(tenant):
    """上传一份资料：文本照旧存正文，同时**切块存进这一行**（GEO 自己的库）。"""
    from app.api.v1 import knowledge

    body = _upload("策略.txt", LONG.encode("utf-8"))
    assert body["ok"] is True
    assert body["data"]["chunks"] >= 2

    items = knowledge._load()
    assert len(items) == 1
    item = items[0]
    assert item["source_type"] == "file"
    assert item["file_name"] == "策略.txt"
    assert item["chunks"] == len(item["text_chunks"]) >= 2
    for c in item["text_chunks"]:
        assert item["content"][c["start"]:c["end"]] == c["text"]

    stats = asyncio.run(knowledge.list_materials())["data"]["stats"]
    assert stats["files"] == 1 and stats["chunks"] == item["chunks"]


def test_upload_that_yields_no_text_is_still_an_honest_error(tenant):
    from app.api.v1 import knowledge

    body = _upload("空的.txt", b"   \n  ")
    assert "error" in body["data"]
    assert knowledge._load() == []


def test_editing_the_body_rechunks_so_the_chunks_never_lie(tenant):
    from app.api.v1 import knowledge

    _upload("策略.txt", (LONG * 3).encode("utf-8"))
    item = knowledge._load()[0]
    before = item["chunks"]

    asyncio.run(knowledge.update_material(item["id"], knowledge.MaterialPatchIn(content="只有一句话。")))
    after = knowledge._load()[0]
    assert after["content"] == "只有一句话。"
    assert after["chunks"] == 1 and after["chunks"] != before
    assert after["text_chunks"][0]["text"] == "只有一句话。"


def test_chunking_never_calls_a_model_or_writes_to_the_knowledge_base():
    """只切块：这个模块**只准依赖标准库**（没有模型、没有向量、没有知识库客户端）。

    用 AST 读 import，而不是扫字符串 —— 注释里写着「不做 embedding」不该被判成违规。
    """
    import ast
    import inspect

    import services.chunking as chunking

    tree = ast.parse(inspect.getsource(chunking))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"__future__", "re", "datetime", "typing"}, imported
