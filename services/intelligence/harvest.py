"""WebSearch Harvest — 外部补搜（Phase A）

冻结：External Evidence 开发方案 Phase A。
- 调 eios-tool web.platform_search（与 Advisor 同一工具）
- 收成 geo_evidence：source_type=research_harvest, capture_mode=search_result
- 采集成功 = 搜索 + 写库 + enqueue；不依赖 LLM
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.store import current_tenant

from services.intelligence import queue, repo

logger = logging.getLogger("eios.intelligence.harvest")

DEFAULT_TOOL_URL = os.environ.get("EIOS_TOOL_URL", "http://host.docker.internal:3300")
HARVEST_COOLDOWN_SECONDS = 60
MAX_KEYWORDS = 5
MAX_PER_KEYWORD_CAP = 20

# run_id → 状态（内存；进程重启丢失，可接受 V0）
_runs: dict[str, dict[str, Any]] = {}
_last_harvest_ts: float = 0.0
_lock = asyncio.Lock()


def get_run(run_id: str) -> dict | None:
    return _runs.get(run_id)


def _url_hash(url: str, title: str) -> str:
    raw = (url or title or "").strip().encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _build_evidence(
    *,
    run_id: str,
    company: str,
    keyword: str,
    platform: str,
    rank: int,
    item: dict,
) -> dict:
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    snippet = (item.get("snippet") or item.get("desc") or "").strip()
    source = (item.get("source") or platform or "").strip()
    parent_ref = f"harvest:{run_id}:{_url_hash(url, title)}"
    evidence_id = parent_ref  # 稳定可读
    # 明确标注：搜索摘要，非网页正文
    raw_text = (
        "【搜索摘要 · 非网页正文】\n"
        f"标题：{title}\n"
        f"摘要：{snippet}\n"
        f"链接：{url}\n"
        "（capture_mode=search_result；不得当作消费者原话或页面全文）"
    )
    ctx = {
        "capture_mode": "search_result",
        "keyword": keyword,
        "harvest_run_id": run_id,
        "result_rank": rank,
        "title": title,
        "discovered_url": url,
        "question": f"外网补搜：{keyword}",
        "engine": platform,
        "competitors": [],
    }
    return {
        "id": evidence_id,
        "source_type": "research_harvest",
        "platform": platform or source or "sogou",
        "url": url or None,
        "subject_company": company,
        "raw_text": raw_text,
        "context_json": ctx,
        "parent_ref": parent_ref,
        "observed_at": datetime.now(timezone.utc),
        "tenant_id": current_tenant(),
    }


async def _invoke_platform_search(platform: str, keyword: str, max_n: int) -> dict:
    tool_url = os.environ.get("EIOS_TOOL_URL") or DEFAULT_TOOL_URL
    payload = {
        "tool": "web.platform_search",
        "args": {"platform": platform, "keyword": keyword, "max": max_n},
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(f"{tool_url.rstrip('/')}/api/tools/invoke", json=payload)
        data = resp.json()
    if not data.get("success"):
        err = (data.get("error") or {}).get("message") or data.get("error") or f"HTTP {resp.status_code}"
        raise RuntimeError(f"web.platform_search 失败: {err}")
    result = data.get("result") or {}
    return result if isinstance(result, dict) else {"results": []}


def ingest_search_results(
    *,
    run_id: str,
    company: str,
    keyword: str,
    platform: str,
    results: list,
    enqueue_parsing: bool = True,
) -> dict:
    """把搜索结果收成 evidence；返回写入统计。"""
    written = 0
    skipped = 0
    enqueued = 0
    evidence_ids: list[str] = []
    for i, item in enumerate(results or []):
        if not isinstance(item, dict):
            continue
        if not (item.get("title") or item.get("url") or item.get("snippet")):
            continue
        ev = _build_evidence(
            run_id=run_id,
            company=company,
            keyword=keyword,
            platform=platform,
            rank=i + 1,
            item=item,
        )
        row, created = repo.upsert_evidence(ev)
        eid = row["id"]
        evidence_ids.append(eid)
        if created:
            written += 1
            if enqueue_parsing:
                queue.enqueue(eid)
                enqueued += 1
        else:
            skipped += 1
    return {
        "written": written,
        "skipped": skipped,
        "enqueued": enqueued,
        "evidence_ids": evidence_ids,
    }


async def _run_harvest(run_id: str) -> None:
    run = _runs.get(run_id)
    if not run:
        return
    run["status"] = "running"
    run["started_at"] = datetime.now(timezone.utc).isoformat()
    company = run["company"]
    platform = run["platform"]
    max_n = run["max_per_keyword"]
    total_written = total_skipped = total_enqueued = 0
    errors: list[str] = []

    try:
        for kw in run["keywords"]:
            try:
                result = await _invoke_platform_search(platform, kw, max_n)
                rows = result.get("results") or []
                stats = ingest_search_results(
                    run_id=run_id,
                    company=company,
                    keyword=kw,
                    platform=platform,
                    results=rows,
                    enqueue_parsing=True,
                )
                total_written += stats["written"]
                total_skipped += stats["skipped"]
                total_enqueued += stats["enqueued"]
                run.setdefault("keyword_stats", []).append(
                    {"keyword": kw, "results": len(rows), **{k: stats[k] for k in ("written", "skipped", "enqueued")}}
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"{kw}: {exc}"
                logger.warning("harvest keyword failed %s", msg)
                errors.append(msg)
                run.setdefault("keyword_stats", []).append({"keyword": kw, "error": str(exc)})

        run["written"] = total_written
        run["skipped"] = total_skipped
        run["enqueued"] = total_enqueued
        if errors and total_written == 0:
            run["status"] = "failed"
            run["error"] = "; ".join(errors)[:500]
        else:
            run["status"] = "done"
            if errors:
                run["partial_errors"] = errors
    except Exception as exc:  # noqa: BLE001
        run["status"] = "failed"
        run["error"] = str(exc)[:500]
        logger.exception("harvest run failed %s", run_id)
    finally:
        run["finished_at"] = datetime.now(timezone.utc).isoformat()


async def start_search_harvest(
    *,
    company: str,
    keywords: list[str],
    platform: str = "sogou",
    max_per_keyword: int = 10,
) -> dict:
    """限流后创建 run 并后台执行。返回 run 摘要。"""
    global _last_harvest_ts

    company = (company or "").strip()
    if not company:
        raise ValueError("company 必填")
    kws = [k.strip() for k in (keywords or []) if isinstance(k, str) and k.strip()]
    if not kws:
        raise ValueError("keywords 至少一条")
    kws = kws[:MAX_KEYWORDS]
    platform = (platform or "sogou").strip().lower()
    if platform not in ("sogou", "baidu", "weibo"):
        raise ValueError("platform 仅支持 sogou|baidu|weibo")
    max_n = max(1, min(int(max_per_keyword or 10), MAX_PER_KEYWORD_CAP))

    async with _lock:
        now = time.time()
        if now - _last_harvest_ts < HARVEST_COOLDOWN_SECONDS:
            raise RuntimeError(f"rate_limited:{HARVEST_COOLDOWN_SECONDS}")
        _last_harvest_ts = now

    run_id = f"hrv_{uuid.uuid4().hex[:12]}"
    run = {
        "run_id": run_id,
        "kind": "websearch",
        "status": "pending",
        "company": company,
        "keywords": kws,
        "platform": platform,
        "max_per_keyword": max_n,
        "written": 0,
        "skipped": 0,
        "enqueued": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _runs[run_id] = run
    asyncio.create_task(_run_harvest(run_id))
    return {"run_id": run_id, "status": "pending", "keywords": kws, "platform": platform}
