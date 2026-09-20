"""关键词拓展（P0 stub，P2 实现）"""
from fastapi import APIRouter

from app.core.envelope import ok

router = APIRouter(prefix="/api/v1/keywords")


@router.post("/expand")
async def expand():
    """拓词（P2）"""
    return ok({}, stage="p0")  # TODO(P2)
