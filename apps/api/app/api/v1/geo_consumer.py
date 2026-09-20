"""GEO 的只读交接面：让别的产品（顾问）查 GEO 自己的库。

Owner 2026-09-20 拍板：「留一个能让顾问连接到这个数据库里的接口，查 geo 的数据库」。

这个面暴露的是**GEO 自己的东西**，分两类：

1. GEO 的正本产物：监测对象、客户问题池、缺口、内容计划、GEO 自己的素材库；
2. GEO 从企业知识库读到的**快照**（``geo_knowledge_snapshots``）——每条都带
   ``source`` / ``contract`` / ``read_at`` / ``authoritative=false``，因为正本在知识库，
   GEO 这份可能已经旧了。顾问拿到的是快照，不是知识库。

它**不是**知识库的转口：这里没有 ``/knowledge/search`` 那种直通知识库的路。顾问要读
知识库，应该自己按知识库的契约去读（顾问本来就有那个能力）。这个面只回答「GEO 知道什么」。

身份：``app.product.consumer_auth`` 验签，fail-closed（无票 401 / 无 scope 403 /
本服务没配信任钥 503 / 本进程没有 PDP 503 / PDP 拒绝 403）。``audience`` 必须是 GEO。

每个响应都如实报出**这次读取的策略事实**（``policy.decision_id`` / ``policy_version`` /
``policy_enforcement``）—— 允许时也报。原因很直：不接受「已授权」这种由本服务自己拼的说法，
只接受一次真实决策的 id。``policy_enforcement`` 是这台机器上的 PDP 算不算数的独立事实：
``enforced`` 才是强制；dev 的 ``development_allow`` 是允许一切的替身，会照原样报出来。

租户诚实说明：GEO 现在的业务数据仍按 legacy 租户柜（``tenant_id``）存，还没迁到 EIOS
的部署/企业身份，所以这里如实把 ``tenant_id`` 一起报出来 —— 不假装按企业做了隔离。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.envelope import ok
from app.product.consumer_auth import ConsumerPrincipal, require_consumer
from app.services import knowledge_snapshot as snapshot_store
from app.services.store import current_tenant, get_store

router = APIRouter(prefix="/api/v1/geo/consumer")

MAX_LIMIT = 100
MAX_QUERY = 200


def _shape(principal: ConsumerPrincipal) -> dict:
    """每个响应都带上：谁在读、读的是哪个柜、正本在哪。"""
    return {
        "contract": "product.geo_consumer/v1",
        "read_by": {
            "subject": principal.subject,
            "service_id": principal.service_id,
            "deployment_id": principal.deployment_id,
            "enterprise_id": principal.enterprise_id,
            "scopes": list(principal.scopes),
        },
        "policy": {
            **principal.policy_decision,
            "enforcement": principal.policy_enforcement,
        },
        "tenant_id": current_tenant(),
        "tenant_note": "GEO 业务数据仍按 legacy 租户柜存放，尚未按 EIOS 企业身份分区",
    }


def _limit(value: int) -> int:
    return max(1, min(int(value or 20), MAX_LIMIT))


def _hit(text: str, tokens: list[str]) -> bool:
    low = (text or "").lower()
    return any(t in low for t in tokens)


def _tokens(query: str) -> list[str]:
    q = (query or "").strip().lower()
    if not q:
        return []
    parts = [p for p in q.replace("，", " ").replace(",", " ").split() if p]
    return parts or [q]


@router.get("/summary")
async def geo_consumer_summary(principal: ConsumerPrincipal = Depends(require_consumer)):
    """GEO 手里有什么：正本产物计数 + 读过的知识快照概况。"""
    store = get_store()
    items = store.load("monitor_items")
    questions = store.load("questions")
    gaps = store.load("gaps")
    plans = store.load("content_plans")
    materials = store.load("kb")
    snap = snapshot_store.summary()
    return ok(
        {
            **_shape(principal),
            "geo": {
                "monitor_items": len(items),
                "questions": len(questions),
                "gaps": len(gaps),
                "content_plans": len(plans),
                "materials": len(materials),
            },
            "knowledge_snapshots": snap,
        }
    )


@router.get("/snapshots")
async def geo_consumer_snapshots(
    kind: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20),
    principal: ConsumerPrincipal = Depends(require_consumer),
):
    """GEO 从企业知识库读到过的东西（快照，不是正本）。"""
    rows = snapshot_store.list_recent(kind=kind, limit=_limit(limit))
    return ok({**_shape(principal), "kind": kind, "count": len(rows), "snapshots": rows})


@router.get("/knowledge")
async def geo_consumer_knowledge(
    q: str = Query(default="", max_length=MAX_QUERY),
    limit: int = Query(default=20),
    principal: ConsumerPrincipal = Depends(require_consumer),
):
    """在 GEO 自己的库里找东西：GEO 正本产物 + 知识快照文本。

    没给 ``q`` 时列出 GEO 的正本产物（相当于目录），不给假命中。
    """
    top = _limit(limit)
    tokens = _tokens(q)
    found: list[dict] = []

    def add(kind: str, title: str, detail: str, *, origin: str, **extra) -> None:
        if len(found) >= top:
            return
        if tokens and not _hit(f"{title} {detail}", tokens):
            return
        found.append(
            {
                "kind": kind,
                "title": title,
                "detail": detail,
                "origin": origin,
                "authoritative": origin == "geo",
                "source": "GEO 自己的库" if origin == "geo" else "GEO 读知识库留下的快照",
                **extra,
            }
        )

    store = get_store()
    for it in store.load("monitor_items"):
        cfg = it.get("config_json") or {}
        add(
            "monitor_item",
            str(it.get("entity") or cfg.get("company") or ""),
            f"type={it.get('type')} status={it.get('status')}",
            origin="geo",
            monitor_id=it.get("monitor_id"),
        )
    for it in store.load("questions"):
        add("question", str(it.get("question") or ""), str(it.get("intent") or ""), origin="geo")
    for it in store.load("gaps"):
        add(
            "gap",
            str(it.get("question") or ""),
            str(it.get("missing_information") or ""),
            origin="geo",
        )
    for it in store.load("content_plans"):
        add("content_plan", str(it.get("topic") or ""), str(it.get("reason") or ""), origin="geo")
    for it in store.load("kb"):
        add("material", str(it.get("title") or ""), str(it.get("source") or ""), origin="geo")

    for row in snapshot_store.list_recent(limit=MAX_LIMIT):
        payload = row.get("payload") or {}
        for hit in payload.get("hits") or []:
            add(
                "snapshot_hit",
                str(hit.get("canonical_name") or hit.get("document_title") or ""),
                str(hit.get("snippet") or "")[:400],
                origin="knowledge_snapshot",
                knowledge_object_id=hit.get("object_id"),
                document_id=hit.get("document_id"),
                document_title=hit.get("document_title"),
                evidence_ids=hit.get("evidence_ids") or [],
                read_at=row.get("last_read_at"),
                snapshot_id=row.get("snapshot_id"),
            )
        for item in payload.get("items") or []:
            add(
                "snapshot_object"
                if item.get("object_id")
                else ("snapshot_document" if item.get("document_id") else "snapshot_item"),
                str(item.get("canonical_name") or item.get("title") or ""),
                str(item.get("object_type") or item.get("status") or ""),
                origin="knowledge_snapshot",
                knowledge_object_id=item.get("object_id"),
                document_id=item.get("document_id"),
                evidence_ids=item.get("evidence_ids") or [],
                read_at=row.get("last_read_at"),
                snapshot_id=row.get("snapshot_id"),
            )

    return ok(
        {
            **_shape(principal),
            "query": q,
            "count": len(found),
            "items": found,
            "truncated": len(found) >= top,
            "note": "knowledge_snapshot 条目是读过的快照，可能已过期；正本在知识库",
        }
    )
