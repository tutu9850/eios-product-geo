"""Strict Product-owned monitor-run endpoint for the P2 vertical slice."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.envelope import ok
from app.product.runtime.monitor_run import (
    MonitorRunCommand,
    ProductMonitorRunService,
    ProductOperationError,
    ProductRuntimeUnavailable,
)


router = APIRouter(prefix="/api/v2/product/monitor-runs", tags=["geo-product"])


class MonitorRunIn(BaseModel):
    subject_namespace: str = Field(min_length=1, max_length=64)
    subject_type: str = Field(min_length=1, max_length=64)
    subject_id: str = Field(min_length=1, max_length=256)
    query: str = Field(min_length=1, max_length=8000)
    source_type: str = "ai_answer"


@router.post("")
async def run_monitor_item(
    payload: MonitorRunIn,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", default=""),
):
    """Run one GEO monitor operation with formal product identity and state."""
    session = getattr(request.state, "product_session", None)
    if session is None:
        raise HTTPException(status_code=503, detail="ProductSession middleware is not active")
    policy = getattr(request.app.state, "product_operation_policy", None)
    provider = getattr(request.app.state, "geo_monitor_provider", None)
    engine = getattr(request.app.state, "product_database_engine", None)
    if policy is None or provider is None or engine is None:
        raise HTTPException(status_code=503, detail="GEO Product runtime dependencies are not configured")
    try:
        result = ProductMonitorRunService(
            engine=engine, policy=policy, provider=provider
        ).execute(
            session=session,
            command=MonitorRunCommand(
                subject_namespace=payload.subject_namespace,
                subject_type=payload.subject_type,
                subject_id=payload.subject_id,
                query=payload.query,
                source_type=payload.source_type,
                idempotency_key=idempotency_key,
            ),
        )
    except ProductOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    return ok(
        {
            "task_id": result.task_id,
            "run_id": result.run_id,
            "observation_id": result.observation_id,
            "trace_ref": result.trace_ref,
            "replayed": result.replayed,
        }
    )
