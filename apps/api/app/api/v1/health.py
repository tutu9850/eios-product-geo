"""健康检查"""
import os

from fastapi import APIRouter

from app.core.envelope import ok

# prefix /api/v1：与 monitor 等 router 统一前缀（Builder 代理 GEO_BASE_URL 含 /api/v1）
router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def health():
    from app.product.http_auth import auth_mode, product_storage_ready

    return ok({
        "status": "ok",
        "service": "eios-geo",
        "version": "0.1.0",
        "runtime_mode": os.environ.get("GEO_RUNTIME_MODE", "normal"),
        "auth_mode": auth_mode(),
        "storage_mode": "postgres" if product_storage_ready() else "legacy",
    })
