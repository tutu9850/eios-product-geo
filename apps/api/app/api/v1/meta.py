"""元信息：引擎配置状态 + 连通性实测"""
from fastapi import APIRouter

from app.core.config import engine_status
from app.core.envelope import ok

router = APIRouter(prefix="/api/v1/meta")


@router.get("/engines")
async def engines():
    from adapters.engines import engine_status

    return ok({"engines": await engine_status()})


@router.post("/engines/{engine_id}/ping")
async def engine_ping(engine_id: str):
    """单引擎连通性实测（P0）"""
    from adapters.engines import ping

    result = await ping(engine_id)
    return ok({"engine": result})
