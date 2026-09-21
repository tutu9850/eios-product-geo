#!/usr/bin/env python
"""退役 `brand_mention` 里**没有证据父行**的孤儿行（维护脚本，默认 dry-run）。

为什么需要这个脚本
------------------
`brand_mention` 是 `geo_evidence` 的展开明细，但它**没有 `tenant_id` 列**，
所以账号分柜之后的 `reset_all()`（`POST /knowledge/reset`）对这张表无从下手：
清一个柜的时候，它的 evidence 父行被删了，mentions 却留了下来 —— 变成孤儿。

Owner 2026-09-22 拍板「登录账号分柜　清掉　3 暂时不用，先把 GEO 自己的柜做对」，
随后 2026-09-22 明确「继续清，都清干净了」。这张表没有退役门，本脚本就是这一条
清理动作的**唯一**入口（`docs/audits/2026-09-22-account-cabinet-residue.md` 有登记），
不再散落一次性 SQL。

判据（不是「删掉这 11 行」，而是一条可复现的规则）
--------------------------------------------------
一行 `brand_mention` 是孤儿 ⟺ 它的 `evidence_id` 在 `geo_evidence` 里**找不到**父行。
父行还在的 mention 一行都不碰 —— 脚本会在动手前再核一遍并拒绝执行。

用法
----
    cd ~/eios-product-geo
    .venv/bin/python scripts/retire_orphan_brand_mentions.py            # 只看
    .venv/bin/python scripts/retire_orphan_brand_mentions.py --apply    # 真删
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def db_path() -> Path:
    """与运行时同一份解析：`GEO_DB_PATH` 优先，否则 GEO 自己的 `apps/geo.db`。"""
    import os

    return Path(os.environ.get("GEO_DB_PATH", str(REPO / "apps" / "geo.db")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="真的删；不带就是 dry-run")
    args = ap.parse_args()

    path = db_path()
    if not path.exists():
        print(f"FAIL: 库不存在：{path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(path)
    try:
        total = conn.execute("select count(*) from brand_mention").fetchone()[0]
        orphans = conn.execute(
            """
            select id, analysis_id, brand_name, mention_type, created_at
              from brand_mention m
             where not exists (select 1 from geo_evidence e where e.id = m.evidence_id)
             order by created_at
            """
        ).fetchall()
        live = total - len(orphans)

        print(f"库：{path}")
        print(f"brand_mention 共 {total} 行；孤儿 {len(orphans)} 行；父行还在 {live} 行（一行不碰）")
        for oid, analysis_id, brand, mtype, created in orphans:
            print(f"  - {oid} | {analysis_id} | {brand} | {mtype} | {created}")

        if live:
            print(
                f"注意：仍有 {live} 行父行健在 —— 本次只删孤儿，不动它们。",
                file=sys.stderr,
            )
        if not orphans:
            print("没有孤儿行，什么都不用做。")
            return 0
        if not args.apply:
            print("\ndry-run：没有删任何行。要真删请加 --apply。")
            return 0

        ids = [o[0] for o in orphans]
        placeholders = ",".join("?" for _ in ids)
        # 再核一遍判据（期间可能有新写入），只删这一刻仍然是孤儿的行。
        cur = conn.execute(
            f"delete from brand_mention where id in ({placeholders}) "
            "and not exists (select 1 from geo_evidence e where e.id = brand_mention.evidence_id)",
            ids,
        )
        conn.commit()
        print(f"\n已删 {cur.rowcount} 行孤儿；剩余 {conn.execute('select count(*) from brand_mention').fetchone()[0]} 行。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
