"""健康检查"""
from fastapi import APIRouter

from app.core.envelope import ok

# prefix /api/v1：与 monitor 等 router 统一前缀（Builder 代理 GEO_BASE_URL 含 /api/v1）
router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def health():
    return ok({"status": "ok", "service": "eios-geo", "version": "0.1.0"})
