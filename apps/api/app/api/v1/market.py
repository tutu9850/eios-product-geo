"""市场感知（S1）：关注列表 + 外部采集 + 信号流（三分法落点）

- 关注列表：竞品域名/行业源 URL（type: website|news|zhihu，徽章区分）
- 采集：复用 services/collector（httpx + bs4，raw 落盘 geo_collect_raw.json）
- 信号状态机：raw → extracted（LLM 提取可核验事实）→ confirmed / planned（记入内容计划）/ ignored
- 三分法：可核验事实 → 留 GEO 自己的库；策略/行业信号 → 仅留 GEO；流水不落
- 红线（Owner 2026-09-20）：**GEO 不允许写知识库**。原来 confirmed 会调
  adapters/eios.write_candidate 把事实写回企业知识库，那条路已经封死：本接口现在
  明确回 AUTHORITY_WRITE_NOT_ALLOWED(403)，不再有写动作，也不再假装写过。
- 反爬失败如实报错不编造
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import err, ok

router = APIRouter(prefix="/api/v1/market")

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
WATCH_FILE = DATA_DIR / "geo_watchlist.json"


def _load_watch() -> list[dict]:
    from app.services.store import get_store

    return get_store().load("watchlist")


def _save_watch(items: list[dict]) -> None:
    from app.services.store import get_store

    get_store().save("watchlist", items)


class WatchIn(BaseModel):
    name: str
    url: str = ""
    type: str = "website"  # website | news | zhihu


class CollectIn(BaseModel):
    watch_ids: list[str] | None = None  # 空 = 采集全部


# ── 关注列表 ──


@router.get("/watchlist")
async def list_watchlist():
    return ok({"items": _load_watch()})


@router.post("/watchlist")
async def add_watch(payload: WatchIn):
    name = payload.name.strip()
    if not name:
        return ok({"error": "名称必填"})
    item = {
        "id": f"w_{uuid.uuid4().hex[:8]}",
        "name": name,
        "url": payload.url.strip(),
        "type": payload.type if payload.type in ("website", "news", "zhihu") else "website",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _load_watch()
    items.insert(0, item)
    _save_watch(items)
    return ok({"item": item})


@router.delete("/watchlist/{watch_id}")
async def delete_watch(watch_id: str):
    items = [i for i in _load_watch() if i.get("id") != watch_id]
    _save_watch(items)
    return ok({"deleted": watch_id})


# ── 采集 ──


@router.post("/collect")
async def collect(payload: CollectIn):
    from services.collector import collect_url, _load_raw

    items = _load_watch()
    targets = [i for i in items if not payload.watch_ids or i.get("id") in payload.watch_ids]
    if not targets:
        return ok({"signals": [], "errors": [], "total": 0, "error": "没有可采集的关注项（先添加关注列表）"})
    signals = []
    errors = []
    for t in targets:
        result = await collect_url(t)
        if result.get("error"):
            errors.append({"watch_id": t.get("id"), "name": t.get("name"), "error": result["error"]})
        else:
            signals.append(result["signal"])
    return ok({
        "signals": signals,
        "errors": errors,
        "total": len(_load_raw()),
    })


# ── 信号流 ──


@router.get("/signals")
async def list_signals(limit: int = 50):
    from services.collector import _load_raw

    items = _load_raw()
    return ok({"items": items[:limit], "total": len(items)})


@router.post("/signals/{signal_id}/extract")
async def extract_facts(signal_id: str):
    """LLM 提取可核验事实（竞品发布/融资/合作/数据）；宣传口径不提取为事实"""
    from services.collector import _load_raw, set_signal_status
    from adapters.llm import chat, LLMNotConfiguredError, LLMError

    signal = next((s for s in _load_raw() if s.get("id") == signal_id), None)
    if not signal:
        return ok({"error": "信号不存在"})
    if signal.get("status") in ("confirmed", "ignored"):
        return ok({"error": f"信号已{signal['status']}，不能重复提取"})

    text = (signal.get("text") or "")[:3000]
    prompt = (
        "从以下网页内容中提取**可核验的事实性信息**（如：发布产品/服务、融资、合作、获奖、"
        "明确的数据指标），逐条输出。规则：\n"
        "1. 只输出客观可核验的陈述（主体做了什么、何时、可查证）\n"
        "2. 宣传性、推测性、无来源的口径（如'行业领先''效果提升 X%'没有出处）**不输出**\n"
        "3. 每条事实格式：主体|谓词|宾语（宾语含时间/数据）\n"
        f"内容：\n{text}\n"
        "输出 JSON 数组：[\"主体|谓词|宾语\", ...]（没有可核验事实输出 []，不要其他内容）"
    )
    try:
        result = await chat(prompt, max_tokens=600)
    except LLMNotConfiguredError as e:
        return ok({"error": str(e)})
    except LLMError as e:
        return ok({"error": e.message})

    import re

    facts: list[str] = []
    m = re.search(r"\[[\s\S]*\]", result)
    if m:
        try:
            facts = [str(f).strip() for f in json.loads(m.group(0)) if str(f).strip()]
        except Exception:  # noqa: BLE001
            facts = []
    set_signal_status(signal_id, "extracted", facts)
    return ok({"facts": facts, "signal_id": signal_id})


@router.post("/signals/{signal_id}/confirm")
async def confirm_signal(signal_id: str):
    """人工确认信号 —— **不写知识库**（Owner 2026-09-20）。

    外部情报属于 GEO 自己的材料，知识库只由它的治理链写。原来这个端点会把可核验事实
    经 write_candidate 写回企业知识库，现在整条路封死：直接回 403，说清楚为什么，
    并且不改信号状态（一半成功一半失败的假象比干脆拒绝更坏）。
    """
    from services.collector import _load_raw

    signal = next((s for s in _load_raw() if s.get("id") == signal_id), None)
    if not signal:
        return err("signal_not_found", "信号不存在")
    return err(
        "AUTHORITY_WRITE_NOT_ALLOWED",
        "GEO 不允许写企业知识库：外部情报只留在 GEO 自己的库里，"
        "知识库由它自己的治理链写入。需要沉淀请走知识库的上传/治理入口。",
    )


@router.post("/signals/{signal_id}/to-plan")
async def signal_to_plan(signal_id: str):
    """信号 → 内容计划（source=market_signal，reason 带市场信号来源）"""
    from services.collector import _load_raw, set_signal_status
    from app.api.v1.distill import PLANS_FILE, _load_plans, _save_plans

    signal = next((s for s in _load_raw() if s.get("id") == signal_id), None)
    if not signal:
        return ok({"error": "信号不存在"})
    title = (signal.get("title") or "").strip()
    if not title:
        return ok({"error": "信号无标题，无法入计划"})
    plans = _load_plans()
    existing = {p.get("topic") for p in plans}
    if title in existing:
        return ok({"dup": True, "error": None, "message": "该主题已在内容计划中（未重复添加）"})
    plans.append({
        "id": f"p_{uuid.uuid4().hex[:10]}",
        "topic": title[:60],
        "reason": f"市场信号：{signal.get('source_name') or signal.get('source_type')} 采集到该主题（{signal.get('url', '')}），市场在谈，建议生产内容",
        "target_question": "",
        "recommended_content_type": "新闻动态",
        "priority": 80,
        "gap_id": None,
        "source": "market_signal",
        "status": "planned",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_plans(plans)
    set_signal_status(signal_id, "planned")
    return ok({"added": True, "dup": False, "total": len(plans), "error": None})


@router.post("/signals/{signal_id}/ignore")
async def ignore_signal(signal_id: str):
    from services.collector import set_signal_status

    s = set_signal_status(signal_id, "ignored")
    if not s:
        return ok({"error": "信号不存在"})
    return ok({"ignored": signal_id})
