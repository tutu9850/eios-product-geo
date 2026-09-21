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
def _containment(a: set[str], b: set[str]) -> float:
    """较小一侧被覆盖的比例（能不能说「一份基本被另一份包含」）。"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def select_a3(docs: list[dict], question: str, top_k: int, lam: float = 0.4,
              min_score: int = 2, contain_thr: float = 0.85) -> list[dict]:
    """A3 = Owner 2026-09-21 指定的流程顺序：

    候选 → 排序 → **同事实/同版本重复识别** → 每簇选代表 → 选其他非重复内容
    → 最低分过滤 → Context Pack（不凑数）。

    关键差异（相对 A2）：
    - 去重判据是**包含度 containment**（较小一侧被覆盖比例），不是 Jaccard 相似度。
      真实语料实测：同一份材料的重复导入/重复切片 containment ≈ 0.98–1.00；
      而「同主题不同回答角色」「不同期间月报」containment ≤ 0.57。相似度分不开这两类。
    - 去重在**候选排序之后、贪心选取之前**完成（不是混在贪心里当惩罚项）。
    - 同一份文档默认**最多占 1 个名额**（避免同一文档的两个块把名额吃光）。
    """
    q = _n_gram_keys(question)
    # 文档级：一份基本被另一份包含 → 视为「重复导入」，只保留更完整的那份
    doc_keys = {d["id"]: _n_gram_keys(str(d.get("content") or "")) for d in docs}
    by_id = {d["id"]: d for d in docs}
    subsumed: set[str] = set()
    for a in docs:
        for b in docs:
            if a["id"] == b["id"] or a["id"] in subsumed:
                continue
            ka, kb = doc_keys[a["id"]], doc_keys[b["id"]]
            if len(ka) < len(kb) and _containment(ka, kb) >= contain_thr:
                subsumed.add(a["id"])  # a 是 b 的子集 → 保留 b（更完整）

    cands: list[dict] = []
    for d in docs:
        if d["id"] in subsumed:
            continue
        tb = title_bonus(question, d)
        for c, hit in chunk_scores(question, d):
            if hit <= 0:
                continue
            cands.append({"doc_id": d["id"], "title": d["title"], "chunk_ordinal": c.get("ordinal"),
                          "chunk_score": hit, "keys": _n_gram_keys(str(c["text"])),
                          "chunk_text": str(c.get("text") or "")[:80], "title_bonus": tb,
                          "text": str(c.get("text") or "")})
    cands.sort(key=lambda c: (-c["chunk_score"], -len(c["text"])))

    # 簇级：同事实/同版本（包含度高）只留代表（分更高；并列则取更完整的那块）
    keep: list[dict] = []
    for c in cands:
        dup_of = None
        for k in keep:
            if _containment(c["keys"], k["keys"]) >= contain_thr:
                dup_of = k
                break
        if dup_of is None:
            keep.append(c)
    reps = sorted(keep, key=lambda c: (-c["chunk_score"], -len(c["text"])))

    chosen: list[dict] = []
    used_docs: set[str] = set()
    for c in reps:
        if len(chosen) >= top_k:
            break
        if c["chunk_score"] < min_score:
            break  # 宪法 §17：低于阈值不凑数
        if c["doc_id"] in used_docs:
            continue  # 同一文档默认只占 1 个名额
        chosen.append(c)
        used_docs.add(c["doc_id"])
    out = []
    for c in chosen:
        out.append({"doc_id": c["doc_id"], "title": c["title"], "chunk_ordinal": c["chunk_ordinal"],
                    "chunk_score": c["chunk_score"], "chunk_text": c["chunk_text"],
                    "score": float(c["chunk_score"] + 2 * c["title_bonus"]),
                    "selection_reason": f"chunk hit {c['chunk_score']} key(s); dedup by containment>={contain_thr}, one slot per document"})
    return out


def _apply_knowledge_ordinal_rule(docs: list[dict], sel: list[dict]) -> list[dict]:
    """裁定 6：Knowledge 侧不提供段号时不虚造 —— ordinal 如实为 null。"""
    kinds = {d["id"]: d.get("source_type") for d in docs}
    for row in sel:
        if kinds.get(row["doc_id"]) == "knowledge_document_chunk":
            row["chunk_ordinal"] = None
            row["selection_reason"] = (row.get("selection_reason") or "") + " · Knowledge 未提供段号（不虚造）"
    return sel


def evaluate(data: dict, top_k: int, lam: float, min_score: int) -> dict:
    docs = data["documents"]
    groups = data.get("duplicate_groups") or {}
    # 去重之后「内容还在不在」要按**重复簇代表**判定，而不是按具体文件名：
    # 例如策略报告去重后代表是完整版，那么「前31页在不在」应等价于「该簇在不在」。
    group_of: dict[str, str] = {}
    for gname, ids in groups.items():
        for i in ids:
            group_of[i] = gname

    def canon(doc_id: str) -> str:
        return f"@{group_of[doc_id]}" if doc_id in group_of else doc_id

    def has(sel_ids: list[str], want: str) -> bool:
        return any(canon(i) == canon(want) for i in sel_ids)
    algos = {
        "A0_whole_doc": lambda q: select_a0(docs, q, top_k),
        "A1_best_chunk": lambda q: select_a1(docs, q, top_k, 1),
        "A2_chunk_dedup_cover": lambda q: select_a2(docs, q, top_k, lam, min_score),
        "A3_containment_dedup": lambda q: select_a3(docs, q, top_k, lam, min_score),
    }
    report: dict = {"top_k": top_k, "lambda": lam, "min_score": min_score, "tasks": {}}
    for task in data["tasks"]:
        q, exp = task["question"], task["expect"]
        row: dict = {"question": q, "category": task["category"], "algos": {}}
        for name, fn in algos.items():
            sel = _apply_knowledge_ordinal_rule(docs, fn(q))
            sel_ids = [s["doc_id"] for s in sel]
            r = {"selected": [{"doc_id": s["doc_id"], "chunk_ordinal": s["chunk_ordinal"],
                               "score": round(s["score"], 2)} for s in sel],
                 "empty": not sel}
            # hit@K
            if exp.get("must_include"):
                r["hit"] = all(has(sel_ids, i) for i in exp["must_include"])
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
            # 不同回答角色必须并存（Owner 2026-09-21：同主题 ≠ 同内容）
            if exp.get("coexist"):
                missing = [i for i in exp["coexist"] if not has(sel_ids, i)]
                r["coexist_missing"] = missing
                r["pass_coexist"] = not missing
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
    names = ["A0_whole_doc", "A1_best_chunk", "A2_chunk_dedup_cover", "A3_containment_dedup"]
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
            if exp.get("coexist"):
                tot[n]["coexist_n"] = tot[n].get("coexist_n", 0) + 1
                tot[n]["coexist"] = tot[n].get("coexist", 0) + (1 if r.get("pass_coexist") else 0)
    for n in names:
        t = tot[n]
        lines.append(
            f"{n:<22} hit@K {t['hit']}/{t['hit_n']}  "
            f"不重复占组 {t['group']}/{t['group_n']}  "
            f"无资料不凑数 {t['empty']}/{t['empty_n']}  "
            f"排序正确 {t['rank']}/{t['rank_n']}  "
            f"不同角色并存 {t.get('coexist', 0)}/{t.get('coexist_n', 0)}"
        )
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=2)
    ap.add_argument("--lam", type=float, default=0.6)
    ap.add_argument("--min-score", type=int, default=2)
    ap.add_argument("--json", type=str, default="")
    ap.add_argument("--set", type=str, default=str(EVAL_SET),
                    help="评估集 JSON（默认构造语料；可指向真实正式资料语料）")
    args = ap.parse_args()

    data = load_corpus(Path(args.set))
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
            if "pass_coexist" in r:
                flags.append("coexist-ok" if r["pass_coexist"] else f"COEXIST-MISS{ r['coexist_missing'] }")
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
