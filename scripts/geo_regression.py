#!/usr/bin/env python3
"""GEO 可复用回归体检脚本（只读为主，可多次跑）

用途：
  - 服务存活 / 超时探测（连接通但迟迟无响应 = 事件循环卡死）
  - 核心只读接口：HTTP 码、envelope.ok、延迟
  - 口径契约：推荐度=提及覆盖、情感字段存在、PATCH 部分更新
  - 可选 --live：真实跑 1 引擎监测（贵且慢，默认关）
  - 可选 --unit：跑 pytest apps/api/tests

用法：
  cd ~/eios-geo
  .venv/bin/python scripts/geo_regression.py              # 默认体检
  .venv/bin/python scripts/geo_regression.py --base http://127.0.0.1:3002
  .venv/bin/python scripts/geo_regression.py --live       # 含 1 次 deepseek check
  .venv/bin/python scripts/geo_regression.py --unit       # + pytest
  .venv/bin/python scripts/geo_regression.py --json out.json

退出码：0=全部 PASS；1=有 FAIL；2=服务不可达/卡死
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "http://127.0.0.1:3002"

# 只读探针：路径 → 最大允许秒数（超过记 WARN/FAIL）
# fact-check / competitor 可能扫全量 history，给更宽预算
READ_PROBES: list[tuple[str, float]] = [
    ("GET", "/health", 3.0),
    # 现在只读部署的模型目录（一次 HTTP）；预算仍给宽，因为统一入口可能正忙
    ("GET", "/api/v1/meta/engines", 25.0),
    ("GET", "/api/v1/monitor/items", 5.0),
    ("GET", "/api/v1/monitor/tasks", 5.0),
    ("GET", "/api/v1/monitor/answers?limit=5", 8.0),
    ("GET", "/api/v1/monitor/overview", 10.0),
    ("GET", "/api/v1/monitor/sentiment", 15.0),
    ("GET", "/api/v1/monitor/public-opinion", 15.0),
    ("GET", "/api/v1/monitor/sources", 10.0),
    ("GET", "/api/v1/monitor/competitor", 20.0),
    ("GET", "/api/v1/monitor/rank-sentiment", 10.0),
    ("GET", "/api/v1/distill/overview", 8.0),
    ("GET", "/api/v1/distill/questions?limit=20", 10.0),
    ("GET", "/api/v1/distill/gaps?limit=20", 8.0),
    ("GET", "/api/v1/distill/plans?limit=20", 10.0),
    ("GET", "/api/v1/distill/cognition-map", 8.0),
    ("GET", "/api/v1/distill/cognition-profile", 10.0),
    ("GET", "/api/v1/knowledge/materials", 8.0),
    # 同 engines：现在读一次部署目录（不再按引擎逐个拉 key）
    ("GET", "/api/v1/stats/overview", 25.0),
    ("GET", "/api/v1/links", 5.0),
    ("GET", "/api/v1/market/watchlist", 5.0),
    # fact-check 会并发打 Kernel，最容易慢/卡
    ("GET", "/api/v1/monitor/fact-check", 45.0),
    # ── Intelligence 分析层（V2：认知总表/策略/缺口；strategies+gap 会逐维度查 Kernel）──
    ("GET", "/api/v1/intelligence/matrix?days=30", 10.0),
    ("GET", "/api/v1/intelligence/overview?days=30&mode=comparison", 10.0),
    ("GET", "/api/v1/intelligence/keywords?days=30", 10.0),
    ("GET", "/api/v1/intelligence/compare?days=30&min_level=mention", 10.0),
    ("GET", "/api/v1/intelligence/reports/latest", 8.0),
    ("GET", "/api/v1/intelligence/strategies?days=30", 30.0),
    ("GET", "/api/v1/intelligence/gap-analysis?days=30", 30.0),
    ("GET", "/api/v1/intelligence/factor-gaps?days=30", 10.0),
]


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL | WARN | SKIP
    detail: str = ""
    ms: float | None = None
    http_code: int | None = None


@dataclass
class Report:
    started_at: str
    base: str
    results: list[CheckResult] = field(default_factory=list)

    def add(self, r: CheckResult) -> None:
        self.results.append(r)
        mark = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "SKIP": "-"}.get(r.status, "?")
        ms = f" {r.ms:.0f}ms" if r.ms is not None else ""
        code = f" HTTP{r.http_code}" if r.http_code is not None else ""
        print(f"  [{mark}] {r.status:4} {r.name}{code}{ms}  {r.detail}".rstrip())

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warned(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")


def _http(
    method: str,
    url: str,
    *,
    timeout: float,
    body: dict | None = None,
) -> tuple[int, Any, float]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            elapsed = (time.perf_counter() - t0) * 1000
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                payload = {"_raw": raw[:200].decode("utf-8", "replace")}
            return resp.status, payload, elapsed
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - t0) * 1000
        try:
            payload = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            payload = {"error": str(e)}
        return e.code, payload, elapsed
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        raise TimeoutError(f"{type(e).__name__}: {e} ({elapsed:.0f}ms)") from e


def check_liveness(report: Report, base: str) -> bool:
    """连接通 + 短超时有响应。卡死时立刻 FAIL 并建议重启。"""
    print("\n== 1) 服务存活 ==")
    try:
        code, payload, ms = _http("GET", f"{base}/health", timeout=3.0)
    except TimeoutError as e:
        report.add(
            CheckResult(
                "liveness",
                "FAIL",
                f"3s 内无响应（端口可能 LISTEN 但事件循环卡死）。{e} → 重启: bash scripts/run_dev.sh",
            )
        )
        return False
    ok = payload.get("ok") if isinstance(payload, dict) else None
    # health 路由可能是裸 dict 或 envelope
    if code == 200:
        report.add(CheckResult("liveness", "PASS", "健康检查可达", ms=ms, http_code=code))
        return True
    report.add(CheckResult("liveness", "FAIL", f"unexpected ok={ok}", ms=ms, http_code=code))
    return False


def check_read_probes(report: Report, base: str) -> None:
    print("\n== 2) 只读接口探针 ==")
    for method, path, budget in READ_PROBES:
        name = f"{method} {path}"
        try:
            code, payload, ms = _http(method, f"{base}{path}", timeout=budget)
        except TimeoutError as e:
            report.add(CheckResult(name, "FAIL", f"超时(>{budget}s) {e}"))
            continue
        if code != 200:
            report.add(CheckResult(name, "FAIL", "非 200", ms=ms, http_code=code))
            continue
        if not isinstance(payload, dict):
            report.add(CheckResult(name, "WARN", "非 JSON object", ms=ms, http_code=code))
            continue
        # /health 可能无 envelope
        if path == "/health":
            report.add(CheckResult(name, "PASS", "ok", ms=ms, http_code=code))
            continue
        if payload.get("ok") is not True:
            report.add(
                CheckResult(
                    name,
                    "FAIL",
                    f"envelope.ok!=true err={payload.get('error')!r}",
                    ms=ms,
                    http_code=code,
                )
            )
            continue
        # 延迟：超过预算 70% 记 WARN；依赖 Builder 的接口 >3s 也 WARN（UI 会觉得卡）
        slow_builder = path in ("/api/v1/meta/engines", "/api/v1/stats/overview") and ms > 3000
        status = "WARN" if (ms > budget * 700 or slow_builder) else "PASS"
        detail = "慢（疑 Builder key 拉取 N+1）" if slow_builder else ("慢" if status == "WARN" else "ok")
        report.add(CheckResult(name, status, detail, ms=ms, http_code=code))


def check_contracts(report: Report, base: str) -> None:
    print("\n== 3) 业务契约 ==")

    # 3a 推荐度口径：value 来自 coverage_pct（提及），UI 若写正面则文档问题——这里验 API 字段存在且可 null
    try:
        code, payload, ms = _http("GET", f"{base}/api/v1/monitor/overview", timeout=15.0)
        data = (payload or {}).get("data") or {}
        rec = data.get("recommend") or {}
        if code == 200 and payload.get("ok"):
            # 契约：recommend.value 可为 null；若有值应 0-100
            v = rec.get("value")
            if v is not None and not (0 <= float(v) <= 100):
                report.add(CheckResult("contract.recommend_range", "FAIL", f"value={v}", ms=ms))
            else:
                # 额外：若有批次但 recommend 与「无任何 recommend 意图」并存——仅提示，不 FAIL
                report.add(
                    CheckResult(
                        "contract.recommend_range",
                        "PASS",
                        f"value={v}（后端=提及覆盖率≠正面推荐；文案勿写正面）",
                        ms=ms,
                    )
                )
        else:
            report.add(CheckResult("contract.recommend_range", "FAIL", "overview 失败", http_code=code))
    except TimeoutError as e:
        report.add(CheckResult("contract.recommend_range", "FAIL", str(e)))

    # 3b 情感：overview 字段齐全；negative 可为 0
    try:
        code, payload, ms = _http("GET", f"{base}/api/v1/monitor/sentiment", timeout=20.0)
        ov = ((payload or {}).get("data") or {}).get("overview") or {}
        need = {"total", "positive", "negative", "neutral", "pos_pct", "neg_pct", "neu_pct"}
        if code == 200 and payload.get("ok") and need.issubset(ov.keys()):
            report.add(
                CheckResult(
                    "contract.sentiment_shape",
                    "PASS",
                    f"total={ov.get('total')} neg={ov.get('negative')}（规则词表，已移除上下文词风险；仍可能误伤）",
                    ms=ms,
                )
            )
        else:
            report.add(CheckResult("contract.sentiment_shape", "FAIL", f"缺字段 ov={list(ov)}", http_code=code))
    except TimeoutError as e:
        report.add(CheckResult("contract.sentiment_shape", "FAIL", str(e)))

    # 3c PATCH 只改 status（历史 P0：曾 422）
    try:
        code, payload, ms = _http("GET", f"{base}/api/v1/monitor/items", timeout=8.0)
        items = ((payload or {}).get("data") or {}).get("items") or []
        active = next((i for i in items if i.get("status") == "active"), None)
        if not active:
            report.add(CheckResult("contract.patch_status", "SKIP", "无 active item 可测"))
        else:
            mid = active["monitor_id"]
            code2, p2, ms2 = _http(
                "PATCH",
                f"{base}/api/v1/monitor/items/{mid}",
                timeout=8.0,
                body={"status": "paused"},
            )
            if code2 == 200 and p2.get("ok") and (p2.get("data") or {}).get("status") == "paused":
                # 还原
                _http(
                    "PATCH",
                    f"{base}/api/v1/monitor/items/{mid}",
                    timeout=8.0,
                    body={"status": "active"},
                )
                report.add(CheckResult("contract.patch_status", "PASS", f"{mid} pause→active", ms=ms2))
            else:
                report.add(
                    CheckResult(
                        "contract.patch_status",
                        "FAIL",
                        f"pause 失败 code={code2} body={str(p2)[:160]}",
                        http_code=code2,
                    )
                )
    except TimeoutError as e:
        report.add(CheckResult("contract.patch_status", "FAIL", str(e)))

    # 3d distill questions envelope
    try:
        code, payload, ms = _http("GET", f"{base}/api/v1/distill/questions?limit=5", timeout=12.0)
        data = (payload or {}).get("data") or {}
        if code == 200 and payload.get("ok") and "items" in data:
            report.add(CheckResult("contract.distill_questions", "PASS", f"total={data.get('total')}", ms=ms))
        else:
            report.add(CheckResult("contract.distill_questions", "FAIL", str(payload)[:120], http_code=code))
    except TimeoutError as e:
        report.add(CheckResult("contract.distill_questions", "FAIL", str(e)))

    # 3e Intelligence 分析层契约（V2：认知总表/策略公式/缺口分离）
    try:
        code, payload, ms = _http("GET", f"{base}/api/v1/intelligence/compare?days=30&min_level=mention", timeout=12.0)
        data = (payload or {}).get("data") or {}
        if code == 200 and payload.get("ok") and len(data.get("matrix") or []) == 7:
            brands = data.get("brands") or []
            has_factors = all("factors" in b for b in brands)
            has_sample = bool(data.get("sample_note"))
            if has_factors and has_sample:
                report.add(
                    CheckResult(
                        "contract.intel_compare",
                        "PASS",
                        f"7 维 × {len(brands)} 主体，brands 带 factors，样本可信度={data.get('sample_note', {}).get('reliability')}",
                        ms=ms,
                    )
                )
            else:
                report.add(CheckResult("contract.intel_compare", "FAIL", f"缺 factors/sample_note brands={len(brands)}", ms=ms))
        else:
            report.add(CheckResult("contract.intel_compare", "FAIL", f"matrix≠7 或失败 {str(payload)[:120]}", http_code=code))
    except TimeoutError as e:
        report.add(CheckResult("contract.intel_compare", "FAIL", str(e)))

    # 3f strategies：Score = 公式五项乘积；每项带素材
    try:
        code, payload, ms = _http("GET", f"{base}/api/v1/intelligence/strategies?days=30", timeout=30.0)
        data = (payload or {}).get("data") or {}
        strs = data.get("strategies") or []
        if code == 200 and payload.get("ok") and "score_formula" in data:
            bad = [
                s["dimension"]
                for s in strs
                if abs(s.get("score", 0) - round(
                    s["formula"]["demand"] * s["formula"]["gap"] * s["formula"]["changeability"]
                    * s["formula"]["evidence"] * s["formula"]["importance"], 1)) > 0.2
            ]
            if not bad:
                report.add(
                    CheckResult("contract.intel_strategies", "PASS", f"{len(strs)} 条策略，Score 公式一致", ms=ms)
                )
            else:
                report.add(CheckResult("contract.intel_strategies", "FAIL", f"Score≠公式乘积: {bad}", ms=ms))
        else:
            report.add(CheckResult("contract.intel_strategies", "FAIL", f"失败 {str(payload)[:120]}", http_code=code))
    except TimeoutError as e:
        report.add(CheckResult("contract.intel_strategies", "FAIL", str(e)))

    # 3g gap-analysis：Knowledge/Evidence 两类分离 + note
    try:
        code, payload, ms = _http("GET", f"{base}/api/v1/intelligence/gap-analysis?days=30", timeout=30.0)
        data = (payload or {}).get("data") or {}
        if (
            code == 200
            and payload.get("ok")
            and isinstance(data.get("knowledge_gaps"), list)
            and isinstance(data.get("evidence_gaps"), list)
            and "note" in data
        ):
            report.add(
                CheckResult(
                    "contract.intel_gaps",
                    "PASS",
                    f"Knowledge={len(data['knowledge_gaps'])} Evidence={len(data['evidence_gaps'])}（两类分离）",
                    ms=ms,
                )
            )
        else:
            report.add(CheckResult("contract.intel_gaps", "FAIL", f"失败 {str(payload)[:120]}", http_code=code))
    except TimeoutError as e:
        report.add(CheckResult("contract.intel_gaps", "FAIL", str(e)))

    # 3h evidence：因子证据链（传播强度 + 来源原话）
    try:
        q = urllib.parse.quote("云边端协同")
        code, payload, ms = _http("GET", f"{base}/api/v1/intelligence/evidence?factor={q}", timeout=12.0)
        data = (payload or {}).get("data") or {}
        if code == 200 and payload.get("ok") and "propagation" in data and isinstance(data.get("sources"), list):
            report.add(
                CheckResult("contract.intel_evidence", "PASS", f"传播强度={data['propagation']} 来源={len(data['sources'])}", ms=ms)
            )
        else:
            report.add(CheckResult("contract.intel_evidence", "FAIL", f"失败 {str(payload)[:120]}", http_code=code))
    except TimeoutError as e:
        report.add(CheckResult("contract.intel_evidence", "FAIL", str(e)))


def check_live(report: Report, base: str) -> None:
    print("\n== 4) LIVE 引擎（可选，可能 15–90s）==")
    try:
        code, payload, ms = _http(
            "POST",
            f"{base}/api/v1/monitor/check",
            timeout=90.0,
            body={
                "question": "企业知识库哪个好？（回归探针，可忽略）",
                "company_name": "云启智能科技有限公司",
                "engines": ["deepseek"],
                "full": False,
            },
        )
        if code == 200 and payload.get("ok"):
            results = (payload.get("data") or {}).get("results") or []
            report.add(
                CheckResult(
                    "live.monitor_check_deepseek",
                    "PASS",
                    f"engines={len(results)}",
                    ms=ms,
                    http_code=code,
                )
            )
        else:
            report.add(
                CheckResult(
                    "live.monitor_check_deepseek",
                    "FAIL",
                    f"{str(payload)[:160]}",
                    ms=ms,
                    http_code=code,
                )
            )
    except TimeoutError as e:
        report.add(CheckResult("live.monitor_check_deepseek", "FAIL", f"超时/失败 {e}"))


def check_unit(report: Report) -> None:
    print("\n== 5) pytest 单元 ==")
    cmd = [sys.executable, "-m", "pytest", "apps/api/tests", "-q", "--tb=line"]
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        out = (p.stdout or "") + (p.stderr or "")
        tail = " | ".join(out.strip().splitlines()[-3:])
        if p.returncode == 0:
            report.add(CheckResult("unit.pytest", "PASS", tail[:200]))
        else:
            report.add(CheckResult("unit.pytest", "FAIL", tail[:300]))
    except subprocess.TimeoutExpired:
        report.add(CheckResult("unit.pytest", "FAIL", "pytest >120s"))
    except Exception as e:
        report.add(CheckResult("unit.pytest", "FAIL", str(e)))


def check_static_timeouts(report: Report) -> None:
    """不连服务：核对引擎超时配置是否过短（代码体检）。"""
    print("\n== 0) 静态：引擎归属与超时 ==\n")
    eng = (ROOT / "adapters" / "engines" / "__init__.py").read_text("utf-8", errors="replace")
    mon = (ROOT / "apps" / "api" / "app" / "api" / "v1" / "monitor.py").read_text("utf-8", errors="replace")
    llm = (ROOT / "adapters" / "llm.py").read_text("utf-8", errors="replace")
    # 引擎并发（审计 P0-5：串行 6×15s=90s/问题）。超时现在归部署的绑定（timeout_seconds），
    # GEO 这边只剩「并发地问」这一件事要保住。
    if "asyncio.gather" in mon:
        report.add(CheckResult("static.engine_concurrency", "PASS", "_run_check 引擎并发（gather）"))
    else:
        report.add(
            CheckResult(
                "static.engine_concurrency",
                "WARN",
                "批量监测未见并发 gather：慢引擎会拖垮整批",
            )
        )
    if "_TIMEOUT = 60.0" in llm or "timeout=60" in llm:
        report.add(CheckResult("static.llm_timeout", "PASS", "LLM timeout≈60s"))
    else:
        report.add(CheckResult("static.llm_timeout", "WARN", "请确认 adapters/llm.py 超时"))
    # Owner 2026-09-21：「GEO 不保留 Builder / .env / 自己的模型 Key」「GEO 不再写死 6 个」。
    # 引擎面只剩「读部署目录 + 调统一入口」；端点/凭据/模型名一个都不该在这里。
    # 只看**代码**：注释里点名这些词正是要说明「它们不该在这」（例如模块 docstring 列出
    # 已经搬去部署的那几样），拿注释判 FAIL 就成了自己咬自己。
    import ast as _ast

    _doc = _ast.get_docstring(_ast.parse(eng)) or ""
    _code = "\n".join(line for line in eng.replace(_doc, "").splitlines() if not line.lstrip().startswith("#"))
    leaked = [token for token in ("base_url", "api_key", "env_key", "BUILDER_GEO", "ENGINES =") if token in _code]
    if leaked:
        report.add(
            CheckResult(
                "static.engine_ownership",
                "FAIL",
                "adapters/engines 又出现了部署侧的东西：" + ", ".join(leaked),
            )
        )
    else:
        report.add(
            CheckResult(
                "static.engine_ownership",
                "PASS",
                "engines 适配器只读部署目录 + 调统一入口（无端点/凭据/硬编码引擎表）",
            )
        )
    # 引擎名是部署目录说了算：GEO 里不许再出现「6」这种写死的引擎数
    if "list_engines" not in eng:
        report.add(CheckResult("static.engines_from_catalog", "FAIL", "engines 未从部署目录取清单"))
    else:
        report.add(CheckResult("static.engines_from_catalog", "PASS", "引擎清单来自部署模型目录"))
    # 情感词表（审计 P0-2）：“风险” 是上下文词，命中免责声明 → 误判负面
    # 用正则提取 _NEGATIVE_WORDS 元组体（避免撞注释里的 "风险" 字样）
    neg_block = re.search(r"_NEGATIVE_WORDS = \((.*?)\)", mon, re.S)
    neg_body = neg_block.group(1) if neg_block else ""
    if neg_block and '"风险"' in neg_body:
        report.add(
            CheckResult(
                "static.sentiment_wordlist",
                "WARN",
                "负面词表仍含上下文词「风险」（风险提示/规避风险会误判负面）",
            )
        )
    elif neg_block and "不值得" in neg_body:
        report.add(CheckResult("static.sentiment_wordlist", "PASS", "负面词表已移除「风险」且补否定词（不值得/不放心等）"))
    else:
        report.add(CheckResult("static.sentiment_wordlist", "PASS", "未发现词表异常"))
    # 口径污染：前端文案写「正面提及」但后端 recommend=提及覆盖
    overview_fe = Path.home() / "eios-chat/src/components/GeoOverview.tsx"
    if overview_fe.is_file():
        txt = overview_fe.read_text("utf-8", errors="replace")
        if "正面提及" in txt:
            report.add(
                CheckResult(
                    "static.fe_recommend_copy",
                    "WARN",
                    "GeoOverview 文案「正面提及」与 API recommend=提及覆盖率不一致",
                )
            )
        elif "提及≠推荐" in txt:
            report.add(CheckResult("static.fe_recommend_copy", "PASS", "文案已诚实化（提及≠推荐）"))
        else:
            report.add(CheckResult("static.fe_recommend_copy", "PASS", "未发现正面提及误文案"))


def main() -> int:
    ap = argparse.ArgumentParser(description="GEO 回归体检")
    ap.add_argument("--base", default=DEFAULT_BASE, help="GEO base URL")
    ap.add_argument("--live", action="store_true", help="跑真实 deepseek check")
    ap.add_argument("--unit", action="store_true", help="跑 pytest")
    ap.add_argument("--skip-fact-check", action="store_true", help="跳过最慢的 fact-check")
    ap.add_argument("--json", dest="json_out", default="", help="写入 JSON 报告路径")
    args = ap.parse_args()

    global READ_PROBES
    if args.skip_fact_check:
        READ_PROBES = [p for p in READ_PROBES if "fact-check" not in p[1]]

    report = Report(started_at=datetime.now(timezone.utc).isoformat(), base=args.base)
    print(f"GEO Regression @ {report.started_at}")
    print(f"base={args.base}")

    check_static_timeouts(report)
    alive = check_liveness(report, args.base)
    if not alive:
        print("\n*** 服务不可达或卡死：后续 HTTP 探针跳过 ***")
        print("修复：杀掉卡住的 uvicorn 后执行  bash scripts/run_dev.sh")
        _finish(report, args.json_out)
        return 2

    check_read_probes(report, args.base)
    check_contracts(report, args.base)
    if args.live:
        check_live(report, args.base)
    else:
        report.add(CheckResult("live.monitor_check_deepseek", "SKIP", "未传 --live"))
    if args.unit:
        check_unit(report)
    else:
        report.add(CheckResult("unit.pytest", "SKIP", "未传 --unit"))

    return _finish(report, args.json_out)


def _finish(report: Report, json_out: str) -> int:
    print("\n== 汇总 ==")
    n = len(report.results)
    print(f"total={n}  PASS={sum(1 for r in report.results if r.status=='PASS')}  "
          f"FAIL={report.failed}  WARN={report.warned}  "
          f"SKIP={sum(1 for r in report.results if r.status=='SKIP')}")
    if json_out:
        Path(json_out).write_text(
            json.dumps(
                {
                    "started_at": report.started_at,
                    "base": report.base,
                    "failed": report.failed,
                    "warned": report.warned,
                    "results": [asdict(r) for r in report.results],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"json → {json_out}")
    if report.failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS" + (" (with warnings)" if report.warned else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
