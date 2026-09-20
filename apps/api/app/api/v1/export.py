"""EIOS 导出（P0 stub，P3 实现）"""
from fastapi import APIRouter

from app.core.envelope import ok

router = APIRouter(prefix="/api/v1/eios")


@router.get("/export/knowledge-index")
async def export_knowledge_index():
    """seed.knowledge.json 兼容索引导出（非全文，P3）"""
    return ok({"index": []}, stage="p0")  # TODO(P3)
