"""诊断与分析（P0 stub，P2 实现）"""
from fastapi import APIRouter

from app.core.envelope import ok

router = APIRouter(prefix="/api/v1/analyze")


@router.post("/diagnose")
async def diagnose():
    """官网诊断（异步，P2）"""
    return ok({}, stage="p0")  # TODO(P2)


@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    """诊断报告（P2）"""
    return ok({"id": report_id}, stage="p0")  # TODO(P2)
