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


def _resolve_monitor_company(company: str | None, monitor_id: str | None) -> tuple[str | None, str | None]:
    """Resolve the selected monitor to the company used by the intelligence tables.

    The intelligence aggregators deliberately accept a company name because that is
    their stable storage key.  The product UI, however, selects a MonitorItem.  Keep
    that translation at the route boundary so a multi-brand account cannot silently
    fall back to whichever subject happens to have the most mentions.

    ``all`` is an explicit aggregate scope and therefore remains ``None``.  A concrete
    monitor id must resolve to an active item with a non-empty company/entity name;
    otherwise the request fails closed instead of mixing subjects or guessing one.
    """
    explicit = str(company or "").strip()
    picked = str(monitor_id or "").strip()
    if explicit:
        return explicit, None
    if not picked or picked.lower() == "all":
        return None, None
    try:
        from app.services.store import get_store

        rows = get_store().load("monitor_items")
    except Exception as exc:  # noqa: BLE001
        return None, f"监测主体读取失败：{str(exc)[:120]}"
    row = next((item for item in rows if str(item.get("monitor_id") or "") == picked), None)
    if not row:
        return None, "选中的监测主体不存在或不属于当前账号"
    if str(row.get("status") or "active") in {"deleted", "inactive", "paused", "archived"}:
        return None, "选中的监测主体当前未启用"
    cfg = row.get("config_json") or {}
    resolved = str(cfg.get("company") or row.get("entity") or "").strip()
    if not resolved:
        return None, "选中的监测主体没有可用于分析的企业名称"
    return resolved, None


def _scoped_company(company: str | None, monitor_id: str | None):
    resolved, error = _resolve_monitor_company(company, monitor_id)
    if error:
        return None, err("SUBJECT_SCOPE_INVALID", error)
    return resolved, None


class AnalyzeIn(BaseModel):
    evidence_ids: list[str] | None = None  # 指定补跑
    answer_ids: list[str] | None = None  # 兼容别名
    monitor_id: str | None = None  # 按监测对象补跑
    since: str | None = None  # ISO 时间过滤
    limit: int | None = 20  # 新入库上限（默认 20）
    auto_report: bool = True  # 受控样本解析可显式关闭自动周期报告


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
        auto_report=payload.auto_report,
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
def sov(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """SOV 声量份额（汇报第一指标）：品牌 vs 竞品在 AI 推荐中的 % 份额 + 趋势。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(aggregator.share_of_voice(company=company, days=days, source_type=source_type))


@router.get("/trend-delta")
def trend_delta(company: str | None = None, monitor_id: str | None = None, days: int = 60, source_type: str = "ai_answer"):
    """推荐率趋势变化：相邻周期（7 天）品牌推荐 gained/lost/rising/falling。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(aggregator.trend_delta(company=company, days=days, source_type=source_type))


@router.get("/overview")
def overview(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer", mode: str = "comparison"):
    """品牌提及概览：我方 vs 竞品提及率%。mode=comparison 只统计推荐/对比类回答（公平分母，对外看板默认）。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(aggregator.brand_overview(company=company, days=days, source_type=source_type, mode=mode))


@router.get("/keywords")
def keywords(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """必备关键词：高频维度按提及数排序。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok({"keywords": aggregator.keywords(company=company, days=days, source_type=source_type)})


@router.get("/humanize")
def humanize(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """商业化翻译层：一句话结论 + 三数字 + 左右列 + 行动清单（人话版）。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(cognition.humanize(company=company, days=days, source_type=source_type))


@router.get("/factor-gaps")
def factor_gaps(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """因子级左右对比：竞品有·我方无（left，要补）vs 我方有·竞品无（right，优势）vs both。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(cognition.factor_gaps(company=company, days=days, source_type=source_type))


@router.get("/gap-analysis")
def gap_analysis(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """知识缺口两种分离：Knowledge Gap（补知识库/放弃）vs Evidence Gap（发内容）。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(cognition.gap_analysis(company=company, days=days, source_type=source_type))


@router.get("/strategies")
def strategies(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """内容策略（GEO Action Score）：需求×差距×可改变性×证据强度×竞争重要性，纯规则无 LLM。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(cognition.strategies(company=company, days=days, source_type=source_type))


@router.get("/evidence")
def evidence(factor: str, company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """证据链：某因子的全部原话 + 传播强度 + 关联因子。"""
    if not factor:
        return err("missing_factor")
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(cognition.evidence_chain(factor=factor, company=company, days=days, source_type=source_type))


@router.get("/compare")
def compare(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer", min_level: str = "mention"):
    """认知总表（方案 V2）：维度 × 主体 × 认知层级 × 认知状态 + 证据引用。min_level=recommended 只看被推荐层级。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(cognition.compare(company=company, days=days, source_type=source_type, min_level=min_level))


@router.get("/matrix")
def matrix(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """差距矩阵（S1 聚合，无 LLM）：维度榜 + 三色 + 观察区。gap_type 留 S2。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(aggregator.matrix(company=company, days=days, source_type=source_type))


@router.get("/perception")
def perception(company: str | None = None, monitor_id: str | None = None, days: int = 30, source_type: str = "ai_answer"):
    """认知标签分布（S1 聚合，无 LLM）。"""
    company, failure = _scoped_company(company, monitor_id)
    return failure or ok(aggregator.perception(company=company, days=days, source_type=source_type))


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
async def reports_latest_pdf(company: str | None = None):
    """导出当前实时认知报告。

    保留已经在 Product API 冻结门中的历史路径，但内容改为当前监测、
    认知、竞品、信源、缺口与计划的实时聚合，不再依赖一份历史 report_json。
    ``company`` 仅为旧客户端兼容参数；实际企业身份来自已验证的宿主会话。
    """
    from app.api.v1.report import export_report

    return await export_report()


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
async def recover(
    monitor_id: str | None = None,
    since: str | None = None,
    limit: int | None = None,
    auto_report: bool = True,
):
    """启动恢复：无 succeeded extraction 的 evidence 重新入队（幂等）。

    A concrete monitor scope is resolved before work is queued.  The previous
    no-argument path remains the explicit account-wide recovery used by legacy
    callers; the insight workspace always sends its selected subject (including
    ``all``), so it cannot silently recover another brand's queue.
    """
    picked = str(monitor_id or "").strip()
    if picked and picked.lower() != "all":
        _, failure = _scoped_company(None, picked)
        if failure:
            return failure
        # Re-ingest history without enqueueing, then use the same pending scan
        # for both old evidence and newly discovered rows.  This keeps one queue
        # door and prevents a new row from being queued twice.
        ingested = adapter.ingest_from_history(
            monitor_id=picked,
            since=since,
            limit=limit,
            enqueue_parsing=False,
        )
        n = await queue.recover_pending(
            monitor_id=picked,
            limit=limit,
            auto_report=auto_report,
        )
        return ok({"recovered": n, "monitor_id": picked, "ingested": ingested})
    n = await queue.recover_pending(limit=limit, auto_report=auto_report)
    return ok({"recovered": n, "monitor_id": "all" if picked.lower() == "all" else None})


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
def stats(monitor_id: str | None = None):
    """分析引擎状态（S0 用）：各表计数。"""
    from sqlalchemy import func

    from app.models.geo_models import BrandMention, GeoEvidence, GeoExtraction, SessionLocal, init_db
    from app.services.store import current_tenant

    init_db()
    picked = str(monitor_id or "").strip()
    if picked and picked.lower() != "all":
        _, failure = _scoped_company(None, picked)
        if failure:
            return failure
    with SessionLocal() as db:
        tenant_id = current_tenant()
        evidence_rows = db.query(GeoEvidence).filter(GeoEvidence.tenant_id == tenant_id).all()
        if picked and picked.lower() != "all":
            scoped_evidence = []
            for row in evidence_rows:
                try:
                    context = json.loads(row.context_json or "{}")
                except (TypeError, json.JSONDecodeError):
                    context = {}
                if str(context.get("monitor_id") or "") == picked:
                    scoped_evidence.append(row)
            evidence_rows = scoped_evidence
        evidence_ids = {row.id for row in evidence_rows}
        extraction_rows = db.query(GeoExtraction).filter(GeoExtraction.tenant_id == tenant_id).all()
        if picked and picked.lower() != "all":
            extraction_rows = [row for row in extraction_rows if row.monitor_id == picked or row.evidence_id in evidence_ids]
        mention_count = db.query(func.count(BrandMention.id)).filter(BrandMention.tenant_id == tenant_id)
        if picked and picked.lower() != "all":
            mention_count = mention_count.filter(BrandMention.evidence_id.in_(evidence_ids)) if evidence_ids else None
        counts = {
            "evidence": len(evidence_rows),
            "extraction": len(extraction_rows),
            "succeeded": sum(1 for row in extraction_rows if row.status == "succeeded"),
            "failed": sum(1 for row in extraction_rows if row.status == "failed"),
            "mentions": (mention_count.scalar() if mention_count is not None else 0),
            "research_harvest": sum(1 for row in evidence_rows if row.source_type == "research_harvest"),
        }
    return ok({**counts, "monitor_id": "all" if picked.lower() == "all" else (picked or None)})


@router.get("/progress")
async def progress(monitor_id: str | None = None):
    """认知解析与外网补搜的统一进度，不要求用户拿 run_id 拼接口。"""
    picked = str(monitor_id or "").strip()
    if picked and picked.lower() != "all":
        _, failure = _scoped_company(None, picked)
        if failure:
            return failure
    return ok({
        "parse": await queue.snapshot(monitor_id=None if picked.lower() == "all" else (picked or None)),
        "harvest": harvest.latest_run(),
        "monitor_id": "all" if picked.lower() == "all" else (picked or None),
        "note": "解析进度来自证据解析队列；补搜进度为本进程最近一次外网补搜任务。",
    })
