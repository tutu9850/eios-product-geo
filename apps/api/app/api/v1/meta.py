"""元信息：引擎配置状态 + 连通性实测

「配置」在这里只有一件事是产品能说的：这个部署登记了哪些模型（读部署的模型目录）。
凭据在不在企业部署手里，产品看不到 —— 所以这里不再报 configured；能不能通，看 ping 实测。
"""
from fastapi import APIRouter

from app.core.envelope import err, ok

router = APIRouter(prefix="/api/v1/meta")


@router.get("/engines")
async def engines():
    from adapters.engines import EngineFaceError, engine_status

    try:
        return ok({"engines": await engine_status()})
    except EngineFaceError as exc:
        # 原样说清是哪一类：入口没配 / 入口不在 / 权威侧拒绝，各有各的码。
        return err(exc.code, exc.message)


@router.post("/engines/{engine_id}/ping")
async def engine_ping(engine_id: str):
    """单引擎连通性实测（P0）"""
    from adapters.engines import ping

    result = await ping(engine_id)
    return ok({"engine": result})
