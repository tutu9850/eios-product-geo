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
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


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


__all__ = ["payload_hash", "record", "list_recent", "summary", "SOURCE"]
