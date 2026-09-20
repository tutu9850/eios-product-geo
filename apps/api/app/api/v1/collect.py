"""外部采集（P0 stub，P1 实现）"""
from fastapi import APIRouter

from app.core.envelope import ok

router = APIRouter(prefix="/api/v1/collect")


@router.post("/crawl")
async def crawl():
    """爬取 URL → raw 落盘 storage/raw（P1）"""
    return ok({}, stage="p0")  # TODO(P1)
