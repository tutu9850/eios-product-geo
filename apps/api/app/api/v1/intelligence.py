"""EIOS 统一分析引擎（Intelligence）— V1 路由

冻结方案 §七；S0 范围：analyze（触发/回填）+ analyses（条级查询）。
matrix / perception / reports 属 S1/S2，不提前实现。
Builder 访问：/api/geo/api/v1/intelligence/*（代理剥 /api/geo 前缀 → 3002）。
"""
import json

from fastapi import APIRouter, Body
from pydantic import BaseModel

from app.core.envelope import err, ok

from services.intelligence import adapter, aggregator, cognition, harvest, queue, reasoning, repo

router = APIRouter(prefix="/api/v1/intelligence")

# reports/run 限流：5 分钟内只跑一次（防误触烧 token）
_last_run_ts: float = 0.0
RUN_COOLDOWN_SECONDS = 300


class AnalyzeIn(BaseModel):
    evidence_ids: list[str] | None = None  # 指定补跑
    answer_ids: list[str] | None = None  # 兼容别名
    monitor_id: str | None = None  # 按监测对象补跑
    since: str | None = None  # ISO 时间过滤
    limit: int | None = 20  # 新入库上限（默认 20）


class HarvestSearchIn(BaseModel):
    company: str
    keywords: list[str]
    platform: str | None = "sogou"  # sogou|baidu|weibo
    max_per_keyword: int | None = 10


@router.post("/analyze")
def analyze(payload: AnalyzeIn | None = None):
    """手动触发解析：指定 evidence_ids，或从监测历史回填（monitor_id/since/limit）。"""
    payload = payload or AnalyzeIn()

    ids = payload.evidence_ids or payload.answer_ids
    if ids:
        n = 0
        for eid in ids:
            # 幂等 upsert 不存在则跳过；已存在的直接入队重跑（升 version）
            ev = repo.get_evidence(eid)
            if ev:
                queue.enqueue(eid)
                n += 1
        return ok({"enqueued": n, "from": "evidence_ids"})

    result = adapter.ingest_from_history(
        monitor_id=payload.monitor_id,
        since=payload.since,
        limit=payload.limit,
        enqueue_parsing=True,
    )
    return ok(result)


@router.get("/analyses")
def analyses(evidence_id: str | None = None, answer_id: str | None = None):
    """条级解析结果（兼容 answer_id 别名）。"""
    eid = evidence_id or answer_id
    if not eid:
        return err("missing_evidence_id", "缺少 evidence_id / answer_id")
    ext = repo.latest_extraction(eid)
    if not ext:
        return ok({"evidence_id": eid, "status": "not_found"})
    mentions = repo.list_mentions(evidence_id=eid)
    return ok(
        {
            "evidence_id": eid,
            "status": ext.get("status"),
            "version": ext.get("version"),
            "model": ext.get("model"),
            "error": ext.get("error"),
            "analysis": ext.get("analysis_json"),
            "mentions": mentions,
        }
    )


@router.get("/sov")
def sov(company: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """SOV 声量份额（汇报第一指标）：品牌 vs 竞品在 AI 推荐中的 % 份额 + 趋势。"""
    return ok(aggregator.share_of_voice(company=company, days=days, source_type=source_type))


@router.get("/trend-delta")
def trend_delta(company: str | None = None, days: int = 60, source_type: str = "ai_answer"):
    """推荐率趋势变化：相邻周期（7 天）品牌推荐 gained/lost/rising/falling。"""
    return ok(aggregator.trend_delta(company=company, days=days, source_type=source_type))


@router.get("/overview")
def overview(company: str | None = None, days: int = 30, source_type: str = "ai_answer", mode: str = "comparison"):
    """品牌提及概览：我方 vs 竞品提及率%。mode=comparison 只统计推荐/对比类回答（公平分母，对外看板默认）。"""
    return ok(aggregator.brand_overview(company=company, days=days, source_type=source_type, mode=mode))


@router.get("/keywords")
def keywords(company: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """必备关键词：高频维度按提及数排序。"""
    return ok({"keywords": aggregator.keywords(company=company, days=days, source_type=source_type)})


@router.get("/humanize")
def humanize(company: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """商业化翻译层：一句话结论 + 三数字 + 左右列 + 行动清单（人话版）。"""
    return ok(cognition.humanize(company=company, days=days, source_type=source_type))


@router.get("/factor-gaps")
def factor_gaps(company: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """因子级左右对比：竞品有·我方无（left，要补）vs 我方有·竞品无（right，优势）vs both。"""
    return ok(cognition.factor_gaps(company=company, days=days, source_type=source_type))


@router.get("/gap-analysis")
def gap_analysis(company: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """知识缺口两种分离：Knowledge Gap（补知识库/放弃）vs Evidence Gap（发内容）。"""
    return ok(cognition.gap_analysis(company=company, days=days, source_type=source_type))


@router.get("/strategies")
def strategies(company: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """内容策略（GEO Action Score）：需求×差距×可改变性×证据强度×竞争重要性，纯规则无 LLM。"""
    return ok(cognition.strategies(company=company, days=days, source_type=source_type))


@router.get("/evidence")
def evidence(factor: str, company: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """证据链：某因子的全部原话 + 传播强度 + 关联因子。"""
    if not factor:
        return err("missing_factor")
    return ok(cognition.evidence_chain(factor=factor, company=company, days=days, source_type=source_type))


@router.get("/compare")
def compare(company: str | None = None, days: int = 30, source_type: str = "ai_answer", min_level: str = "mention"):
    """认知总表（方案 V2）：维度 × 主体 × 认知层级 × 认知状态 + 证据引用。min_level=recommended 只看被推荐层级。"""
    return ok(cognition.compare(company=company, days=days, source_type=source_type, min_level=min_level))


@router.get("/matrix")
def matrix(company: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """差距矩阵（S1 聚合，无 LLM）：维度榜 + 三色 + 观察区。gap_type 留 S2。"""
    return ok(aggregator.matrix(company=company, days=days, source_type=source_type))


@router.get("/perception")
def perception(company: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """认知标签分布（S1 聚合，无 LLM）。"""
    return ok(aggregator.perception(company=company, days=days, source_type=source_type))


@router.get("/reports/latest")
def reports_latest(company: str | None = None):
    """最新周期报告。company 空则取全局最新；指定公司名则精确匹配 company_name。"""
    rec = repo.latest_report(company_name=company if company else None)
    if not rec:
        return ok({"company": company, "report": None})
    rj = rec.get("report_json")
    if isinstance(rj, str):
        try:
            rj = json.loads(rj)
        except json.JSONDecodeError:
            pass
    return ok({"company": rec.get("company_name"), "created_at": rec.get("created_at"), "report": rj})


def _brand_mention_stats():
    """品牌提及统计：从 brand_mention 表聚合（报告品牌对比表数据源）。"""
    from sqlalchemy import func as _func
    from app.models.geo_models import SessionLocal, BrandMention

    with SessionLocal() as db:
        rows = (
            db.query(BrandMention.brand_name, _func.count().label("n"))
            .group_by(BrandMention.brand_name)
            .order_by(_func.count().desc())
            .limit(8)
            .all()
        )
        total = sum(r.n for r in rows) or 1
        return [
            {"brand": r.brand_name, "mention_count": r.n, "share": round(r.n / total * 100, 1)}
            for r in rows
        ]


@router.get("/reports/latest/pdf")
def reports_latest_pdf(company: str | None = None):
    """最新周期报告 PDF 下载（2026-08-15 新增）。无报告 → 404。"""
    from fastapi.responses import Response
    from app.services.report_pdf import render_report_pdf

    rec = repo.latest_report(company or "unknown")
    if not rec:
        return {"ok": False, "error": "暂无报告，请先在报告页生成"}
    # 补充监测历史/问题池/品牌对比（V3 报告章节 02/03/04 数据源）
    from app.services.store import get_store

    history = get_store().load("monitor_history")
    questions = get_store().load("questions")
    brand_stats = _brand_mention_stats()
    trend = aggregator.trend_delta()
    try:
        pdf_bytes = render_report_pdf(
            rec.get("report_json") or {}, rec.get("created_at"),
            history=history, questions=questions, brand_stats=brand_stats, trend=trend,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"PDF 生成失败：{e}"}
    company_name = (rec.get("report_json") or {}).get("company") or company or "企业"
    from urllib.parse import quote

    fname = f"GEO_{company_name}_AI可见性报告.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        # RFC 5987：中文文件名需 filename*（HTTP 头 latin-1 不能直接带中文）
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


@router.post("/reports/run")
async def reports_run(
    company: str | None = None,
    days: int = 30,
    payload: dict | None = Body(default=None),
):
    """触发 Reasoning 生成报告（限流 5 分钟一次）。

    company/days 支持 query；若 Builder 传 JSON body 也接受（兼容）。
    """
    global _last_run_ts
    import time

    body = payload or {}
    if isinstance(body, dict):
        company = company or body.get("company")
        if body.get("days") is not None:
            days = int(body.get("days") or days)

    now_ts = time.time()
    if now_ts - _last_run_ts < RUN_COOLDOWN_SECONDS:
        return ok({"skipped": "rate_limited", "cooldown_seconds": RUN_COOLDOWN_SECONDS})
    _last_run_ts = now_ts
    report = await reasoning.generate_report(company=company, days=days)
    return ok(
        {
            "generated": True,
            "company": company,
            "dimensions": len(report.get("gap_matrix") or []),
            "actions": len(report.get("actions") or []),
        }
    )


@router.post("/recover")
async def recover():
    """启动恢复：无 succeeded extraction 的 evidence 重新入队（幂等）。"""
    n = await queue.recover_pending()
    return ok({"recovered": n})


@router.post("/harvest/search")
async def harvest_search(payload: HarvestSearchIn):
    """Phase A：外网补搜（WebSearch Harvest）。采集成功不依赖 LLM。"""
    try:
        summary = await harvest.start_search_harvest(
            company=payload.company,
            keywords=payload.keywords,
            platform=payload.platform or "sogou",
            max_per_keyword=payload.max_per_keyword or 10,
        )
        return ok(summary)
    except ValueError as exc:
        return err("bad_request", str(exc))
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("rate_limited:"):
            sec = int(msg.split(":", 1)[1])
            return ok({"skipped": "rate_limited", "cooldown_seconds": sec})
        return err("harvest_failed", msg)


@router.get("/harvest/runs/{run_id}")
def harvest_run_status(run_id: str):
    """补搜 run 状态（采集态，与解析成功与否无关）。"""
    run = harvest.get_run(run_id)
    if not run:
        return err("not_found", f"run 不存在: {run_id}")
    return ok(run)


@router.get("/stats")
def stats():
    """分析引擎状态（S0 用）：各表计数。"""
    from sqlalchemy import func

    from app.models.geo_models import BrandMention, GeoEvidence, GeoExtraction, SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        counts = {
            "evidence": db.query(func.count(GeoEvidence.id)).scalar() or 0,
            "extraction": db.query(func.count(GeoExtraction.id)).scalar() or 0,
            "succeeded": db.query(func.count(GeoExtraction.id)).filter(GeoExtraction.status == "succeeded").scalar() or 0,
            "failed": db.query(func.count(GeoExtraction.id)).filter(GeoExtraction.status == "failed").scalar() or 0,
            "mentions": db.query(func.count(BrandMention.id)).scalar() or 0,
            "research_harvest": db.query(func.count(GeoEvidence.id))
            .filter(GeoEvidence.source_type == "research_harvest")
            .scalar()
            or 0,
        }
    return ok(counts)
