"""GEO 统一存储层（2026-08-07：JSON 文件库 → SQLite 兼容层）

设计：对上层保持原 `_load()/list` 与 `_save(items)` 语义，
底层换 SQLite 表（事务原子写）。各模块只改 _load_/_save_ 函数体，
业务逻辑零改动。表结构见 models/geo_models.py（data_json 原样存记录）。
"""
import hashlib
import json
import logging
import uuid
import re
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.geo_models import (
    SessionLocal,
    TABLES,
    init_db,
)

logger = logging.getLogger("eios.geo.store")

# ── S1 租户上下文（2026-08-19）：中间件从 X-Tenant-Id 头注入，路由层零改动 ──
_tenant_var: ContextVar[str] = ContextVar("geo_tenant_id", default="tenant_corp_01")
_TENANT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def current_tenant() -> str:
    """当前请求的租户（默认 tenant_corp_01 兼容存量）。"""
    return _tenant_var.get()


def normalize_tenant(tenant_id: str | None) -> str:
    """部门名 → 柜号。ASCII 原样；中文等非法头稳定哈希为 dept_<16hex>，不丢进默认柜。

    与 yayu BFF geoTenantId 同算法（sha256 utf-8 前 16 hex）。空值才回落 tenant_corp_01。
    """
    t = (tenant_id or "").strip()
    if not t:
        return "tenant_corp_01"
    if _TENANT_RE.match(t):
        return t
    digest = hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]
    return f"dept_{digest}"


def set_tenant(tenant_id: str) -> str:
    """注入租户（中间件调用）。空头回落默认；中文部门名哈希，不再并进默认柜。"""
    t = normalize_tenant(tenant_id)
    _tenant_var.set(t)
    return t


def list_tenant_ids() -> list[str]:
    """库里出现过的 GEO 柜号（调度器按柜跑，避免只扫默认柜）。"""
    init_db()
    found: set[str] = set()
    db = SessionLocal()
    try:
        for model in TABLES.values():
            if not hasattr(model, "tenant_id"):
                continue
            for (tid,) in db.query(model.tenant_id).distinct().all():
                if tid:
                    found.add(str(tid))
    finally:
        db.close()
    return sorted(found)


# ── S1 热表拆列：data_json 同步到专用列（查询/约束走列，旧行列 NULL 由 data_json 兜底）──
HOT_COLUMNS: dict[str, dict[str, str]] = {
    "questions": {"question": "question", "priority": "priority", "validated": "validated"},
    "gaps": {"question": "question", "missing_information": "missing_information"},
    "content_plans": {"topic": "topic", "status": "status", "priority": "priority"},
    "monitor_items": {"monitor_id": "monitor_id", "type": "type", "status": "status"},
    "monitor_tasks": {"task_id": "task_id", "status": "status", "schedule": "schedule"},
    "kb": {"title": "title", "source": "source"},
}


def _hot_kwargs(table: str, payload: dict) -> dict:
    """从 data_json 负载提取热表列值（只映射存在且类型可转换的键）。"""
    out: dict = {}
    for col, key in HOT_COLUMNS.get(table, {}).items():
        if key not in payload:
            continue
        v = payload[key]
        if v is None:
            continue
        if col in ("priority", "validated") and not isinstance(v, (int, float, bool)):
            continue
        if isinstance(v, (dict, list)):
            continue
        out[col] = v
    return out


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """通用记录存取：table 名见 TABLES（questions/gaps/content_plans/...）。"""

    def __init__(self, db: Session):
        self.db = db

    def load(self, table: str, tenant_id: str | None = None) -> list[dict]:
        tenant_id = tenant_id or current_tenant()
        model = TABLES.get(table)
        if model is None:
            return []
        rows = (
            self.db.query(model)
            .filter(model.tenant_id == tenant_id)
            .order_by(model.created_at.asc())
            .all()
        )
        out = []
        for r in rows:
            try:
                d = json.loads(r.data_json or "{}")
            except Exception:
                d = {}
            d.setdefault("id", r.id)
            out.append(d)
        return out

    def save(self, table: str, items: list[dict], tenant_id: str | None = None) -> None:
        """整表替换（单事务原子）：删除该租户全部行 → 插入新行。
        与原 JSON 整文件写回语义一致，但具备事务性。

        审计 B10：整表替换会把**所有行**的 created_at 刷成同一时刻，
        于是「最新 N 条」的排序实际上依赖 SQLite 行序，不是设计保证。
        这里按 id 保留已存在行的原始 created_at（JSON 负载与列值都保留），
        只有真正的新行才写当前时刻。
        """
        tenant_id = tenant_id or current_tenant()
        model = TABLES.get(table)
        if model is None:
            return
        now = datetime.now(timezone.utc)
        keep_created: dict[str, tuple[object, object]] = {}
        for r in (
            self.db.query(model.id, model.data_json, model.created_at)
            .filter(model.tenant_id == tenant_id)
            .all()
        ):
            try:
                d = json.loads(r.data_json or "{}")
            except Exception:
                d = {}
            keep_created[r.id] = (d.get("created_at"), r.created_at)
        self.db.query(model).filter(model.tenant_id == tenant_id).delete(
            synchronize_session=False
        )
        for it in items:
            row_id = it.get("id") or _new_id(table)
            payload = dict(it)
            payload.pop("id", None)
            # The write scope is selected by the trusted call context (or an
            # explicit internal argument), never by a record supplied from an
            # HTTP payload. Retain no tenant field inside the JSON body either:
            # it is legacy authority metadata, not product data.
            payload.pop("tenant_id", None)
            prev_json_created, prev_col_created = keep_created.get(row_id, (None, None))
            if prev_json_created and not payload.get("created_at"):
                payload["created_at"] = prev_json_created
            row = model(
                id=row_id,
                data_json=json.dumps(payload, ensure_ascii=False),
                tenant_id=tenant_id,
                created_at=prev_col_created or now,
            )
            for col, v in _hot_kwargs(table, payload).items():
                setattr(row, col, v)
            self.db.add(row)
        self.db.commit()

    def insert(self, table: str, item: dict, tenant_id: str | None = None) -> dict:
        """追加单条（不整表替换）。"""
        tenant_id = tenant_id or current_tenant()
        model = TABLES.get(table)
        if model is None:
            return item
        row_id = item.get("id") or _new_id(table)
        payload = dict(item)
        payload.pop("id", None)
        payload.pop("tenant_id", None)
        row = model(
            id=row_id,
            data_json=json.dumps(payload, ensure_ascii=False),
            tenant_id=tenant_id,
            created_at=datetime.now(timezone.utc),
        )
        for col, v in _hot_kwargs(table, payload).items():
            setattr(row, col, v)
        self.db.add(row)
        self.db.commit()
        out = dict(item)
        out["id"] = row_id
        return out

    def update(self, table: str, item_id: str, patch: dict, tenant_id: str | None = None) -> dict | None:
        """按 id 更新单行 data_json（合并 patch，保留原 created_at）。

        修复（审计 H2）：原整表 save() 会把全表 created_at 刷成同一时刻，
        趋势/排序时间戳失真。更新单行时用本方法，不动其他行。
        """
        tenant_id = tenant_id or current_tenant()
        model = TABLES.get(table)
        if model is None:
            return None
        row = (
            self.db.query(model)
            .filter(model.id == item_id, model.tenant_id == tenant_id)
            .first()
        )
        if row is None:
            return None
        try:
            d = json.loads(row.data_json or "{}")
        except Exception:
            d = {}
        d.update(patch)
        d.pop("id", None)
        row.data_json = json.dumps(d, ensure_ascii=False)
        for col, v in _hot_kwargs(table, patch).items():
            setattr(row, col, v)
        self.db.commit()
        out = dict(d)
        out["id"] = item_id
        return out

    def delete(self, table: str, item_id: str, tenant_id: str | None = None) -> bool:
        tenant_id = tenant_id or current_tenant()
        model = TABLES.get(table)
        if model is None:
            return False
        n = (
            self.db.query(model)
            .filter(model.id == item_id, model.tenant_id == tenant_id)
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return n > 0


def get_store() -> Store:
    init_db()
    return Store(SessionLocal())


def reset_all(tenant_id: str = "tenant_corp_01") -> dict[str, int]:
    """重置 GEO 数据库：清空全部业务表（保留表结构）+ 解析层仅清 GEO 来源（ai_answer）。

    供「重置 GEO 数据」按钮使用——删除所有客户生成/添加的内容（问题池/缺口/
    计划/监测历史/内容资产/关注/采集/链接/媒体记录），恢复出厂状态。
    解析层按来源粒度清理：只删 GEO 监测来源（ai_answer）的 evidence/extraction/mention，
    **其他来源（website/xiaohongshu/comment/video 等）的解析数据保留**；
    周期报告（geo_insight_reports，公司级聚合）V1 全清（无来源标签，未来加 source 字段再按来源）。
    注意：媒体文件与 Qdrant 向量由调用方（reset 接口）一并清理。
    """
    tenant_id = normalize_tenant(tenant_id)
    db = SessionLocal()
    stats: dict[str, int] = {}
    try:
        # ── 1. 业务表（GEO 用户数据）──
        for table, model in TABLES.items():
            n = db.query(model).filter(model.tenant_id == tenant_id).count()
            db.query(model).filter(model.tenant_id == tenant_id).delete(synchronize_session=False)
            stats[table] = n
        # ── 2. 解析层：仅 GEO 来源（ai_answer），其他来源保留 ──
        from app.models.geo_models import GeoEvidence, GeoExtraction, BrandMention, GeoInsightReports

        # 2a. brand_mention：按 evidence 的来源删除（子查询）
        n = db.query(BrandMention).filter(
            BrandMention.evidence_id.in_(
                db.query(GeoEvidence.id).filter(
                    GeoEvidence.source_type == "ai_answer", GeoEvidence.tenant_id == tenant_id
                )
            )
        ).delete(synchronize_session=False)
        stats["brand_mention"] = n
        # 2b. geo_extraction：条级解析
        n = db.query(GeoExtraction).filter(GeoExtraction.source_type == "ai_answer").delete(synchronize_session=False)
        stats["geo_extraction"] = n
        # 2c. geo_evidence：统一原文层（GEO 来源）
        n = db.query(GeoEvidence).filter(
            GeoEvidence.source_type == "ai_answer", GeoEvidence.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        stats["geo_evidence"] = n
        # 2d. geo_insight_reports：公司级聚合报告（V1 全清，未来按来源标签细化）
        n = db.query(GeoInsightReports).delete(synchronize_session=False)
        stats["geo_insight_reports"] = n
        db.commit()
    finally:
        db.close()
    return stats


# ── 迁移：JSON 文件 → SQLite（脚本与启动时均可用）────────────────────────────

MIGRATE_MAP = {
    "geo_questions.json": ("questions", None),        # (文件, 合并目标)
    "geo_question_pool.json": ("questions", None),    # dict 结构 → 特殊处理并入 questions
    "geo_gaps.json": ("gaps", None),
    "geo_content_plans.json": ("content_plans", None),
    "geo_plans.json": ("content_plans", None),        # 空文件并入（无数据）
    "geo_monitor_history.json": ("monitor_history", None),
    "geo_kb.json": ("kb", None),
    "geo_watchlist.json": ("watchlist", None),
    "geo_collect_raw.json": ("collect_raw", None),
    "geo_links.json": ("links", None),
}


def migrate_json_to_db(data_dir, db_path=None, dry_run: bool = False) -> dict:
    """一次性迁移：读 JSON 文件 → 写 SQLite 表。

    - geo_question_pool.json 合并进 questions（每条 pool.questions 为一条记录）
    - geo_plans.json（空）并入 content_plans
    - 返回每表迁移行数（核对用）
    """
    from pathlib import Path

    import sqlalchemy as sa

    if db_path:
        eng = sa.create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        SessionL = sa.orm.sessionmaker(bind=eng)
        from app.models.geo_models import Base as _B

        _B.metadata.create_all(eng)
    else:
        from app.models.geo_models import SessionLocal as SessionL, Base as _B

        init_db()

    result = {}
    data_dir = Path(data_dir)
    db = SessionL()
    # 先聚合（同一表可能来自多个文件——不能逐文件 save，否则整表替换互相覆盖）
    aggregated: dict[str, list[dict]] = {}
    try:
        for fname, (table, _merge) in MIGRATE_MAP.items():
            fp = data_dir / fname
            if not fp.exists():
                result[fname] = "跳过（无文件）"
                continue
            try:
                raw = json.loads(fp.read_text("utf-8"))
            except Exception as e:  # noqa: BLE001
                result[fname] = f"读取失败: {e}"
                continue
            items = raw if isinstance(raw, list) else []
            rows = [dict(i) for i in items if isinstance(i, dict)]
            # 合并 geo_question_pool.json → questions（dict 结构）
            if isinstance(raw, dict) and fname == "geo_question_pool.json":
                rows = [
                    {"question": q, "source": "pool", "company_name": raw.get("company_name")}
                    for q in (raw.get("questions") or [])
                ]
            aggregated.setdefault(table, []).extend(rows)
            result[fname] = f"{len(rows)} 条 → {table}"
        if not dry_run:
            st = Store(db)
            for table, rows in aggregated.items():
                st.save(table, rows)
            db.commit()
    finally:
        db.close()
    return result
