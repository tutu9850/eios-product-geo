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

DB_PATH = Path(_os.environ.get("GEO_DB_PATH", str(_GEO_ROOT / "apps" / "geo.db")))

TENANT = "tenant_corp_01"


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
            (TENANT,),
        ).fetchall()
        out = []
        for r in rows:
            try:
                d = json.loads(r["data_json"] or "{}")
            except Exception:
                d = {}
            d.setdefault("id", r["id"])
            out.append(d)
        return out
    finally:
        conn.close()


def save_table(table: str, items: list[dict]) -> None:
    """整表替换（事务原子）。"""
    conn = _conn()
    try:
        conn.execute(f"DELETE FROM {table} WHERE tenant_id=?", (TENANT,))
        now = datetime.now(timezone.utc).isoformat()
        for it in items:
            row_id = it.get("id") or f"{table}_{uuid.uuid4().hex[:12]}"
            payload = dict(it)
            payload.pop("id", None)
            conn.execute(
                f"INSERT INTO {table} (id, data_json, tenant_id, created_at) VALUES (?,?,?,?)",
                (row_id, json.dumps(payload, ensure_ascii=False), TENANT, now),
            )
        conn.commit()
    finally:
        conn.close()
