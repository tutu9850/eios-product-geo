"""市场感知（S1）：关注列表 + 外部采集 + 信号流（三分法落点）

- 关注列表：竞品域名/行业源 URL（type: website|news|zhihu，徽章区分）
- 采集：复用 services/collector（httpx + bs4，raw 落盘 geo_collect_raw.json）
- 信号状态机：raw → extracted（LLM 提取可核验事实）→ confirmed（write_candidate 写 Kernel，仅可核验事实）
  → planned（记入内容计划）/ ignored
- 三分法：可核验事实 → Kernel candidate（人工确认）；策略/行业信号 → 仅留 GEO；流水不落
- 红线：只走既有 Kernel 接口（adapters/eios.py write_candidate）；反爬失败如实报错不编造
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import ok

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
    """人工确认 → 可核验事实 write_candidate 写 Kernel（永远 candidate）"""
    from services.collector import _load_raw, set_signal_status
    from adapters.eios import write_candidate

    signal = next((s for s in _load_raw() if s.get("id") == signal_id), None)
    if not signal:
        return ok({"error": "信号不存在"})
    facts = signal.get("facts") or []
    if not facts:
        return ok({"error": "该信号还没有提取出事实（先点「提取事实」）"})
    written = []
    failed = []
    for f in facts:
        parts = [p.strip() for p in f.split("|")]
        if len(parts) < 3:
            failed.append({"fact": f, "error": "格式错误"})
            continue
        subject, predicate, value = parts[0], parts[1], "|".join(parts[2:])
        try:
            # 修复（审计 H4）：write_candidate 成功返回 data dict（无 "ok" 字段），失败抛 KernelError。
            # 原代码 `resp.get("ok")` 在 data dict 上恒为 None → 所有事实误报 failed（error:"None"），
            # 且信号永远无法流转到 confirmed。改为「无异常即成功」。
            await write_candidate(canonical_name=subject[:80], predicate=predicate[:60], value=value[:500])
            written.append(f)
        except Exception as exc:  # noqa: BLE001
            failed.append({"fact": f, "error": str(exc)[:100]})
    if written:
        set_signal_status(signal_id, "confirmed")
    return ok({"written": written, "failed": failed, "signal_id": signal_id})


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
