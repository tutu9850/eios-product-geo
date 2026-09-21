"""GEO 知识库：行业素材 / 问答库（GEO 侧，MVP 本地 JSON 存储）

企业正式知识走 企业知识库（/documents 上传 + compile + publish）；
这里存 GEO 专用的外部素材（行业报告、竞品文章、FAQ 草稿等），
P3 阶段可把素材经 Evidence → Fact → Knowledge Object 写入 企业知识库。
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from app.core.envelope import ok

router = APIRouter(prefix="/api/v1/knowledge")

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
DATA_DIR.mkdir(exist_ok=True)
KB_FILE = DATA_DIR / "geo_kb.json"


class MaterialIn(BaseModel):
    title: str
    content: str = ""
    source_type: str = "text"  # text | url | file | faq | generated
    url: str | None = None
    coverage_questions: list[str] | None = None  # 覆盖分析结果（V1.1 埋线，V2 效果回流用）
    published_at: str | None = None  # 人工发布打点（V1.1 埋线）
    published_url: str | None = None  # S4 打点：已发布 URL（小贝/人工发布后填，监测引用对上 citation）


class MaterialPatchIn(BaseModel):
    """S4 素材部分更新（打点等）：全部可选，只更新传了的字段。"""

    title: str | None = None
    content: str | None = None
    source_type: str | None = None
    coverage_questions: list[str] | None = None
    published_at: str | None = None
    published_url: str | None = None


def _load() -> list[dict]:
    from app.services.store import get_store

    return get_store().load("kb")


def _save(items: list[dict]) -> None:
    from app.services.store import get_store

    get_store().save("kb", items)


@router.post("/reset")
async def reset_geo_data(confirm: bool = False):
    """重置 GEO 数据（出厂状态）：清空全部业务表 + 媒体文件 + Qdrant 素材向量。

    危险操作：confirm 必须为 true，否则拒绝。删除范围 = GEO 自己的数据库
    （geo.db 9 表 + storage/media + geo_materials 向量）；不动 企业知识库/Builder。
    """
    if not confirm:
        return ok({"error": "危险操作：请确认（confirm=true）后再重置", "deleted": {}})
    from app.services.store import reset_all

    stats = reset_all()
    # 媒体文件目录清空
    media_dir = Path(_config.GEO_MEDIA_DIR)
    removed_files = 0
    if media_dir.exists():
        for f in media_dir.glob("*"):
            if f.is_file():
                f.unlink(missing_ok=True)
                removed_files += 1
    # Qdrant 素材向量清理（geo_materials collection——暗地里的数据）
    qdrant_cleared = False
    try:
        import httpx as _httpx

        coll = "geo_materials"
        r = _httpx.delete(f"http://127.0.0.1:6333/collections/{coll}", timeout=5)
        qdrant_cleared = r.status_code in (200, 404)
    except Exception:  # noqa: BLE001
        qdrant_cleared = False
    return ok(
        {
            "deleted": stats,
            "media_files_removed": removed_files,
            "qdrant_cleared": qdrant_cleared,
            "message": "GEO 数据已重置（问题池/缺口/计划/监测历史/内容资产/关注/采集/链接/媒体全清空）",
        }
    )


@router.get("/profile")
async def get_company_profile(company_name: str = "", tenant_id: str = "tenant_corp_01"):
    """企业画像组装（认知编译器第 1 层）：企业知识库事实+关系 → 画像卡片。"""
    from app.services.company_profile import build_company_profile

    if not company_name.strip():
        return ok({"error": "company_name 必填"})
    profile = await build_company_profile(company_name.strip(), tenant_id=tenant_id)
    return ok(profile)


@router.get("/materials")
async def list_materials():
    items = _load()
    total_chars = sum(len(i.get("content") or "") for i in items)
    stats = {
        "files": len(items),
        "chunks": sum(i.get("chunks", 0) for i in items),
        "vectors": sum(i.get("vectors", 0) for i in items),
        "storage_mb": round(total_chars / 1024 / 1024, 2),
    }
    return ok({"items": items, "stats": stats})


@router.get("/materials/search")
async def search_materials(q: str = "", top_k: int = 8):
    """素材混合检索（S1b）：n-gram 关键词为主 + 向量语义补充；向量不可用自动降级纯 n-gram"""
    q = (q or "").strip()
    if not q:
        return ok({"items": [], "query": q, "mode": "n-gram"})
    from services.embed import hybrid_search

    items = await hybrid_search(q, top_k=top_k)
    return ok({"items": items, "query": q, "mode": "hybrid"})


@router.post("/materials/vectorize")
async def vectorize_materials():
    """素材向量化（幂等，S1b）：Qdrant 在 → geo_materials collection；不在 → 内存+落盘缓存"""
    from services.embed import ensure_vectors, _load_materials

    stats = await ensure_vectors(_load_materials())
    return ok(stats)


@router.get("/materials/{material_id}")
async def get_material(material_id: str):
    """素材详情 + 效果聚合（S0 效果卡：列表数据无 effects，须单独拉）"""
    items = _load()
    mat = next((m for m in items if m.get("id") == material_id), None)
    if not mat:
        return ok({"error": "素材不存在"})
    from app.api.v1.monitor import _material_effects_sync

    effects = _material_effects_sync(material_id)
    return ok({"item": mat, "effects": effects})


@router.post("/materials")
async def add_material(payload: MaterialIn):
    item = {
        "id": f"m_{uuid.uuid4().hex[:12]}",
        "title": payload.title,
        "content": payload.content,
        "source_type": payload.source_type,
        "url": payload.url,
        "coverage_questions": payload.coverage_questions or [],
        "published_at": payload.published_at,
        "status": "stored",  # stored | vectorized（P3 接向量）
        "chunks": 0,
        "vectors": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _load()
    items.insert(0, item)
    _save(items)
    return ok({"item": item})


@router.post("/materials/upload")
async def upload_material(file: UploadFile = File(...)):
    """文件直接入库素材（2026-08-18）：提取文本 → 建素材（可检索/可被报告引用）。

    支持 txt/md/csv（直读）/ pdf（PyMuPDF 文字层）/ docx / xlsx / 图片（OCR）。
    扫描件/图片型 PDF 提取不到文字层时如实报错（OCR 未内置）。
    """
    fname = (file.filename or "untitled").strip()
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        return ok({"error": "文件过大（上限 20MB）"})
    text = ""
    try:
        if ext in ("txt", "md", "csv"):
            text = raw.decode("utf-8", errors="ignore")
        elif ext == "pdf":
            import fitz  # PyMuPDF（requirements 已加）

            doc = fitz.open(stream=raw, filetype="pdf")
            text = "\n".join((p.get_text("text") or "") for p in doc)
            doc.close()
        elif ext == "docx":
            import io

            from docx import Document

            d = Document(io.BytesIO(raw))
            text = "\n".join(p.text.strip() for p in d.paragraphs if p.text and p.text.strip())
        elif ext in ("xlsx", "xlsm"):
            import io

            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
            parts: list[str] = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            wb.close()
            text = "\n".join(parts)
        elif ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp"):
            # 图片 OCR（2026-08-18）：RapidOCR（PaddleOCR ONNX 轻量版，本地 CPU）
            from rapidocr_onnxruntime import RapidOCR

            ocr = RapidOCR()
            result, _ = ocr(raw)  # RapidOCR 接受 bytes/ndarray/路径，不接受 BytesIO
            parts = [line[1] for line in (result or []) if len(line) > 1 and line[1]]
            text = "\n".join(parts)
        else:
            return ok({"error": f"暂不支持 .{ext} 类型，支持 txt / md / csv / pdf / docx / xlsx / 图片"})
    except Exception as e:  # noqa: BLE001
        return ok({"error": f"文件解析失败：{str(e)[:150]}"})
    text = text.strip()
    if len(text) < 10:
        return ok({"error": "未能从文件中提取到有效文本（扫描件/图片型 PDF 需先 OCR）"})
    title = fname.rsplit(".", 1)[0] or fname
    item = {
        "id": f"m_{uuid.uuid4().hex[:12]}",
        "title": title,
        "content": text,
        "source_type": "file",
        "url": None,
        "coverage_questions": [],
        "published_at": None,
        "status": "stored",
        "chunks": 0,
        "vectors": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "file_name": fname,
    }
    items = _load()
    items.insert(0, item)
    _save(items)
    return ok({"item": item, "chars": len(text)})


# ── 媒体存储（2026-08-07）：图片/文件存 storage/media/，库存路径指针 ──
import mimetypes
import os as _os
import shutil as _shutil
import uuid as _uuid

from app.core import config as _config


@router.post("/media/upload")
async def upload_media(file: UploadFile = File(...)):
    """上传图片/文件：存 storage/media/，返回可访问 URL 与路径。大小上限 10MB（审计 P1-11）。"""
    MAX_MB = 10 * 1024 * 1024
    size = 0
    media_dir = Path(_config.GEO_MEDIA_DIR)
    media_dir.mkdir(parents=True, exist_ok=True)
    ext = _os.path.splitext(file.filename or "")[1] or ".bin"
    fname = f"{_uuid.uuid4().hex[:12]}{ext}"
    dest = media_dir / fname
    with dest.open("wb") as out:
        while chunk := file.file.read(1024 * 256):
            size += len(chunk)
            if size > MAX_MB:
                out.close()
                dest.unlink(missing_ok=True)
                return ok({"error": f"文件超过大小上限（10MB）"})
            out.write(chunk)
    mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    from app.services.store import get_store

    rec = get_store().insert(
        "media_files",
        {
            "filename": file.filename or fname,
            "path": fname,
            "mime": mime,
            "size": size,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return ok({"file_id": rec.get("id"), "url": f"/api/v1/knowledge/media/{fname}", "size": size, "mime": mime})


@router.get("/media/{filename}")
async def get_media(filename: str):
    """读取媒体文件（前端 <img src> 用）。路径校验：必须落在 media_dir 内（审计 P0-3 目录遍历）。"""
    from fastapi.responses import FileResponse

    media_dir = Path(_config.GEO_MEDIA_DIR).resolve()
    fp = (media_dir / filename).resolve()
    if not str(fp).startswith(str(media_dir) + "/") or not fp.is_file():
        return ok({"error": "文件不存在"})
    return FileResponse(str(fp))


@router.put("/materials/{material_id}")
async def update_material(material_id: str, payload: MaterialPatchIn):
    """更新素材（部分更新：只改传了的字段；发布打点填 published_url）"""
    items = _load()
    for m in items:
        if m.get("id") == material_id:
            if payload.title is not None:
                m["title"] = payload.title.strip() or m.get("title", "")
            if payload.content is not None:
                m["content"] = payload.content
            if payload.source_type is not None:
                m["source_type"] = payload.source_type
            if payload.coverage_questions is not None:
                m["coverage_questions"] = payload.coverage_questions
            if payload.published_at is not None:
                m["published_at"] = payload.published_at
            if payload.published_url is not None:
                m["published_url"] = payload.published_url
            m["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save(items)
            return ok({"item": m})
    return ok({"error": "素材不存在"})


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str):
    items = [i for i in _load() if i.get("id") != material_id]
    _save(items)
    # 修复（审计 H5）：级联清理 Qdrant/内存向量，避免孤儿点残留
    from services.embed import delete_vectors

    qdrant_cleaned = await delete_vectors(material_id)
    return ok({"deleted": material_id, "vectors_cleaned": qdrant_cleaned})
