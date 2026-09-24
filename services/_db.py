"""services 层 SQLite 直连 helper（collector/embed 等非 API 模块用）

不依赖 app.* 导入（services 目录独立于 apps/api 的 PYTHONPATH），
直接用 sqlite3 标准库操作同一 geo.db（表结构由 app.models.geo_models.init_db 创建）。
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

_GEO_ROOT = Path(__file__).resolve().parents[1]
# 2026-08-15 修复：统一用 GEO_DB_PATH（与 API 层 apps/api/app/core/config.py 一致）。
# 原实现硬编码仓库根 geo.db（0 字节空库无表）→ collector/embed 读写与 API 层 apps/geo.db 分裂，
# market/signals 等经 collector 读表时表不存在 → 500。默认 apps/geo.db 即实际业务库。
import os as _os
from contextvars import ContextVar

DB_PATH = Path(_os.environ.get("GEO_DB_PATH", str(_GEO_ROOT / "apps" / "geo.db")))

#: 默认柜。旧调用方（脚本 / 后台任务 / 没带任何身份的请求）落这里。
#:
#: Owner 2026-09-22 拍板「登录账号分柜」后，柜号不再写死：请求走 API 时由
#: ``app.product.session.cabinet_for_session`` 按已验证账号分配，经 store 的 contextvar
#: 传下来（见 ``_tenant()``）。这里保留的默认值只服务「没有请求上下文」的那几种调用。
DEFAULT_TENANT = "tenant_corp_01"

# Per-context snapshots used by save_table's three-way merge.  This keeps the
# legacy helper safe for concurrent background jobs without changing its API.
_snapshots: ContextVar[dict[tuple[str, str], dict[str, dict]]] = ContextVar(
    "geo_db_snapshots", default={}
)


def _tenant() -> str:
    """当前柜号：优先读 API 层的当前租户，读不到才回落默认柜。

    本模块刻意不依赖 ``app.*``（见文件头），所以用延迟 import + 兜底的方式取同一个值，
    而不是再定义一份租户状态 —— 两份状态会各自漂移，那就成了第二个 store。
    """
    try:
        from app.services.store import current_tenant

        return current_tenant() or DEFAULT_TENANT
    except Exception:  # noqa: BLE001 — 独立脚本 / 后台线程没有 API 层上下文
        return DEFAULT_TENANT


def current_tenant_or_default() -> str:
    """当前柜号（没有请求上下文时是默认柜）。给别的 services 模块共用同一套解析。"""
    return _tenant()


def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_table(table: str) -> list[dict]:
    """读表全部记录（data_json 解码，按创建顺序）。"""
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT id, data_json FROM {table} WHERE tenant_id=? ORDER BY created_at ASC",
            (_tenant(),),
        ).fetchall()
        out = []
        for r in rows:
            try:
                d = json.loads(r["data_json"] or "{}")
            except Exception:
                d = {}
            d.setdefault("id", r["id"])
            out.append(d)
        snapshots = dict(_snapshots.get())
        snapshots[(table, _tenant())] = {str(d["id"]): dict(d) for d in out}
        _snapshots.set(snapshots)
        return out
    finally:
        conn.close()


def save_table(table: str, items: list[dict]) -> None:
    """事务内 upsert，基于最近一次 load_table 做三路合并。

    调用方仍可传入完整列表；并发请求新增、修改或删除不同记录时，
    不会再因为整表 DELETE/INSERT 而互相覆盖。未经过 load_table 的内部
    调用保留旧的全量替换语义。
    """
    conn = _conn()
    try:
        tenant = _tenant()
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            f"SELECT id, data_json, created_at FROM {table} WHERE tenant_id=?", (tenant,)
        ).fetchall()
        current = {}
        created = {}
        for r in rows:
            try:
                d = json.loads(r["data_json"] or "{}")
            except Exception:
                d = {}
            d.setdefault("id", r["id"])
            current[str(r["id"])] = d
            created[str(r["id"])] = r["created_at"]
        supplied = {}
        for it in items:
            row_id = it.get("id") or f"{table}_{uuid.uuid4().hex[:12]}"
            supplied[str(row_id)] = dict(it, id=row_id)
        baseline = _snapshots.get().get((table, tenant))
        if baseline is None:
            merged = supplied
        else:
            merged = dict(current)
            for row_id, sent in supplied.items():
                if row_id not in baseline or row_id not in current:
                    merged[row_id] = sent
                    continue
                before = baseline[row_id]
                if sent == before:
                    continue
                patch = {k: v for k, v in sent.items() if before.get(k) != v}
                updated = dict(current[row_id]); updated.update(patch); updated["id"] = row_id
                merged[row_id] = updated
            for row_id, before in baseline.items():
                if row_id not in supplied and row_id in current and current[row_id] == before:
                    merged.pop(row_id, None)
        merged_ids = set(merged)
        for row_id in set(current) - merged_ids:
            conn.execute(f"DELETE FROM {table} WHERE id=? AND tenant_id=?", (row_id, tenant))
        now = datetime.now(timezone.utc).isoformat()
        for row_id, it in merged.items():
            payload = dict(it)
            payload.pop("id", None)
            payload.pop("tenant_id", None)
            conn.execute(
                f"INSERT INTO {table} (id, data_json, tenant_id, created_at) VALUES (?,?,?,?) "
                f"ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json",
                (row_id, json.dumps(payload, ensure_ascii=False), tenant, created.get(row_id, now)),
            )
        conn.commit()
        snapshots = dict(_snapshots.get()); snapshots[(table, tenant)] = {k: dict(v) for k, v in merged.items()}; _snapshots.set(snapshots)
    finally:
        conn.close()
