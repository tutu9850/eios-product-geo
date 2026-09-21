"""Intelligence 分析引擎 — 字段级表数据访问层

原则：
- 只碰 5 张字段级表（geo_evidence / geo_extraction / brand_mention /
  geo_insight_reports / geo_dimension_synonyms），不碰 10 张通用表。
- 幂等键：(tenant_id, source_type, parent_ref) 唯一，命中即跳过。
- extraction 版本：同一 evidence 重跑 insert 新 version，查最新用
  ORDER BY version DESC LIMIT 1（外部评审钉死）。
- 分析结论永不写 企业知识库（本模块禁 import write_candidate）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.geo_models import (
    BrandMention,
    GeoDimensionSynonyms,
    GeoEvidence,
    GeoExtraction,
    GeoInsightReports,
    SessionLocal,
    init_db,
)

from services._db import current_tenant_or_default

DEFAULT_TENANT = "tenant_corp_01"


def _resolve_tenant(tenant: str | None) -> str:
    """没显式传租户时用**当前请求的柜**（账号分柜，Owner 2026-09-22）。

    显式传进来的租户一律照用 —— 脚本和后台任务靠这个跑指定柜，不能被悄悄改道。
    """
    return tenant or current_tenant_or_default()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def init_tables() -> None:
    """启动时幂等建表（含新 5 表）。"""
    init_db()


# ── geo_evidence ────────────────────────────────────────────────────────────


def upsert_evidence(ev: dict) -> tuple[dict, bool]:
    """幂等写入统一原文；命中幂等键返回 (已有行, False)，否则 (新行, True)。"""
    init_tables()
    with SessionLocal() as db:
        existing = (
            db.query(GeoEvidence)
            .filter(
                GeoEvidence.tenant_id == ev.get("tenant_id", DEFAULT_TENANT),
                GeoEvidence.source_type == ev.get("source_type", "ai_answer"),
                GeoEvidence.parent_ref == ev["parent_ref"],
            )
            .first()
        )
        if existing:
            return _row_to_dict(existing), False
        row = GeoEvidence(
            id=ev.get("id") or _new_id("ev"),
            source_type=ev.get("source_type", "ai_answer"),
            platform=ev.get("platform"),
            url=ev.get("url"),
            subject_company=ev.get("subject_company", ""),
            raw_text=ev["raw_text"],
            context_json=json.dumps(ev.get("context_json") or {}, ensure_ascii=False),
            parent_ref=ev["parent_ref"],
            observed_at=ev.get("observed_at") or _now(),
            tenant_id=ev.get("tenant_id", DEFAULT_TENANT),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row), True


def get_evidence(evidence_id: str, tenant_id: str | None = None) -> dict | None:
    tenant_id = _resolve_tenant(tenant_id)
    with SessionLocal() as db:
        row = (
            db.query(GeoEvidence)
            .filter(GeoEvidence.id == evidence_id, GeoEvidence.tenant_id == tenant_id)
            .first()
        )
        return _row_to_dict(row) if row else None


def list_evidence_pending(tenant_id: str | None = None) -> list[dict]:
    """无 succeeded extraction 的 evidence（启动重扫 / 补跑用）。

    排除最新为 failed 的：失败需手动指定重跑，避免 recover 死循环烧 token。
    """
    tenant_id = _resolve_tenant(tenant_id)
    init_tables()
    with SessionLocal() as db:
        # 每 evidence 取最新版本（row_number 窗口，多版本时 DISTINCT(evidence_id,status) 会带出旧行）
        latest = (
            db.query(
                GeoExtraction.evidence_id,
                GeoExtraction.status,
                func.row_number()
                .over(partition_by=GeoExtraction.evidence_id, order_by=GeoExtraction.version.desc())
                .label("rn"),
            )
            .subquery()
        )
        rows = (
            db.query(GeoEvidence)
            .filter(GeoEvidence.tenant_id == tenant_id)
            .outerjoin(latest, (GeoEvidence.id == latest.c.evidence_id) & (latest.c.rn == 1))
            .filter(
                # 无解析记录，或最新状态是 pending/running（可重跑）；succeeded/failed 不捡
                (latest.c.evidence_id.is_(None))
                | ((latest.c.status != "succeeded") & (latest.c.status != "failed"))
            )
            .order_by(GeoEvidence.observed_at.asc())
            .all()
        )
        return [_row_to_dict(r) for r in rows]


# ── geo_extraction ──────────────────────────────────────────────────────────


def insert_extraction(rec: dict) -> dict:
    """插入一条 extraction（调用方负责递增 version）。"""
    init_tables()
    now = _now()
    with SessionLocal() as db:
        row = GeoExtraction(
            id=rec.get("id") or _new_id("ex"),
            evidence_id=rec["evidence_id"],
            source_type=rec.get("source_type", "ai_answer"),
            subject_company=rec.get("subject_company", ""),
            status=rec.get("status", "pending"),
            model=rec.get("model"),
            analysis_json=json.dumps(rec["analysis_json"], ensure_ascii=False) if rec.get("analysis_json") else None,
            error=rec.get("error"),
            version=rec.get("version", 1),
            question=rec.get("question"),
            engine=rec.get("engine"),
            monitor_id=rec.get("monitor_id"),
            created_at=rec.get("created_at") or now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)


def latest_extraction(evidence_id: str) -> dict | None:
    """查最新版本（ORDER BY version DESC LIMIT 1，评审钉死）。"""
    with SessionLocal() as db:
        row = (
            db.query(GeoExtraction)
            .filter(GeoExtraction.evidence_id == evidence_id)
            .order_by(GeoExtraction.version.desc())
            .first()
        )
        return _row_to_dict(row) if row else None


def next_version(evidence_id: str) -> int:
    with SessionLocal() as db:
        row = (
            db.query(GeoExtraction)
            .filter(GeoExtraction.evidence_id == evidence_id)
            .order_by(GeoExtraction.version.desc())
            .first()
        )
        return (row.version + 1) if row else 1


def update_extraction(row_id: str, **fields: Any) -> dict | None:
    """按 id 更新一行（同一次解析内 running → succeeded/failed 走 update，不占新 version）。"""
    init_tables()
    allowed = {"status", "model", "analysis_json", "error", "updated_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "analysis_json" in updates and updates["analysis_json"] is not None and not isinstance(updates["analysis_json"], str):
        updates["analysis_json"] = json.dumps(updates["analysis_json"], ensure_ascii=False)
    with SessionLocal() as db:
        row = db.query(GeoExtraction).filter(GeoExtraction.id == row_id).first()
        if not row:
            return None
        for k, v in updates.items():
            setattr(row, k, v)
        row.updated_at = _now()
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)


# ── brand_mention ───────────────────────────────────────────────────────────


def insert_mentions(mentions: list[dict]) -> int:
    """展开写品牌↔原话明细；缺 evidence_quote 的行丢弃（铁律 2）。

    幂等（2026-08-15 修复）：同一 analysis 先清旧 mentions 再插——
    重试/重跑（update_extraction 失败后重试）不再产生重复提及，聚合计数不虚高。
    """
    init_tables()
    if not mentions:
        return 0
    n = 0
    now = _now()
    analysis_id = (mentions[0].get("analysis_id") or mentions[0].get("evidence_id") or "")
    with SessionLocal() as db:
        if analysis_id:
            db.query(BrandMention).filter(
                BrandMention.analysis_id == analysis_id
            ).delete(synchronize_session=False)
        for m in mentions:
            quote = (m.get("evidence_quote") or "").strip()
            if not quote:
                continue  # 无原话不展开入库
            factor = (m.get("factor") or "").strip() or "__missing__"
            db.add(
                BrandMention(
                    id=_new_id("bm"),
                    evidence_id=m["evidence_id"],
                    analysis_id=m.get("analysis_id") or m["evidence_id"],
                    brand_name=(m.get("brand_name") or "").strip() or "unknown",
                    mention_type=m.get("mention_type", "reason"),
                    factor=factor,
                    evidence_quote=quote[:500],
                    confidence=m.get("confidence"),
                    created_at=now,
                )
            )
            n += 1
        db.commit()
    return n


def list_mentions(evidence_id: str | None = None, brand_name: str | None = None, tenant_id: str | None = None) -> list[dict]:
    tenant_id = _resolve_tenant(tenant_id)
    with SessionLocal() as db:
        q = db.query(BrandMention)
        if evidence_id:
            q = q.filter(BrandMention.evidence_id == evidence_id)
        if brand_name:
            q = q.filter(BrandMention.brand_name == brand_name)
        rows = q.order_by(BrandMention.created_at.asc()).limit(5000).all()
        return [_row_to_dict(r) for r in rows]


# ── 报告 / 同义词（S2 / 聚合层预留） ────────────────────────────────────────


def insert_report(rec: dict) -> dict:
    init_tables()
    with SessionLocal() as db:
        row = GeoInsightReports(
            id=rec.get("id") or _new_id("rp"),
            company_name=rec["company_name"],
            period_start=rec["period_start"],
            period_end=rec["period_end"],
            report_json=json.dumps(rec["report_json"], ensure_ascii=False),
            model=rec.get("model"),
            prompt_version=rec.get("prompt_version"),
            schema_version=rec.get("schema_version", "1.0"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)


def latest_report(company_name: str | None = None) -> dict | None:
    """最新报告；company_name 为空时取全局最新一份。"""
    with SessionLocal() as db:
        q = db.query(GeoInsightReports)
        if company_name:
            q = q.filter(GeoInsightReports.company_name == company_name)
        row = q.order_by(GeoInsightReports.created_at.desc()).first()
        return _row_to_dict(row) if row else None


def list_synonyms(tenant_id: str | None = None) -> dict[str, str]:
    """alias → canonical 映射（聚合层合并用）。"""
    tenant_id = _resolve_tenant(tenant_id)
    with SessionLocal() as db:
        rows = db.query(GeoDimensionSynonyms).all()
        return {r.alias: r.canonical for r in rows}


def add_synonym(canonical: str, alias: str) -> bool:
    init_tables()
    with SessionLocal() as db:
        exists = db.query(GeoDimensionSynonyms).filter(GeoDimensionSynonyms.alias == alias).first()
        if exists:
            return False
        db.add(GeoDimensionSynonyms(id=_new_id("sy"), canonical=canonical, alias=alias))
        db.commit()
        return True


# ── 工具 ────────────────────────────────────────────────────────────────────


def _row_to_dict(row: Any) -> dict:
    d: dict = {}
    for col in row.__table__.columns:
        v = getattr(row, col.name)
        if isinstance(v, datetime):
            v = v.isoformat()
        d[col.name] = v
    # JSON 列还原
    if d.get("context_json") and isinstance(d["context_json"], str):
        try:
            d["context_json"] = json.loads(d["context_json"])
        except Exception:  # noqa: BLE001
            pass
    if d.get("analysis_json") and isinstance(d["analysis_json"], str):
        try:
            d["analysis_json"] = json.loads(d["analysis_json"])
        except Exception:  # noqa: BLE001
            pass
    if d.get("report_json") and isinstance(d["report_json"], str):
        try:
            d["report_json"] = json.loads(d["report_json"])
        except Exception:  # noqa: BLE001
            pass
    return d
