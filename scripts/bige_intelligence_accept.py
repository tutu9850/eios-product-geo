#!/usr/bin/env python3
"""笔革 §十 验收种子 + 触发解析/报告（统一分析引擎收口）

用法（在 eios-geo 仓库根，GEO :3002 已起）:
  python scripts/bige_intelligence_accept.py          # 灌种子 + 入队
  python scripts/bige_intelligence_accept.py --report # 再触发报告
  python scripts/bige_intelligence_accept.py --check  # 只查状态

种子为「模拟 AI 回答」原文（source_type=ai_answer），不写 Kernel。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "http://127.0.0.1:3002"
COMPANY = "笔革"

# 可验收：竞品因「意式高定/设计师渠道」被荐；笔革信息少或弱
SEED = [
    {
        "id": "ans_bige_accept_001_deepseek",
        "parent_ref": "ans_bige_accept_001_deepseek",
        "source_type": "ai_answer",
        "platform": "deepseek",
        "subject_company": COMPANY,
        "raw_text": (
            "问：成都想做意式极简真皮沙发高定，有什么品牌推荐？\n"
            "答：很多人会先提到「顾家家居」「左右沙发」这类全国连锁，以及红星美凯龙里的进口意式品牌组合。"
            "它们常被推荐的原因是：展厅多、设计师渠道成熟、意式极简案例多。"
            "至于「笔革家居」，公开可检索的高定案例与医疗级/医院渠道叙事都很少，"
            "目前相关公开信息较少，所以在 AI 搜索回答里往往排不上推荐位。"
        ),
        "context_json": {
            "question": "成都意式极简真皮沙发高定推荐",
            "engine": "deepseek",
            "history_id": "bige_accept",
            "query_id": "q001",
            "competitors": ["顾家家居", "左右沙发"],
        },
    },
    {
        "id": "ans_bige_accept_002_deepseek",
        "parent_ref": "ans_bige_accept_002_deepseek",
        "source_type": "ai_answer",
        "platform": "deepseek",
        "subject_company": COMPANY,
        "raw_text": (
            "对比高定软体时，决策因素通常是：颜值与搭配、设计师口碑、交期与售后。"
            "竞品「顾家」因全案案例多、抖音投放声量大被频繁提及；"
            "「笔革」若强调全品类非标定制、不做全屋定制套餐、统一折扣与框架终身质保，"
            "但这些卖点在外部 AI 回答里几乎未被引用，存在「能力有、外界不知道」的认知缺口。"
        ),
        "context_json": {
            "question": "高定软体家具怎么选",
            "engine": "deepseek",
            "history_id": "bige_accept",
            "query_id": "q002",
            "competitors": ["顾家家居"],
        },
    },
    {
        "id": "ans_bige_accept_003_deepseek",
        "parent_ref": "ans_bige_accept_003_deepseek",
        "source_type": "ai_answer",
        "platform": "deepseek",
        "subject_company": COMPANY,
        "raw_text": (
            "有用户问笔革家居靠谱吗。回答里能确认的公开信息有限："
            "成都展厅约一万平、预约制接待、主推琥珀沙发等，"
            "但缺少成体系的官网与大众点评高分评价沉淀，信任信号弱于头部连锁。"
            "建议优先补：品牌资质与案例页、设计师渠道内容、售后保养手册对外可见版本。"
        ),
        "context_json": {
            "question": "笔革家居靠谱吗",
            "engine": "deepseek",
            "history_id": "bige_accept",
            "query_id": "q003",
            "competitors": [],
        },
    },
]


def _req(method: str, path: str, body: dict | None = None) -> dict:
    url = BASE + path
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "error": raw, "status": e.code}


def seed_via_repo() -> list[str]:
    """直接写库（脚本在 GEO 进程外时走 HTTP analyze 不便写原文）——优先 HTTP 若有 ingest。"""
    # 用 analyze + 先通过内部 Python 路径：脚本应在 apps/api 环境下跑；否则退化为仅 enqueue 已有
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "apps" / "api"))
    from services.intelligence import queue, repo  # type: ignore

    ids = []
    now = datetime.now(timezone.utc)
    for s in SEED:
        ev = {
            **s,
            "observed_at": now,
            "tenant_id": "tenant_corp_01",
            "url": None,
        }
        row, created = repo.upsert_evidence(ev)
        eid = row["id"]
        ids.append(eid)
        queue.enqueue(eid)
        print(f"  evidence {eid} created={created}")
    return ids


def seed_http_fallback() -> list[str]:
    """无本地 repo 时：只触发 recover + 报告（依赖已有数据）。"""
    print("WARN: 无法写库，改为 POST /recover + 查现有矩阵")
    _req("POST", "/api/v1/intelligence/recover")
    return [s["id"] for s in SEED]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--wait", type=int, default=180, help="等待解析秒数")
    args = ap.parse_args()

    health = _req("GET", "/healthz")
    if not health.get("ok") and "status" not in str(health):
        # geo health may be 404 on /healthz — try meta
        pass
    print("GEO base", BASE)

    if args.check:
        q = urllib.parse.quote(COMPANY)
        matrix = _req("GET", f"/api/v1/intelligence/matrix?company={q}&days=90")
        report = _req("GET", f"/api/v1/intelligence/reports/latest?company={q}")
        print(json.dumps({"matrix": matrix.get("data"), "report": (report.get("data") or {}).get("report")}, ensure_ascii=False, indent=2)[:4000])
        return 0

    try:
        ids = seed_via_repo()
    except Exception as e:
        print("seed_via_repo failed:", e)
        ids = seed_http_fallback()

    # 确保服务侧也入队（跨进程时本地 enqueue 无效）
    r = _req("POST", "/api/v1/intelligence/analyze", {"evidence_ids": ids})
    print("analyze", r.get("data") or r)

    deadline = time.time() + args.wait
    while time.time() < deadline:
        ok_n = 0
        for eid in ids:
            a = _req("GET", f"/api/v1/intelligence/analyses?evidence_id={urllib.parse.quote(eid)}")
            st = (a.get("data") or {}).get("status")
            if st == "succeeded":
                ok_n += 1
        print(f"  parsed {ok_n}/{len(ids)}")
        if ok_n >= len(ids):
            break
        time.sleep(5)

    if args.report or True:
        # company/days 是 query（不是 JSON body）
        qco = urllib.parse.urlencode({"company": COMPANY, "days": "90"})
        rr = _req("POST", f"/api/v1/intelligence/reports/run?{qco}")
        print("report/run", rr.get("data") or rr.get("error") or rr)
        # 限流时仍可读最新
        time.sleep(1)

    q = urllib.parse.quote(COMPANY)
    matrix = _req("GET", f"/api/v1/intelligence/matrix?company={q}&days=90")
    report = _req("GET", f"/api/v1/intelligence/reports/latest?company={q}")
    # 若按公司名为空，回退全局最新（兼容历史 company_name=unknown）
    data_r = (report.get("data") or {}).get("report")
    if not data_r:
        report = _req("GET", "/api/v1/intelligence/reports/latest")
        data_r = (report.get("data") or {}).get("report")
    data_m = matrix.get("data") or {}
    actions = (data_r or {}).get("actions") if isinstance(data_r, dict) else None
    # 条级：至少一条 succeeded 且带 evidence_quote
    quote_ok = False
    for eid in ids:
        a = _req("GET", f"/api/v1/intelligence/analyses?evidence_id={urllib.parse.quote(eid)}")
        ad = a.get("data") or {}
        if ad.get("status") != "succeeded":
            continue
        analysis = ad.get("analysis") or {}
        sb = analysis.get("self_brand") or {}
        brands = analysis.get("brands") or []
        if sb.get("evidence_quote") or any((b.get("reasons") or [{}])[0].get("evidence_quote") for b in brands if b.get("reasons")):
            quote_ok = True
            break
    print("--- acceptance snapshot ---")
    print("evidence_count", data_m.get("evidence_count"))
    print("missing_sample", (data_m.get("missing") or [])[:2])
    print("report_actions", len(actions or []) if actions is not None else None)
    print("quote_ok", quote_ok)
    passed = int(data_m.get("evidence_count") or 0) >= 1 and quote_ok
    print("PASS_FIELD_GATE" if passed else "FAIL_FIELD_GATE")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
