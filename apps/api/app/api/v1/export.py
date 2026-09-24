"""EIOS 导出（P0 stub，P3 实现）"""
from fastapi import APIRouter

from fastapi.responses import JSONResponse

from app.core.envelope import err

router = APIRouter(prefix="/api/v1/eios")


@router.get("/export/knowledge-index")
async def export_knowledge_index():
    """seed.knowledge.json 兼容索引导出（非全文，P3）"""
    return JSONResponse(status_code=501, content=err("feature_not_implemented", "知识索引导出接口尚未启用", stage="p3"))
