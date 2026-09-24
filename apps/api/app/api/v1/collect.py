"""外部采集（P0 stub，P1 实现）"""
from fastapi import APIRouter

from fastapi.responses import JSONResponse

from app.core.envelope import err

router = APIRouter(prefix="/api/v1/collect")


@router.post("/crawl")
async def crawl():
    """爬取 URL → raw 落盘 storage/raw（P1）"""
    return JSONResponse(status_code=501, content=err("feature_not_implemented", "通用爬取接口尚未启用", stage="p1"))
