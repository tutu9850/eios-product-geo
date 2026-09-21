#!/usr/bin/env python3
"""GEO 内容生成选材算法 · 离线评估（宪法 §21/§24 允许的评估工作）。

只做评估，**不改生产选材逻辑**。三种候选算法全部确定性、不调模型、不联网。

- A0 = 现状（生产口径）：整篇 n_gram_scores（标题 2x + 正文 1x）→ 按文档分排序取 Top-K，
       并列保持原顺序（= 最新在前）。
- A1 = 最佳 Chunk（宪法 §8/§9）：文档分来自其**最高相关的 Chunk**，不做整篇累计。
- A2 = A1 + 重复过滤 + 信息覆盖（宪法 §10–§12）：按 Chunk 贪心选取，
       每步分数 = Chunk 相关分 - λ × 与已选 Chunk 的最大相似度；
       低于最低分阈值的候选一律不选（宪法 §17：无资料不凑数）。

用法：
    .venv/bin/python scripts/geo_selection_eval.py [--top-k 2] [--lam 0.6] [--min-score 2] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.chunking import chunk_text  # noqa: E402  确定性切块（与生产同一套）
from services.embed import _n_gram_keys, n_gram_scores  # noqa: E402  确定性打分原语

EVAL_SET = Path(__file__).resolve().parent / "geo_selection_eval_set.json"


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_corpus(path: Path = EVAL_SET) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for d in data["documents"]:
        d["text_chunks"] = chunk_text(d["content"])  # Raw Material → Chunk（裁定 4）
    return data


def doc_group(doc_id: str, groups: dict[str, list[str]]) -> str | None:
    for name, ids in groups.items():
        if doc_id in ids:
            return name
    return None


# ---------------- A0：现状（整篇累计口径） ----------------
def select_a0(docs: list[dict], question: str, top_k: int) -> list[dict]:
    scores = n_gram_scores(question, docs, title_key="title", content_key="content")
    order = sorted(docs, key=lambda d: -scores.get(str(d["id"]), 0.0))  # 稳定排序 = 并列保持原序
    out = []
    for d in order[:top_k]:
        out.append({"doc_id": d["id"], "title": d["title"], "score": scores.get(d["id"], 0.0),
                    "chunk_ordinal": None, "chunk_score": None,
                    "selection_reason": "whole-document key overlap (current production rule)"})
    return out


# ---------------- A1：最佳 Chunk ----------------
def chunk_scores(question: str, doc: dict) -> list[tuple[dict, int]]:
    q = _n_gram_keys(question)
    return [(c, len(q & _n_gram_keys(str(c["text"])))) for c in doc["text_chunks"]]


def title_bonus(question: str, doc: dict) -> int:
    q = _n_gram_keys(question)
    return len(q & _n_gram_keys(str(doc.get("title") or "")))


def select_a1(docs: list[dict], question: str, top_k: int, min_score: int = 1) -> list[dict]:
    rows = []
    for d in docs:
        scored = chunk_scores(question, d)
        if not scored:
            continue
        best, best_hit = max(scored, key=lambda t: t[1])
        total = best_hit + 2 * title_bonus(question, d)
        if best_hit < min_score:
            continue
        rows.append({"doc_id": d["id"], "title": d["title"], "score": float(total),
                     "chunk_ordinal": best.get("ordinal"), "chunk_score": best_hit,
                     "chunk_text": str(best.get("text") or "")[:80],
                     "selection_reason": f"best chunk hit {best_hit} key(s)"})
    rows.sort(key=lambda r: -r["score"])
    return rows[:top_k]


# ---------------- A2：A1 + 去重 + 覆盖 ----------------
def select_a2(docs: list[dict], question: str, top_k: int, lam: float = 0.6,
              min_score: int = 2) -> list[dict]:
    q = _n_gram_keys(question)
    cands: list[dict] = []
    for d in docs:
        tb = title_bonus(question, d)
        for c, hit in chunk_scores(question, d):
            if hit <= 0:
                continue
            cands.append({"doc_id": d["id"], "title": d["title"], "chunk_ordinal": c.get("ordinal"),
                          "chunk_score": hit, "keys": _n_gram_keys(str(c["text"])),
                          "chunk_text": str(c.get("text") or "")[:80], "title_bonus": tb})
    chosen: list[dict] = []
    while cands and len(chosen) < top_k:
        best_i, best_val = None, None
        for i, c in enumerate(cands):
            sim = max((_jaccard(c["keys"], s["keys"]) for s in chosen), default=0.0)
            val = c["chunk_score"] - lam * sim
            if best_val is None or val > best_val or (val == best_val and c["chunk_score"] > cands[best_i]["chunk_score"]):
                best_i, best_val = i, val
        pick = cands.pop(best_i)
        sim = max((_jaccard(pick["keys"], s["keys"]) for s in chosen), default=0.0)
        if pick["chunk_score"] < min_score and chosen:
            break  # 宪法 §17：低于阈值不再凑数
        if pick["chunk_score"] < min_score:
            break
        chosen.append({**pick, "score": float(pick["chunk_score"] + 2 * pick["title_bonus"]),
                       "selection_reason": f"chunk hit {pick['chunk_score']} key(s), dedup-penalised (last sim {sim:.2f})"})
    out = []
    for c in chosen:
        c.pop("keys", None)
        c.pop("title_bonus", None)
        out.append(c)
    return out


# ---------------- 评分 ----------------
def evaluate(data: dict, top_k: int, lam: float, min_score: int) -> dict:
    docs = data["documents"]
    groups = data.get("duplicate_groups") or {}
    algos = {
        "A0_whole_doc": lambda q: select_a0(docs, q, top_k),
        "A1_best_chunk": lambda q: select_a1(docs, q, top_k, 1),
        "A2_chunk_dedup_cover": lambda q: select_a2(docs, q, top_k, lam, min_score),
    }
    report: dict = {"top_k": top_k, "lambda": lam, "min_score": min_score, "tasks": {}}
    for task in data["tasks"]:
        q, exp = task["question"], task["expect"]
        row: dict = {"question": q, "category": task["category"], "algos": {}}
        for name, fn in algos.items():
            sel = fn(q)
            sel_ids = [s["doc_id"] for s in sel]
            r = {"selected": [{"doc_id": s["doc_id"], "chunk_ordinal": s["chunk_ordinal"],
                               "score": round(s["score"], 2)} for s in sel],
                 "empty": not sel}
            # hit@K
            if exp.get("must_include"):
                r["hit"] = any(i in sel_ids for i in exp["must_include"])
            else:
                r["hit"] = None
            # 无资料任务
            if exp.get("expect_empty"):
                r["pass_empty"] = not sel
            # 重复组不得超过 group_max
            if exp.get("group_max") is not None:
                counts: dict[str, int] = {}
                for s in sel:
                    g = doc_group(s["doc_id"], groups)
                    if g:
                        counts[g] = counts.get(g, 0) + 1
                r["max_from_one_group"] = max(counts.values(), default=0)
                r["pass_group_max"] = r["max_from_one_group"] <= exp["group_max"]
            # 排序比较
            cmp = exp.get("must_rank_above")
            if cmp:
                if cmp["better"] in sel_ids and cmp["worse"] in sel_ids:
                    r["pass_rank"] = sel_ids.index(cmp["better"]) < sel_ids.index(cmp["worse"])
                else:
                    r["pass_rank"] = None
                r["order"] = sel_ids
            row["algos"][name] = r
        # 诊断（陷阱量化）：T2 两份文档的两种口径分
        if task["id"] == "T2":
            diag = {}
            for did in ("doc_case_wuxi", "doc_wuxi_short"):
                d = next(x for x in docs if x["id"] == did)
                whole = n_gram_scores(q, [d], title_key="title", content_key="content").get(did, 0.0)
                per_chunk = chunk_scores(q, d)
                diag[did] = {
                    "whole_doc_score": whole,
                    "best_chunk_hit": max((h for _, h in per_chunk), default=0),
                    "chunk_hits": [h for _, h in per_chunk],
                }
            row["diag"] = diag
        report["tasks"][task["id"]] = row
    return report


def summarize(report: dict, data: dict) -> list[str]:
    lines = []
    names = ["A0_whole_doc", "A1_best_chunk", "A2_chunk_dedup_cover"]
    tot = {n: {"hit": 0, "hit_n": 0, "group": 0, "group_n": 0, "empty": 0, "empty_n": 0,
               "rank": 0, "rank_n": 0} for n in names}
    for tid, row in report["tasks"].items():
        exp = next(t for t in data["tasks"] if t["id"] == tid)["expect"]
        for n in names:
            r = row["algos"][n]
            if exp.get("must_include"):
                tot[n]["hit_n"] += 1
                tot[n]["hit"] += 1 if r["hit"] else 0
            if exp.get("expect_empty"):
                tot[n]["empty_n"] += 1
                tot[n]["empty"] += 1 if r["pass_empty"] else 0
            if exp.get("group_max") is not None:
                tot[n]["group_n"] += 1
                tot[n]["group"] += 1 if r.get("pass_group_max") else 0
            if exp.get("must_rank_above"):
                tot[n]["rank_n"] += 1
                tot[n]["rank"] += 1 if r.get("pass_rank") else 0
    for n in names:
        t = tot[n]
        lines.append(
            f"{n:<22} hit@K {t['hit']}/{t['hit_n']}  "
            f"不重复占组 {t['group']}/{t['group_n']}  "
            f"无资料不凑数 {t['empty']}/{t['empty_n']}  "
            f"排序正确 {t['rank']}/{t['rank_n']}"
        )
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=2)
    ap.add_argument("--lam", type=float, default=0.6)
    ap.add_argument("--min-score", type=int, default=2)
    ap.add_argument("--json", type=str, default="")
    args = ap.parse_args()

    data = load_corpus()
    report = evaluate(data, args.top_k, args.lam, args.min_score)
    print(f"=== 评估集：{len(data['documents'])} 篇资料 / {len(data['tasks'])} 个任务"
          f"（top_k={args.top_k}, lambda={args.lam}, min_score={args.min_score}）===")
    for tid, row in report["tasks"].items():
        print(f"\n[{tid}] {row['question']}  · {row['category']}")
        for n, r in row["algos"].items():
            flags = []
            if r["hit"] is not None:
                flags.append("hit" if r["hit"] else "MISS")
            if "pass_empty" in r:
                flags.append("empty-ok" if r["pass_empty"] else "NOT-EMPTY")
            if "pass_group_max" in r:
                flags.append(f"group={r['max_from_one_group']}" + ("ok" if r["pass_group_max"] else " DUP"))
            if r.get("pass_rank") is not None:
                flags.append("rank-ok" if r["pass_rank"] else "RANK-WRONG")
            sel = ", ".join(f"{s['doc_id']}#{s['chunk_ordinal']}({s['score']})" for s in r["selected"]) or "∅"
            print(f"   {n:<22} {sel}")
            print(f"   {'':<22} {' '.join(flags)}")
        if "diag" in row:
            for did, v in row["diag"].items():
                print(f"   diag {did:<18} 整篇分={v['whole_doc_score']} "
                      f"最好Chunk命中={v['best_chunk_hit']} 各Chunk命中={v['chunk_hits']}")
    print("\n=== 汇总 ===")
    for line in summarize(report, data):
        print(line)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
