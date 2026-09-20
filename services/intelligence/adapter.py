"""Intelligence 分析引擎 — AiAnswerAdapter（V1 唯一 Adapter）

把监测历史（monitor_history.questions[].engine_detail[].answer）收成
geo_evidence 统一原文，幂等写入并入队解析。
- evidence_id = ans_{history_id}_{query_id}_{engine_name}（history 无稳定行级
  ID，由本模块生成，评审 P1-5）
- 幂等键 (tenant_id, source_type, parent_ref) 命中即跳过
- S1 接入 monitor._append_history 异步钩子；S0 由手动/回填触发
"""
import json
import logging
from datetime import datetime, timezone

from app.services.store import current_tenant, get_store

from services.intelligence import queue, repo

logger = logging.getLogger("eios.intelligence.adapter")


def _resolve_subject(q: dict, history: dict) -> str:
    """监测主体：产品对象（type=product）用对象 entity（产品名），其余用公司名。

    优先 monitor_items 里该 monitor_id 的 config_json.company（非产品对象），
    回退 history.company_name，再回退空串。
    """
    monitor_id = q.get("monitor_id")
    if monitor_id:
        try:
            items = get_store().load("monitor_items")
            for it in items:
                if it.get("monitor_id") == monitor_id:
                    cfg = it.get("config_json") or {}
                    it_type = it.get("type") or ""
                    if it_type == "product":
                        # 产品对象：subject = 产品名（entity），按产品分组分析
                        entity = (it.get("entity") or "").strip()
                        if entity:
                            return entity
                    if cfg.get("company"):
                        return cfg["company"]
        except Exception:  # noqa: BLE001
            pass
    hc = (history.get("company_name") or "").strip()
    if hc:
        return hc
    # 兜底：history 也没公司名时，取任一 active 非产品对象的 config.company（自动配置 run 曾传空 company_name）
    try:
        for it in get_store().load("monitor_items"):
            if it.get("status") != "active":
                continue
            if (it.get("type") or "") == "product":
                continue
            c = ((it.get("config_json") or {}).get("company") or "").strip()
            if c:
                return c
    except Exception:  # noqa: BLE001
        pass
    return ""


def build_evidence(history_id: str, q: dict, er: dict, history: dict) -> dict | None:
    """构造 evidence dict；answer 为空返回 None。"""
    answer = (er.get("answer") or "").strip()
    if not answer:
        return None
    engine_name = er.get("engine_name") or "unknown"
    query_id = q.get("query_id") or "na"
    evidence_id = f"ans_{history_id}_{query_id}_{engine_name}"
    observed = history.get("created_at")
    try:
        observed_dt = datetime.fromisoformat(observed) if observed else datetime.now(timezone.utc)
    except ValueError:
        observed_dt = datetime.now(timezone.utc)

    ctx = {
        "capture_mode": "ai_answer",
        "question": q.get("question") or "",
        "engine": engine_name,
        "monitor_id": q.get("monitor_id"),
        "item_type": q.get("item_type"),
        "history_id": history_id,
        "query_id": query_id,
        "subjects": er.get("subjects"),  # 双主体探针（竞品）：company/competitor
        "competitors": _competitors_from(history, q),
    }
    return {
        "id": evidence_id,
        "source_type": "ai_answer",
        "platform": engine_name,
        "subject_company": _resolve_subject(q, history),
        "raw_text": answer,
        "context_json": ctx,
        "parent_ref": evidence_id,
        "observed_at": observed_dt,
        "tenant_id": current_tenant(),
    }


def _competitors_from(history: dict, q: dict) -> list[str]:
    """竞品名单：优先该 monitor_id 对应 monitor_item 的 config_json.competitor。"""
    monitor_id = q.get("monitor_id")
    if not monitor_id:
        return []
    try:
        items = get_store().load("monitor_items")
        for it in items:
            if it.get("monitor_id") == monitor_id:
                cfg = it.get("config_json") or {}
                comps = cfg.get("competitor") or []
                return [c for c in comps if isinstance(c, str)] if isinstance(comps, list) else []
    except Exception:  # noqa: BLE001
        pass
    return []


def ingest_one_history(history_item: dict, enqueue_parsing: bool = True) -> int:
    """处理单条 history（monitor 钩子用）：构造 evidence 幂等写入并入队。返回新入库数。"""
    h_id = history_item.get("id") or ""
    new = 0
    for q in history_item.get("questions") or []:
        for er in q.get("engine_detail") or []:
            ev = build_evidence(h_id, q, er, history_item)
            if not ev:
                continue
            _, created_ok = repo.upsert_evidence(ev)
            if created_ok:
                new += 1
                if enqueue_parsing:
                    queue.enqueue(ev["id"])
    return new


def ingest_from_history(
    monitor_id: str | None = None,
    since: str | None = None,
    limit: int | None = None,
    enqueue_parsing: bool = True,
) -> dict:
    """从监测历史回填/补跑：构造新 evidence（幂等跳过已存在）并入队。

    返回 {"scanned": N, "new": N, "skipped": N, "enqueued": N}
    """
    items = get_store().load("monitor_history")
    scanned = new = skipped = enqueued = 0

    for h in items:
        h_id = h.get("id") or ""
        created = h.get("created_at") or ""
        if since and created and created < since:
            continue
        for q in h.get("questions") or []:
            if monitor_id and q.get("monitor_id") != monitor_id:
                continue
            for er in q.get("engine_detail") or []:
                ev = build_evidence(h_id, q, er, h)
                if not ev:
                    continue
                scanned += 1
                _, created_ok = repo.upsert_evidence(ev)
                if created_ok:
                    new += 1
                    if enqueue_parsing:
                        queue.enqueue(ev["id"])
                        enqueued += 1
                else:
                    skipped += 1
                if limit and new >= limit:
                    return {
                        "scanned": scanned,
                        "new": new,
                        "skipped": skipped,
                        "enqueued": enqueued,
                        "truncated": True,
                    }
    return {
        "scanned": scanned,
        "new": new,
        "skipped": skipped,
        "enqueued": enqueued,
        "truncated": False,
    }
