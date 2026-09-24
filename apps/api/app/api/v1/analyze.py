"""诊断与分析（P0 stub，P2 实现）"""
from fastapi import APIRouter

from fastapi.responses import JSONResponse

from app.core.envelope import err

router = APIRouter(prefix="/api/v1/analyze")


@router.post("/diagnose")
async def diagnose():
    """官网诊断（异步，P2）"""
    return JSONResponse(status_code=501, content=err("feature_not_implemented", "官网诊断报告接口尚未启用", stage="p2"))


@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    """诊断报告（P2）"""
    return JSONResponse(status_code=501, content=err("feature_not_implemented", "诊断报告接口尚未启用", stage="p2"))
