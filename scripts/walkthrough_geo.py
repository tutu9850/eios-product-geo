"""GEO 系统用户视角走查脚本：逐板块调用，记录结果与流程问题。
只读端点为主；写端点用最小参数。"""
import json
import sys
import httpx

BASE = "http://127.0.0.1:3002/api/v1"
TENANT = "tenant_corp_01"
results = []

def call(name, method, path, **kw):
    url = f"{BASE}{path}"
    try:
        r = httpx.request(method, url, timeout=30, **kw)
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text[:200]}
        ok = body.get("ok", "?")
        err = body.get("error")
        data = body.get("data")
        # 摘要数据（避免超长）
        if isinstance(data, dict):
            summary = {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in list(data.items())[:6]}
        elif isinstance(data, list):
            summary = f"list[{len(data)}]"
        else:
            summary = data
        results.append({
            "板块": name, "状态码": r.status_code, "ok": ok,
            "数据概要": summary, "错误": (err.get("message") if isinstance(err, dict) else err) if err else None,
        })
    except Exception as e:
        results.append({"板块": name, "状态码": "ERR", "ok": "?", "数据概要": None, "错误": str(e)[:120]})

# ── 1. 工作台 ──
call("工作台-统计总览", "GET", "/stats/overview")
call("工作台-引擎状态", "GET", "/meta/engines")
call("工作台-健康", "GET", "/health")

# ── 2. 蒸馏（问题池/缺口/计划/认知地图）──
call("蒸馏-总览", "GET", "/distill/overview")
call("蒸馏-问题列表", "GET", "/distill/questions?limit=5")
call("蒸馏-缺口列表", "GET", "/distill/gaps?limit=5")
call("蒸馏-计划列表", "GET", "/distill/plans?limit=5")
call("蒸馏-计划weak排序", "GET", "/distill/plans?sort=weak&limit=5")
call("蒸馏-计划effect排序", "GET", "/distill/plans?sort=effect&limit=5")
call("蒸馏-认知地图", "GET", "/distill/cognition-map")

# ── 3. 内容资产 ──
call("内容资产-素材列表", "GET", "/knowledge/materials?limit=5")

# ── 4. 监测 ──
call("监测-对象列表", "GET", "/monitor/items")
call("监测-历史", "GET", "/monitor/history?limit=5")
call("监测-引用追踪", "GET", "/monitor/citations?limit=5")
call("监测-导出报告", "GET", "/monitor/export")
call("监测-来源", "GET", "/monitor/sources")
call("监测-答案", "GET", "/monitor/answers?limit=3")

# ── 5. 认知分析（intelligence）──
call("认知-总览", "GET", "/intelligence/overview")
call("认知-关键词", "GET", "/intelligence/keywords")
call("认知-humanize", "GET", "/intelligence/humanize")
call("认知-策略", "GET", "/intelligence/strategies")
call("认知-缺口分析", "GET", "/intelligence/gap-analysis")
call("认知-因子缺口", "GET", "/intelligence/factor-gaps")
call("认知-对比", "GET", "/intelligence/compare")
call("认知-矩阵", "GET", "/intelligence/matrix")
call("认知-感知", "GET", "/intelligence/perception")
call("认知-报告最新", "GET", "/intelligence/reports/latest")

# ── 6. 市场感知 ──
call("市场-关注列表", "GET", "/market/watchlist")
call("市场-信号列表", "GET", "/market/signals?limit=5")

# ── 7. 链接 ──
call("链接-列表", "GET", "/links")

# ── 8. 对战/诊断 ──
call("对战-引擎列表", "GET", "/battle/engines")

# 输出结果表
print(f"{'板块':<28}{'状态':<6}{'ok':<5}{'错误/概要'}")
print("-" * 100)
for r in results:
    err_s = r["错误"] or ""
    data_s = json.dumps(r["数据概要"], ensure_ascii=False) if r["数据概要"] is not None else ""
    line = f"{r['板块']:<28}{str(r['状态码']):<6}{str(r['ok']):<5}{err_s[:40]}{data_s[:60]}"
    print(line)
