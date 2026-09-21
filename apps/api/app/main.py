"""EIOS GEO 服务入口（P0 空壳）"""
import os
import sys
from pathlib import Path

# 仓库根（services/ adapters/ 所在）加入 import 路径
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.v1 import (
    analyze,
    battle,
    cognition,
    collect,
    content,
    diagnose,
    distill,
    enterprise_profile,
    export,
    geo_consumer,
    health,
    intelligence,
    kb_init,
    keywords,
    knowledge,
    links,
    market,
    meta,
    monitor,
    onboard,
    stats,
)
from app.api.v2 import product_monitor
from app.core.envelope import err
from app.product.consumer_auth import ConsumerAuthError
from app.product.door import ProductDoorMiddleware
from app.product.http_auth import (
    ProductAuthenticationError,
    auth_context_mode_enabled,
    product_storage_ready,
    resolve_http_product_session,
)
from app.product.session import bind_product_session

app = FastAPI(title="EIOS GEO Service", version="0.1.0", docs_url="/docs", openapi_url="/openapi.json")


@app.middleware("http")
async def _tenant_context(request, call_next):
    """S1 租户隔离（2026-08-19）：从 X-Tenant-Id 头注入当前请求租户（store 层 contextvars 读取）。

    - 无头/非法值 → 默认 tenant_corp_01（兼容存量与旧调用方）
    - 后台任务（scheduler/监测 run）无请求上下文：asyncio.create_task 快照发起时 context，
      从请求发起的任务自动继承租户；独立线程任务需显式传 tenant_id（见各调用点注释）
    """
    if auth_context_mode_enabled():
        try:
            session = await resolve_http_product_session(request)
        except ProductAuthenticationError as exc:
            return JSONResponse(status_code=exc.status_code, content=err(exc.code, exc.message))
        request.state.product_session = session
        # P1 refuses to bind formal identity to the legacy SQLite tenant column.
        # P2 may enable this mode only once product-owned PostgreSQL is live.
        if request.url.path != "/api/v1/health" and not product_storage_ready():
            return JSONResponse(
                status_code=503,
                content=err("PRODUCT_STORAGE_NOT_READY", "product PostgreSQL ownership is not active"),
            )
        with bind_product_session(session):
            return await call_next(request)

    from app.services.store import set_tenant

    set_tenant(request.headers.get("X-Tenant-Id", ""))
    return await call_next(request)


@app.on_event("startup")
async def _startup():
    from app.product.runtime.lifecycle import start_product_database
    from app.runtime.mode import is_baseline_mode

    _compose_consumer_policy()
    start_product_database(app)

    # Baseline mode is intentionally inert: it exists to capture deterministic
    # API/state fixtures without scheduler, recovery worker, or Provider calls.
    if is_baseline_mode():
        print("[main] GEO_RUNTIME_MODE=baseline; scheduler and recovery disabled")
        return

    from services.scheduler import start_scheduler

    try:
        start_scheduler()
    except Exception as exc:  # noqa: BLE001
        print(f"[main] scheduler 启动失败（不影响服务）: {exc}")

    # 统一分析引擎：启动消费者 + 恢复未解析 evidence（冻结 §S1 / 收口红线）
    try:
        from services.intelligence import queue as intel_queue

        intel_queue.bind_main_loop()
        intel_queue.ensure_worker()
        n = await intel_queue.recover_pending()
        print(f"[main] intelligence queue ready, recover_pending={n}")
    except Exception as exc:  # noqa: BLE001
        print(f"[main] intelligence recover 失败（不影响服务）: {exc}")


def _compose_consumer_policy() -> None:
    """只读交接面的策略（Owner 2026-09-21「正式 PDP 声明 geo.knowledge.read」）。

    PDP **只由部署声明决定**（``EIOS_PDP_MODE``，基座 ``configured_policy_decision_point``）：
    ``deployment_reads`` + ``EIOS_PDP_BUSINESS_READERS`` / ``EIOS_PDP_BUSINESS_SCOPES`` 是正式路线；
    没声明（或声明残缺）→ ``FailClosedPolicyDecisionPoint`` → 消费面 503，不会变成空 allow-list。
    dev 的 ``development_allow`` 是显式的本机替身，响应里会如实报成 ``development_allow``。

    组合失败也不许把面留成「没有策略」以外的样子：这里只如实打印，面的判定仍然 fail-closed
    （``consumer_auth`` 对 ``consumer_pdp is None`` 回 503）。
    """
    try:
        from eios_policy import configured_policy_decision_point, policy_enforcement_mode
    except ImportError as exc:
        print(f"[main] eios_policy 不可用，消费面 fail-closed（503）: {exc}")
        return
    environment = os.environ.get("EIOS_ENVIRONMENT", "production")
    pdp = configured_policy_decision_point(environment=environment)
    app.state.consumer_pdp = pdp
    app.state.consumer_policy_enforcement = policy_enforcement_mode(pdp)
    print(
        "[main] consumer PDP composed: "
        f"{type(pdp).__name__} enforcement={app.state.consumer_policy_enforcement}"
    )


@app.on_event("shutdown")
async def _shutdown():
    from app.product.runtime.lifecycle import stop_product_database
    from app.runtime.mode import is_baseline_mode

    stop_product_database(app)

    if is_baseline_mode():
        return

    from services.scheduler import shutdown_scheduler

    shutdown_scheduler()

# v1 路由（prefix 已在各 router 定义）
for r in (health.router, meta.router, monitor.router, collect.router,
          analyze.router, keywords.router, content.router, knowledge.router,
          distill.router, links.router, stats.router, battle.router,
          diagnose.router, export.router, market.router, onboard.router,
          cognition.router,
          intelligence.router, enterprise_profile.router,
          # 内测：从企业知识库初始化「本公司资料」（Owner 2026-09-21）。
          kb_init.router):
    app.include_router(r)

# 只读交接面（Owner 2026-09-20）：别的产品（顾问）按验签过的 AuthContext 读 GEO 自己的库。
# 它自带身份门（app.product.consumer_auth），不等于 GEO 自己的产品门，也不受
# GEO_PRODUCT_DOOR / GEO_AUTH_MODE 影响 —— 关掉产品门不会把这个面一起关掉，反之亦然。
app.include_router(geo_consumer.router)

# V2 is a product-owned strict path.  It has no legacy Store, tenant header,
# or Kernel dependency, and only works in auth_context + postgres mode.
app.include_router(product_monitor.router)


@app.exception_handler(ConsumerAuthError)
async def consumer_auth_failed(_request, exc: ConsumerAuthError):
    """消费方的身份问题按它自己的状态码回答，不伪装成 500。"""
    return JSONResponse(status_code=exc.status_code, content=err(exc.code, exc.message))


@app.exception_handler(Exception)
async def unhandled(_request, _exc):
    return JSONResponse(status_code=500, content=err("internal_error", "服务内部错误"))


# 产品门（2026-09-20 GEO-01B）：把冻结的 /api/product/geo/* 映射到既有 v1 use case。
# 默认关闭，只有 GEO_PRODUCT_DOOR=on 的部署才暴露该命名空间。
# 必须最后 add 才会成为最外层 middleware：先把 EIOS-Auth-Context 归一化成 bearer、
# 再重写路径；之后 _tenant_context、路由与异常处理器看到的请求与旧链完全一致。
app.add_middleware(ProductDoorMiddleware)
