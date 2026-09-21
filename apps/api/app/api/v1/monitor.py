"""AI 曝光监测（P1：问 6 引擎"有没有推荐我"）

- /check：单问题监测
- /batch：问题池批量监测（一次 N 个客户问题 → 覆盖率 + 薄弱问题榜）
- /generate-questions：AI 生成客户问题（问题池来源）
- /history：监测历史（统计页用）
未配置 key 的引擎跳过并标注 no_api_key。
"""
import hashlib
import json
import re
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.core.envelope import ok, err

router = APIRouter(prefix="/api/v1/monitor")

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "geo_monitor_history.json"
POOL_FILE = DATA_DIR / "geo_question_pool.json"
KB_FILE = DATA_DIR / "geo_kb.json"  # 内容资产（效果卡 material 侧聚合用）


def _load_pool() -> dict:
    """问题池持久化（定时监测用）：池条目存 questions 表（source=pool）"""
    from app.services.store import get_store

    items = get_store().load("questions")
    pool_items = [i for i in items if i.get("source") == "pool"]
    company = pool_items[0].get("company_name") if pool_items else None
    return {"company_name": company, "questions": [i["question"] for i in pool_items if i.get("question")]}


def _save_pool(pool: dict) -> None:
    """池替换：删除旧 pool 来源条目，写入新池（保持 questions 表单一来源）。

    修复（审计 H2）：原 st.save 整表重写会把全表问题的 created_at 刷成同一时刻，
    改为逐条 delete + insert，保留非池问题的原始时间戳。
    """
    from app.services.store import get_store

    st = get_store()
    for i in st.load("questions"):
        if i.get("source") == "pool":
            st.delete("questions", i.get("id") or "")
    for q in (pool.get("questions") or []):
        st.insert("questions", {"question": q, "source": "pool", "company_name": pool.get("company_name")})


class MonitorCheckIn(BaseModel):
    question: str
    company_name: str | None = None
    engines: list[str] | None = None  # 默认全部引擎
    full: bool = False  # True 时返回完整回答（对战页用）


class BatchIn(BaseModel):
    questions: list[str] = []
    company_name: str | None = None
    engines: list[str] | None = None
    # 0.2：统一走 MonitorItem → Query 流程（旧 questions[] 自动转临时 item）
    items: list[dict] | None = None


class GenerateQuestionsIn(BaseModel):
    company_name: str | None = None
    industry: str | None = None
    count: int = 8


def _load_history() -> list[dict]:
    from app.services.store import get_store

    return get_store().load("monitor_history")


# ── 0.2 监测对象（MonitorItem）：长期监测对象，反复监测、跨次对比 ──
# 设计：type + config_json（不固定字段），status 生命周期（软删保历史），
# 详见 GEO_监测板块全景规划_0到02_V1.md（2026-08-08 拍板）

MONITOR_TYPES = ("brand", "product", "competitor", "keyword", "review", "question")
MONITOR_STATUSES = ("active", "paused", "archived")


def _load_items() -> list[dict]:
    from app.services.store import get_store

    return get_store().load("monitor_items")


def _save_items(items: list[dict]) -> None:
    from app.services.store import get_store

    get_store().save("monitor_items", items)


def _new_monitor_id() -> str:
    import uuid

    return f"mi_{uuid.uuid4().hex[:10]}"


class MonitorItemIn(BaseModel):
    type: str
    config_json: dict = {}
    status: str = "active"
    entity: str | None = None  # 冗余展示字段（可选）：品牌/竞品名等，方便列表一眼识别


class MonitorItemPatchIn(BaseModel):
    """PATCH 专用：全字段可选（部分更新，不整包覆盖）——审计 P0 修复"""
    model_config = ConfigDict(extra="ignore")
    type: str | None = None
    config_json: dict | None = None
    status: str | None = None
    entity: str | None = None


@router.post("/items/preview")
async def preview_item(payload: MonitorItemIn):
    """0.2+：监测对象探针预览——不落库，返回系统将生成的探针问题 + 成本估算

    前端新建对象弹层实时预览：生成问题列表 / 可用引擎数（真实 key）/ 预计耗时
    """
    t = (payload.type or "").strip()
    if t not in MONITOR_TYPES:
        return err("invalid_input", f"type 必须是 {MONITOR_TYPES} 之一")
    item = {"type": t, "config_json": payload.config_json or {}, "entity": payload.entity}
    queries = generate_queries(item)
    # brand 额外返回 6 类分类（前端按维度分组展示）
    categories = None
    if t == "brand":
        g = generate_brand_queries(payload.config_json or {}, (payload.config_json or {}).get("tier") or "standard")
        categories = {k: {"label": _BRAND_CATEGORY_LABELS.get(k, k), "queries": v} for k, v in g["categories"].items()}

    from adapters.engines import EngineFaceError, list_engines

    # 引擎清单 = 这个部署登记的模型（Owner 2026-09-21：「GEO 不再写死 6 个」）。
    # 入口接不上时如实说接不上：估时宁可给 0，也不编一个引擎数出来。
    engines_error = None
    try:
        engines = [e["name"] for e in await list_engines()]
    except EngineFaceError as exc:
        engines = []
        engines_error = f"{exc.code}：{exc.message}"[:200]
    n = len(queries) * max(len(engines), 0)
    est_minutes = max(1, (n + 3) // 4) if n else 0  # 并发 ≤4，向上取整
    return ok(
        {
            "type": t,
            "queries": queries,
            "categories": categories,
            "query_count": len(queries),
            "engines": engines,
            "engine_count": len(engines),
            "total_answers": n,
            "est_minutes": est_minutes,
            "note": engines_error,
        }
    )


@router.post("/items/{mid}/run")
async def run_item(mid: str, engines: list[str] | None = None):
    """0.2+：手动触发单监测对象运行（建完对象即可单独监测，不必先建任务）

    history 落库带 monitor_id/query_id（与任务运行同一套 run_batch_items 流程）
    """
    items = _load_items()
    target = next((i for i in items if i.get("monitor_id") == mid), None)
    if not target:
        return err("not_found", f"monitor_id 不存在: {mid}")
    if target.get("status") == "archived":
        return err("not_found", "监测对象已归档，不能运行")
    if target.get("status") == "paused":
        return err("invalid_input", "监测对象已暂停，先启用再运行")
    data = await run_batch_items([target], engines=engines)
    # 更新 last_run_at
    items = _load_items()
    for it in items:
        if it.get("monitor_id") == mid:
            from datetime import datetime, timezone

            it["last_run_at"] = datetime.now(timezone.utc).isoformat()
            break
    _save_items(items)
    return ok(data)


@router.get("/items")
async def list_items(include_archived: bool = False):
    """0.2：监测对象列表（默认只 active/paused，archived 单独看）"""
    items = _load_items()
    if not include_archived:
        items = [i for i in items if i.get("status") != "archived"]
    # 配置状态（active/paused）与运行结果是两回事。按最新一批包含该对象的历史记录
    # 计算结果状态，避免「监测中」让用户误以为已经拿到过有效回答。
    latest_by_id: dict[str, dict] = {}
    for batch in reversed(_load_history()):
        for question in batch.get("questions") or []:
            mid = question.get("monitor_id")
            if mid and mid not in latest_by_id:
                latest_by_id[mid] = {"batch": batch, "questions": []}
            if mid and latest_by_id.get(mid, {}).get("batch") is batch:
                latest_by_id[mid]["questions"].append(question)
    enriched = []
    for item in items:
        latest = latest_by_id.get(item.get("monitor_id"))
        if not latest:
            run = {"state": "never", "label": "从未成功", "last_run_at": item.get("last_run_at"), "answered": 0, "failed": 0}
        else:
            engines = [e for q in latest["questions"] for e in (q.get("engine_detail") or [])]
            answered = sum(1 for e in engines if e.get("mentioned") is not None)
            failed = sum(1 for e in engines if e.get("error") or e.get("mentioned") is None)
            state = "success" if answered else "failed"
            run = {
                "state": state,
                "label": "已有有效结果" if state == "success" else "最近运行失败",
                "last_run_at": latest["batch"].get("created_at") or latest["batch"].get("ts"),
                "answered": answered,
                "failed": failed,
            }
        enriched.append({**item, "run_result": run})
    enriched.sort(key=lambda x: x.get("created_time", ""), reverse=True)
    return ok({"items": enriched, "total": len(enriched)})


@router.post("/items")
async def create_item(payload: MonitorItemIn):
    """0.2：新建监测对象（type 四枚举校验；status 默认 active）"""
    t = (payload.type or "").strip()
    if t not in MONITOR_TYPES:
        return err("invalid_input", f"type 必须是 {MONITOR_TYPES} 之一")
    if payload.status not in MONITOR_STATUSES:
        return err("invalid_input", f"status 必须是 {MONITOR_STATUSES} 之一")
    from datetime import datetime, timezone

    item = {
        "monitor_id": _new_monitor_id(),
        "type": t,
        "config_json": payload.config_json or {},
        "entity": payload.entity,
        "query_count": len(generate_queries({"type": t, "config_json": payload.config_json or {}, "entity": payload.entity})),
        "status": payload.status,
        "created_time": datetime.now(timezone.utc).isoformat(),
        "updated_time": datetime.now(timezone.utc).isoformat(),
    }
    items = _load_items()
    items.append(item)
    _save_items(items)
    return ok(item)


@router.patch("/items/{mid}")
async def update_item(mid: str, payload: MonitorItemPatchIn):
    """0.2：更新监测对象（部分更新：只改传入字段，不整包覆盖）——审计 P0 修复"""
    items = _load_items()
    target = next((i for i in items if i.get("monitor_id") == mid), None)
    if not target:
        return err("not_found", f"monitor_id 不存在: {mid}")
    from datetime import datetime, timezone

    changed = []
    if payload.type is not None:
        if payload.type not in MONITOR_TYPES:
            return err("invalid_input", f"type 必须是 {MONITOR_TYPES} 之一")
        target["type"] = payload.type
        changed.append("type")
    if payload.config_json is not None:
        # 合并而非覆盖：保留未传的配置键（防审计发现的整包覆盖抹配置）
        cfg = dict(target.get("config_json") or {})
        cfg.update(payload.config_json)
        target["config_json"] = cfg
        changed.append("config_json")
    if payload.entity is not None:
        target["entity"] = payload.entity
        changed.append("entity")
    if payload.status is not None:
        if payload.status not in MONITOR_STATUSES:
            return err("invalid_input", f"status 必须是 {MONITOR_STATUSES} 之一")
        target["status"] = payload.status
        changed.append("status")
    if changed:
        target["updated_time"] = datetime.now(timezone.utc).isoformat()
    _save_items(items)
    return ok({**target, "_changed": changed})


@router.delete("/items/{mid}")
async def archive_item(mid: str):
    """0.2：软删除（status → archived，历史趋势保留，不硬删）"""
    items = _load_items()
    target = next((i for i in items if i.get("monitor_id") == mid), None)
    if not target:
        return err("not_found", f"monitor_id 不存在: {mid}")
    target["status"] = "archived"
    from datetime import datetime, timezone

    target["updated_time"] = datetime.now(timezone.utc).isoformat()
    _save_items(items)
    return ok({"monitor_id": mid, "status": "archived", "message": "已归档（历史趋势保留）"})


# ── 0.3 监测任务（MonitorTask）：一组监测对象 + 周期，自动积累趋势 ──
# 设计：task → 1:N items（item 加 task_id 软引用，无 task_id = 独立对象兼容 0.2）
# 频率第一版：daily / weekly（cron 表达式后置）；不补跑错过的周期；无通知
# 详见 GEO_监测板块全景规划_0到02_V1.md（0.3 节）

TASK_STATUSES = ("active", "paused", "archived")
TASK_SCHEDULES = ("daily", "weekly")


def _load_tasks() -> list[dict]:
    from app.services.store import get_store

    return get_store().load("monitor_tasks")


def _save_tasks(tasks: list[dict]) -> None:
    from app.services.store import get_store

    get_store().save("monitor_tasks", tasks)


class MonitorTaskIn(BaseModel):
    name: str
    schedule: str = "daily"  # daily | weekly
    item_ids: list[str] = []  # 任务包含的监测对象
    status: str = "active"


@router.get("/tasks")
async def list_tasks(include_archived: bool = False):
    """0.3：监测任务列表（含每任务的 item 数与最近运行时间）"""
    tasks = _load_tasks()
    if not include_archived:
        tasks = [t for t in tasks if t.get("status") != "archived"]
    items = _load_items()
    # 附 item 数 + 最近运行时间（从 history 找最后一条带该 task 的运行）
    hist = _load_history()
    out = []
    for t in tasks:
        tid = t.get("task_id")
        task_items = [i for i in items if i.get("task_id") == tid and i.get("status") != "archived"]
        last_run = ""
        for h in reversed(hist):
            if h.get("task_id") == tid:
                last_run = h.get("created_at", "")
                break
        out.append({**t, "item_count": len(task_items), "last_run_at": last_run})
    out.sort(key=lambda x: x.get("created_time", ""), reverse=True)
    return ok({"tasks": out, "total": len(out)})


@router.post("/tasks")
async def create_task(payload: MonitorTaskIn):
    """0.3：新建监测任务（名字 + 频率 + 绑定的监测对象）"""
    name = (payload.name or "").strip()
    if not name:
        return err("invalid_input", "name 必填")
    if payload.schedule not in TASK_SCHEDULES:
        return err("invalid_input", f"schedule 必须是 {TASK_SCHEDULES} 之一")
    if payload.status not in TASK_STATUSES:
        return err("invalid_input", f"status 必须是 {TASK_STATUSES} 之一")
    from datetime import datetime, timezone

    task_id = f"tk_{_new_monitor_id()[3:]}"
    # 校验 item_ids 存在
    items = _load_items()
    valid_ids = {i.get("monitor_id") for i in items}
    bad = [i for i in payload.item_ids if i not in valid_ids]
    if bad:
        return err("not_found", f"item 不存在: {bad[:3]}")
    task = {
        "task_id": task_id,
        "name": name,
        "schedule": payload.schedule,
        "status": payload.status,
        "item_ids": payload.item_ids,
        "created_time": datetime.now(timezone.utc).isoformat(),
        "updated_time": datetime.now(timezone.utc).isoformat(),
    }
    tasks = _load_tasks()
    tasks.append(task)
    _save_tasks(tasks)
    # 回写 item 的 task_id（软引用）
    for i in items:
        if i.get("monitor_id") in payload.item_ids:
            i["task_id"] = task_id
    _save_items(items)
    return ok(task)


@router.patch("/tasks/{tid}")
async def update_task(tid: str, payload: MonitorTaskIn):
    """0.3：更新任务（改名/改频率/改绑定/启停）"""
    tasks = _load_tasks()
    target = next((t for t in tasks if t.get("task_id") == tid), None)
    if not target:
        return err("not_found", f"task_id 不存在: {tid}")
    if payload.schedule not in TASK_SCHEDULES:
        return err("invalid_input", f"schedule 必须是 {TASK_SCHEDULES} 之一")
    if payload.status not in TASK_STATUSES:
        return err("invalid_input", f"status 必须是 {TASK_STATUSES} 之一")
    from datetime import datetime, timezone

    # 修复（审计 H7）：PATCH 部分更新——只应用请求里显式传入的字段。
    # 原实现整包覆盖：只传 name/schedule 时 item_ids 被默认值 [] 重置，悄悄解绑全部监测对象。
    # pydantic v2 exclude_unset 可区分「未传」与「显式传空」。
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        target["name"] = str(updates["name"] or "").strip()
    if "schedule" in updates:
        target["schedule"] = updates["schedule"]
    if "status" in updates:
        target["status"] = updates["status"]
    if "item_ids" in updates:
        # 解绑旧 item 的 task_id，再绑定新列表
        items = _load_items()
        for i in items:
            if i.get("task_id") == tid:
                i.pop("task_id", None)
        target["item_ids"] = updates["item_ids"]
        for i in items:
            if i.get("monitor_id") in updates["item_ids"]:
                i["task_id"] = tid
        _save_items(items)
    target["updated_time"] = datetime.now(timezone.utc).isoformat()
    _save_tasks(tasks)
    return ok(target)


@router.delete("/tasks/{tid}")
async def archive_task(tid: str):
    """0.3：软删除任务（status → archived；item 解绑但保留）"""
    tasks = _load_tasks()
    target = next((t for t in tasks if t.get("task_id") == tid), None)
    if not target:
        return err("not_found", f"task_id 不存在: {tid}")
    target["status"] = "archived"
    from datetime import datetime, timezone

    target["updated_time"] = datetime.now(timezone.utc).isoformat()
    _save_tasks(tasks)
    # 取消任务 → 监测对象回到未绑定（task_id 清空，对象保留，可单独运行/重绑）
    items = _load_items()
    changed = 0
    for it in items:
        if it.get("task_id") == tid:
            it["task_id"] = None
            changed += 1
    if changed:
        _save_items(items)
    return ok({"task_id": tid, "status": "archived", "message": f"任务已归档（{changed} 个监测对象已解绑，保留可单独运行）"})


async def _run_task_items(task: dict) -> dict:
    """跑一个任务：取任务下 active items → 统一采集流程 → history 带 task_id"""
    items = _load_items()
    task_items = [i for i in items if i.get("task_id") == task.get("task_id") and i.get("status") == "active"]
    if not task_items:
        return {"task_id": task.get("task_id"), "summary": None, "results": [], "skipped": "无 active 监测对象"}
    data = await run_batch_items(task_items)
    # history 补 task_id 标记（修复 H2：原来整表 _save_history 重写会刷掉全表 created_at）
    hist = _load_history()
    if hist:
        last = hist[-1]
        from app.services.store import get_store

        get_store().update(
            "monitor_history",
            last.get("id") or "",
            {"task_id": task.get("task_id"), "task_name": task.get("name")},
        )
    return data


@router.post("/tasks/{tid}/run")
async def run_task(tid: str, engines: list[str] | None = None):
    """0.3：手动触发任务运行（engines 可指定，默认全部已配置引擎）"""
    tasks = _load_tasks()
    # S3 兼容：恢复的数据可能只有 id 无 task_id 字段（BFF 镜像时 task_id 当主键），两者都认
    target = next((t for t in tasks if (t.get("task_id") or t.get("id")) == tid), None)
    if not target:
        return err("not_found", f"task_id 不存在: {tid}")
    if target.get("status") == "archived":
        return err("not_found", "任务已归档，不能运行")
    data = await _run_task_items(target)
    return ok(data)


@router.get("/tasks/{tid}/overview")
async def task_overview(tid: str):
    """0.3：任务级聚合——任务下每 item 的最新状态 + 任务整体指标"""
    tasks = _load_tasks()
    target = next((t for t in tasks if (t.get("task_id") or t.get("id")) == tid), None)
    if not target:
        return err("not_found", f"task_id 不存在: {tid}")
    items = _load_items()
    task_items = [i for i in items if i.get("task_id") == tid and i.get("status") != "archived"]
    hist = _load_history()
    # 找任务最近一次运行（batch 且 task_id 匹配）
    latest = None
    for h in reversed(hist):
        if h.get("task_id") == tid:
            latest = h
            break
    item_states = []
    for it in task_items:
        mid = it.get("monitor_id")
        # 该 item 最近一次记录（最新 history 里匹配 monitor_id）
        last = None
        for h in reversed(hist):
            for q in h.get("questions") or []:
                if q.get("monitor_id") == mid:
                    last = q
                    break
            if last:
                break
        item_states.append(
            {
                "monitor_id": mid,
                "type": it.get("type"),
                "entity": it.get("entity"),
                "status": it.get("status"),
                "last_visibility": (
                    round(last.get("mentioned_count", 0) / last.get("configured_count", 1) * 100)
                    if last and last.get("configured_count")
                    else None
                ),
                "last_mentioned": last.get("mentioned_count") if last else None,
                "last_run_at": latest.get("created_at", "") if latest else "",
            }
        )
    return ok({
        "task": target,
        "item_count": len(task_items),
        "item_states": item_states,
        "last_run_at": latest.get("created_at", "") if latest else "",
        "last_summary": latest.get("summary") if latest else None,
    })


# ── 0.2 Query 生成器：MonitorItem → MonitorQuery（探针） ──
# 设计：generate_queries(item, context) 接口留扩展点——模板是第一版实现，
# 未来可按行业/上下文生成更贴合的查询（医疗→"医院知识库哪个好"），不写死 if-else 链。
# 各类型：brand→品牌认知三问；competitor→对比问；keyword→行业问；question→透传。

def _item_company(item: dict) -> str:
    """item 的主企业名（brand=company；competitor=target；其余取 entity 兜底）"""
    cfg = item.get("config_json") or {}
    if item.get("type") == "brand":
        return cfg.get("company") or item.get("entity") or ""
    if item.get("type") == "competitor":
        return cfg.get("target") or item.get("entity") or ""
    return cfg.get("company") or item.get("entity") or ""


_BRAND_TIER_COUNT = {"lite": 2, "standard": 4, "deep": 8}
_BRAND_CATEGORY_LABELS = {
    "awareness": "品牌认知", "trust": "信任判断", "recommend": "推荐意图",
    "comparison": "竞品比较", "scenario": "场景需求", "risk": "风险认知",
}


def generate_brand_queries(cfg: dict, tier: str = "standard") -> dict:
    """品牌认知探针：6 类维度 × 档位数量（lite 2 / standard 4 / deep 8）

    维度链 = 认识我→信任我→推荐我→比较我→联想到我→为什么不选我；
    推荐意图用**间接探针**（问品类/场景，不问自己——真实用户不会问"推荐云启吗"）。
    """
    company = (cfg.get("company") or "").strip()
    products = cfg.get("product") or []
    if isinstance(products, str):
        products = [products]
    products = [p.strip() for p in products if p and p.strip()]
    product = products[0] if products else ""
    industry = (cfg.get("industry") or "").strip()
    customer = (cfg.get("customer") or "").strip()
    competitors = cfg.get("competitor") or []
    if isinstance(competitors, str):
        competitors = [competitors]
    competitors = [c.strip() for c in competitors if c and c.strip()]

    n = _BRAND_TIER_COUNT.get(tier, 4)
    cats: dict[str, list[str]] = {}

    # 1 基础认知（认识我）
    a = []
    if company:
        a += [f"{company}是什么？", f"{company}是做什么的？"]
        if product:
            a.append(f"{company}有哪些产品？")
        if customer:
            a.append(f"{company}服务哪些客户？")
        if industry:
            a.append(f"{company}属于哪个行业？")
    cats["awareness"] = a[:n]

    # 2 信任判断（敢不敢推荐）
    t = []
    if company:
        t += [f"{company}靠谱吗？", f"{company}值得合作吗？"]
        if product:
            t.append(f"{company}的{product}有什么优势？")
        t.append(f"{company}有什么成功案例？")
    cats["trust"] = t[:n]

    # 3 推荐意图（间接探针，不问自己）
    r = []
    if product:
        r.append(f"{product}推荐哪些公司？")
    if industry:
        r.append(f"国内{industry}平台有哪些？")
    if customer:
        r.append(f"适合{customer}的AI系统有哪些？")
    if product and customer:
        r.append(f"如果{customer}想部署{product}，推荐什么？")
    if company:
        r.append(f"有没有类似{company}的产品？")
    cats["recommend"] = r[:n]

    # 4 竞品比较（为什么别人赢）
    c = []
    for comp in competitors:
        if company:
            c.append(f"{company}和{comp}哪个好？")
            c.append(f"{company}和{comp}有什么区别？")
    if product and competitors:
        c.append(f"{product}应该选{company or '哪家'}还是{competitors[0]}？")
    cats["comparison"] = c[:n]

    # 5 场景需求（什么时候想到我）
    s = []
    if product:
        s.append(f"企业如何建立{product}？")
    if industry:
        s.append(f"{industry}有哪些应用方案？")
    if customer:
        s.append(f"{customer}如何应用AI？")
    if product or industry or customer:
        s.append("企业数字化转型应该选择什么工具？")
    cats["scenario"] = s[:n]

    # 6 风险认知（为什么不选我）
    risk = []
    if company:
        # 2026-09-21（Owner 点名「怎么还会问这么愚蠢的问题」）：删掉
        # 「使用{company}需要注意什么？」—— 公司不是能「使用」的东西，这句话本身不成立；
        # 而且这类探针不问事实，只逼模型替我们编一份「注意事项」，
        # 于是监测里出现「输出正常但不正确」的条目（实测：模型答「建议查工商信息/警惕风险」，
        # 被记成 negative，再进总览当负面情绪）。
        # 留下的四句都是真实用户在决策前会搜的话，测的是「AI 会不会说我们坏话」，不是让 AI 编坏话。
        risk += [f"{company}有哪些缺点？", f"{company}有什么负面评价？"]
        risk += [f"{company}适合哪些企业？", f"{company}不适合哪些企业？"]
    cats["risk"] = risk[:n]

    # 展平（去重保序）
    queries: list[str] = []
    for k in ("awareness", "trust", "recommend", "comparison", "scenario", "risk"):
        for q in cats[k]:
            if q not in queries:
                queries.append(q)
    return {"categories": cats, "queries": queries}


def generate_queries(item: dict, context: dict | None = None) -> list[str]:
    """MonitorItem → 本次运行要问 AI 的查询问题列表（探针）

    context（预留扩展点）：未来可带 industry/region/intent 等上下文，
    模板只是第一版实现，后续在不动调用方的前提下替换生成策略。
    """
    t = item.get("type")
    cfg = item.get("config_json") or {}
    queries: list[str] = []

    if t == "brand":
        # 6 类维度 × 档位（lite/standard/deep），推荐意图用间接探针
        tier = cfg.get("tier") or "standard"
        queries = generate_brand_queries(cfg, tier)["queries"]
    elif t == "product":
        product = cfg.get("product") or item.get("entity") or ""
        # kind=service（自动配置勾的服务）：问法要像服务，不像一件货
        # （「量尺哪个好？」这种问出来没有意义）。
        is_service = str(cfg.get("kind") or "") == "service"
        if product and is_service:
            queries = [
                f"{product}哪家公司做得好？",
                f"{product}怎么收费？",
                f"{product}一般包含哪些内容？",
            ]
        elif product:
            queries = [
                # 「{product}推荐？」缺宾语（问出来是半句话，模型只能反问「你想推荐什么」）
                f"{product}推荐哪些公司？",
                f"{product}价格多少？",
                f"{product}哪个好？",
            ]
    elif t == "competitor":
        # 0.4 竞品分析：5 类竞争探针（brand/comparison/selection/capability/scenario）
        # 双主体信息：我方 company/aliases/product/industry + 竞品名/别名
        target = cfg.get("company") or cfg.get("target") or item.get("entity") or ""
        comp = cfg.get("competitor") or ""
        if isinstance(comp, list):
            comp = comp[0] if comp else ""
        product = cfg.get("product") or ""
        if isinstance(product, list):
            product = product[0] if product else ""
        industry = cfg.get("industry") or ""
        if target and comp:
            # ① 品牌/比较类
            queries.extend(
                [
                    f"{target}和{comp}哪个好？",
                    f"{target}和{comp}有什么区别？",
                    f"{comp}为什么被推荐？",
                ]
            )
            # ② 选择类（用户决策场景）
            if industry:
                queries.append(f"{industry}应该选择{target}还是{comp}？")
            if product:
                queries.append(f"{product}应该选{target}还是{comp}？")
            # ③ 能力类
            queries.append(f"{target}和{comp}分别有什么优势？")
            # ④ 场景类（结合我方行业）
            # 2026-09-21：原来这里写死了「企业知识管理应该选择X还是Y？」—— 家装公司也会被问
            # 「企业知识管理…」，跟它的生意毫无关系，而且当行业存在时与上一句完全重复。
            if industry:
                queries.append(f"{industry}领域，{comp}和{target}谁更适合？")
    elif t == "keyword":
        kw = cfg.get("keyword") or ""
        industry = cfg.get("industry") or ""
        if kw:
            suffix = f"{industry}（{kw}）" if industry else kw
            queries = [
                f"{kw}哪个好？",
                f"{kw}有哪些推荐？",
                f"怎么选{suffix}？",
            ]
    elif t == "review":
        audience = cfg.get("audience") or item.get("entity") or ""
        scenario = cfg.get("scenario") or ""
        if audience or scenario:
            base = audience or "用户"
            queries = [
                f"{base}为什么要用知识库？",
                f"{base}最关心哪些功能？",
            ]
            if scenario:
                queries.append(f"{scenario}怎么办？")
    elif t == "question":
        q = cfg.get("query") or ""
        if q:
            queries = [q]
    # 去重保序：竞品分支是逐条 append 的，写法一变就可能出现同一句问两遍（白烧模型额度）
    deduped: list[str] = []
    for q in queries:
        q = (q or "").strip()
        if q and q not in deduped:
            deduped.append(q)
    return deduped


def _load_published_materials() -> list[dict]:
    """已发布素材（引用检测目标集）：kb 表里 published_at 非空"""
    from app.services.store import get_store

    items = get_store().load("kb")
    return [m for m in items if m.get("published_at")]


def _detect_citations(answer: str, materials: list[dict]) -> list[dict]:
    """检测回答是否引用已发布素材（规则匹配第一版，LLM 精判后置）

    精确率底线（评审意见 4，防误报）：
    - 标题：去《》后核心串 ≥8 字，必须精确出现在回答里（独特标题误报低）
    - 关键句：内容前 80 字去标点 ≥12 字连续串出现在回答（去标点后匹配，长片段才命中）
    返回 [{material_id, title, snippet}]（同一素材多条命中只留第一条）。
    """
    if not answer or not materials:
        return []
    hits: dict[str, dict] = {}
    for m in materials:
        title = (m.get("title") or "").strip().replace("《", "").replace("》", "").strip()
        if len(title) >= 8 and title in answer:
            idx = answer.find(title)
            hits[m["id"]] = {
                "material_id": m["id"],
                "title": m.get("title", ""),
                "snippet": answer[max(0, idx - 40): idx + len(title) + 60],
            }
            continue
        key = re.sub(r"[\s\W]+", "", (m.get("content") or "")[:80])
        if len(key) >= 12 and key in re.sub(r"[\s\W]+", "", answer):
            hits[m["id"]] = {
                "material_id": m["id"],
                "title": m.get("title", ""),
                "snippet": answer[:240],  # 关键句命中：无准确定位，取回答开头作片段
            }
    return list(hits.values())


def _save_history(items: list[dict]) -> None:
    from app.services.store import get_store

    get_store().save("monitor_history", items)


def _append_history(item: dict) -> None:
    """追加单条 history（insert 而非整表替换——A4：监测频繁写入不重写全表）"""
    from app.services.store import get_store

    get_store().insert("monitor_history", item)
    # Intelligence 钩子（S1-3）：history 落库成功后，异步收成 geo_evidence 入队解析。
    # 铁律：monitor 业务逻辑/规则统计不改；钩子失败不影响监测返回（fire-and-forget）。
    try:
        from services.intelligence.adapter import ingest_one_history

        n = ingest_one_history(item, enqueue_parsing=True)
        if n:
            import logging

            logging.getLogger("eios.intelligence.adapter").info("hook ingested %d evidences from history %s", n, item.get("id"))
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("eios.intelligence.adapter").exception("monitor hook failed (不影响监测): history %s", item.get("id"))


# ── P0：平均排名 + 评价解析（数据可视化地基，纯规则省 token） ──

# 企业名后缀剥离（回答常用简称，如"云启智能科技有限公司"→"云启智能"）
_COMPANY_SUFFIXES = (
    "股份有限公司", "有限责任公司", "有限公司", "集团公司", "集团", "科技", "股份",
)


def _strip_company_suffix(name: str) -> str:
    """剥离常见公司后缀得到简称；无后缀原样返回（循环剥，如"云启智能科技有限公司"→"云启智能"）"""
    n = (name or "").strip()
    changed = True
    while changed and len(n) > 1:
        changed = False
        for s in _COMPANY_SUFFIXES:
            if n.endswith(s) and len(n) > len(s):
                n = n[: -len(s)]
                changed = True
                break
    return n


# 评价词表（规则第一版，省 token；精判 LLM 后置）
# 审计 P0-2（2026-08-09）："风险" 是上下文词（风险提示/规避风险/风险评估），
# 免责声明高频命中 → 误判负面，已移除；补常见否定前缀词
# （"不值得/不放心" 含正面子串"值得/放心"，covered 逻辑会自动消正，不会双计）。
_POSITIVE_WORDS = (
    "推荐", "值得", "优质", "领先", "好评", "可靠", "专业", "实力", "认可",
    "优秀", "首选", "口碑好", "性价比高", "信得过", "放心", "满意", "受欢迎",
)
_NEGATIVE_WORDS = (
    "不推荐", "不值得", "不放心", "不满意", "不可靠", "不认可", "差评", "投诉",
    "虚假", "夸大", "失望", "不好", "不行", "质疑", "翻车", "骗", "坑",
    "质量问题", "不靠谱", "避雷", "后悔",
)


def _mention_cands(company_name: str | None, aliases: list[str] | None = None) -> list[str]:
    """候选名列表（长名子串匹配；短名独立成词匹配）"""
    out: list[str] = []
    if company_name:
        out.append(company_name)
        s = _strip_company_suffix(company_name)
        if s and s not in out:
            out.append(s)
    for a in aliases or []:
        a = (a or "").strip()
        if not a:
            continue
        if a not in out:
            out.append(a)
        s = _strip_company_suffix(a)
        if s and s not in out:
            out.append(s)
    return out


def _is_mention(answer: str, cands: list[str]) -> bool:
    """回答是否提及任一候选名

    召回优先（2026-08-08 拍板，Cursor 验收 P1-2 修正）：
    - 长候选名（≥4 字）：子串匹配
    - 短候选名（≤3 字）：同样子串匹配，不做前后边界——
      "认为云启/推荐云启/包括云启" 是真实中文最常见用法，边界会大面积漏检
      （漏检 → "从未被提及"假象，比撞名误算更伤数据可信度）
    - 已知边界：短别名与别家产品撞名（"云启"vs"云启视界"）会误算，
      由配置者用 4 字以上独特别名规避（诚实标注，不牺牲召回）
    """
    for c in cands:
        if c and c in answer:
            return True
    return False


def _analyze_answer(company_name: str | None, answer: str, aliases: list[str] | None = None) -> dict:
    """解析 AI 回答：企业平均排名（估算）+ 评价倾向（规则）

    - rank_est：企业名首次出现的句序号（按 [。！？\\n] 切句），未提及 = None
    - sentiment：**仅企业被提及（mentioned=True）时才有评价**——未提及 = None
      （诚实红线：AI 没提我们就不算评价，避免把回答整体情绪误当"对企业评价"）
    - aliases（0.2 新增）：候选名 = company + aliases + 各自剥后缀——
      AI 常写简称"云启/云启科技"，剥后缀只解决"有限公司"，解决不了别名（影响 mentioned 可信度）
    - 短别名（≤3 字）独立成词匹配，防"云启"误撞"云启视界"
    - 规则词表计数比较；无命中 = neutral（source=rule 标注）
    """
    rank_est: int | None = None
    mentioned = False
    if company_name and answer:
        cands = _mention_cands(company_name, aliases)
        sentences = re.split(r"[。！？!?\n；;]", answer)
        for i, s in enumerate(sentences):
            if _is_mention(s, cands):
                rank_est = i + 1
                mentioned = True
                break

    sentiment = None
    if mentioned and answer:
        # P1-5（Cursor 验收）：否定词优先——"不推荐"含"推荐"、""不好"含"好"，
        # 子串正词会吃掉否定。先计否定词，再从正面计数中扣除被否定覆盖的命中。
        pos = 0
        neg = 0
        # 1) 负面词全量计数（含"不推荐/不好"这类含正词子串的）
        for w in _NEGATIVE_WORDS:
            neg += answer.count(w)
        # 2) 正面词计数：剔除被负面词覆盖的（负面词出现处附近的正面子串不算）
        for w in _POSITIVE_WORDS:
            hits = 0
            start = 0
            while True:
                i = answer.find(w, start)
                if i < 0:
                    break
                # 检查该命中是否被负面词覆盖：落在任一负面词内部，或紧贴其后
                # （审计 08-09："不值得推荐"=否定词+正词拼接，"推荐"紧邻"不值得"尾，
                #   原边界 [j, j+len) 开区间漏判 → neutral；finditer 覆盖全部出现位置）
                covered = any(
                    j <= i < j + len(nw) + 1
                    for nw in _NEGATIVE_WORDS
                    for j in (m.start() for m in re.finditer(re.escape(nw), answer))
                )
                if not covered:
                    hits += 1
                start = i + 1
            pos += hits
        if pos > neg:
            sentiment = "positive"
        elif neg > pos:
            sentiment = "negative"
        else:
            sentiment = "neutral"

    return {"rank_est": rank_est, "mentioned": mentioned, "sentiment": sentiment, "sentiment_source": "rule"}


async def _run_check(
    question: str,
    company_name: str | None = None,
    engines: list[str] | None = None,
    full: bool = False,
    aliases: list[str] | None = None,
    competitor_name: str | None = None,
    competitor_aliases: list[str] | None = None,
) -> list[dict]:
    """单个问题跑全部（已配置）引擎，返回 results 列表

    aliases（0.2）：企业别名集合，mentioned 判定候选名 = 全称 + 别名 + 各自剥后缀。
    双主体（0.4，竞品分析）：competitor_name 传入时，额外判定竞品主体，
    结果放 subjects（company/competitor 各带 mentioned/rank_est/sentiment）；
    顶层字段保持 = 我方（兼容旧分析页，零破坏）。
    """
    from adapters.engines import EngineFaceError, list_engines as _list_engines, ask_with_meta

    published = _load_published_materials()
    # 候选名（全称 + 别名 + 剥后缀），外层 mentioned 与 _analyze_answer 保持一致
    cands = _mention_cands(company_name, aliases)
    comp_cands = _mention_cands(competitor_name, competitor_aliases) if competitor_name else []

    # 引擎并发（审计 P0-5 修复）：原实现串行 await ask，6 引擎 × 15s 超时 =
    # 单问题最坏 90s，批量监测慢引擎拖垮整批。并发后单问题 ≤ 最长引擎 15s。
    # 引擎清单 = 部署登记的模型。接不上就如实抛错，由调用方回一句人话；不编引擎、不假装跑过。
    all_engines = await _list_engines()

    async def _one(e: dict) -> dict | None:
        if engines and e["id"] not in engines:
            return None
        try:
            meta = await ask_with_meta(e["id"], question)
            answer = meta["content"]
            web_realtime = meta.get("web_realtime", False)
            parsed = _analyze_answer(company_name, answer, aliases)
            # P0-1（Cursor 验收红线①）：mentioned 统一取解析结果，杜绝与落库分叉
            mentioned = parsed["mentioned"]
            # 双主体：竞品判定（仅 competitor 探针启用，复用同一规则解析）
            subjects = None
            if competitor_name and answer:
                cp = _analyze_answer(competitor_name, answer, competitor_aliases)
                subjects = {
                    "company": {"mentioned": mentioned, "rank_est": parsed["rank_est"], "sentiment": parsed["sentiment"]},
                    "competitor": {"mentioned": cp["mentioned"], "rank_est": cp["rank_est"], "sentiment": cp["sentiment"]},
                }
            snippet = ""
            if mentioned and company_name:
                idx = answer.find(company_name)
                if idx < 0:
                    # 别名命中：找第一个候选名位置
                    idx = min((answer.find(c) for c in cands if c and c in answer), default=0)
                snippet = answer[max(0, idx - 120) : idx + 240]
            elif not mentioned:
                snippet = answer[:240]
            return {
                "engine_id": e["id"],
                "engine_name": e["name"],
                "configured": True,
                "mentioned": mentioned,
                "rank_est": parsed["rank_est"],
                "sentiment": parsed["sentiment"],
                "subjects": subjects,
                "snippet": snippet,
                "web_realtime": web_realtime,
                "source": {"type": "llm", "name": e["name"]},  # 轻量预留：engine ≠ 未来全部来源
                "citations": _detect_citations(answer, published),
                "answer": answer if full else None,
                "error": None,
            }
        except ValueError as ve:
            return {
                "engine_id": e["id"],
                "engine_name": e["name"],
                "configured": False,
                "mentioned": None,
                "snippet": None,
                "error": str(ve),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "engine_id": e["id"],
                "engine_name": e["name"],
                "configured": True,
                "mentioned": None,
                "snippet": None,
                "error": f"{type(exc).__name__}: {str(exc)[:120]}",
            }

    done = await asyncio.gather(*[_one(e) for e in all_engines])
    results = [r for r in done if r is not None]
    return results


def _summarize(results: list[dict]) -> dict:
    checked = [r for r in results if r.get("mentioned") is not None]
    return {
        "mentioned": sum(1 for r in checked if r["mentioned"]),
        "not_mentioned": sum(1 for r in checked if not r["mentioned"]),
        "unconfigured": sum(1 for r in results if not r["configured"]),
        "score": round(sum(1 for r in checked if r["mentioned"]) / len(checked) * 100) if checked else 0,
    }


@router.get("/history")
async def history(limit: int = 20):
    items = _load_history()
    return ok({"items": items[-limit:][::-1]})


@router.get("/competitor")
async def competitor():
    """全智解析·竞品分析（0.4 升级）：从监测回答聚合竞争认知

    规则估算（诚实标注）：全部指标基于「回答文本词频 + 情感词」，
    **非因果判断，不反映 AI 真实观点**——产品侧禁止把词频当观点。
    只统计 item_type === "competitor" 的对象（brand 对象不混入，防趋势分裂）。

    输出：胜负统计 / 归因词频 / 认知对比 / 能力矩阵（相对分）/ 竞争机会（snippet 溯源）
    """
    hist = _load_history()
    items = _load_items()
    comp_items = [i for i in items if i.get("type") == "competitor" and i.get("status") != "archived"]

    # 归因/矩阵用关键词表（词频估算）
    REASON_WORDS = [
        ("品牌影响", ["品牌", "知名度", "大厂", "巨头", "知名度高", "知名"]),
        ("生态完善", ["生态", "集成", "打通", "一体化", "全家桶", "互通"]),
        ("案例丰富", ["案例", "客户数", "用户量", "企业客户", "落地", "服务了"]),
        ("安全可信", ["安全", "合规", "认证", "可信", "数据安全", "隐私"]),
        ("价格优势", ["免费", "便宜", "性价比", "价格", "成本低", "优惠"]),
        ("AI能力", ["AI", "智能", "大模型", "智能体", "Agent", "自动化"]),
        ("成熟稳定", ["成熟", "稳定", "完善", "可靠", "多年", "老牌"]),
    ]
    MATRIX_DIMS = [
        ("AI能力", ["AI", "智能", "大模型", "智能体", "Agent", "自动化", "算法"]),
        ("产品成熟", ["成熟", "稳定", "完善", "功能", "好用", "文档", "集成"]),
        ("行业深度", ["行业", "制造", "医疗", "零售", "场景", "垂直", "解决方案"]),
        ("品牌影响", ["品牌", "知名度", "大厂", "巨头", "口碑", "知名"]),
        ("生态", ["生态", "集成", "打通", "一体化", "全家桶", "第三方", "开放平台"]),
    ]

    rows: list[dict] = []

    # 同体检测词表（规则估算，诚实红线：仅显式"同一主体"表述才归入，不猜）
    SAME_ENTITY_PATTERNS = [
        "同一家", "同一个", "同一主体", "同一事物", "同一个事物",
        "公司主体", "产品关系", "是这家公司", "这家公司推出",
        "他们家的", "自己家的", "旗下", "隶属", "母子公司", "自研产品",
    ]

    def _same_entity_hit(a: str, t: str, c: str) -> bool:
        if not c or not a:
            return False
        if (t and t not in a) and (c not in a):
            return False
        return any(p in a for p in SAME_ENTITY_PATTERNS)

    def _brand_filter(words: list[str], exclude: list[str]) -> list[str]:
        """认知对比关键词过滤：排除双方品牌名（含子串），避免"关键词=品牌名"假象"""
        skip = [s for s in exclude if s]
        if not skip:
            return words
        return [w for w in words if not any(s in w or w in s for s in skip)]

    for it in comp_items:
        cfg = it.get("config_json") or {}
        target = cfg.get("company") or cfg.get("target") or ""
        comp_cfg = cfg.get("competitor") or ""
        if isinstance(comp_cfg, str):
            comp_cfg = comp_cfg.strip()
            comps = [c.strip() for c in re.split(r"[,，/、]", comp_cfg) if c.strip()]
            if not comps and comp_cfg:
                comps = [comp_cfg]
        else:
            comps = [c for c in comp_cfg if c] if comp_cfg else []
        # 防御：竞品名与 target 相同 → 剔除；无竞品 → 单行占位（前端显示"未配置竞品"）
        comps = [c for c in comps if c and c != target] or [""]
        mid = it.get("monitor_id")
        # 收集该对象所有回答（含 subjects 双主体，旧数据无 subjects → 文本子串回退）
        recs = []
        for h in reversed(hist):
            for q in h.get("questions") or []:
                if q.get("monitor_id") != mid:
                    continue
                for ed in q.get("engine_detail") or []:
                    ans = ed.get("answer") or ed.get("snippet") or ""
                    subj = ed.get("subjects")
                    recs.append(
                        {
                            "question": q.get("question") or q.get("query") or "",
                            "answer": ans,
                            "engine": ed.get("engine_name") or "",
                            "m_company": (subj or {}).get("company", {}).get("mentioned") if subj else None,
                            "r_company": (subj or {}).get("company", {}).get("rank_est") if subj else None,
                            "m_comp": (subj or {}).get("competitor", {}).get("mentioned") if subj else None,
                            "r_comp": (subj or {}).get("competitor", {}).get("rank_est") if subj else None,
                            "s_company": (subj or {}).get("company", {}).get("sentiment") if subj else None,
                            "s_comp": (subj or {}).get("competitor", {}).get("sentiment") if subj else None,
                        }
                    )
        # 2026-09-21 口径修正（Owner：「输出正常但不正确」）：分母只算**真作答**的回答行。
        # 没配 key / 调用失败的引擎在 history 里也留一条 engine_detail（answer 空、mentioned None），
        # 把它算进分母，页面上就会出现「共 96 条回答 · 我方 9% vs 竞品 10%」这种假数字
        # （真实是 16 条回答 · 56% vs 63%）；胜负桶里 92 条 "none" 也不是「AI 没选我们」，
        # 而是「压根没回答」。与 monitor P0-5 口径一致：**没问到 ≠ 没被提及**。
        probe_rows = len(recs)
        recs = [r for r in recs if r.get("answer")]
        total = len(recs)
        unanswered = probe_rows - total
        # 多竞品：每个竞品独立一行（胜负/提及/矩阵各自统计），samples/归因共享回答池
        for comp in comps:
            if total == 0:
                rows.append(
                    {
                        "monitor_id": mid, "target": target, "competitor": comp,
                        "competitors": [comp] if comp else [],
                        "total": 0, "unanswered": unanswered,
                        "target_mentioned": 0, "target_pct": 0,
                        "comp_mentioned": 0, "comp_pct": 0,
                        "same_entity": 0, "same_entity_pct": 0,
                        "win": {"company": 0, "competitor": 0, "none": 0, "same_entity": 0},
                        "win_reasons": [], "samples": [],
                        "company_win_samples": [], "comp_win_samples": [],
                        "none_samples": [], "same_entity_samples": [],
                        "target_mention_samples": [], "comp_mention_samples": [],
                        "perception": {
                            "company": {"snippets": [], "keywords": []},
                            "competitor": {"snippets": [], "keywords": []},
                        },
                        "matrix": [], "opportunities": [],
                        "note": "暂无回答",
                    }
                )
                continue

            # 逐条判定（优先 subjects，旧数据回退文本子串；同体检测优先于胜负）
            win = {"company": 0, "competitor": 0, "none": 0, "same_entity": 0}
            target_mentioned = 0
            comp_mentioned = 0
            samples = []
            win_answers: list[str] = []
            win_recs: list[dict] = []  # 竞品胜出的完整记录（归因因子样本用）
            company_win_samples: list[dict] = []
            comp_win_samples: list[dict] = []
            none_samples: list[dict] = []
            same_entity_samples: list[dict] = []
            target_mention_samples: list[dict] = []
            comp_mention_samples: list[dict] = []
            # 桶内去重（按回答全文）+ 命中词收集
            # seen_full：胜负/同体分桶共享（一条回答只归一个结论桶）；
            # seen_mention：提及桶独立（"提到某方"是超集，允许与结论桶重叠）
            seen_full: set = set()
            seen_mention: set = set()

            def _push(bucket: list[dict], r: dict, a: str, hits: list[str], cap: int = 3, seen: set | None = None):
                seen = seen_full if seen is None else seen
                if not a or a in seen or len(bucket) >= cap:
                    return
                seen.add(a)
                bucket.append(
                    {"question": r["question"], "engine": r["engine"], "answer": a, "hits": hits}
                )
            for r in recs:
                a = r["answer"]
                if r["m_company"] is not None:
                    mc, cc = r["m_company"], r["m_comp"]
                else:
                    mc = bool(target and target in a)
                    cc = bool(comp and comp in a)
                if mc:
                    target_mentioned += 1
                if cc:
                    comp_mentioned += 1
                if _same_entity_hit(a, target, comp):
                    win["same_entity"] += 1
                    kind = "same_entity"
                elif mc and cc:
                    rc = r["r_company"] if r["r_company"] is not None else (a.find(target) + 1 if target in a else 99)
                    rp = r["r_comp"] if r["r_comp"] is not None else (a.find(comp) + 1 if comp in a else 99)
                    if rc < rp:
                        win["company"] += 1
                        kind = "company"
                    elif rp < rc:
                        win["competitor"] += 1
                        kind = "competitor"
                    else:
                        win["none"] += 1
                        kind = "none"
                elif mc:
                    win["company"] += 1
                    kind = "company"
                elif cc:
                    win["competitor"] += 1
                    kind = "competitor"
                else:
                    win["none"] += 1
                    kind = "none"
                if kind == "competitor":
                    win_answers.append(a)
                    win_recs.append(r)
                    _push(
                        comp_win_samples, r, a,
                        [w for _, ws in REASON_WORDS for w in ws if w in a],
                    )
                elif kind == "company":
                    _push(
                        company_win_samples, r, a,
                        [w for _, ws in REASON_WORDS for w in ws if w in a],
                    )
                elif kind == "none":
                    _push(none_samples, r, a, [])
                elif kind == "same_entity":
                    _push(
                        same_entity_samples, r, a,
                        [p for p in SAME_ENTITY_PATTERNS if p in a],
                    )
                if mc:
                    _push(target_mention_samples, r, a, [target] if target else [], cap=3, seen=seen_mention)
                if cc:
                    _push(comp_mention_samples, r, a, [comp] if comp else [], cap=3, seen=seen_mention)
                if len(samples) < 5 and a:
                    samples.append({"question": r["question"], "engine": r["engine"], "answer": a[:240]})

            # 归因词频：竞品胜出的回答里关键词出现占比（sample_n 供前端判断是否展示百分比）
            # 每因子附样本（≤2 条全文 + 命中词）——每个归因结论都有数据支撑
            win_reasons = []
            if win_answers:
                for label, words in REASON_WORDS:
                    cnt = sum(1 for a in win_answers if any(w in a for w in words))
                    if cnt > 0:
                        rs = []
                        for r in win_recs:
                            if len(rs) >= 2:
                                break
                            if any(w in r["answer"] for w in words):
                                rs.append(
                                    {"question": r["question"], "engine": r["engine"], "answer": r["answer"],
                                     "hits": [w for w in words if w in r["answer"]]}
                                )
                        win_reasons.append(
                            {"factor": label, "count": cnt, "pct": round(cnt / len(win_answers) * 100),
                             "sample_n": len(win_answers), "samples": rs}
                        )
                win_reasons.sort(key=lambda x: -x["count"])

            # 认知对比：双方被 AI 描述的回答片段 + 高频词（过滤品牌名）
            def _keywords(ans_list: list[str], n: int = 6) -> list[str]:
                from collections import Counter

                c = Counter()
                for a in ans_list:
                    for w in re.findall(r"[\u4e00-\u9fa5]{2,6}", a):
                        if w in ("一个", "我们", "可以", "企业", "进行", "通过", "这个", "没有", "不是", "就是", "什么", "如何", "以及", "或者", "一些", "对于", "如果", "同时", "提供", "支持", "需要", "能够", "用户", "使用", "产品", "公司"):
                            continue
                        c[w] += 1
                return [w for w, _ in c.most_common(n)]

            def _pick_snippets(recs_list: list[dict], who: str, n: int = 3) -> list[str]:
                out = []
                for r in recs_list:
                    if who == "company":
                        hit = r["m_company"] if r["m_company"] is not None else bool(target and target in r["answer"])
                    else:
                        hit = r["m_comp"] if r["m_comp"] is not None else bool(comp and comp in r["answer"])
                    if hit and len(out) < n:
                        a = r["answer"]
                        idx = a.find(target if who == "company" else comp)
                        out.append(a[max(0, idx - 60) : idx + 160] if idx >= 0 else a[:220])
                return out

            _excl = [target, comp]
            perception = {
                "company": {
                    "snippets": _pick_snippets(recs, "company"),
                    "keywords": _brand_filter(
                        _keywords([r["answer"] for r in recs if (r["m_company"] if r["m_company"] is not None else bool(target and target in r["answer"]))]),
                        _excl,
                    ),
                },
                "competitor": {
                    "snippets": _pick_snippets(recs, "competitor"),
                    "keywords": _brand_filter(
                        _keywords([r["answer"] for r in recs if (r["m_comp"] if r["m_comp"] is not None else bool(comp and comp in r["answer"]))]),
                        _excl,
                    ),
                },
            }

            # 能力矩阵：双方各维词频 + 情感 → 相对分（1-5，归一化；命中样本少时区分度低）
            matrix = []
            for label, words in MATRIX_DIMS:
                my_hits = sum(1 for r in recs if (r["m_company"] if r["m_company"] is not None else bool(target and target in r["answer"])) and any(w in r["answer"] for w in words))
                cp_hits = sum(1 for r in recs if (r["m_comp"] if r["m_comp"] is not None else bool(comp and comp in r["answer"])) and any(w in r["answer"] for w in words))
                denom = max(1, total)
                score_c = round(min(5, max(1, cp_hits / denom * 12)))
                score_t = round(min(5, max(1, my_hits / denom * 12)))
                # 维度样本：命中该维词且提到任一主体的回答（≤2 条全文+hits）——每维都有数据支撑
                dim_samples: list[dict] = []
                for r in recs:
                    if len(dim_samples) >= 2:
                        break
                    a = r["answer"]
                    mentioned = (r["m_company"] if r["m_company"] is not None else bool(target and target in a)) or (
                        r["m_comp"] if r["m_comp"] is not None else bool(comp and comp in a)
                    )
                    if mentioned and any(w in a for w in words):
                        dim_samples.append(
                            {"question": r["question"], "engine": r["engine"], "answer": a,
                             "hits": [w for w in words if w in a]}
                        )
                matrix.append({"dim": label, "company": score_t, "competitor": score_c, "basis": f"{my_hits}/{total} vs {cp_hits}/{total} 条回答出现相关词", "samples": dim_samples})

            # 竞争机会：我方弱维度 + 我方认知关键词缺失 → 可追溯建议
            opportunities = []
            for m in matrix:
                if m["company"] < m["competitor"]:
                    opp = {
                        "title": f"补强「{m['dim']}」认知",
                        "problem": f"AI 回答中关于你方「{m['dim']}」的内容少于竞品",
                        "evidence": [f"能力矩阵 {m['basis']}"],
                        "priority": "high" if m["competitor"] - m["company"] >= 2 else "medium",
                        "recommended_content_type": "案例+白皮书" if m["dim"] in ("产品成熟", "行业深度") else "品牌定位文章",
                    }
                    for r in recs:
                        if (r["m_comp"] if r["m_comp"] is not None else bool(comp and comp in r["answer"])) and any(w in r["answer"] for w in [x[1] for x in MATRIX_DIMS if x[0] == m["dim"]][0]) and len(opp["evidence"]) < 3:
                            a = r["answer"]
                            idx = a.find(comp)
                            opp["evidence"].append(f"「{r['question']}」（{r['engine']}）：{a[max(0, idx - 40):idx + 120]}")
                            break
                    opportunities.append(opp)
            opportunities.sort(key=lambda x: -("high" == x["priority"]))

            rows.append(
                {
                    "monitor_id": mid,
                    "target": target,
                    "competitor": comp,
                    "competitors": [comp] if comp else [],
                    "total": total,
                    "unanswered": unanswered,
                    "target_mentioned": target_mentioned,
                    "target_pct": round(target_mentioned / total * 100) if total else 0,
                    "comp_mentioned": comp_mentioned,
                    "comp_pct": round(comp_mentioned / total * 100) if total else 0,
                    "same_entity": win["same_entity"],
                    "same_entity_pct": round(win["same_entity"] / total * 100) if total else 0,
                    "samples": samples,
                    "win": win,
                    "win_reasons": win_reasons,
                    "company_win_samples": company_win_samples,
                    "comp_win_samples": comp_win_samples,
                    "none_samples": none_samples,
                    "same_entity_samples": same_entity_samples,
                    "target_mention_samples": target_mention_samples,
                    "comp_mention_samples": comp_mention_samples,
                    "perception": perception,
                    "matrix": matrix,
                    "opportunities": opportunities,
                }
            )

    return ok(
        {
            "pairs": rows,
            "note": "规则词频估算（回答文本中公司名出现次数 + 情感词计数），非因果判断，不代表 AI 真实观点",
        }
    )


@router.get("/sources")
async def sources():
    """全智解析·信源分析：各 AI 引擎（信源）的表现排行

    规则估算（诚实标注）：从监测回答聚合每引擎的 提及率/正面率/回答数。
    """
    hist = _load_history()
    per_engine: dict[str, dict] = {}
    for h in reversed(hist):
        for q in h.get("questions") or []:
            for ed in q.get("engine_detail") or []:
                # 2026-08-09 修复：空壳记录（未配置 key / 未真实回答，answer+snippet+mentioned 全空）
                # 是"题库规模"占位，不是该引擎的真实回答——参与统计会伪造"123 条回答 0 提及"假象
                if not (ed.get("answer") or ed.get("snippet")) and ed.get("mentioned") is None:
                    continue
                name = ed.get("engine_name") or "未知"
                e = per_engine.setdefault(name, {"engine": name, "total": 0, "mentioned": 0, "positive": 0, "negative": 0, "neutral": 0})
                e["total"] += 1
                if ed.get("mentioned"):
                    e["mentioned"] += 1
                s = ed.get("sentiment")
                if s == "positive":
                    e["positive"] += 1
                elif s == "negative":
                    e["negative"] += 1
                elif s == "neutral":
                    e["neutral"] += 1
    rows = []
    for e in per_engine.values():
        total = e["total"]
        rows.append(
            {
                "engine": e["engine"],
                "total": total,
                "mentioned": e["mentioned"],
                "mention_pct": round(e["mentioned"] / total * 100) if total else 0,
                "positive": e["positive"],
                "negative": e["negative"],
                "neutral": e["neutral"],
            }
        )
    rows.sort(key=lambda x: (-x["mention_pct"], -x["total"]))
    return ok({"sources": rows, "note": "规则估算：按监测回答聚合，非 LLM 精判"})


@router.get("/answers")
async def answers(limit: int = 100, item_type: str | None = None):
    """0.2+：监测报告数据源——把 history 拍平成逐探针 × 逐引擎的回答列表

    每条 = {ts, monitor_id, item_type, query(探针问题), engine, mentioned,
            rank_est, sentiment, snippet}；按时间倒序，前端按分类/时间筛选。
    旧记录无 monitor_id/engine_detail → 跳过（诚实，不伪造归属）。
    """
    hist = _load_history()
    out: list[dict] = []
    all_items = _load_items()
    for h in reversed(hist):
        ts = h.get("created_at") or h.get("ts") or ""
        qs = h.get("questions")
        if qs:  # batch：逐问题 × 逐引擎
            for q in qs:
                mid = q.get("monitor_id")
                if not mid:
                    continue
                # 取 item 类型（从 items 表反查；查不到标 unknown）
                meta = next((x for x in all_items if x.get("monitor_id") == mid), None)
                itype = (meta or {}).get("type") or "question"
                if item_type and itype != item_type:
                    continue
                for ed in q.get("engine_detail") or []:
                    out.append(
                        {
                            "ts": ts,
                            "monitor_id": mid,
                            "item_type": itype,
                            "query": q.get("query") or q.get("question") or "",
                            "engine": ed.get("engine_name") or "",
                            "mentioned": ed.get("mentioned"),
                            "rank_est": ed.get("rank_est"),
                            "sentiment": ed.get("sentiment"),
                            "snippet": ed.get("snippet") or "",
                            "answer": ed.get("answer") or "",
                        }
                    )
        else:  # 单条 check：问题带 company 但无 item 归属 → 跳过（由监测对象体系产生）
            continue
        if len(out) >= limit:
            break
    return ok({"answers": out[:limit], "total": len(out[:limit])})


@router.post("/check")
async def check(payload: MonitorCheckIn):
    question = payload.question.strip()
    if not question:
        return ok({"question": question, "company_name": payload.company_name, "results": [], "summary": None})

    from adapters.engines import EngineFaceError

    try:
        results = await _run_check(question, payload.company_name, payload.engines, payload.full)
    except EngineFaceError as exc:
        return err(exc.code, exc.message)
    summary = _summarize(results)
    # P0：单条 check 也聚合排名/评价（评价分析/驾驶舱统计单次监测）
    ranks = [r["rank_est"] for r in results if r.get("rank_est") is not None]
    summary["rank_avg"] = round(sum(ranks) / len(ranks), 1) if ranks else None
    sents = [r.get("sentiment") for r in results if r.get("sentiment")]
    summary["sentiment_summary"] = {
        "positive": sum(1 for s in sents if s == "positive"),
        "negative": sum(1 for s in sents if s == "negative"),
        "neutral": sum(1 for s in sents if s == "neutral"),
    }

    # 2026-08-15 修复：改 _append_history 单条追加（原 `_save_history(items[-100:])`
    # 整表替换只留最近 100 条，频繁单次监测会静默丢历史；append 不丢且触发
    # intelligence 钩子——单次 check 数据也进入分析层）
    _append_history(
        {
            "id": f"h_{uuid.uuid4().hex[:12]}",
            "question": question,
            "company_name": payload.company_name,
            "summary": summary,
            "engine_detail": [
                {
                    "engine_name": r.get("engine_name"),
                    "mentioned": r.get("mentioned"),
                    "rank_est": r.get("rank_est"),
                    "sentiment": r.get("sentiment"),
                    "snippet": (r.get("snippet") or "")[:240],
                }
                for r in results
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    return ok({"question": question, "company_name": payload.company_name, "results": results, "summary": summary})


@router.post("/batch")
async def batch(payload: BatchIn):
    """批量监测：支持两入口（0.2 统一内部流程，不留两套执行逻辑）

    - 旧入口 questions[]：自动转临时 MonitorItem（type=question，temporary=True）
    - 新入口 items[]：MonitorItem → generate_queries → 引擎采集
    - 无任何入口 → 默认跑全部 active 监测对象
    """
    # 旧入口 → 临时 question item（外部兼容，内部统一）
    temp_items: list[dict] = []
    for q in payload.questions or []:
        q = (q or "").strip()
        if q:
            temp_items.append(
                {
                    "monitor_id": f"tmp_{hashlib.md5(q.encode()).hexdigest()[:8]}",
                    "type": "question",
                    "config_json": {"query": q},
                    "temporary": True,
                    "entity": payload.company_name,
                }
            )
    if payload.items is not None:
        temp_items = [dict(i) for i in payload.items]

    # 无入口 → 默认全部 active items
    if not temp_items:
        temp_items = [i for i in _load_items() if i.get("status") == "active"]

    if not temp_items:
        return ok({"items": [], "results": [], "summary": None})

    data = await run_batch_items(temp_items, payload.company_name, payload.engines)
    return ok(data)


async def run_batch_items(items: list[dict], company_name: str | None = None, engines: list[str] | None = None, progress_cb: callable = None) -> dict:
    """0.2 统一批量监测核心：MonitorItem → generate_queries → 引擎采集 → history

    与旧 run_batch 的差异：每问题带 monitor_id/query_id（跨次对比锚点），
    engine_detail 带 source（轻量预留：engine ≠ 未来全部采集来源）。
    progress_cb(done, total)：探针级进度回调（编排/长任务用，可选）。
    """
    # 一个引擎都没有时，先如实收场（沿用既有 skipped 形状）：跑一遍空探针只会得到
    # 「0 个答案」，看不出原因。Owner 2026-09-21：「GEO 不再写死 6 个」——有几个看部署。
    from adapters.engines import EngineFaceError, list_engines

    try:
        deployment_engines = await list_engines()
    except EngineFaceError as exc:
        return {"summary": None, "results": [], "skipped": f"{exc.code}：{exc.message}"}
    if not deployment_engines:
        return {"summary": None, "results": [], "skipped": "这个部署还没有登记任何模型"}

    # 生成探针：item → queries（保留 item 归属）
    probes: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        qs = generate_queries(it, {"company_name": company_name})
        if not qs:
            continue
        company = _item_company(it) or company_name
        aliases = (it.get("config_json") or {}).get("aliases") or []
        # 双主体：competitor 对象带竞品名（config.competitor 单值主竞品 + 别名）
        cfg = it.get("config_json") or {}
        comp_name = cfg.get("competitor") if it.get("type") == "competitor" else None
        if isinstance(comp_name, list):
            comp_name = comp_name[0] if comp_name else None
        comp_aliases = cfg.get("competitor_aliases") or []
        for q in qs:
            probes.append(
                {
                    "item": it,
                    "query": q,
                    "company": company,
                    "aliases": aliases,
                    "competitor": comp_name,
                    "competitor_aliases": comp_aliases,
                }
            )

    results = []
    cited_map: dict[str, dict] = {}
    # 2026-08-15 修复：探针并发（原串行 for await，N 探针 × 6 引擎 × 15s 最坏极慢）；
    # asyncio.Semaphore(4) 限并发防打爆引擎；gather 保持顺序（与 probes 一致）
    import asyncio as _asyncio

    _probe_sem = _asyncio.Semaphore(4)

    async def _probe_one(p: dict) -> list:
        q = p["query"]
        async with _probe_sem:
            try:
                return await _run_check(
                    q, p["company"], engines, True,
                    aliases=p["aliases"], competitor_name=p.get("competitor"),
                    competitor_aliases=p.get("competitor_aliases"),
                )
            except Exception as e:  # noqa: BLE001
                import logging

                logging.getLogger("eios.monitor").warning("探针失败跳过: %s (%s)", q[:40], str(e)[:120])
                return []

    engine_results_all = await _asyncio.gather(*(_probe_one(p) for p in probes))
    for p, engine_results in zip(probes, engine_results_all):
        q = p["query"]
        if progress_cb:
            progress_cb(len(results) + 1, len(probes))
        mentioned_count = sum(1 for r in engine_results if r.get("mentioned"))
        configured_count = sum(1 for r in engine_results if r.get("configured"))
        # 审计 P0-5：answered = 至少一个引擎成功回答（mentioned 非 None），
        # error 引擎不进 coverage 分母（"没问到"≠"没被提及"）
        answered_count = sum(1 for r in engine_results if r.get("mentioned") is not None)
        ranks = [r["rank_est"] for r in engine_results if r.get("rank_est") is not None]
        rank_avg = round(sum(ranks) / len(ranks), 1) if ranks else None
        sents = [r.get("sentiment") for r in engine_results if r.get("sentiment")]
        sentiment_summary = {
            "positive": sum(1 for s in sents if s == "positive"),
            "negative": sum(1 for s in sents if s == "negative"),
            "neutral": sum(1 for s in sents if s == "neutral"),
        }
        q_cited: dict[str, dict] = {}
        for er in engine_results:
            for c in er.get("citations") or []:
                mid = c["material_id"]
                entry = q_cited.setdefault(mid, {"count": 0, "title": c["title"], "snippet": c.get("snippet", "")})
                entry["count"] += 1
        results.append(
            {
                "monitor_id": p["item"].get("monitor_id") or "",
                "item_type": p["item"].get("type"),
                "query_id": f"qy_{hashlib.md5(q.encode()).hexdigest()[:8]}",
                "question": q,
                "engine_results": engine_results,
                "mentioned_count": mentioned_count,
                "configured_count": configured_count,
                "answered_count": answered_count,
                "rank_avg": rank_avg,
                "sentiment_summary": sentiment_summary,
                "citations": list(q_cited.values()),
            }
        )
        for mid, e in q_cited.items():
            g = cited_map.setdefault(mid, {"material_id": mid, "title": e["title"], "count": 0, "snippets": [], "questions": []})
            g["count"] += e["count"]
            if e["snippet"] and e["snippet"] not in g["snippets"]:
                g["snippets"].append(e["snippet"])
            if q not in g["questions"]:
                g["questions"].append(q)

    citations_summary = sorted(cited_map.values(), key=lambda x: -x["count"])
    for c in citations_summary:
        c["snippets"] = c["snippets"][:3]

    total = len(results)
    answered_questions = sum(1 for x in results if x.get("answered_count", 0) > 0)
    mentioned_questions = sum(1 for x in results if x["mentioned_count"] > 0)
    # 审计 P0-5 口径：分母=有回答的问题（error 引擎问题不算"未提及"，不拉低覆盖）
    coverage = round(mentioned_questions / answered_questions * 100) if answered_questions else 0
    weak = [x["question"] for x in results if x.get("answered_count", 0) > 0 and x["mentioned_count"] == 0]
    all_ranks = [x["rank_avg"] for x in results if x.get("rank_avg") is not None]
    batch_rank_avg = round(sum(all_ranks) / len(all_ranks), 1) if all_ranks else None
    batch_sentiment = {
        "positive": sum((x.get("sentiment_summary") or {}).get("positive", 0) for x in results),
        "negative": sum((x.get("sentiment_summary") or {}).get("negative", 0) for x in results),
        "neutral": sum((x.get("sentiment_summary") or {}).get("neutral", 0) for x in results),
    }
    summary = {
        "total_questions": total,
        "answered_questions": answered_questions,
        "mentioned_questions": mentioned_questions,
        "coverage_pct": coverage,
        "weak_questions": weak,
        "rank_avg": batch_rank_avg,
        "sentiment_summary": batch_sentiment,
    }

    items2 = _load_history()
    hist_rec = {
        # 修复（审计 H3）：原 `h_{len(items2)+1}` 在历史 ID 不连续时（如 h_1、h_3 并存）
        # 会撞 UNIQUE 约束 → 整批监测结果落库失败、蒸馏不接续。改用 uuid 保证唯一。
        "id": f"h_{uuid.uuid4().hex[:12]}",
        "question": f"批量监测（{total} 个问题）",
        "company_name": company_name,
        "summary": {
            "mentioned": mentioned_questions,
            "not_mentioned": answered_questions - mentioned_questions,
            "score": coverage,
            "unconfigured": 0,
            "total_questions": total,
            "answered_questions": answered_questions,
            "mentioned_questions": mentioned_questions,
            "coverage_pct": coverage,
            "weak_questions": weak,
            "rank_avg": batch_rank_avg,
            "sentiment_summary": batch_sentiment,
        },
        "questions": [
            {
                "monitor_id": x.get("monitor_id"),
                "item_type": x.get("item_type"),
                "query_id": x.get("query_id"),
                "question": x["question"],
                "mentioned_count": x["mentioned_count"],
                "configured_count": x["configured_count"],
                "answered_count": x["answered_count"],
                "rank_avg": x["rank_avg"],
                "sentiment_summary": x["sentiment_summary"],
                "citations": len(x.get("citations") or []),
                "engine_detail": [
                    {
                        "engine_name": er.get("engine_name"),
                        "source": {"type": "llm", "name": er.get("engine_name")},  # 轻量预留：engine ≠ 未来全部来源
                        "mentioned": er.get("mentioned"),
                        "rank_est": er.get("rank_est"),
                        "sentiment": er.get("sentiment"),
                        "subjects": er.get("subjects"),  # 双主体（竞品探针）：company/competitor 各 mentioned/rank/sentiment
                        "snippet": (er.get("snippet") or "")[:240],
                        "answer": er.get("answer") or "",  # 全文（监测报告展开用；full=True 时采集）
                        "error": er.get("error"),  # 运行状态审计：失败原因必须跟历史一起保存
                    }
                    for er in x.get("engine_results") or []
                ],
            }
            for x in results
        ],
        "citations": citations_summary,
        "batch": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _append_history(hist_rec)

    # 蒸馏钩子（2026-08-10）：任何批量监测完成后自动接蒸馏闭环（问题→缺口→计划→机会）。
    # 幂等（去重）：重复跑不产生重复缺口/计划；失败不影响监测返回（fire-and-forget）。
    # 覆盖：自动配置 run / 手动批量监测 / 每日定时监测——统一在此触发，不留独立入口。
    try:
        _seeds: list[str] = []
        _seen_s: set[str] = set()
        for _it in items:
            _cfg = _it.get("config_json") or {}
            _t = _it.get("type")
            _cand = None
            if _t == "product":
                _cand = _cfg.get("product") or _it.get("entity")
            elif _t == "keyword":
                _cand = _cfg.get("keyword")
            elif _t == "brand":
                _cand = _cfg.get("company")
            if _cand and str(_cand).strip() and str(_cand).strip() not in _seen_s:
                _seen_s.add(str(_cand).strip())
                _seeds.append(str(_cand).strip())
            if len(_seeds) >= 10:
                break

        async def _distill_after_run() -> None:
            try:
                from app.api.v1 import distill as D

                # 等解析排空再蒸馏（手动批量监测/每日定时同一链路：机会必须基于完整解析数据）
                try:
                    from services.intelligence import queue as Q

                    await Q.wait_drained(timeout=1200)
                except Exception:  # noqa: BLE001
                    pass
                qr = await D.gen_questions(D.QuestionsIn(seed_keywords=_seeds, count=10))
                _ = qr  # 问题池（gen_questions 内部兜底：种子空则 _auto_keywords）
                await D.detect_gaps(limit=30)
                await D.gen_opportunities(limit=15)
                # 审计 B11：自动链以前跑的是 gen_plans（缺口 → LLM 直接编计划的旧算法），
                # 而 2026-08-19 拍板的新算法（问题价值×AI缺口 → 48 子项压力 → 内容计划）
                # 只有 UI 手动点才跑 → 同一张表两种口径，自动来的没有 subitem/before_snapshot，
                # 复测无从对比。自动链改为跑新算法，与 UI 手动口径一致。
                await D.gen_content_plan(limit=10)
                import logging

                logging.getLogger("eios.monitor").info("[distill hook] 监测后蒸馏闭环完成（缺口/机会/内容计划V1）")
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger("eios.monitor").exception("distill hook failed (不影响监测)")

        asyncio.get_running_loop().create_task(_distill_after_run())
    except Exception:  # noqa: BLE001
        pass

    return {"items": items, "results": results, "summary": summary, "citations": citations_summary}


@router.get("/export")
async def export_report():
    """导出监测报告（markdown）：批量监测汇总 + 薄弱问题榜 + 内容建议

    给老板/客户看的一页报告：覆盖率 + 薄弱问题 + 下一步该做什么。
    """
    items = _load_history()
    batches = [i for i in items if i.get("batch")]
    latest = batches[-1] if batches else None

    lines = ["# GEO 曝光监测报告", ""]
    if not items:
        lines += ["暂无监测数据。", "", "> 在「报告」页输入问题池并运行批量监测后生成。"]
        return ok({"markdown": "\n".join(lines), "error": None})

    lines += [
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()[:19]}",
        f"- 监测总次数：{len(items)} 次（其中批量监测 {len(batches)} 次）",
    ]
    if latest:
        s = latest.get("summary", {})
        total = s.get("total_questions") if s.get("total_questions") is not None else (s.get("mentioned", 0) + s.get("not_mentioned", 0))
        mentioned = s.get("mentioned_questions") if s.get("mentioned_questions") is not None else s.get("mentioned", 0)
        coverage = s.get("coverage_pct") if s.get("coverage_pct") is not None else s.get("score", 0)
        lines += ["", "## 一、最近一次批量监测", "",
                  f"- 监测问题数：{total} 个",
                  f"- 被 AI 搜索提到：{mentioned} 个",
                  f"- **曝光覆盖率：{coverage}%**"]
        weak = s.get("weak_questions") or []
        if weak:
            lines += ["", "## 二、薄弱问题（AI 回答未提及企业）", ""]
            lines += [f"{i + 1}. {q}" for i, q in enumerate(weak)]
            lines += ["", "## 三、被 AI 引用的内容", ""]
            cited = latest.get("citations") or []
            if cited:
                for c in cited[:6]:
                    lines.append(f"- 《{c.get('title', '')}》：被引用 {c.get('count', 0)} 次（回答「{('、'.join((c.get('questions') or [])[:2]))}」时提及）")
            else:
                lines.append("暂无——发布内容到内容资产后重新监测，这里会显示哪些内容被 AI 提到了。")
            lines += ["", "## 四、内容建议", "",
                      "以下问题说明 AI 在回答时不知道或未推荐本企业，建议优先生产内容补齐："]
            lines += [f"- 为「{q}」生产 FAQ / 文章（存入内容资产，内容生成自动引用）" for q in weak[:6]]
            lines += ["", "> 生产内容并人工发布后，重新运行批量监测，验证覆盖率是否提升。"]
        else:
            lines += ["", "## 二、薄弱问题", "", "无——本批问题全部被 AI 提及 ✓",
                      "", "## 三、被 AI 引用的内容", ""]
            cited = latest.get("citations") or []
            if cited:
                for c in cited[:6]:
                    lines.append(f"- 《{c.get('title', '')}》：被引用 {c.get('count', 0)} 次（回答「{('、'.join((c.get('questions') or [])[:2]))}」时提及）")
            else:
                lines.append("暂无——发布内容到内容资产后重新监测。")
    lines += ["", "---", "", "*由 EIOS GEO 自动生成（数据来自 6 国内 AI 引擎曝光监测）*"]
    return ok({"markdown": "\n".join(lines), "error": None})


@router.get("/citations")
async def list_citations(limit: int = 10):
    """被 AI 引用的内容 Top N（S2：聚合 history batch 条目的 citations 字段）"""
    items = _load_history()
    agg: dict[str, dict] = {}
    for h in items:
        for c in h.get("citations") or []:
            mid = c.get("material_id")
            if not mid:
                continue
            g = agg.setdefault(mid, {"material_id": mid, "title": c.get("title", ""), "count": 0, "snippets": [], "questions": []})
            g["count"] += c.get("count", 0)
            for s in (c.get("snippets") or [])[:1]:
                if s and s not in g["snippets"]:
                    g["snippets"].append(s)
            for q in (c.get("questions") or []):
                if q and q not in g["questions"]:
                    g["questions"].append(q)
    top = sorted(agg.values(), key=lambda x: -x["count"])[:limit]
    return ok({"items": top, "total": len(agg)})


class PoolIn(BaseModel):
    company_name: str | None = None
    questions: list[str] = []


@router.get("/pool")
async def get_pool():
    return ok(_load_pool())


@router.post("/pool")
async def save_pool(payload: PoolIn):
    pool = {
        "company_name": payload.company_name,
        "questions": [q.strip() for q in payload.questions if q and q.strip()],
    }
    _save_pool(pool)
    return ok(pool)


@router.post("/generate-questions")
async def generate_questions(payload: GenerateQuestionsIn):
    """AI 生成客户问题（问题池来源）：围绕企业/行业生成真实搜索问法

    一切从知识库找（对齐蒸馏页）：企业名空 → 自动识别企业实体；
    行业空 → 自动提取 企业知识库产品/服务实体作为关键词依据。
    """
    from adapters.llm import chat, LLMNotConfiguredError, LLMError

    company = payload.company_name
    if not company:
        try:
            from adapters.eios import get_entities

            ents = await get_entities()
            for e in ents or []:
                name = e.get("canonical_name") or e.get("name") or ""
                if any(k in name for k in ("有限公司", "集团", "科技")):
                    company = name
                    break
        except Exception:  # noqa: BLE001
            pass

    # 自动提取产品/服务关键词（企业知识库实体，与蒸馏页同源）
    keywords: list[str] = []
    if not payload.industry:
        try:
            from app.api.v1.distill import _auto_keywords

            keywords = await _auto_keywords()
        except Exception:  # noqa: BLE001
            keywords = []

    ctx = []
    if company:
        ctx.append(f"企业：{company}")
    if payload.industry:
        ctx.append(f"行业：{payload.industry}")
    if keywords:
        ctx.append(f"企业产品/服务：{'、'.join(keywords[:5])}")
    ctx_line = "、".join(ctx) if ctx else "该企业所在行业"
    prompt = (
        f"围绕「{ctx_line}」，生成 {payload.count} 个客户最常搜索/询问 AI 的问题（中文，贴近真实搜索场景："
        "如'XX多少钱'、'XX哪家好'、'XX怎么选'、'XX和YY哪个好'、'XX效果怎么样'等）。\n"
        '严格按 JSON 数组输出，不要其他内容：["问题1", "问题2", ...]'
    )
    try:
        text = await chat(prompt, max_tokens=500)
    except LLMNotConfiguredError as e:
        return ok({"questions": [], "error": str(e)})
    except LLMError as e:
        return ok({"questions": [], "error": e.message})
    m = re.search(r"\[[\s\S]*\]", text)
    questions = []
    if m:
        try:
            questions = json.loads(m.group(0))[: payload.count]
        except Exception:  # noqa: BLE001
            questions = []
    questions = [str(q).strip() for q in questions if str(q).strip()]
    return ok({
        "questions": questions,
        "error": None,
        "source": {"company": company, "keywords": keywords[:5]},
    })


# ── S0：单内容效果卡（material 侧聚合，不加 history 字段） ──


def _material_effects_sync(material_id: str) -> dict:
    """单内容效果卡：用素材 coverage_questions × 监测历史统计命中

    material↔question 多对多，不做 monitor/history 加 asset_id（避免脏关联）；
    聚合源 = 单次 check 记录（question 精确匹配）+ 批量监测明细（questions 数组）。
    三态：未发布 / 已发布无数据 / 有数据（有发布前记录才有基线对比）。
    """
    try:
        from app.services.store import get_store

        items = get_store().load("kb")
    except Exception:  # noqa: BLE001
        items = []
    mat = next((m for m in items if m.get("id") == material_id), None)
    if not mat:
        return {"error": "素材不存在"}

    questions = mat.get("coverage_questions") or []
    published_at = mat.get("published_at")
    if not published_at:
        return {
            "material_id": material_id,
            "published": False,
            "message": "未发布，无效果数据",
            "has_baseline": False,
            "covered_questions": questions,
            "mentioned_questions": [],
            "weak_questions": [],
            "mentioned_count": 0,
            "total_checks": 0,
            "before": None,
            "trend": [],
            "conclusion": None,
        }

    history = _load_history()
    hits: list[dict] = []
    for h in history:
        ts = h.get("created_at", "")
        if h.get("question") in questions:
            sm = h.get("summary") or {}
            hits.append({
                "ts": ts,
                "question": h.get("question"),
                "mentioned": sm.get("mentioned", 0),
                "configured": sm.get("mentioned", 0) + sm.get("not_mentioned", 0),
            })
        if h.get("batch"):
            for q in h.get("questions") or []:
                if q.get("question") in questions:
                    hits.append({
                        "ts": ts,
                        "question": q.get("question"),
                        "mentioned": q.get("mentioned_count", 0),
                        "configured": q.get("answered_count") if q.get("answered_count") is not None else sum(1 for e in (q.get("engine_detail") or []) if e.get("mentioned") is not None),
                    })
    hits.sort(key=lambda x: x["ts"])
    after = [x for x in hits if x["ts"] >= published_at]
    before = [x for x in hits if x["ts"] < published_at]
    if not after:
        return {
            "material_id": material_id,
            "published": True,
            "data_empty": True,
            "message": "已发布，暂无监测数据",
            "has_baseline": bool(before),
            "covered_questions": questions,
            "mentioned_questions": [],
            "weak_questions": [],
            "mentioned_count": 0,
            "total_checks": 0,
            "before": None,
            "trend": [],
            "conclusion": None,
        }

    # 每次监测一个趋势点（同 ts 多条命中合并；问题级：几个覆盖问题被提到）
    by_ts: dict[str, dict] = {}
    for x in after:
        d = by_ts.setdefault(x["ts"], {"ts": x["ts"], "mentioned_questions": 0, "total_questions": len(questions), "engine_checks": 0})
        if x["mentioned"] > 0:
            d["mentioned_questions"] += 1
        d["engine_checks"] += x["configured"]
    trend = sorted(by_ts.values(), key=lambda t: t["ts"])
    latest_ts = trend[-1]["ts"]
    latest_hits = [x for x in after if x["ts"] == latest_ts]
    mentioned_q_set = {x["question"] for x in latest_hits if x["mentioned"] > 0}
    mentioned_q = len(mentioned_q_set)
    weak_q = [q for q in questions if q not in mentioned_q_set]
    engine_mentioned = sum(x["mentioned"] for x in latest_hits)
    engine_total = sum(x["configured"] for x in latest_hits)

    before_point = None
    if before:
        b_ts = before[-1]["ts"]
        b_hits = [x for x in before if x["ts"] == b_ts]
        before_point = {
            "mentioned_questions": len({x["question"] for x in b_hits if x["mentioned"] > 0}),
            "engine_mentioned": sum(x["mentioned"] for x in b_hits),
            "engine_total": sum(x["configured"] for x in b_hits),
        }

    conclusion = f"发布后监测 {len(trend)} 次，覆盖问题 {len(questions)} 个中 {mentioned_q} 个被 AI 提到"
    if weak_q:
        conclusion += f"；薄弱：「{'」「'.join(weak_q[:3])}」仍未覆盖"
    if before_point:
        conclusion += f"（发布前 {before_point['mentioned_questions']}/{len(questions)} → 发布后 {mentioned_q}/{len(questions)}）"
    # S2：该素材在 history batch citations 里的累计引用
    citations_count = 0
    for h in history:
        for c in h.get("citations") or []:
            if c.get("material_id") == material_id:
                citations_count += c.get("count", 0)
    if citations_count:
        conclusion += f"；内容被 AI 引用 {citations_count} 次"

    return {
        "material_id": material_id,
        "published": True,
        "data_empty": False,
        "message": None,
        "has_baseline": bool(before),
        "covered_questions": questions,
        "mentioned_questions": sorted(mentioned_q_set),
        "weak_questions": weak_q,
        "mentioned_count": engine_mentioned,
        "total_checks": engine_total,
        "citations_count": citations_count,
        "before": before_point,
        "trend": trend,
        "conclusion": conclusion,
    }


@router.get("/effects")
async def material_effects(material_id: str):
    """单内容效果卡（S0）：素材详情弹窗「效果」区块数据源"""
    return ok(_material_effects_sync(material_id))


# ── P0：排名 + 评价聚合接口（数据可视化：驾驶舱/评价分析/舆情分析共用） ──


def _aggregate_rank_sentiment(items: list[dict]) -> dict:
    """从 history 聚合平均排名（估算）+ 评价分布 + 逐批次趋势

    兼容旧数据：batch 条目读 summary.rank_avg/sentiment_summary（无字段跳过），
    单条 check 条目无这些字段（旧记录）→ 只参与趋势统计不参与排名/评价聚合。
    返回 rank_avg / sentiment / trend（按批次时间正序，每批一个点）。
    """
    ranks: list[float] = []
    sent = {"positive": 0, "negative": 0, "neutral": 0}
    trend: list[dict] = []
    for h in items:
        s = h.get("summary") or {}
        rank_avg = s.get("rank_avg")
        if rank_avg is not None:
            ranks.append(float(rank_avg))
        ss = s.get("sentiment_summary") or {}
        for k in ("positive", "negative", "neutral"):
            sent[k] += int(ss.get(k, 0))
        # 趋势点：有 coverage 的 batch 才画点（单次 check 无 coverage_pct 不参与）
        if s.get("coverage_pct") is not None:
            trend.append(
                {
                    "ts": h.get("created_at", ""),
                    "coverage_pct": s.get("coverage_pct"),
                    "rank_avg": rank_avg,
                    "positive": ss.get("positive", 0),
                    "negative": ss.get("negative", 0),
                    "neutral": ss.get("neutral", 0),
                    "citations": len(h.get("citations") or []),
                }
            )
    trend.sort(key=lambda t: t["ts"])
    return {
        "rank_avg": round(sum(ranks) / len(ranks), 1) if ranks else None,
        "rank_samples": len(ranks),
        "sentiment": sent,
        "sentiment_total": sent["positive"] + sent["negative"] + sent["neutral"],
        "trend": trend,
    }


@router.get("/rank-sentiment")
async def rank_sentiment():
    """P0：平均排名（估算）+ 评价分布 + 趋势（驾驶舱/评价分析共用）"""
    return ok(_aggregate_rank_sentiment(_load_history()))


def _aggregate_overview(items: list[dict]) -> dict:
    """数据总览四指标 + 分平台趋势（驾驶舱）

    指标口径（冻结，见产品目标 V2 第四节；语义 08-08 拍板=提及率）：
    - 推荐度 = 监测问题中"AI 回答提及企业"的问题占比（= coverage_pct，规则估算；提及≠正面推荐）
    - 平均排名 = 企业名首次出现句序号均值（估算，未提及不参与）
    - 内容引用数 = history batch citations 累计次数
    - 内容引用率 = 被引用素材数 ÷ 已发布素材数（读 kb 表）
    分平台趋势：batch 条目的 questions[].engine_detail 按平台聚合推荐度
    （每批一个点：该平台 mentioned/configured 合计）。
    """
    batches = [h for h in items if h.get("batch")]

    # 四指标（用最新 batch 与上期对比；无上期 → 持平）
    latest = batches[-1] if batches else None
    prev = batches[-2] if len(batches) >= 2 else None
    latest_s = (latest or {}).get("summary") or {}
    prev_s = (prev or {}).get("summary") or {}

    rec = {
        "value": latest_s.get("coverage_pct"),
        "delta": None if prev is None or latest_s.get("coverage_pct") == prev_s.get("coverage_pct")
        else round((latest_s.get("coverage_pct") or 0) - (prev_s.get("coverage_pct") or 0), 1),
    }
    rank = {
        "value": latest_s.get("rank_avg"),
        "delta": None if prev is None or latest_s.get("rank_avg") == prev_s.get("rank_avg")
        else round((latest_s.get("rank_avg") or 0) - (prev_s.get("rank_avg") or 0), 1),
    }

    # 内容引用数：全部 batch citations 累计
    citations_count = sum(c.get("count", 0) for h in items for c in (h.get("citations") or []))
    # 内容引用率：被引用素材数 ÷ 已发布素材数
    try:
        from app.services.store import get_store
        kbs = get_store().load("kb")
    except Exception:  # noqa: BLE001
        kbs = []
    published = [m for m in kbs if m.get("published_at")]
    cited_ids = {c.get("material_id") for h in items for c in (h.get("citations") or []) if c.get("material_id")}
    cited_pub = [m for m in published if m.get("id") in cited_ids]
    cite_rate = round(len(cited_pub) / len(published) * 100, 1) if published else None

    # 分平台趋势（逐批次，engine_detail 聚合）
    platform_order: list[str] = []
    platform_points: dict[str, list[dict]] = {}
    for h in batches:
        ts = h.get("created_at", "")
        per_platform: dict[str, dict] = {}
        for q in h.get("questions") or []:
            for er in q.get("engine_detail") or []:
                name = er.get("engine_name")
                # 没配凭据或调用失败时 mentioned=None：这是「没有回答」，不是 0% 提及。
                # 不为这类探针创建平台趋势点，否则总览会把六个登记模型全部画成 0%。
                if not name or er.get("mentioned") is None:
                    continue
                p = per_platform.setdefault(name, {"mentioned": 0, "configured": 0})
                if er.get("mentioned") is True:
                    p["mentioned"] += 1
                p["configured"] += 1
        for name, p in per_platform.items():
            if name not in platform_points:
                platform_points[name] = []
                platform_order.append(name)
            platform_points[name].append(
                {
                    "ts": ts,
                    "recommend_pct": round(p["mentioned"] / p["configured"] * 100) if p["configured"] else 0,
                    "mentioned": p["mentioned"],
                    "configured": p["configured"],
                }
            )

    return {
        "recommend": rec,
        "rank": rank,
        "citations_count": citations_count,
        "cite_rate": cite_rate,
        "published_count": len(published),
        "cited_count": len(cited_pub),
        "latest_batch_at": latest.get("created_at") if latest else None,
        "platforms": {name: platform_points[name] for name in platform_order},
        # 逐问题明细（对齐竞品"优化单元"表：推荐度/排名/评价/引用率）
        "questions": [
            {
                "question": q.get("question"),
                "recommend_pct": round(
                    q.get("mentioned_count", 0) / q.get("answered_count", 0) * 100
                ) if q.get("answered_count") else round(
                    q.get("mentioned_count", 0) / q.get("configured_count", 0) * 100
                ) if q.get("configured_count") else 0,
                "rank_avg": q.get("rank_avg"),
                "sentiment_summary": q.get("sentiment_summary") or {},
                "citations": q.get("citations", 0),
            }
            for q in ((latest or {}).get("questions") or [])
        ],
    }


@router.get("/overview")
async def overview():
    """P0：数据总览驾驶舱四指标 + 分平台趋势"""
    return ok(_aggregate_overview(_load_history()))


def _aggregate_public_opinion(items: list[dict]) -> dict:
    """舆情分析页（对齐竞品 7 区块）：健康分 + 四指标 + 趋势 + 平台分布 + 高风险 top3 + 明细

    数据源：history 的 engine_detail（单次 check + batch questions 明细都算），
    只统计 sentiment 非 None（即 AI 提到企业）的回答——诚实红线。
    - 健康分 = 100 − 负面占比×100（负面回答数 ÷ 已判定回答数）
    - 检测记录数 = 已判定回答数（有 sentiment 的 engine 记录）
    - 舆情风险数 = 负面回答数
    - 影响用户意图 = 出现负面回答的问题数（按 question 去重）
    - 影响优化单元 = 0（优化单元 P1-6 落地前诚实为 0）
    - 趋势 = 逐批次负面占比（每批一个点，仅 batch）
    - 平台分布 = 每平台负面率（聚合全部 history）
    - 高风险 top3 = 负面回答最多的问题
    - 明细 = 逐条（question/platform/sentiment/ts），按时间倒序
    """
    # 收集所有已判定回答（sentiment 非 None）
    records: list[dict] = []
    for h in items:
        ts = h.get("created_at", "")
        batch = bool(h.get("batch"))
        if batch:
            for qi in h.get("questions") or []:
                q = qi.get("question")
                for er in qi.get("engine_detail") or []:
                    s = er.get("sentiment")
                    if s is not None:
                        records.append({
                            "question": q,
                            "platform": er.get("engine_name"),
                            "sentiment": s,
                            "ts": ts,
                        })
        else:
            q = h.get("question")
            for er in h.get("engine_detail") or []:
                s = er.get("sentiment")
                if s is not None:
                    records.append({
                        "question": q,
                        "platform": er.get("engine_name"),
                        "sentiment": s,
                        "ts": ts,
                    })

    total = len(records)
    neg = sum(1 for r in records if r["sentiment"] == "negative")
    pos = sum(1 for r in records if r["sentiment"] == "positive")
    neu = sum(1 for r in records if r["sentiment"] == "neutral")
    neg_pct = round(neg / total * 100) if total else 0
    health = max(0, 100 - neg_pct) if total else None
    health_label = "良好" if health is not None and health >= 80 else ("一般" if health is not None and health >= 60 else ("偏低" if health is not None else None))

    # 影响用户意图（负面问题去重）
    neg_questions = sorted({r["question"] for r in records if r["sentiment"] == "negative"})

    # 高风险 top3（负面回答最多的意图）
    by_q: dict[str, int] = {}
    for r in records:
        if r["sentiment"] == "negative":
            by_q[r["question"]] = by_q.get(r["question"], 0) + 1
    risk_top = [{"question": q, "negative": n} for q, n in sorted(by_q.items(), key=lambda x: -x[1])[:3]]

    # 趋势：逐 batch 负面占比（有负面或总数>0 的批次才画点）
    trend: list[dict] = []
    for h in items:
        if not h.get("batch"):
            continue
        ts = h.get("created_at", "")
        batch_records = [r for r in records if r["ts"] == ts]
        if not batch_records:
            continue
        b_neg = sum(1 for r in batch_records if r["sentiment"] == "negative")
        trend.append({
            "ts": ts,
            "neg_pct": round(b_neg / len(batch_records) * 100) if batch_records else 0,
            "negative": b_neg,
            "total": len(batch_records),
        })
    trend.sort(key=lambda t: t["ts"])

    # 平台分布（负面率）
    by_platform: dict[str, dict] = {}
    for r in records:
        p = by_platform.setdefault(r["platform"], {"platform": r["platform"], "negative": 0, "total": 0})
        p["total"] += 1
        if r["sentiment"] == "negative":
            p["negative"] += 1
    platforms = [
        {
            "platform": p["platform"],
            "negative": p["negative"],
            "total": p["total"],
            "neg_pct": round(p["negative"] / p["total"] * 100) if p["total"] else 0,
        }
        for p in by_platform.values()
    ]
    order = {"DeepSeek": 0, "豆包": 1, "文心一言": 2, "通义千问": 3, "Kimi": 4, "智谱": 5}
    platforms.sort(key=lambda x: (order.get(x["platform"], 99), x["platform"]))

    # 明细（倒序，最近在前）
    details = sorted(records, key=lambda r: r["ts"], reverse=True)

    return {
        "health": {"score": health, "label": health_label, "neg_pct": neg_pct, "total": total},
        "metrics": {
            "check_records": total,
            "risk_count": neg,
            "positive": pos,
            "neutral": neu,
            "affected_questions": len(neg_questions),
            "affected_units": 0,  # 优化单元 P1-6 落地前诚实为 0
        },
        "trend": trend,
        "platforms": platforms,
        "risk_top": risk_top,
        "details": details[:100],
        "detail_total": len(details),
    }


@router.get("/public-opinion")
async def public_opinion():
    """P1：舆情分析页（健康分 + 四指标 + 趋势 + 平台分布 + 高风险 top3 + 明细）"""
    return ok(_aggregate_public_opinion(_load_history()))


# ── P1-6：行业分析（2026-08-08 新增） ─────────────────────
@router.get("/industry")
async def industry():
    """全智解析·行业分析：从行业/关键词监测对象回答聚合行业格局

    数据源：type=keyword（行业）监测对象的回答文本。
    口径（诚实标注）：规则词频——用竞品对象名 + 通用企业名特征在回答文本中匹配，
    统计各企业被 AI 提及的次数与占比；提及≠推荐/好评，非 LLM 精判。
    无行业对象 → 空态引导去监测中心建行业对象。
    """
    hist = _load_history()
    items = _load_items()
    kw_items = [i for i in items if i.get("type") == "keyword" and i.get("status") != "archived"]

    # 候选企业名：所有 competitor 对象的竞品名 + 我方公司名 + 通用特征后缀
    cands: dict[str, str] = {}  # 名称 → 类别（self/competitor）
    for it in items:
        cfg = it.get("config_json") or {}
        if it.get("type") == "brand":
            nm = cfg.get("company") or it.get("entity") or ""
            if nm:
                cands[nm] = "self"
        elif it.get("type") == "competitor":
            comp = cfg.get("competitor") or []
            if isinstance(comp, str):
                comp = [comp]
            for c in comp[:2]:
                if c:
                    cands[str(c)] = "competitor"
    # 收集行业对象回答（单遍扫描；文本截前 800 字防大文本拖慢正则）
    kw_ids = {i["monitor_id"] for i in kw_items}
    mentions: dict[str, dict] = {}
    total_answers = 0
    for h in reversed(hist):
        ts = h.get("created_at", "")
        for q in h.get("questions") or []:
            if q.get("monitor_id") not in kw_ids:
                continue
            for ed in q.get("engine_detail") or []:
                text = (ed.get("answer") or ed.get("snippet") or "")[:800]
                if not text:
                    continue
                total_answers += 1
                qtext = q.get("question") or ""
                engine = ed.get("engine_name") or "未知模型"
                seen_in_answer: set[str] = set()
                # 已知候选匹配
                for name, cat in cands.items():
                    if name and name in text:
                        mentions.setdefault(name, {"name": name, "category": cat, "count": 0, "questions": set(), "evidence": []})
                        seen_in_answer.add(name)
                # 通用企业名探测（XX有限公司/集团）
                for match in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9]{2,20}?(?:有限公司|集团|股份公司|科技公司))", text):
                    nm = match.group(0)
                    if nm not in cands:
                        mentions.setdefault(nm, {"name": nm, "category": "other", "count": 0, "questions": set(), "evidence": []})
                        seen_in_answer.add(nm)
                # 同一回答重复出现同一企业只算一次，并保留可核验原文。
                for name in seen_in_answer:
                    record = mentions[name]
                    record["count"] += 1
                    if qtext:
                        record["questions"].add(qtext)
                    if len(record["evidence"]) < 3:
                        at = text.find(name)
                        start = max(0, at - 60)
                        record["evidence"].append({"question": qtext, "engine": engine, "snippet": text[start:start + 180], "ts": ts})

    rows = []
    for m in mentions.values():
        rows.append({"name": m["name"], "category": m["category"], "count": m["count"], "questions": len(m["questions"]), "evidence": m["evidence"]})
    rows.sort(key=lambda x: -x["count"])
    total_mention = sum(r["count"] for r in rows)

    return ok({
        "industry": kw_items[0].get("entity") if kw_items else None,
        "objects": len(kw_items),
        "total_answers": total_answers,
        "total_mention": total_mention,
        "players": rows[:15],
        "note": "规则估算：每条回答中识别到企业名即记 1 次提及，并保留回答原文；同一回答重复出现不重复计数。提及≠推荐/好评，也不代表真实市场份额。",
        "empty": not kw_items,
        "hint": "暂无行业监测对象——先在监测中心建「行业/关键词」对象（如：工业AI质检）后跑监测" if not kw_items else None,
    })


def _collect_sentiment_records(items: list[dict]) -> list[dict]:
    """收集所有已判定回答（sentiment 非 None）——评价分析/舆情分析共用"""
    records: list[dict] = []
    for h in items:
        ts = h.get("created_at", "")
        if h.get("batch"):
            for qi in h.get("questions") or []:
                q = qi.get("question")
                for er in qi.get("engine_detail") or []:
                    s = er.get("sentiment")
                    if s is not None:
                        records.append({
                            "question": q,
                            "platform": er.get("engine_name"),
                            "sentiment": s,
                            "snippet": er.get("snippet") or "",
                            "ts": ts,
                        })
        else:
            q = h.get("question")
            for er in h.get("engine_detail") or []:
                s = er.get("sentiment")
                if s is not None:
                    records.append({
                        "question": q,
                        "platform": er.get("engine_name"),
                        "sentiment": s,
                        "snippet": er.get("snippet") or "",
                        "ts": ts,
                    })
    return records


def _aggregate_sentiment(items: list[dict]) -> dict:
    """评价分析页（对齐竞品）：占比 + 趋势 + 用户意图维度 + 负面高频词

    数据源：history engine_detail（sentiment 非 None = AI 提到企业）。
    - 占比：正面/负面/中立计数 + 百分比
    - 趋势：逐批次正/负/中计数
    - 用户意图维度：每问题 正/负/中 计数 + 倾向
    - 负面高频词：负面回答 snippet 的 2-4 字词频 top10（规则，诚实标注"基于回答片段"）
    """
    records = _collect_sentiment_records(items)

    pos = sum(1 for r in records if r["sentiment"] == "positive")
    neg = sum(1 for r in records if r["sentiment"] == "negative")
    neu = sum(1 for r in records if r["sentiment"] == "neutral")
    total = len(records)

    def pct(n: int) -> int:
        return round(n / total * 100) if total else 0

    # 趋势：逐批次
    trend: list[dict] = []
    for h in items:
        ts = h.get("created_at", "")
        batch_records = [r for r in records if r["ts"] == ts]
        if not batch_records:
            continue
        trend.append({
            "ts": ts,
            "positive": sum(1 for r in batch_records if r["sentiment"] == "positive"),
            "negative": sum(1 for r in batch_records if r["sentiment"] == "negative"),
            "neutral": sum(1 for r in batch_records if r["sentiment"] == "neutral"),
            "total": len(batch_records),
        })
    trend.sort(key=lambda t: t["ts"])

    # 用户意图维度
    by_q: dict[str, dict] = {}
    for r in records:
        q = by_q.setdefault(r["question"], {"question": r["question"], "positive": 0, "negative": 0, "neutral": 0})
        q[r["sentiment"]] += 1
    questions = []
    for q in by_q.values():
        sentiment = (
            "negative" if q["negative"] > q["positive"]
            else "positive" if q["positive"] > q["negative"]
            else "neutral"
        )
        questions.append({**q, "sentiment": sentiment})
    questions.sort(key=lambda x: -(x["negative"] * 10 + x["positive"]))

    # 负面高频词：负面 snippet 2-4 字词频（stop 只停虚词，不停"质量/投诉"等领域词）
    from collections import Counter

    # 负面高频词：负面 snippet 2-4 字词频（stop 只停虚词，不停"质量/投诉"等领域词）
    # 2026-08-09 修复：markdown 符号进分隔符（消灭 ** 碎词）、过滤含符号/品牌名/公司后缀词
    from collections import Counter

    stop = set("的了是在有和就不都一个也这那与及或很我们你们他们我的你的他的它的进行哪个哪些什么怎么为什么因为所以但是可以需要应该不会没有相关为了通过同时能够使用以及或者如果是否自己这个那个帮你帮")
    # 品牌候选名（公司/别名/简称）——负面词里出现公司名无信息量
    brand_cands: list[str] = []
    for it in _load_items():
        cfg = it.get("config_json") or {}
        c = cfg.get("company") or cfg.get("target")
        if c:
            brand_cands = _mention_cands(c, cfg.get("aliases") or [])
            break
    counter: Counter = Counter()
    for r in records:
        if r["sentiment"] != "negative":
            continue
        text = r.get("snippet") or ""
        # 按标点/空白/markdown 符号切分 → 每段做 2-4 字滑动窗口
        parts = re.split(r"[\s，。！？、；：,.!?;:（）()「」\"'\'《》【】\n*#_~`>|/\\-]", text)
        for p in parts:
            p = p.strip()
            if len(p) < 2:
                continue
            for n in (2, 3, 4):
                for i in range(len(p) - n + 1):
                    w = p[i : i + n]
                    if all(c in stop for c in w):
                        continue  # 全虚词窗口无信息量
                    if any(not ("\u4e00" <= c <= "\u9fa5") for c in w):
                        continue  # 含 markdown/符号残留
                    if any(bc and (w in bc or bc in w) for bc in brand_cands):
                        continue  # 品牌名及其子串无信息量（"云启智能科技"切出的"云启/智能/科技"全是品牌名碎片）
                    counter[w] += 1
    top_words = [{"word": w, "count": c} for w, c in counter.most_common(12)]
    negative_samples = [
    # 负面明细（2026-08-08：用户要求"怎么个负面法"——具体回答片段，可下钻）
        {
            "question": r["question"],
            "platform": r["platform"],
            "snippet": (r.get("snippet") or "")[:240],
            "ts": r["ts"],
        }
        for r in records
        if r["sentiment"] == "negative"
    ][:10]

    return {
        "overview": {
            "total": total,
            "positive": pos,
            "negative": neg,
            "neutral": neu,
            "pos_pct": pct(pos),
            "neg_pct": pct(neg),
            "neu_pct": pct(neu),
        },
        "trend": trend,
        "questions": questions,
        "top_words": top_words,
        "negative_samples": negative_samples,  # 负面回答明细（问题+引擎+片段）
    }


@router.get("/sentiment")
async def sentiment():
    """P1：评价分析页（占比 + 趋势 + 用户意图维度 + 负面高频词）"""
    return ok(_aggregate_sentiment(_load_history()))


# ── P1-5：事实分析（监测侧失真检测，对齐竞品"基于知识库识别 AI 回复失真"） ──

# 断言锚点：含数字/认证/对比等可核验事实的句子才检测（防把客套句当断言）
_CLAIM_ANCHORS = (
    "认证", "通过", "获得", "荣获", "评为", "入选", "认定", "获批", "授予", "中标",
    "第一", "领先", "首家", "最大", "唯一", "销量", "客户", "用户", "门店", "覆盖",
    "成立于", "年成立", "注册资本", "员工", "人", "家", "款", "亿", "万",
    # 2026-09-21：价格类断言原来一条都不检测 ——「9800 元」既不含「万/亿」也不含上面任何词，
    # 于是「亚宇臻隆科技主营X，价格 9800 元」被判成「无事实断言」直接放过。
    "价格", "报价", "费用", "收费", "元", "免费", "折扣", "返点",
)


async def _check_answer_facts(company_name: str, snippet: str, question: str) -> dict:
    """单条回答失真检测：提到企业的断言句 → 企业知识库检索比对

    诚实红线：只标"知识库未覆盖/缺少依据"，不判"造假"（知识库不全 ≠ 企业造假）。
    - 断言句 = 含企业名（或简称）的句子，且含数字/认证/对比锚点
    - 检索 score ≥ 0.5 且命中实体相关 → 有依据（grounded）
    - 否则 → 异常（main_type="缺少依据"）
    - 知识库不可用 → 返回 knowledge_ok=false（前端区分"不可用"vs"无匹配"）
    """
    if not company_name or not snippet:
        return {"checked": False, "abnormal": False, "reason": "无文本"}

    cands = {company_name, _strip_company_suffix(company_name)}
    cands.discard("")
    sentences = re.split(r"[。！？!?\n；;]", snippet)
    claim_sentences = []
    for s in sentences:
        if not any(c and c in s for c in cands):
            continue
        if any(a in s for a in _CLAIM_ANCHORS):
            claim_sentences.append(s.strip())

    if not claim_sentences:
        return {"checked": True, "abnormal": False, "reason": "无事实断言"}

    try:
        from adapters.eios import search_knowledge

        knowledge_ok = True
        ungrounded: list[str] = []
        for s in claim_sentences[:3]:
            res = await search_knowledge(s, top_k=3, include_candidates=False)
            hits = (res or {}).get("hits") or []
            # 证据文本取**全部**命中片段，不只看最高分那条：断言里的数字出现在哪一条都算有依据，
            # 只看第一条会造成「明明有依据却说没依据」的假阳性。
            # 注意：不比较 score —— EIOS 知识库的 n 是无界 rank 分（见下方说明），
            # 它不是 0~1 的置信度，拿阈值卡它是上一版的老知识库假设。
            hit_blob = " ".join(
                str(h.get(k, "") or "")
                for h in hits
                for k in ("canonical_name", "name", "predicate", "value", "text")
            )
            # 实体相关性收紧（防"公司名必在知识库"导致全命中）：
            # 断言句去掉公司名后的 4 字窗口必须出现在命中文本里，才算有依据
            # （"通过了国家高新技术企业认证" → 窗口"高新技术/技术企业/企业认证"命中才算）
            claim_core = s
            for c in cands:
                claim_core = claim_core.replace(c, "")
            ngrams = {claim_core[i : i + 4] for i in range(max(0, len(claim_core) - 3)) if len(claim_core[i : i + 4]) == 4}
            related = any(g in hit_blob for g in ngrams) if ngrams else False
            # 2026-09-21 修：原来这里还有一条 `best < 0.5`。
            # 那个 0.5 是换知识源前的老适配器的归一化分阈值，而 EIOS 知识库的 n 是无界 rank 分
            # （契约 eios.knowledge_retrieval_hit/v2：`n` 只有 minimum，fixture 里就是 1.5 / 3.5；
            #  本机实测同一批检索在 10.0~14.0），所以 `best < 0.5` **永远不成立** ——
            # 等于只要检索回来任何东西，所有断言都算「有依据」。
            # 实测：凭空编的「亚宇臻隆科技成立于 2005 年，注册资本 1 亿元，员工 800 人」
            # 被判成「断言均有知识库依据」。现在改成**断言里的数字必须原样出现在证据里**：
            # 证据里查不到的年份/金额/人数就是没有依据，不再靠词面巧合（4-gram 命中）放行。
            digits = re.findall(r"\d+(?:\.\d+)?", claim_core)
            missing_digits = [d for d in digits if not re.search(r"(?<!\d)" + re.escape(d) + r"(?!\d)", hit_blob)]
            if not related or missing_digits:
                ungrounded.append(s)
        if ungrounded:
            return {
                "checked": True,
                "abnormal": True,
                "main_type": "缺少依据",
                "claims": ungrounded,
                "knowledge_ok": True,
                "reason": f"{len(ungrounded)} 条断言知识库未覆盖",
            }
        return {"checked": True, "abnormal": False, "reason": "断言均有知识库依据", "knowledge_ok": True}
    except Exception:  # noqa: BLE001
        return {"checked": True, "abnormal": False, "reason": "知识库不可用", "knowledge_ok": False}


def _aggregate_fact_check(items: list[dict], company_name: str | None = None) -> dict:
    """事实分析页聚合：命中库/异常回复/关联意图/关联信源 + 排行 + 明细

    数据源：history 中 AI 提到企业的回答（mentioned=True 且 sentiment 非 None 的记录
    取 snippet 做断言检测）。公司名取最近批次 company_name。
    检测是异步 企业知识库检索——聚合函数返回待检测记录，由路由层并发执行。
    """
    # 确定企业名（最近 batch 的 company_name，兜底从 brand 监测对象取——2026-08-08 修复）
    if not company_name:
        for h in reversed(items):
            if h.get("company_name"):
                company_name = h["company_name"]
                break
    if not company_name:
        try:
            from app.services.store import get_store

            for it in get_store().load("monitor_items"):
                if it.get("type") == "brand":
                    company_name = (it.get("config_json") or {}).get("company") or it.get("entity") or ""
                    if company_name:
                        break
        except Exception:  # noqa: BLE001
            pass

    records: list[dict] = []
    for h in items:
        ts = h.get("created_at", "")
        if h.get("batch"):
            for qi in h.get("questions") or []:
                for er in qi.get("engine_detail") or []:
                    if er.get("mentioned") and er.get("sentiment") is not None:
                        records.append({
                            "question": qi.get("question"),
                            "platform": er.get("engine_name"),
                            "snippet": er.get("snippet") or "",
                            "ts": ts,
                        })
        else:
            for er in h.get("engine_detail") or []:
                if er.get("mentioned") and er.get("sentiment") is not None:
                    records.append({
                        "question": h.get("question"),
                        "platform": er.get("engine_name"),
                        "snippet": er.get("snippet") or "",
                        "ts": ts,
                    })
    return {"company_name": company_name, "records": records}


@router.get("/fact-check")
async def fact_check():
    """P1-5：事实分析页（基于知识库识别 AI 回复失真：命中/异常/排行/明细）"""
    items = _load_history()
    base = _aggregate_fact_check(items)

    # 并发检测每条回答（企业知识库检索）——限前 10 条 + 并发 2（Ollama embedding ~4s/次，12s/检索）
    records = base["records"][:10]
    sem = asyncio.Semaphore(2)

    async def _checked(rec):
        async with sem:
            try:
                return await asyncio.wait_for(
                    _check_answer_facts(base.get("company_name") or "", rec["snippet"], rec["question"]),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                return {"checked": False, "abnormal": False, "reason": "企业知识库检索超时", "knowledge_ok": False}

    checked = await asyncio.gather(*[_checked(r) for r in records])
    results = [{**rec, **ck} for rec, ck in zip(records, checked)]

    abnormal = [r for r in results if r.get("abnormal")]
    # 2026-09-21 口径修正（Owner：「输出正常但不正确」）：
    # `hit` 原来是「跑过检查且没判异常」——可「无事实断言」的回答（模型压根没说企业的事实，
    # 比如只答「请查工商信息」）也满足这个条件，于是它被算进「知识库命中」。
    # 「已核验回答」同理：原来算的是**送检条数**，超时/无文本（checked=False）也算「已核验」。
    checked_ok = [r for r in results if r.get("checked")]
    no_claim = [r for r in checked_ok if r.get("reason") == "无事实断言"]
    claim_checked = [r for r in checked_ok if r.get("reason") != "无事实断言"]
    hit = [r for r in claim_checked if not r.get("abnormal")]

    # 四指标
    hit_kb = len(hit)
    abnormal_count = len(abnormal)
    affected_questions = len({r["question"] for r in abnormal})
    affected_sources = len({r["platform"] for r in abnormal})

    # 失真信源排行（平台维度）
    by_platform: dict[str, dict] = {}
    for r in abnormal:
        p = by_platform.setdefault(r["platform"], {"platform": r["platform"], "count": 0, "types": []})
        p["count"] += 1
        if r.get("main_type") and r["main_type"] not in p["types"]:
            p["types"].append(r["main_type"])
    source_rank = sorted(
        [{"rank": i + 1, "source": p["platform"], "count": p["count"], "main_type": "、".join(p["types"])}
         for i, p in enumerate(by_platform.values())],
        key=lambda x: -x["count"],
    )

    # 用户意图排行（问题维度）
    by_q: dict[str, dict] = {}
    for r in abnormal:
        q = by_q.setdefault(r["question"], {"question": r["question"], "count": 0, "types": []})
        q["count"] += 1
        if r.get("main_type") and r["main_type"] not in q["types"]:
            q["types"].append(r["main_type"])
    question_rank = sorted(
        [{"rank": i + 1, "question": q["question"], "count": q["count"], "main_type": "、".join(q["types"])}
         for i, q in enumerate(by_q.values())],
        key=lambda x: -x["count"],
    )

    # 明细（倒序）
    details = sorted(
        [
            {
                "question": r["question"],
                "platform": r["platform"],
                "abnormal_type": r.get("main_type") or "正常",
                "ai_ref": (r.get("claims") or [""])[0][:120],
                "ts": r["ts"],
            }
            for r in results
            if r.get("abnormal")
        ],
        key=lambda x: x["ts"],
        reverse=True,
    )

    return ok({
        "company_name": base.get("company_name"),
        "truth": {
            "available": base.get("company_name") is not None and len(base["records"]) > 0,
            "hit_kb": hit_kb,
            "abnormal_count": abnormal_count,
            "affected_questions": affected_questions,
            "affected_sources": affected_sources,
            "total_checked": len(checked_ok),       # 真的跑完检查的回答数（不含超时/无文本）
            "claim_checked": len(claim_checked),    # 其中**真的有企业断言**、比对过知识库的条数
            "candidate_total": len(base["records"]),  # 本轮拉到多少条候选回答（受上限截断）
            "no_claim_count": len(no_claim),        # 有回答但没有任何可核验断言（不计命中也不计失真）
            "knowledge_ok": all(r.get("knowledge_ok", True) for r in results) if results else True,
        },
        "source_rank": source_rank,
        "question_rank": question_rank,
        "details": details[:100],
        "detail_total": len(details),
    })


def _aggregate_item_trend(items: list[dict], monitor_id: str, entity: str | None = None) -> dict:
    """0.2：单监测对象跨次趋势（按 monitor_id 聚合历次 history 记录）

    返回每次运行一个点（同一批次的多探针按 ts 聚合）：visibility（提及率）/mention/position/citation/snippet。
    reason（为什么被推荐）结构预留——第一版无数据（解析单独一步，不假装有值）。
    entity 参数预留：未来"云启智能整体认知"聚合趋势（按 entity 而非单 item）。
    """
    if entity:
        # 预留：按 entity 聚合（跨多个 item）——第一版只做 item 维度
        matched = [q for q in items if q.get("company_name") == entity]
    else:
        matched = [q for q in items if q.get("monitor_id") == monitor_id]

    # 按批次时间戳分组（同一批次的多个探针合成一个点）
    by_ts: dict[str, list[dict]] = {}
    for q in matched:
        ts = q.get("created_at", "")
        by_ts.setdefault(ts, []).append(q)

    points: list[dict] = []
    for ts, group in by_ts.items():
        mentioned_count = sum(q.get("mentioned_count", 0) for q in group)
        answered_count = sum(
            q.get("answered_count")
            if q.get("answered_count") is not None
            else sum(1 for er in (q.get("engine_detail") or []) if er.get("mentioned") is not None)
            for q in group
        )
        rank_ests = [
            er.get("rank_est")
            for q in group
            for er in (q.get("engine_detail") or [])
            if er.get("rank_est") is not None
        ]
        rank_avg = round(sum(rank_ests) / len(rank_ests), 1) if rank_ests else None
        sents = [
            er.get("sentiment")
            for q in group
            for er in (q.get("engine_detail") or [])
            if er.get("sentiment")
        ]
        snippets = [er.get("snippet") for q in group for er in (q.get("engine_detail") or []) if er.get("snippet")]
        points.append(
            {
                "ts": ts,
                "visibility": round(mentioned_count / answered_count * 100) if answered_count else None,
                "answered": answered_count,
                "mention": mentioned_count,
                "position": rank_avg,
                "positive": sum(1 for s in sents if s == "positive"),
                "negative": sum(1 for s in sents if s == "negative"),
                "citation": 0,  # 引用于批次级聚合，item 级待细化
                "snippet": (snippets[0] if snippets else "")[:120],
                "reason": [],  # 预留：推荐理由解析落地后填充
            }
        )
    points.sort(key=lambda p: p["ts"])
    return {"monitor_id": monitor_id, "entity": entity, "points": points, "count": len(points)}


@router.get("/items/{mid}/trend")
async def item_trend(mid: str):
    """0.2：监测对象跨次趋势（同一 item 反复监测 → 逐次对比）

    reason 预留（推荐理由解析单独一步）；entity 聚合趋势后置。
    """
    items = _load_history()
    # 把 batch 的 questions 展开成扁平记录（每 question 带 created_at = batch 时间）
    flat: list[dict] = []
    for h in items:
        if h.get("batch"):
            ts = h.get("created_at", "")
            for q in h.get("questions") or []:
                q2 = dict(q)
                q2["created_at"] = ts
                flat.append(q2)
        else:
            q = dict(h)
            q["monitor_id"] = q.get("monitor_id") or f"tmp_{hashlib.md5((q.get('question','') or '').encode()).hexdigest()[:8]}"
            flat.append(q)
    data = _aggregate_item_trend(flat, mid)
    return ok(data)
