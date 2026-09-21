"""GEO 报告 PDF 渲染 V3（2026-08-15）：report_json + 监测历史 → HTML → PDF（weasyprint）

版式套用桌面《GEO监测报告模板_V3.html》（5 页 10 章节）：
  01 AI认知健康 / 02 AI眼中的企业 / 03 客户问题地图 / 04 AI推荐表现 /
  05 竞争格局 / 06 信息来源贡献度 / 07 知识缺口 / 08 内容建设 / 09 行动计划 / 10 下一周期
诚实红线：无数据章节显示「待数据积累」，不编造；AI 推断标注「AI 建议 · 待验证」。
"""
from __future__ import annotations

import html as _html
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_CSS = """
  :root { --accent:#2f6fed; --good:#1f9d55; --warn:#d97706; --bad:#dc2626; --ink:#111; --sub:#6b7280; --line:#e5e7eb; }
  * { margin:0; padding:0; box-sizing:border-box; }
  @page { size: A4; margin: 0; }
  @media print { .page { margin: 0 auto; box-shadow: none; } }
  body { font-family:"Noto Sans CJK SC","PingFang SC","Microsoft YaHei",sans-serif; background:#f3f4f6; color:var(--ink); }
  .page { width:794px; min-height:1123px; margin:24px auto; background:#fff; padding:44px 50px; box-shadow:0 2px 12px rgba(0,0,0,.08); page-break-after:always; }
  .kicker { font-size:11px; letter-spacing:2px; color:var(--sub); text-transform:uppercase; margin-bottom:6px; }
  h1 { font-size:26px; font-weight:700; }
  h2 { font-size:16px; font-weight:700; margin:26px 0 12px; padding-left:10px; border-left:4px solid var(--accent); }
  .meta { display:flex; gap:24px; margin-top:14px; font-size:12px; color:var(--sub); flex-wrap:wrap; }
  .meta b { color:var(--ink); font-weight:600; }
  .gauge { display:flex; align-items:center; gap:32px; margin:22px 0; }
  .score { width:150px; height:150px; border-radius:50%; position:relative;
    background:conic-gradient(var(--accent) 0 72%, #eef1f5 72% 100%); display:flex; flex-direction:column; align-items:center; justify-content:center; }
  .score::after { content:""; position:absolute; inset:16px; background:#fff; border-radius:50%; }
  .score b { position:relative; z-index:1; font-size:30px; }
  .score span { position:relative; z-index:1; font-size:10px; color:var(--sub); margin-top:2px; }
  .gauge .note { font-size:12px; color:var(--sub); line-height:1.9; max-width:400px; }
  .gauge .note b { color:var(--ink); }
  table { width:100%; border-collapse:collapse; margin-top:10px; font-size:12px; }
  th { background:#f8fafc; text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); font-weight:600; }
  td { padding:8px 10px; border-bottom:1px solid var(--line); color:#374151; vertical-align:top; }
  .tag { display:inline-block; padding:1px 8px; border-radius:20px; font-size:11px; font-weight:500; }
  .tag.b { background:#eef2ff; color:var(--accent); } .tag.g { background:#ecfdf5; color:var(--good); }
  .tag.o { background:#fef3c7; color:var(--warn); } .tag.r { background:#fee2e2; color:var(--bad); }
  .card { border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .card h3 { font-size:13px; font-weight:600; margin-bottom:8px; }
  .card li { font-size:12px; color:var(--sub); line-height:1.8; margin-left:16px; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:12px; }
  .bar { display:flex; align-items:center; gap:10px; margin:7px 0; font-size:12px; }
  .bar .name { width:120px; color:var(--ink); font-weight:500; }
  .bar .track { flex:1; height:10px; background:#f0f2f5; border-radius:5px; overflow:hidden; }
  .bar .fill { height:100%; border-radius:5px; background:var(--accent); }
  .bar .val { width:52px; text-align:right; color:var(--sub); }
  .flow { display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:11.5px; color:var(--sub); margin:8px 0; }
  .flow .step { border:1px solid var(--line); border-radius:8px; padding:5px 10px; background:#fafbfc; }
  .flow .arrow { color:#c0c8d4; }
  .p0 { border-left:3px solid var(--bad); } .p1 { border-left:3px solid var(--warn); } .p2 { border-left:3px solid var(--accent); }
  .src { font-size:10px; color:#9ca3af; font-style:normal; }
  .pie { width:130px; height:130px; border-radius:50%; position:relative; margin:0 auto;
    background:conic-gradient(var(--accent) 0 35%, #d97706 35% 57%, #1f9d55 57% 79%, #9ca3af 79% 89%, #e5e7eb 89% 100%); }
  .pie::after { content:""; position:absolute; inset:26px; background:#fff; border-radius:50%; }
  .legend { font-size:11px; color:var(--sub); line-height:1.9; }
  .legend b { color:var(--ink); }
  .foot { margin-top:34px; padding-top:12px; border-top:1px solid var(--line); font-size:10px; color:#9ca3af; display:flex; justify-content:space-between; }
  .ai-note { background:#fff8e6; border:1px solid #f0d080; padding:8px 10px; border-radius:4px; font-size:11px; margin:10px 0; }
  .empty { border:2px dashed #cbd5e1; border-radius:10px; padding:16px; text-align:center; color:var(--sub); font-size:12px; background:#fafbfc; }
"""


def _esc(v: Any) -> str:
    return _html.escape(str(v if v is not None else ""))


def _fmt_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        return str(iso)[:10]
    except Exception:
        return str(iso)[:10]


# ────────────────────────────────────────────────────────────────────────────
# 数据推导（V3 章节需要、report_json 没有的）
# ────────────────────────────────────────────────────────────────────────────

def _rec_position_distribution(history: List[dict]) -> Dict[str, int]:
    """推荐位置分布：从监测历史 engine_detail.rank_est/mentioned 推导。
    位置语义：rank=1 第一推荐 / mentioned 且 rank 2-3 强推荐 / mentioned 普通 /
    对比出现（subjects 含我方但非推荐）→ 简化六类：第一/强/普通/顺带/对比/排除。
    """
    dist = {"第一推荐": 0, "强推荐": 0, "普通推荐": 0, "顺带提及": 0, "对比中出现": 0, "被明确排除": 0}
    total = 0
    for h in history:
        for q in h.get("questions") or []:
            for er in q.get("engine_detail") or []:
                mentioned = er.get("mentioned")
                rank = er.get("rank_est")
                if mentioned is None:
                    continue
                total += 1
                if mentioned is False:
                    dist["被明确排除"] += 1
                elif rank == 1:
                    dist["第一推荐"] += 1
                elif rank in (2, 3):
                    dist["强推荐"] += 1
                elif mentioned is True:
                    dist["普通推荐"] += 1
                else:
                    dist["顺带提及"] += 1
    if total == 0:
        return {}, 0
    return dist, total


def _trend_points(history: List[dict], window: int = 6) -> List[dict]:
    """推荐率趋势：按历史记录时间序列，取最近 N 个时间点的我方推荐率。"""
    pts = []
    for h in sorted(history, key=lambda x: str(x.get("created_at") or "")):
        sm = h.get("summary") or {}
        qs = h.get("questions") or []
        total = 0
        mentioned = 0
        for q in qs:
            for er in q.get("engine_detail") or []:
                m = er.get("mentioned")
                if m is not None:
                    total += 1
                    if m:
                        mentioned += 1
        # 兼容旧 summary 结构
        if total == 0 and sm.get("mentioned") is not None:
            mentioned = sm.get("mentioned", 0)
            total = mentioned + sm.get("not_mentioned", 0)
        if total > 0:
            pts.append({
                "date": _fmt_date(h.get("created_at")),
                "rate": round(mentioned / total * 100),
            })
    return pts[-window:]


def _question_stage_map(questions: List[dict]) -> Dict[str, dict]:
    """客户问题地图：按 intent/customer_stage 分组统计问题数与覆盖（AI 回答含企业依据比例）。"""
    stages = ["认知", "搜索", "比较", "选择", "决策", "信任"]
    out = {s: {"count": 0, "covered": 0, "judged": 0, "coverage_pct": None} for s in stages}
    # intent → V3 六阶段映射（覆盖现有问题池的 intent 取值）
    _STAGE_MAP = {
        "认知": "认知", "awareness": "认知", "认知了解": "认知", "了解": "认知",
        "搜索": "搜索", "检索": "搜索", "信息收集": "搜索",
        "比较": "比较", "对比": "比较", "评估": "比较",
        "选择": "选择", "候选": "选择",
        "决策": "决策", "采购": "决策", "购买": "决策", "下单": "决策", "使用": "决策", "成交": "决策",
        "信任": "信任", "验证": "信任", "售后": "信任", "口碑": "信任",
    }
    for q in questions:
        intent = q.get("intent") or q.get("customer_stage") or "认知"
        key = _STAGE_MAP.get(intent, "认知" if "认知" in intent else intent)
        bucket = out.get(key)
        if bucket is None:
            continue
        bucket["count"] += 1
        level = q.get("evidence_level")
        if level in ("grounded", "partial", "none"):
            bucket["judged"] += 1
        if level == "grounded":
            bucket["covered"] += 1
    for s in stages:
        # 审计 B1：只按「已做过知识判定」的问题算覆盖；一个都没判定 → None（未判定），
        # 不再把「没写过的字段」渲染成 0%。
        judged = out[s].get("judged") or 0
        out[s]["coverage_pct"] = round(out[s]["covered"] / judged * 100) if judged else None
    return out


# ────────────────────────────────────────────────────────────────────────────
# HTML 渲染
# ────────────────────────────────────────────────────────────────────────────

def render_report_html(
    report: Dict[str, Any],
    created_at: Optional[str] = None,
    history: Optional[List[dict]] = None,
    questions: Optional[List[dict]] = None,
    brand_stats: Optional[List[dict]] = None,
    trend: Optional[Dict[str, Any]] = None,
) -> str:
    company = report.get("company") or "企业"
    days = report.get("period_days") or 30
    gen_time = _fmt_date(created_at) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = history or []
    questions = questions or []

    # ── 01 AI 认知健康（评分 + 维度表）──
    perception = report.get("perception") or {}
    tags = perception.get("tags") or []
    # 健康分：用 brand_overview.total_evidence 与缺口数量推导（0-100，规则估算，诚实标注）
    bo = report.get("brand_overview") or {}
    total_ev = bo.get("total_evidence") or 0
    kg_count = len(report.get("knowledge_gaps") or [])
    miss_count = len(report.get("missing") or [])
    health = max(0, min(100, 40 + total_ev * 3 - kg_count * 6 - miss_count * 4))
    health_pct = health
    score_css = f"background:conic-gradient(var(--accent) 0 {health_pct}%, #eef1f5 {health_pct}% 100%)"
    dim_rows = ""
    # 认知维度表：从 perception tags + gap_matrix 推导（每行：维度/得分/依据/解读）
    dims = []
    for t in tags:
        dims.append({"dim": t.get("tag"), "score": round((t.get("share") or 0) * 100), "src": "AI 回答标签占比", "note": "AI 回答中该认知标签的占比"})
    for g in (report.get("gap_matrix") or [])[:4]:
        d = g.get("dimension") or g.get("factor") or ""
        if d:
            dims.append({"dim": d, "score": 50, "src": "缺口矩阵", "note": f"竞品：{g.get('competitor') or '—'} / 我方：{g.get('us') or '—'}"})
    if dims:
        dim_rows = "".join(
            f"<tr><td>{_esc(x['dim'])}</td><td><b>{x['score']}</b></td><td class='src'>{_esc(x['src'])}</td><td>{_esc(x['note'])}</td></tr>"
            for x in dims[:10]
        )
    else:
        dim_rows = "<tr><td colspan='4'>暂无维度数据（证据不足）</td></tr>"

    # ── 02 AI 眼中的企业 ──
    # 品牌对比表：优先 report.brand_overview.brands，否则用 brand_stats（brand_mention 聚合）
    _brands = ((report.get("brand_overview") or {}).get("brands")) or brand_stats or []
    brand_table = ""
    if _brands:
        brand_rows = ""
        for b in _brands:
            brand_rows += (
                f"<tr><td>{_esc(b.get('brand') or b.get('name'))}</td>"
                f"<td class='num'>{b.get('mention_count', b.get('mentions', '—'))}</td>"
                f"<td class='num'>{b.get('exposure_rate', '—')}</td>"
                f"<td class='num'>{b.get('recommendation_rate', '—')}</td></tr>"
            )
        brand_table = (
            "<h3>🏆 品牌提及对比</h3>"
            "<table><thead><tr><th>品牌</th><th>提及</th><th>曝光率</th><th>推荐率</th></tr></thead>"
            f"<tbody>{brand_rows}</tbody></table>"
        )
    ext_perceives = (report.get("capability_gap") or {}).get("external_perceives") or []
    ai_side = "".join(f"<li><b>外部感知</b>：{_esc(x)}</li>" for x in ext_perceives[:5]) or "<li>暂无记录</li>"
    tags_side = "".join(f"<li><b>{_esc(t.get('tag'))}</b>：占比 {(t.get('share') or 0)*100:.0f}%</li>" for t in tags[:5]) or "<li>暂无记录</li>"
    bias_items = ""
    for g in (report.get("gap_matrix") or [])[:6]:
        d = g.get("dimension") or g.get("factor") or ""
        comp = g.get("competitor") or "—"
        us = g.get("us") or "—"
        if comp and us and comp != us:
            bias_items += f"<li><span class='tag o'>偏差</span> 维度「{_esc(d)}」：竞品 {_esc(comp)} vs 我方 {_esc(us)}</li>"
    if not bias_items:
        bias_items = "<li><span class='tag g'>一致</span> 暂无显著认知偏差（数据不足）</li>"

    # ── 03 客户问题地图 ──
    stage_map = _question_stage_map(questions)
    flow = "".join(f"<span class='step'>{s}</span><span class='arrow'>→</span>" for s in ["认知", "搜索", "比较", "选择", "决策", "信任"])
    flow = flow.rstrip("<span class='arrow'>→</span>")
    qm_rows = ""
    for s in ["认知", "搜索", "比较", "选择", "决策", "信任"]:
        v = stage_map.get(s) or {}
        cov = f"{v['coverage_pct']}%" if v.get("coverage_pct") is not None else "—"
        qm_rows += f"<tr><td>{s}</td><td>{v.get('count', 0)}</td><td>{cov}</td><td>{'高' if (v.get('coverage_pct') or 0) >= 60 else '中' if (v.get('coverage_pct') or 0) >= 30 else '低' if v.get('coverage_pct') is not None else '—'}</td></tr>"
    if not any(v.get("count") for v in stage_map.values()):
        qm_rows = "<tr><td colspan='4'>暂无问题池数据</td></tr>"

    # ── 04 AI 推荐表现 ──
    dist, dist_total = _rec_position_distribution(history)
    bar_rows = ""
    if dist:
        bar_colors = {"第一推荐": "var(--good)", "强推荐": "var(--accent)", "普通推荐": "var(--accent)", "顺带提及": "#9ca3af", "对比中出现": "#d97706", "被明确排除": "var(--bad)"}
        for k, v in dist.items():
            pct = round(v / dist_total * 100) if dist_total else 0
            bar_rows += f"<div class='bar'><span class='name'>{k}</span><div class='track'><div class='fill' style='width:{pct}%;background:{bar_colors.get(k, 'var(--accent)')}'></div></div><span class='val'>{pct}%</span></div>"
    else:
        bar_rows = "<p class='empty'>暂无推荐位置数据（待监测积累）</p>"
    # 推荐理由
    why_reasons = ""
    for w in (report.get("why_competitors_win") or [])[:3]:
        why_reasons += f"<li><b>{_esc(w.get('competitor') or '竞品')}</b>：{_esc(w.get('reason') or w.get('summary'))}</li>"
    reason_html = "".join(
        f"<li><b>{_esc(t.get('tag'))}</b>：{(t.get('share') or 0)*100:.0f}%</li>" for t in tags[:4]
    ) or "<li>暂无记录</li>"
    # 趋势 SVG
    # 推荐变化（trend_delta 传入）
    trend_delta_html = ""
    if trend:
        td_items = []
        for b in trend.get("gained") or []:
            td_items.append(f"<li><span class='tag g'>新增推荐</span> {_esc(b)}（上周期未出现）</li>")
        for b in trend.get("lost") or []:
            td_items.append(f"<li><span class='tag r'>掉出推荐</span> {_esc(b)}（上周期有、本周期消失）</li>")
        for b in (trend.get("rising") or [])[:3]:
            td_items.append(f"<li><span class='tag b'>上升</span> {_esc(b.get('brand'))}：{b.get('from')} → {b.get('to')} 次</li>")
        for b in (trend.get("falling") or [])[:3]:
            td_items.append(f"<li><span class='tag o'>下降</span> {_esc(b.get('brand'))}：{b.get('from')} → {b.get('to')} 次</li>")
        if td_items:
            trend_delta_html = f"<div class='card'><ul>{''.join(td_items)}</ul><p class='src'>{_esc(trend.get('note') or '')}</p></div>"
        else:
            trend_delta_html = "<p class='muted'>不足两个周期，趋势变化待数据积累（每 7 天一个周期）</p>"
    else:
        trend_delta_html = "<p class='muted'>暂无变化数据（待多周期积累）</p>"

    pts = _trend_points(history)
    trend_html = "<p class='empty'>暂无趋势数据（待多次监测）</p>"
    if len(pts) >= 2:
        xs = [30 + i * (560 / max(1, len(pts) - 1)) for i in range(len(pts))]
        ys = [130 - (p["rate"] / 100) * 100 for p in pts]
        poly = " ".join(f"{x:.0f},{y:.0f}" for x, y in zip(xs, ys))
        labels = "".join(f"<text x='{x-14:.0f}' y='145' font-size='9' fill='#9ca3af'>{_esc(p['date'][5:])}</text>" for x, p in zip(xs, pts))
        trend_html = f"""<svg class='chart' viewBox='0 0 640 150' xmlns='http://www.w3.org/2000/svg'>
          <line x1='20' y1='130' x2='620' y2='130' stroke='#e5e7eb' stroke-width='1'/>
          <line x1='20' y1='80' x2='620' y2='80' stroke='#f0f2f5' stroke-width='1' stroke-dasharray='4 4'/>
          <polyline points='{poly}' fill='none' stroke='#2f6fed' stroke-width='2.5'/>
          {labels}
          <text x='350' y='20' font-size='10' fill='#2f6fed' font-weight='bold'>我方推荐率</text>
        </svg>"""

    # ── 05 竞争格局 ──
    comp_rows = ""
    for w in (report.get("why_competitors_win") or [])[:6]:
        c = w.get("competitor") or w.get("brand") or "竞品"
        comp_rows += f"<tr><td><span class='tag r'>竞品</span></td><td>{_esc(c)}</td><td>AI 推荐/提及</td><td>{_esc(w.get('reason') or w.get('summary'))}</td></tr>"
    for g in (report.get("gap_matrix") or [])[:4]:
        c = g.get("competitor") or ""
        if c and not any(c in r for r in comp_rows):
            comp_rows += f"<tr><td><span class='tag b'>对标</span></td><td>{_esc(c)}</td><td>{_esc(g.get('dimension') or g.get('factor') or '维度')}</td><td>我方：{_esc(g.get('us') or '—')}</td></tr>"
    if not comp_rows:
        comp_rows = "<tr><td colspan='4'>暂无竞品数据</td></tr>"

    # ── 06 信息来源贡献度 ──
    source_html = "<p class='empty'>外部来源归因待数据积累（当前仅追踪「我方内容被引用」）</p>"

    # ── 07 知识缺口 ──
    gap_rows = ""
    kg = report.get("knowledge_gaps") or []
    for i, g in enumerate(kg[:8]):
        prio = "p0" if i < 2 else "p1" if i < 5 else "p2"
        tagc = "r" if i < 2 else "o" if i < 5 else "b"
        gap_rows += (
            f"<tr class='{prio}'><td><b>{_esc(g.get('dimension'))}</b></td>"
            f"<td>{_esc(g.get('competitor') or '—')}</td>"
            f"<td>{_esc(g.get('suggestion'))}</td>"
            f"<td><span class='tag {tagc}'>P{i}</span></td></tr>"
        )
    if not gap_rows:
        gap_rows = "<tr><td colspan='4'>暂无知识缺口（Kernel 能力条目充足）</td></tr>"

    # ── 08 内容建设 ──
    act_rows = ""
    actions = report.get("actions") or []
    for a in actions[:8]:
        p = a.get("priority") or 1
        tagc = "r" if p <= 1 else "o" if p == 2 else "b"
        act_rows += (
            f"<tr><td><b>{_esc(a.get('task'))}</b></td>"
            f"<td>{_esc(a.get('angle'))}</td>"
            f"<td>{_esc(a.get('reason'))}</td>"
            f"<td><span class='tag {tagc}'>P{p}</span></td></tr>"
        )
    if not act_rows:
        act_rows = "<tr><td colspan='4'>暂无内容建设建议</td></tr>"

    # ── 09 行动计划 ──
    plan_rows = ""
    for a in actions[:8]:
        p = a.get("priority") or 1
        tagc = "r" if p <= 1 else "o" if p == 2 else "b"
        plan_rows += (
            f"<tr class='p{p-1 if p<=3 else 2}'><td><span class='tag {tagc}'>P{p}</span></td>"
            f"<td>{_esc(a.get('task'))}</td><td>{_esc(a.get('angle'))}</td>"
            f"<td>待分配</td><td>未开始</td><td>{_esc(a.get('reason'))}</td></tr>"
        )
    if not plan_rows:
        plan_rows = "<tr><td colspan='6'>暂无行动计划</td></tr>"

    # ── 10 下一周期 ──
    next_rows = (
        f"<tr><td>AI 认知健康度</td><td>{health}</td><td>≥ {min(100, health + 10)}</td></tr>"
        f"<tr><td>AI 推荐率</td><td>{dist.get('第一推荐', 0) + dist.get('强推荐', 0)}/{dist_total} 条</td><td>持续提升</td></tr>"
        f"<tr><td>知识缺口数</td><td>{kg_count}</td><td>≤ {max(0, kg_count - 2)}</td></tr>"
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>GEO · AI 认知报告</title>
<style>{_CSS}</style></head><body>

<!-- ════════ 第 1 页 · 01 + 02 ════════ -->
<div class="page">
  <div class="kicker">GEO · AI 认知报告</div>
  <h1>AI 认知健康报告</h1>
  <div class="meta">
    <span>企业：<b>{_esc(company)}</b></span>
    <span>周期：近 {days} 天</span>
    <span>生成：<b>{gen_time}</b></span>
    <span>数据源：国内 6 大 AI 引擎监测</span>
  </div>
  <div class="ai-note">⚠️ 本报告由 AI 自动生成。标注「AI 建议 · 待验证」的为模型推断；数据基于监测回答的规则统计（可溯源到具体回答样本），无数据章节如实标注。</div>

  <h2>01 · AI 认知健康</h2>
  <div class="gauge">
    <div class="score" style="{score_css}"><b>{health}</b><span>/ 100</span></div>
    <div class="note">
      基于 {total_ev} 条 AI 回答 + 知识库对照分析得出（规则估算）。<br>
      结论：<b>{_esc(report.get('diagnosis') or '待数据积累')}</b>
    </div>
  </div>
  <table>
    <tr><th>认知维度</th><th>得分</th><th>数据依据</th><th>解读</th></tr>
    {dim_rows}
  </table>
  <p class="src">数据口径：得分由监测回答标签占比/缺口矩阵规则推导，每项可溯源到回答样本。</p>

  <h2>02 · AI 眼中的企业（认知画像）</h2>
  {brand_table}
  <div class="grid2">
    <div class="card"><h3>🤖 AI 实际怎么认知（监测回答）</h3><ul>{tags_side}{ai_side}</ul></div>
    <div class="card"><h3>⚖️ 认知偏差（资料 vs AI 实际）</h3><ul>{bias_items}</ul></div>
  </div>
</div>

<!-- ════════ 第 2 页 · 03 + 04 ════════ -->
<div class="page">
  <h2>03 · 客户问题地图（决策链覆盖）</h2>
  <div class="flow">{flow}</div>
  <table>
    <tr><th>客户阶段</th><th>问题数</th><th>我方覆盖</th><th>AI 决策覆盖度</th></tr>
    {qm_rows}
  </table>
  <p class="src">* 我方覆盖 = 该阶段问题中 AI 回答含企业依据（grounded）的比例。</p>

  <h2>04 · AI 推荐表现</h2>
  <div class="grid2">
    <div class="card"><h3>📍 推荐位置（提及 ≠ 推荐）</h3>{bar_rows}</div>
    <div class="card">
      <h3>🧠 AI 为什么提到你</h3>
      <ul>{reason_html}</ul>
      {why_reasons}
    </div>
  </div>
  <div class="card" style="margin-top:14px;">
    <h3>📈 推荐率趋势（监测周期内）</h3>
    {trend_html}
  </div>

  <h2 style="margin-top:24px;">04.5 · 推荐变化（vs 上一周期）</h2>
  {trend_delta_html}

</div>

<!-- ════════ 第 3 页 · 05 + 06 ════════ -->
<div class="page">
  <h2>05 · 竞争格局</h2>
  <table>
    <tr><th>类型</th><th>对象</th><th>抢的是什么</th><th>我们的差距</th></tr>
    {comp_rows}
  </table>

  <h2>06 · 信息来源贡献度（AI 从哪里认识你）</h2>
  {source_html}
  <p class="src">规划：追踪 AI 回答引用的第三方来源（官网/社媒/新闻/百科）并归因占比——待数据积累。</p>
</div>

<!-- ════════ 第 4 页 · 07 + 08 ════════ -->
<div class="page">
  <h2>07 · 知识缺口（影响 × 紧急度）</h2>
  <table>
    <tr><th>缺口</th><th>竞品拥有？</th><th>建议</th><th>优先级</th></tr>
    {gap_rows}
  </table>

  <h2>08 · 内容 / 知识建设（AI 建议 · 待验证）</h2>
  <table>
    <tr><th>建设项</th><th>切入角度</th><th>理由</th><th>优先级</th></tr>
    {act_rows}
  </table>
</div>

<!-- ════════ 第 5 页 · 09 + 10 ════════ -->
<div class="page">
  <h2>09 · 未来 30 天行动计划（AI 建议 · 待验证）</h2>
  <table>
    <tr><th>优先级</th><th>行动</th><th>角度</th><th>负责人</th><th>状态</th><th>预期影响</th></tr>
    {plan_rows}
  </table>
  <p class="src">下次监测将自动核对：行动上线后，AI 回答是否开始引用新信息、覆盖率是否变化。</p>

  <h2>10 · 下一周期（基线 → 目标）</h2>
  <table>
    <tr><th>指标</th><th>本次基线</th><th>下周期目标</th></tr>
    {next_rows}
  </table>

  <div class="foot"><span>GEO AI 认知报告 · EIOS GEO 自动生成</span><span>数据口径：6 国内引擎监测回答 + 企业知识库对照</span></div>
</div>

</body></html>"""
    return html_doc


def render_report_pdf(
    report: Dict[str, Any],
    created_at: Optional[str] = None,
    history: Optional[List[dict]] = None,
    questions: Optional[List[dict]] = None,
    brand_stats: Optional[List[dict]] = None,
    trend: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
) -> bytes:
    from weasyprint import HTML

    html_doc = render_report_html(report, created_at, history, questions, brand_stats, trend)
    if output_path:
        HTML(string=html_doc).write_pdf(output_path)
        with open(output_path, "rb") as f:
            return f.read()
    return HTML(string=html_doc).write_pdf(target=None)
