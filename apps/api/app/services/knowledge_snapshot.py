"""GEO ← EIOS 知识库：读到的内容落进 GEO 自己的库（快照台账）。

Owner 2026-09-20 拍板的两条，这个模块是第二条的落地：

1. **不允许 GEO 往知识库写**（见 ``adapters/eios.write_candidate``）。
2. **读到的所有信息存进自己的数据库里存着**。

所以这里只做一件事：把一次读（检索命中 / 对象目录 / 文档列表 / 关系）连同
「谁给的、什么时候给的、哪份契约」写成一行，供 GEO 自己复用、也供顾问来查。
``authoritative`` 恒为 0 —— 正本在知识库，GEO 这份只是快照，接口上如实标注。

重复读同一份内容不会堆行：payload_hash 相同就累加 read_count 并推进 last_read_at。
哈希只算稳定内容（``_VOLATILE_KEYS`` 里的字段每次调用都会变，不进哈希），
所以这张表回答的是「读到过哪些东西」，不是「调了多少次」。
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.models.geo_models import GeoKnowledgeSnapshots, SessionLocal, init_db
from app.services.store import current_tenant

logger = logging.getLogger("eios.geo.knowledge_snapshot")

SOURCE = "eios-knowledge"
#: 每次调用都会变、但说不出「读到了什么」的字段：不进哈希，否则去重永远不命中。
_VOLATILE_KEYS = ("query_id", "read_at", "provenance", "snapshot_recorded")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(payload: dict[str, Any]) -> str:
    """稳定内容哈希（排序键、去空白差异、丢掉每次都会变的字段）。"""
    stable = {k: v for k, v in payload.items() if k not in _VOLATILE_KEYS}
    blob = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def record(kind: str, payload: dict[str, Any], *, source_url: str = "") -> dict[str, Any]:
    """记一次读。返回 {recorded, snapshot_id, read_count, payload_hash}。

    调用方（``adapters/eios``）把它当尽力而为的一步：记不上不影响这次读，但适配层会
    在返回值里把 ``snapshot_recorded`` 标成 false，不假装记上了。
    """
    init_db()
    tenant_id = current_tenant()
    # 快照必须带上经过宿主票验证的企业范围。旧快照没有这个水印时，
    # 只能视为不可归属，后续读取会 fail-closed，避免不同企业串资料。
    try:
        from app.product.session import current_product_session

        session = current_product_session()
    except Exception:  # legacy/local mode has no product session
        session = None
    scoped_payload = dict(payload)
    if session is not None:
        scoped_payload["_knowledge_scope"] = {
            "deployment_id": session.deployment_id,
            "enterprise_id": session.enterprise_id,
        }
    payload = scoped_payload
    digest = payload_hash(payload)
    contract = payload.get("contract")
    db = SessionLocal()
    try:
        row = (
            db.query(GeoKnowledgeSnapshots)
            .filter(
                GeoKnowledgeSnapshots.tenant_id == tenant_id,
                GeoKnowledgeSnapshots.kind == kind,
                GeoKnowledgeSnapshots.payload_hash == digest,
            )
            .first()
        )
        if row is not None:
            row.read_count = int(row.read_count or 1) + 1
            row.last_read_at = _now()
            if source_url:
                row.source_url = source_url[:256]
            db.commit()
            return {
                "recorded": False,
                "snapshot_id": row.id,
                "read_count": row.read_count,
                "payload_hash": digest,
            }
        row = GeoKnowledgeSnapshots(
            id=f"ksnap_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            kind=kind,
            source=SOURCE,
            source_url=(source_url or "")[:256],
            contract=str(contract)[:64] if contract else None,
            authoritative=0,
            payload_hash=digest,
            read_count=1,
            first_read_at=_now(),
            last_read_at=_now(),
            data_json=json.dumps(payload, ensure_ascii=False, default=str),
        )
        db.add(row)
        db.commit()
        return {
            "recorded": True,
            "snapshot_id": row.id,
            "read_count": 1,
            "payload_hash": digest,
        }
    finally:
        db.close()


def _row_to_dict(row: GeoKnowledgeSnapshots) -> dict[str, Any]:
    try:
        payload = json.loads(row.data_json or "{}")
    except Exception:  # noqa: BLE001
        payload = {}
    return {
        "snapshot_id": row.id,
        "kind": row.kind,
        "source": row.source,
        "source_url": row.source_url,
        "contract": row.contract,
        "authoritative": bool(row.authoritative),
        "note": "这是 GEO 从 EIOS 知识库读到的快照；正本在知识库，可能已经更新",
        "read_count": int(row.read_count or 1),
        "first_read_at": row.first_read_at.isoformat() if row.first_read_at else None,
        "last_read_at": row.last_read_at.isoformat() if row.last_read_at else None,
        "payload": payload,
    }


def _scope_matches(payload: dict[str, Any]) -> bool:
    """Only expose snapshots stamped for the verified current enterprise."""
    try:
        from app.product.session import current_product_session

        session = current_product_session()
    except Exception:
        session = None
    if session is None:
        return True  # explicit legacy/local mode keeps historical compatibility
    scope = payload.get("_knowledge_scope") or {}
    return (
        scope.get("deployment_id") == session.deployment_id
        and scope.get("enterprise_id") == session.enterprise_id
    )


def list_recent(*, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """最近读到的东西（按最后读到时间倒序）。"""
    init_db()
    db = SessionLocal()
    try:
        q = db.query(GeoKnowledgeSnapshots).filter(
            GeoKnowledgeSnapshots.tenant_id == current_tenant()
        )
        if kind:
            q = q.filter(GeoKnowledgeSnapshots.kind == kind)
        rows = q.order_by(GeoKnowledgeSnapshots.last_read_at.desc()).limit(max(1, min(int(limit), 200))).all()
        out = []
        for row in rows:
            item = _row_to_dict(row)
            if _scope_matches(item.get("payload") or {}):
                out.append(item)
        return out
    finally:
        db.close()


def _iter_items(kind: str):
    """按 kind 遍历台账里每一条 payload 的 items（新读到的排前面）。"""
    for row in list_recent(kind=kind, limit=200):
        for item in row["payload"].get("items") or []:
            yield row, item


def chunks_for_document(document_id: str) -> list[dict[str, Any]]:
    """GEO 自己存下来的、某份文档的切块文本（正本在知识库，这是 GEO 读过的快照）。

    为什么需要它：知识库里**未发布**文档（``status=chunked`` 之类）的切块，检索的
    material 层会照给有权限的读者，但 ``GET /documents/{id}/chunks`` 对未发布文档
    额外要求治理 scope —— GEO 只有读 scope，于是那道门 404（fail-closed，不是 bug）。
    GEO 不能改权威的门，但**读到过的切块文本已经在自己的台账里**，这里提供按文档
    取回的通道，接口上如实标 ``authoritative=false``。

    合并顺序：先 ``kind=chunks``（每次读都专门记的），再兜底扫 ``kind=search``
    （早期版本只把切块存在检索命中里）。同一个 chunk_id 只留第一次见到的。
    """
    if not document_id:
        return []
    found: dict[str, dict[str, Any]] = {}

    def _collect(item: dict[str, Any], *, origin: str) -> None:
        if str(item.get("document_id") or "") != document_id:
            return
        text = str(item.get("text") or item.get("content") or item.get("snippet") or item.get("value") or "")
        chunk_id = str(item.get("chunk_id") or "")
        if not chunk_id or not text.strip() or chunk_id in found:
            return
        found[chunk_id] = {
            "document_id": document_id,
            "chunk_id": chunk_id,
            "document_title": str(item.get("document_title") or ""),
            "text": text,
            "ordinal": item.get("ordinal"),
            "layer": item.get("layer") or item.get("authority"),
            "source": "geo_snapshot",
            "origin": origin,
            "authoritative": False,
            "note": "GEO 从企业知识库读到并留下的切块快照；正本在知识库，可能已经更新",
        }

    for _row, item in _iter_items("chunks"):
        _collect(item, origin="snapshot:chunks")
    for _row, item in _iter_items("search"):
        _collect(item, origin="snapshot:search")
    return list(found.values())


def documents_with_chunks() -> list[dict[str, Any]]:
    """GEO 读到过切块的文档（含知识库里**未发布**、在文档列表里看不到的那些）。

    为什么需要：``GET /documents`` 只列已发布文档，而 GEO 从检索的 material 层
    读到过未发布文档的切块（实测两份 docx）。同步/初始化时如果只看文档列表，
    这些「已经读得到、也存下来了」的资料就永远不出现在候选里。

    ``chunks`` 数的是**读到过几个不同的切块**（同一个 chunk 在 ``chunks`` 与
    ``search`` 两种台账里都出现过也只算一次），否则后面每读一次检索这个数就虚涨。
    """
    docs: dict[str, dict[str, Any]] = {}
    for kind, origin in (("chunks", "snapshot:chunks"), ("search", "snapshot:search")):
        for row, item in _iter_items(kind):
            doc_id = str(item.get("document_id") or "")
            chunk_id = str(item.get("chunk_id") or "")
            if not doc_id:
                continue
            entry = docs.setdefault(
                doc_id,
                {
                    "document_id": doc_id,
                    "title": str(item.get("document_title") or ""),
                    "chunk_ids": set(),
                    "sources": set(),
                    "layer": None,
                    "last_read_at": row.get("last_read_at"),
                },
            )
            if chunk_id:
                entry["chunk_ids"].add(chunk_id)
            entry["sources"].add(origin)
            if not entry["title"] and item.get("document_title"):
                entry["title"] = str(item["document_title"])
            if not entry["layer"] and (item.get("layer") or item.get("authority")):
                entry["layer"] = item.get("layer") or item.get("authority")
            if row.get("last_read_at") and (
                not entry["last_read_at"] or row["last_read_at"] > entry["last_read_at"]
            ):
                entry["last_read_at"] = row["last_read_at"]
    out = []
    for entry in docs.values():
        out.append(
            {
                "document_id": entry["document_id"],
                "title": entry["title"] or entry["document_id"],
                "chunks": len(entry["chunk_ids"]),
                "layer": entry["layer"] or "material",
                "sources": sorted(entry["sources"]),
                "last_read_at": entry["last_read_at"],
                "readable_from": ["geo_snapshot"],
                "snapshot_only": True,  # 文档门可能关着；切块文本在 GEO 台账里
                "note": "GEO 读到过切块的文档；正本在知识库，这份是快照",
            }
        )
    out.sort(key=lambda d: (d["title"] or d["document_id"]))
    return out


def chunk_snapshot_payload(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """把一次读到的切块整理成台账 payload（稳定字段，重复读不堆行）。"""
    items = []
    for c in chunks:
        chunk_id = str(c.get("chunk_id") or "")
        text = str(c.get("text") or c.get("snippet") or c.get("value") or "")
        if not chunk_id or not text.strip():
            continue
        items.append(
            {
                "document_id": c.get("document_id"),
                "document_title": c.get("document_title") or "",
                "chunk_id": chunk_id,
                "ordinal": c.get("ordinal"),
                "layer": c.get("layer") or c.get("authority"),
                "text": text,
            }
        )
    return {"contract": "geo.knowledge_chunks/v1", "items": items}



def _dedup_items(items, key):
    """按 key 去重、新读到的排前面（台账本来就是倒序的）。"""
    out, seen = [], set()
    for item in items:
        k = str(item.get(key) or "")
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def objects(*, kind_filter: str | None = None, limit: int = 400) -> list[dict[str, Any]]:
    """GEO 自己柜里的企业知识对象（快照台账 ``kind=objects``）。

    为什么要有它：2026-09-22 Owner 拍板「除了手动的知识库同步以外，不让 GEO 去知识库里
    找东西」。运行时（画像 / 蒸馏 / 监测 / 内容生成）于是改读**这次同步带回来的那份**。
    没有它 = 还没同步过，如实返回空，不去打 :8040。

    ``kind_filter="fact"`` = 只要事实型对象（``type=fact``）；``None`` = 全部（实体 + 事实）。
    """
    items: list[dict[str, Any]] = []
    for _row, item in _iter_items("objects"):
        if kind_filter and str(item.get("object_type") or "") != kind_filter:
            continue
        items.append(item)
    return _dedup_items(items, "object_id")[: max(1, int(limit))]


def documents(limit: int = 200) -> list[dict[str, Any]]:
    """GEO 自己柜里的企业文档列表（快照台账 ``kind=documents``）。"""
    items = [item for _row, item in _iter_items("documents")]
    return _dedup_items(items, "document_id")[: max(1, int(limit))]


def relations(limit: int = 200) -> list[dict[str, Any]]:
    """GEO 自己柜里的对象关系（快照台账 ``kind=relations``）。"""
    items = [item for _row, item in _iter_items("relations")]
    out, seen = [], set()
    for item in items:
        key = f"{item.get('source_id')}|{item.get('relation_type')}|{item.get('target_id')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[: max(1, int(limit))]


def all_chunks(limit: int = 2000) -> list[dict[str, Any]]:
    """GEO 自己柜里读过的**全部文档切块**（快照台账 ``kind=chunks``）。

    内容生成按本企业资料检索时用这个：切块是 GEO 同步时一并带回来的，
    运行时不再回头去打知识库。
    """
    items = []
    for _row, item in _iter_items("chunks"):
        text = str(item.get("text") or item.get("snippet") or item.get("value") or "")
        if str(item.get("chunk_id") or "") and text.strip():
            items.append(item)
    return _dedup_items(items, "chunk_id")[: max(1, int(limit))]


def has_anything() -> bool:
    """GEO 柜里有没有从知识库同步回来的东西（用于如实区分「没同步」与「同步了但没资料」）。"""
    for kind in ("objects", "documents", "chunks", "relations"):
        if next(_iter_items(kind), None) is not None:
            return True
    return False


def summary() -> dict[str, Any]:
    """企业资料就绪度：GEO 到底从知识库读到过什么（本地读，不去打知识库）。

    这是 ``/onboard/status`` 里「企业资料」那一行的真来源 —— 原来那一行拿的是
    监测对象数冒充「已就绪」，是标签错位。
    """
    init_db()
    db = SessionLocal()
    try:
        rows = (
            db.query(GeoKnowledgeSnapshots)
            .filter(GeoKnowledgeSnapshots.tenant_id == current_tenant())
            .all()
        )
    finally:
        db.close()
    kinds: dict[str, int] = {}
    objects = 0
    documents = 0
    last_read_at: str | None = None
    for r in rows:
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
        ts = r.last_read_at.isoformat() if r.last_read_at else None
        if ts and (last_read_at is None or ts > last_read_at):
            last_read_at = ts
        try:
            payload = json.loads(r.data_json or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        if r.kind == "objects":
            objects = max(objects, int(payload.get("count") or 0))
        elif r.kind == "documents":
            documents = max(documents, int(payload.get("count") or 0))
    return {
        "source": SOURCE,
        "authoritative": False,
        "read_ever": bool(rows),
        "snapshot_count": len(rows),
        "objects_seen": objects,
        "documents_seen": documents,
        "kinds": kinds,
        "last_read_at": last_read_at,
        "note": "GEO 只读知识库，读到的内容留在本表的快照里；正本仍在知识库",
    }


__all__ = [
    "payload_hash",
    "record",
    "list_recent",
    "summary",
    "objects",
    "documents",
    "relations",
    "all_chunks",
    "has_anything",
    "SOURCE",
]
