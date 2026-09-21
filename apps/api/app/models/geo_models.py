"""GEO 数据库模型（2026-08-07：JSON 文件库 → SQLite）

设计：通用表模式——每条记录原样存 data_json（JSON 兼容层），
表结构提供主键/事务/租户字段；字段级建模待查询需求出现时再拆。
表名对齐原 JSON 文件，迁移零风险。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.core import config

Base = declarative_base()

DB_URL = f"sqlite:///{config.GEO_DB_PATH}"
# :memory: 必须 StaticPool 单连接共享（NullPool 下每连接=独立空库，测试 init_db 建表
# 对 SessionLocal 新连接不可见 → no such table，2026-08-09 实测）；文件 DB 保持 NullPool
engine = create_engine(
    DB_URL,
    poolclass=StaticPool if config.GEO_DB_PATH == ":memory:" else NullPool,
    connect_args={"check_same_thread": False, "timeout": 30},  # busy_timeout 30s：防写锁等待卡死事件循环
)
# WAL 模式已持久化（数据库文件级，重启不丢）；每连接只设 busy_timeout——
# 不再每连接跑 PRAGMA journal_mode（写操作，30 并发新连接抢写锁 → 串行化 6s+，实测）
from sqlalchemy import event

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class GeoRecord(Base):
    """通用记录表：data_json 保存完整业务记录（兼容原 JSON 结构）。"""

    __abstract__ = True

    id = Column(String(128), primary_key=True)
    data_json = Column(Text, nullable=False, default="{}")
    tenant_id = Column(String(64), nullable=False, default="tenant_corp_01", index=True)
    created_at = Column(DateTime, nullable=False, default=now_utc)


class GeoQuestions(GeoRecord):
    __tablename__ = "geo_questions"  # ← geo_questions.json + geo_question_pool.json 合并
    # S1 热表拆列（2026-08-19）：查询/过滤走列，data_json 仍为完整记录源（列缺失旧数据兜底）
    question = Column(String(512), nullable=True, index=True)
    priority = Column(Integer, nullable=True)
    validated = Column(Integer, nullable=True)


class GeoGaps(GeoRecord):
    __tablename__ = "geo_gaps"  # ← geo_gaps.json
    question = Column(String(512), nullable=True, index=True)
    missing_information = Column(String(512), nullable=True)


class GeoContentPlans(GeoRecord):
    __tablename__ = "geo_content_plans"  # ← geo_content_plans.json + geo_plans.json 合并
    topic = Column(String(512), nullable=True, index=True)
    status = Column(String(32), nullable=True, index=True)
    priority = Column(Integer, nullable=True)


class GeoMonitorHistory(GeoRecord):
    __tablename__ = "geo_monitor_history"  # ← geo_monitor_history.json


class GeoMonitorItems(GeoRecord):
    __tablename__ = "geo_monitor_items"  # 0.2：监测对象（MonitorItem）长期身份，status 软删保历史
    monitor_id = Column(String(128), nullable=True, index=True)
    type = Column(String(32), nullable=True)
    status = Column(String(16), nullable=True)


class GeoMonitorTasks(GeoRecord):
    __tablename__ = "geo_monitor_tasks"  # 0.3：监测任务（MonitorTask）一组监测对象 + 周期
    task_id = Column(String(128), nullable=True, index=True)
    status = Column(String(16), nullable=True)
    schedule = Column(String(32), nullable=True)


class GeoKb(GeoRecord):
    __tablename__ = "geo_kb"  # ← geo_kb.json（内容资产 / materials）
    title = Column(String(512), nullable=True, index=True)
    source = Column(String(64), nullable=True)


class GeoWatchlist(GeoRecord):
    __tablename__ = "geo_watchlist"  # ← geo_watchlist.json


class GeoCollectRaw(GeoRecord):
    __tablename__ = "geo_collect_raw"  # ← geo_collect_raw.json


class GeoLinks(GeoRecord):
    __tablename__ = "geo_links"  # ← geo_links.json


class MediaFiles(GeoRecord):
    __tablename__ = "media_files"  # 新增：图片/媒体（文件在 storage/media/，库存路径）
    filename = Column(String(256), nullable=True)
    path = Column(String(512), nullable=True)
    mime = Column(String(64), nullable=True)
    size = Column(Integer, nullable=True)


class GeoContentImpacts(GeoRecord):
    """内容效果反哺（2026-08-19 内容计划 V1）：发布前基线 vs 复测差值。"""
    __tablename__ = "geo_content_impacts"


# ────────────────────────────────────────────────────────────────────────────
# Intelligence 分析引擎（EIOS 统一分析引擎 V1 · 2026-08-09）
# 字段级建模（打破通用表 data_json 模式）：幂等唯一约束 / evidence_id 关联 /
# subject 过滤 / 时间序列是硬需求（冻结方案 P0-1 + 外部评审 P2 拍板）。
# 现有 10 张通用表不动；以下 5 表不注册进 TABLES（走独立 repo 层）。
# ────────────────────────────────────────────────────────────────────────────


class GeoEvidence(Base):
    """统一原文（冻结方案 §2.2）：任何来源先收成这一层，V1 只接通 ai_answer。"""

    __tablename__ = "geo_evidence"

    id = Column(String(128), primary_key=True)  # evidence_id = ans_{history_id}_{query_id}_{engine}
    source_type = Column(String(32), nullable=False, default="ai_answer")
    platform = Column(String(64), nullable=True)  # deepseek / kimi / ...
    url = Column(String(512), nullable=True)
    subject_company = Column(String(128), nullable=False, default="")  # 监测主体公司名（分组键）；对象类型在 monitor_item
    raw_text = Column(Text, nullable=False)
    context_json = Column(Text, nullable=False, default="{}")  # question / engine / monitor_id 等
    parent_ref = Column(String(256), nullable=False)  # 幂等键原料（V1 = evidence_id 同值）
    observed_at = Column(DateTime, nullable=False)  # 回答时间（时间过滤口子）
    tenant_id = Column(String(64), nullable=False, default="tenant_corp_01", index=True)
    created_at = Column(DateTime, nullable=False, default=now_utc)

    __table_args__ = (
        UniqueConstraint("tenant_id", "source_type", "parent_ref", name="uq_geo_evidence_idem"),
    )


class GeoExtraction(Base):
    """条级解析（冻结方案 §5.2）：同一 evidence 重跑 insert 新 version；查最新 ORDER BY version DESC LIMIT 1。"""

    __tablename__ = "geo_extraction"

    id = Column(String(128), primary_key=True)
    evidence_id = Column(String(128), nullable=False, index=True)  # 主关联
    source_type = Column(String(32), nullable=False, default="ai_answer")
    subject_company = Column(String(128), nullable=False, default="")
    status = Column(String(16), nullable=False, default="pending")  # pending|running|succeeded|failed
    model = Column(String(64), nullable=True)
    analysis_json = Column(Text, nullable=True)  # 冻结方案 §6.1
    error = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    question = Column(String(512), nullable=True)  # 冗余便于查
    engine = Column(String(64), nullable=True)
    monitor_id = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=now_utc)
    updated_at = Column(DateTime, nullable=False, default=now_utc)

    __table_args__ = (
        UniqueConstraint("evidence_id", "version", name="uq_geo_extraction_ver"),
    )


class BrandMention(Base):
    """品牌↔原话（冻结方案 §5.3 必建）：矩阵/感知 API 从本表展开，不扫 JSON。"""

    __tablename__ = "brand_mention"

    id = Column(String(128), primary_key=True)
    evidence_id = Column(String(128), nullable=False, index=True)
    analysis_id = Column(String(128), nullable=False)
    brand_name = Column(String(128), nullable=False)  # 提到谁
    mention_type = Column(String(16), nullable=False)  # reason|trust|missing
    factor = Column(String(128), nullable=False)  # 维度词（LLM 原文；missing 时固定 __missing__；合并只在聚合层）
    evidence_quote = Column(Text, nullable=False)  # 原句 ≤500 字，必填
    confidence = Column(Float, nullable=True)  # 可选 0–1
    created_at = Column(DateTime, nullable=False, default=now_utc)

    __table_args__ = (
        Index("ix_brand_mention_brand", "brand_name", "factor"),
    )


class GeoInsightReports(Base):
    """周期报告（冻结方案 §5.4）：report_json 整包 + 版本字段可追溯。"""

    __tablename__ = "geo_insight_reports"

    id = Column(String(128), primary_key=True)
    company_name = Column(String(128), nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    report_json = Column(Text, nullable=False)
    model = Column(String(64), nullable=True)
    prompt_version = Column(String(32), nullable=True)
    schema_version = Column(String(16), nullable=False, default="1.0")
    created_at = Column(DateTime, nullable=False, default=now_utc)


class GeoDimensionSynonyms(Base):
    """维度同义词词表：canonical=主维度名，alias=同义词；合并只在聚合层做（库内存 LLM 原文 factor）。"""

    __tablename__ = "geo_dimension_synonyms"

    id = Column(String(128), primary_key=True)
    canonical = Column(String(128), nullable=False)
    alias = Column(String(128), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=now_utc)


class GeoCognitionEvaluations(Base):
    """AI 认知评估（V2 2026-08-12）：每条监测回答的语义评估结果（data_json 存完整评估）。"""

    __tablename__ = "cognition_evaluations"

    id = Column(String(128), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="tenant_corp_01", index=True)
    data_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=now_utc)


class GeoEnterpriseProfileItems(Base):
    """企业资料总揽 48 子项定义（2026-08-18）：两套规则落库，新增子项不重构 GEO。"""

    __tablename__ = "enterprise_profile_items"

    id = Column(String(128), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="tenant_corp_01", index=True)
    data_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=now_utc)


class GeoEnterpriseProfileEval(Base):
    """企业资料总揽 · 问题判定结果持久化（2026-08-18）：
    每个客户问题的 _knowledge_check 结果落库，页面刷新/进程重启不重算（秒开）。
    """

    __tablename__ = "enterprise_profile_eval"

    id = Column(String(256), primary_key=True)  # key = question||entities||intent
    tenant_id = Column(String(64), nullable=False, default="tenant_corp_01", index=True)
    data_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=now_utc)


class GeoKnowledgeSnapshots(Base):
    """GEO 读 EIOS 知识库的快照台账（Owner 2026-09-20 拍板）。

    知识库那边的正本永远是知识库自己的；这里存的是「GEO 读到过什么、什么时候读的、
    是哪一份契约给的」。用途有三：企业资料就绪度不必每次都去问知识库、缺口/认知判定
    有可追溯的原材料、顾问来查时能拿到带来源与时间的快照。

    同一份内容重复读到不新增行：payload_hash 相同就累加 read_count 并推进
    last_read_at（哈希算的是稳定内容，丢掉 query_id / read_at 这类每次都变的字段），
    所以这张表是「读到过哪些东西」的账，不是每次调用的流水。
    """

    __tablename__ = "geo_knowledge_snapshots"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="tenant_corp_01", index=True)
    kind = Column(String(32), nullable=False, index=True)  # search|objects|documents|relations|kb_initialization
    source = Column(String(64), nullable=False, default="eios-knowledge")
    source_url = Column(String(256), nullable=False, default="")
    contract = Column(String(64), nullable=True)
    authoritative = Column(Integer, nullable=False, default=0)  # 恒 0：正本不在 GEO
    payload_hash = Column(String(64), nullable=False, index=True)
    read_count = Column(Integer, nullable=False, default=1)
    first_read_at = Column(DateTime, nullable=False, default=now_utc)
    last_read_at = Column(DateTime, nullable=False, default=now_utc)
    data_json = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "payload_hash", name="uq_geo_knowledge_snapshot"),
    )


class GeoEnterpriseProfileKnowledge(Base):
    """企业资料总揽 · Kernel 全量知识持久化（2026-08-18）：
    entities/facts/relations 落库，进程重启后 items 详情不重拉 Kernel（秒开）。
    """

    __tablename__ = "enterprise_profile_knowledge"

    id = Column(String(64), primary_key=True)  # "all"
    tenant_id = Column(String(64), nullable=False, default="tenant_corp_01", index=True)
    data_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=now_utc)


TABLES = {
    "questions": GeoQuestions,
    "gaps": GeoGaps,
    "content_plans": GeoContentPlans,
    "monitor_history": GeoMonitorHistory,
    "monitor_items": GeoMonitorItems,
    "monitor_tasks": GeoMonitorTasks,
    "kb": GeoKb,
    "watchlist": GeoWatchlist,
    "collect_raw": GeoCollectRaw,
    "links": GeoLinks,
    "cognition_evaluations": GeoCognitionEvaluations,
    "enterprise_profile_items": GeoEnterpriseProfileItems,
    "enterprise_profile_eval": GeoEnterpriseProfileEval,
    "enterprise_profile_knowledge": GeoEnterpriseProfileKnowledge,
    # 知识库快照台账（2026-09-20）：随 reset_all 一起清；它不是知识库的正本，
    # 清掉只意味着「GEO 忘了自己读过什么」，下次读会重新记。
    "knowledge_snapshots": GeoKnowledgeSnapshots,
    "content_impacts": GeoContentImpacts,
    "media_files": MediaFiles,  # 修复（审计 H6）：表存在但未注册 → insert 静默不落库（file_id 恒 null）
}


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate_hot_columns()


def _migrate_hot_columns() -> None:
    """S1 热表拆列迁移（2026-08-19）：create_all 只建新表，旧 SQLite 表不会自动加列。

    对 6 张热表逐列检查 PRAGMA table_info，缺列则 ALTER TABLE ADD COLUMN（SQLite 支持，
    默认 NULL 不锁表不丢数据）。列同步逻辑在 store.py（HOT_COLUMNS），旧行 data_json 兜底。
    """
    from sqlalchemy import text

    hot_cols = {
        "geo_questions": {"question": "VARCHAR(512)", "priority": "INTEGER", "validated": "INTEGER"},
        "geo_gaps": {"question": "VARCHAR(512)", "missing_information": "VARCHAR(512)"},
        "geo_content_plans": {"topic": "VARCHAR(512)", "status": "VARCHAR(32)", "priority": "INTEGER"},
        "geo_monitor_items": {"monitor_id": "VARCHAR(128)", "type": "VARCHAR(32)", "status": "VARCHAR(16)"},
        "geo_monitor_tasks": {"task_id": "VARCHAR(128)", "status": "VARCHAR(16)", "schedule": "VARCHAR(32)"},
        "geo_kb": {"title": "VARCHAR(512)", "source": "VARCHAR(64)"},
    }
    try:
        with engine.begin() as conn:
            for table, cols in hot_cols.items():
                existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
                for col, decl in cols.items():
                    if col not in existing:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {decl}"))
    except Exception as exc:  # noqa: BLE001——表不存在等场景不阻塞启动
        print(f"[geo_models] 热表补列跳过（{exc}）")
