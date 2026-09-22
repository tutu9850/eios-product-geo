"""GEO 综合 AI 认知报告：实时聚合当前企业数据并导出 PDF。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import Response

from app.api.v1 import cognition, distill
from app.services.report_pdf import render_live_report_pdf
from app.services.store import get_store

router = APIRouter(prefix="/api/v1/report")


def _data(envelope: dict) -> dict:
    value = envelope.get("data") if isinstance(envelope, dict) else None
    return value if isinstance(value, dict) else {}


def _identity() -> tuple[str, str, list[str]]:
    items = get_store().load("monitor_items")
    company, _aliases = cognition._brand_name_and_aliases()
    products: list[str] = []
    industry = ""
    for item in items:
        cfg = item.get("config_json") or {}
        if not industry:
            industry = str(cfg.get("industry") or "").strip()
        if item.get("type") in {"product", "service"}:
            name = str(item.get("entity") or "").strip()
            if name and name not in products:
                products.append(name)
        configured = cfg.get("product") or []
        if isinstance(configured, str):
            configured = [configured]
        for value in configured:
            name = str(value or "").strip()
            if name and name not in products:
                products.append(name)
    return company or "", industry, products[:10]


@router.get("/export")
async def export_report():
    """导出完整实时报告；当前身份和数据范围由宿主身份门决定。"""
    health = _data(await cognition.health())
    portrait = _data(await cognition.portrait())
    coverage = _data(await cognition.coverage())
    reasons = _data(await cognition.reasons())
    competitors = _data(await cognition.competitors())
    sources = _data(await cognition.sources())
    gaps = _data(await distill.list_gaps(limit=10)).get("items") or []
    plans = _data(await distill.list_plans(status="planned", limit=20, sort="priority")).get("items") or []
    company, industry, products = _identity()
    pdf = render_live_report_pdf({
        "company": company,
        "industry": industry,
        "products": products,
        "health": health,
        "portrait": portrait,
        "coverage": coverage,
        "reasons": reasons,
        "competitors": competitors,
        "sources": sources,
        "gaps": gaps,
        "plans": plans,
        "generated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    })
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=geo-ai-cognition-report.pdf"},
    )
