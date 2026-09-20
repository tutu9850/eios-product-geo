"""S1 数据恢复（2026-08-19）：把 BFF Postgres geo_records 灌回 3002 卷库（tenant_corp_01）。

背景：容器重建后发现 apps/api/.env 的 GEO_DB_PATH 相对路径导致数据库一直写在容器可写层，
卷库从未被真正使用（空壳）→ 重建容器后 3002 数据丢失。BFF 08-15 后一直写本地副本
（Postgres geo_records），这是最完整的数据域副本。

用法（在容器内执行）：
  docker cp /tmp/restore_*.json eios-geo:/tmp/
  docker exec eios-geo python3 /app/apps/api/app/services/geo_restore_from_bff.py

输入：/tmp/restore_<kind>.json = json_agg(data) 数组（psql 导出，无记录时文件内容为 NULL/空）
输出：每表恢复行数 + 失败数
"""
import glob
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/apps/api")

from app.models.geo_models import init_db  # noqa: E402
from app.services.store import Store, get_store  # noqa: E402

# BFF kind → 3002 表名
KIND_TABLE = {
    "questions": "questions",
    "gaps": "gaps",
    "plans": "content_plans",
    "materials": "kb",
    "monitorItems": "monitor_items",
    "monitorTasks": "monitor_tasks",
}

TENANT = "tenant_corp_01"


def load_items(kind: str) -> list[dict]:
    fp = f"/tmp/restore_{kind}.json"
    if not os.path.exists(fp):
        return []
    raw = open(fp, encoding="utf-8").read().strip()
    if not raw or raw == "NULL":
        return []
    try:
        items = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"[{kind}] JSON 解析失败: {exc}")
        return []
    return [i for i in items if isinstance(i, dict)]


def main() -> None:
    init_db()
    store = get_store()
    total_ok = total_fail = 0
    for kind, table in KIND_TABLE.items():
        items = load_items(kind)
        if not items:
            print(f"[{kind}] 无记录，跳过")
            continue
        # 先清目标租户现有行（卷库可能残留旧壳数据，如 3 条 monitor_items），再灌
        existing = store.load(table, TENANT)
        if existing:
            n = 0
            for row in existing:
                if store.delete(table, row.get("id", ""), TENANT):
                    n += 1
            print(f"[{kind}] 清空 {table} 存量 {n} 条")
        ok = 0
        for it in items:
            row = dict(it)
            row.setdefault("tenant_id", TENANT)
            try:
                # insert 同步热表列（question/topic/status/...），data_json 保留全字段
                store.insert(table, row, TENANT)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                total_fail += 1
                print(f"[{kind}] 失败 {row.get('id')}: {exc}")
        total_ok += ok
        print(f"[{kind}] → {table}: 恢复 {ok} 条")
    print(f"\n完成：恢复 {total_ok} 条，失败 {total_fail} 条")


if __name__ == "__main__":
    main()
