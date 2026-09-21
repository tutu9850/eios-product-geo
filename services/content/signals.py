"""内容生成的市场现状信号（审计 A6 · Owner 2026-09-21 拍板「喂」）。

背景：生成内容时此前**一个字都不读**监测与认知评估的结论，等于闭着眼睛写——
不知道 AI 现在怎么回答客户、不知道 AI 编过什么、不知道竞品被夸在哪。
本模块把这些信号聚合出来，供 `build_context` 注入生成 prompt。

原则：
- **只读**。全部来自 GEO 自己的库（monitor_history / cognition_evaluations /
  geo_insight_reports / 因子对比），不写库、不调 LLM。
- **诚实**：没有数据就是空列表，不编造、不用默认值充数。
- **有界**：每条都截断 + 限量，防止 prompt 被历史数据拉爆。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("eios.geo.content.signals")

_ANSWER_LIMIT = 6  # 当前 AI 回答样例上限
_SNIPPET_LEN = 200
_HALLUCINATION_LIMIT = 5
_COMPETITOR_LIMIT = 6
_REPORT_ACTION_LIMIT = 5
_CITATION_LIMIT = 5


def _store():
    from app.services.store import get_store

    return get_store()


def _tokens(text: str) -> set[str]:
    """粗粒度相关性词：2-gram（够用且确定性，不做分词依赖）"""
    chars = [c for c in (text or "") if c.strip()]
    out = {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
    return out


def _relevance(question: str, candidate: str) -> int:
    if not question or not candidate:
        return 0
    return len(_tokens(question) & _tokens(candidate))


def _ai_answers(history: list[dict], question: str) -> tuple[list[dict], list[dict]]:
    """从监测历史取「AI 现在怎么答」+「AI 引用过什么」。

    question 非空时优先取与该问题最相关的监测记录（2-gram 重叠），
    否则取最近一批。只取真实有回答的引擎（mentioned 非 None）。
    """
    batches = [h for h in history if h.get("batch")] or history
    if not batches:
        return [], []
    if question:
        scored = sorted(batches, key=lambda h: -sum(_relevance(question, str(q.get("question") or "")) for q in h.get("questions") or []))
        picked = [scored[0]]
    else:
        picked = [batches[-1]]

    answers: list[dict] = []
    citations: dict[str, dict] = {}
    for h in picked:
        for q in h.get("questions") or []:
            qtext = str(q.get("question") or "")
            for ed in q.get("engine_detail") or []:
                if ed.get("mentioned") is None and not (ed.get("snippet") or "").strip():
                    continue  # 引擎没回答（错误/未配置）→ 不算现状
                txt = str(ed.get("snippet") or ed.get("answer") or "").strip()
                if not txt and ed.get("mentioned") is None:
                    continue
                answers.append({
                    "engine": str(ed.get("engine_name") or "unknown"),
                    "question": qtext,
                    "mentioned": bool(ed.get("mentioned")),
                    "rank_est": ed.get("rank_est"),
                    "sentiment": ed.get("sentiment"),
                    "snippet": txt[:_SNIPPET_LEN],
                })
        for c in h.get("citations") or []:
            title = str(c.get("title") or "").strip()
            if not title:
                continue
            entry = citations.setdefault(title, {"title": title, "count": 0, "questions": []})
            entry["count"] += int(c.get("count") or 0)
            for qn in (c.get("questions") or [])[:2]:
                if qn and qn not in entry["questions"]:
                    entry["questions"].append(str(qn))
    # 未提及优先（那才是「AI 现在不推荐你」的证据），再按引擎名稳定排序
    answers.sort(key=lambda a: (a["mentioned"], a["engine"]))
    cited = sorted(citations.values(), key=lambda c: -c["count"])[:_CITATION_LIMIT]
    return answers[:_ANSWER_LIMIT], cited


def _hallucinations(evals: list[dict]) -> list[dict]:
    """认知评估里被判为 hallucination 的声明（AI 编造过的话，生成时必须纠正）"""
    out: list[dict] = []
    for e in evals:
        for c in e.get("claims") or []:
            if str(c.get("status") or "") != "hallucination":
                continue
            claim = str(c.get("claim") or "").strip()
            if not claim:
                continue
            out.append({
                "claim": claim,
                "claim_type": c.get("claim_type"),
                "engine": e.get("engine"),
                "question": str(e.get("question") or "")[:80],
            })
    return out[:_HALLUCINATION_LIMIT]


def _competitor_edges(days: int = 30) -> list[dict]:
    """竞品被夸而你没被夸的因子（factor-gaps.left）——要重点补的内容方向"""
    try:
        from services.intelligence.cognition import factor_gaps

        left = factor_gaps(company=None, days=days).get("left") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("factor_gaps unavailable: %s", str(exc)[:120])
        return []
    out: list[dict] = []
    for g in left:
        factor = str(g.get("factor") or "").strip()
        if not factor:
            continue
        out.append({
            "factor": factor,
            "competitor": str(g.get("competitor_leader") or ""),
            "mentions": g.get("competitor_mentions"),
        })
    return out[:_COMPETITOR_LIMIT]


def _report_findings() -> list[dict]:
    """最新周期报告的结论（竞品为什么赢 / 能力缺口 / 建议动作）"""
    try:
        from services.intelligence import repo as irepo

        latest = irepo.latest_report()
    except Exception as exc:  # noqa: BLE001
        logger.warning("latest_report unavailable: %s", str(exc)[:120])
        return []
    if not latest:
        return []
    rj = latest.get("report_json") or {}
    findings: list[dict] = []
    for w in (rj.get("why_competitors_win") or [])[:3]:
        comp = str(w.get("competitor") or "")
        factors = [str(f.get("factor") or "") for f in (w.get("factors") or []) if f.get("factor")]
        if comp and factors:
            findings.append({"kind": "why_competitors_win", "competitor": comp, "factors": factors[:4]})
    for row in (rj.get("gap_matrix") or [])[:4]:
        dim = str(row.get("dimension") or "")
        gt = str(row.get("gap_type") or "")
        if dim and gt in ("capability_missing", "capability_hidden", "competitor_advantage", "market_unknown"):
            findings.append({
                "kind": "gap",
                "dimension": dim,
                "gap_type": gt,
                "competitor_mentions": row.get("competitor_mentions"),
            })
    for a in (rj.get("actions") or [])[:_REPORT_ACTION_LIMIT]:
        title = str(a.get("title") or a.get("action") or a.get("suggestion") or "").strip()
        if title:
            findings.append({"kind": "action", "title": title[:120], "priority": a.get("priority")})
    return findings


async def build_market_signals(question: str = "", tenant_id: str | None = None) -> dict:
    """市场现状信号（只读本柜）。没显式给租户时读**当前请求的柜**（账号分柜）。"""
    if not tenant_id:
        from app.services.store import current_tenant

        tenant_id = current_tenant() or "tenant_corp_01"
    """聚合「生成内容前应该看的市场现状」。

    返回 {ai_answers, citations, hallucinations, competitor_edges, report_findings, available}
    available=False 表示四路信号全空（此时 prompt 不注入该段，避免写「暂无」占位）。
    """
    try:
        store = _store()
    except Exception as exc:  # noqa: BLE001
        logger.warning("signals store unavailable: %s", str(exc)[:120])
        return {"ai_answers": [], "citations": [], "hallucinations": [], "competitor_edges": [],
                "report_findings": [], "available": False}

    def _load(table: str) -> list[dict]:
        try:
            return store.load(table) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("signals load %s failed: %s", table, str(exc)[:120])
            return []

    ai_answers, citations = _ai_answers(_load("monitor_history"), question)
    hallucinations = _hallucinations(_load("cognition_evaluations"))
    competitor_edges = _competitor_edges()
    report_findings = _report_findings()
    return {
        "ai_answers": ai_answers,
        "citations": citations,
        "hallucinations": hallucinations,
        "competitor_edges": competitor_edges,
        "report_findings": report_findings,
        "available": bool(ai_answers or citations or hallucinations or competitor_edges or report_findings),
    }


_GAP_TYPE_CN = {
    "capability_missing": "真缺知识（能力缺口）",
    "capability_hidden": "有能力但没讲出来",
    "competitor_advantage": "竞品优势",
    "market_unknown": "市场未知",
}


def render_market_signals(signals: dict) -> str:
    """市场现状 → 生成 prompt 段落（无信号返回空串，不占位、不编造）。"""
    if not signals or not signals.get("available"):
        return ""
    lines: list[str] = []

    if signals.get("ai_answers"):
        lines.append("### AI 现在这样回答客户（监测实测，未提及的必须重点纠正）")
        for a in signals["ai_answers"]:
            state = "已提及本企业" if a.get("mentioned") else "**未提及本企业**"
            meta = [state]
            if a.get("rank_est"):
                meta.append(f"估算排名 {a['rank_est']}")
            if a.get("sentiment"):
                meta.append(f"情感 {a['sentiment']}")
            lines.append(f"- [{a['engine']}] 「{a['question'][:60]}」（{'，'.join(meta)}）")
            if a.get("snippet"):
                lines.append(f"  原话节选：{a['snippet']}")

    if signals.get("citations"):
        lines.append("")
        lines.append("### AI 引用过本企业的内容（说明这类素材有效，可对齐写法）")
        for c in signals["citations"]:
            qs = "、".join(c.get("questions") or [])[:60]
            lines.append(f"- 《{c['title']}》被引用 {c['count']} 次" + (f"（回答「{qs}」时）" if qs else ""))

    if signals.get("hallucinations"):
        lines.append("")
        lines.append("### AI 说错的地方（必须在内容中正面纠正，正文不得沿用这些说法）")
        for h in signals["hallucinations"]:
            lines.append(f"- [{h.get('engine') or '未知引擎'}] {h['claim']}")

    if signals.get("competitor_edges"):
        lines.append("")
        lines.append("### 竞品被夸而本企业没被夸的因子（内容要重点补这些点）")
        for c in signals["competitor_edges"]:
            comp = f"（{c['competitor']} 被提及 {c.get('mentions')} 次）" if c.get("competitor") else ""
            lines.append(f"- {c['factor']}{comp}")

    if signals.get("report_findings"):
        lines.append("")
        lines.append("### 周期报告结论")
        for f in signals["report_findings"]:
            if f["kind"] == "why_competitors_win":
                lines.append(f"- 竞品 {f['competitor']} 胜出因子：{'、'.join(f['factors'])}")
            elif f["kind"] == "gap":
                cn = _GAP_TYPE_CN.get(f["gap_type"], f["gap_type"])
                lines.append(f"- 维度「{f['dimension']}」判定为 {cn}（竞品被提及 {f.get('competitor_mentions') or 0} 次）")
            else:
                lines.append(f"- 建议动作：{f['title']}")

    if not lines:
        return ""
    return (
        "## 当前市场现状（监测 / 认知评估实测，写内容前必须先看）\n"
        + "\n".join(lines)
        + "\n\n写作要求：正文要正面回应上表中的现状——对「未提及本企业」的问题给出可被引用的事实与结构；"
        "对 AI 编造的说法必须以知识库事实纠正（不得沿用幻觉描述）；竞品被夸的因子要重点补证据。"
        "但**只能使用给定企业资料**，不得为了对上这些点而编造事实。"
    )
