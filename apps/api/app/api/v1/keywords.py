"""关键词拓展（P0 stub，P2 实现）"""
from fastapi import APIRouter

from fastapi.responses import JSONResponse

from app.core.envelope import err

router = APIRouter(prefix="/api/v1/keywords")


@router.post("/expand")
async def expand():
    """拓词（P2）"""
    return JSONResponse(status_code=501, content=err("feature_not_implemented", "关键词拓展接口尚未启用", stage="p2"))
