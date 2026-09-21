"""Intelligence 分析引擎 — Reasoning（周期报告，S2）

流程：聚合摘要 + 企业知识库 active 对照 → 规则定 gap_type → LLM 生成报告文案
      → 校验 refs → 写 geo_insight_reports。

铁律：
- 企业知识库只读 active（include_candidates=False）；企业知识库不可达 → 保守视为无能力（不编造）
- gap_type 由规则判定（不让模型自由发挥）：🔴 + 知识库已有能力 = capability_hidden（推文章）
  ；🔴+无=capability_missing（知识缺口）；🟢 已有；👁 观察区不处理
- 无 refs 的 action / knowledge_gaps 不产出；禁无基线定量承诺
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone

from adapters.eios import hits_of, search_knowledge
from adapters.llm import LLMNotConfiguredError, chat

from services.intelligence import aggregator, repo
from services.intelligence.extractor import _parse_json
from services.intelligence.prompts import PROMPT_VERSION, REASONING_PROMPT, REASONING_SYSTEM

logger = logging.getLogger("eios.intelligence.reasoning")

DEFAULT_TENANT = "tenant_corp_01"


async def _knowledge_has(dimension: str) -> bool | None:
    """企业知识库是否有该维度对应能力（只读 active；保守判定，防编造）。

    三态：True=有能力（检索命中）/ False=无能力（检索无命中）/ None=企业知识库不可达（无法判定）。
    None 与 False 必须区分——企业知识库宕机不等于企业没能力。

    审计 B7：旧实现用 ``best >= 0.5`` —— 那个 0.5 是按换知识源前的旧适配器的 0–1 余弦分定的。
    换成 EIOS 检索后 ``score`` 是排序分（实测 13.5~14.0），条件恒真、阈值成了摆设。
    这里不再假装有个可校准的阈值：以权威侧给的事实为准 —— 命中即有能力。
    """
    try:
        r = await search_knowledge(dimension, top_k=3, include_candidates=False)
        hits = hits_of(r)
        if "matched" in r:
            return bool(r.get("matched")) or bool(hits)
        return bool(hits)
    except Exception as exc:  # noqa: BLE001
        logger.warning("knowledge check failed for %r: %s", dimension, str(exc)[:120])
        return None  # 企业知识库不可达 → 无法判定（≠ 企业无能力）


async def _knowledge_summary(company: str, limit: int = 50) -> str:
    """企业知识库 active 摘要（实体名 + 事实短句，≤limit 条，契约钉死防拉爆）。"""
    lines: list[str] = []
    try:
        r = await search_knowledge(company or "企业", top_k=limit, include_candidates=False)
        for h in hits_of(r)[:limit]:
            # 审计 B6：``_map_hit`` 不产出 ``kind`` 字段，旧代码按 kind == "fact"/"chunk"
            # 分流 → 全部落兜底分支，只带实体名、丢掉 predicate/value。
            # 现在按「命中里有没有正文」分流：有正文就用正文，否则至少带上实体名。
            name = (h.get("canonical_name") or h.get("name") or "").strip()
            pred = (h.get("predicate") or "").strip()
            val = (h.get("value") or h.get("snippet") or "").strip()
            if val:
                head = ": ".join(p for p in (name, " ".join(p for p in (pred, val) if p)) if p)
                lines.append(head[:160])
            else:
                lines.append(name or str(h.get("object_id") or h.get("document_id") or ""))
    except Exception as exc:  # noqa: BLE001
        lines.append(f"（企业知识库不可达：{str(exc)[:60]}）")
    return "\n".join([l for l in lines if l][:limit]) or "（企业知识库暂无 active 内容）"


def _aggregate_text(m: dict, p: dict) -> str:
    """把矩阵/感知聚合成 LLM 可读文本（含 evidence_id 供 refs）。"""
    lines = [f"已解析回答数：{m.get('evidence_count', 0)}"]
    for d in m.get("dimensions") or []:
        lines.append(
            f"- 维度「{d['dimension']}」{d['band_label']} 总提及{d['total_mentions']} 我方{d['self_mentions']} 他方{d['other_mentions']}"
            f" knowledge_has={d.get('knowledge_has')} gap_type={d.get('gap_type')}"
        )
        for q in d.get("quotes") or []:
            lines.append(f"    证据[{q.get('evidence_id')}] {q.get('brand')}：{q.get('quote')}")
    for o in m.get("observation") or []:
        lines.append(f"- 观察区「{o['dimension']}」（1 次，暂不处理）")
    for mn in m.get("missing") or []:
        lines.append(f"- 提到我方但未推荐：{mn.get('quote')}")
    if p.get("tags"):
        lines.append("- 他方认知标签：" + "、".join(f"{t['tag']}×{t['count']}" for t in p["tags"][:10]))
    if p.get("self_tags"):
        lines.append("- 我方认知标签：" + "、".join(f"{t['tag']}×{t['count']}" for t in p["self_tags"][:10]))
    return "\n".join(lines)


async def generate_report(
    company: str | None = None,
    days: int = 30,
    tenant: str = DEFAULT_TENANT,
) -> dict:
    """生成一份周期报告并入库。返回报告 dict。"""
    m = aggregator.matrix(company=company, days=days, tenant=tenant)
    p = aggregator.perception(company=company, days=days, tenant=tenant)
    overview = aggregator.brand_overview(company=company, days=days, tenant=tenant)
    kw = aggregator.keywords(company=company, days=days, tenant=tenant)

    # 1. 企业知识库对照 + 规则定 gap_type（维度逐个查，检索不花生成 token）
    #    knowledge_has 三态：True/False/None(不可达)——None 不判 gap_type，防「知识库宕=企业没能力」
    for dim in m["dimensions"]:
        dim["knowledge_has"] = await _knowledge_has(dim["dimension"])
        if dim["band"] == "red":
            if dim["knowledge_has"] is None:
                dim["gap_type"] = None
                dim["knowledge_unknown"] = True
            else:
                dim["gap_type"] = "capability_hidden" if dim["knowledge_has"] else "capability_missing"
        else:
            dim["gap_type"] = None

    # 2. LLM 生成报告文案（actions / knowledge_gaps / diagnosis / why / perception）
    knowledge_summary = await _knowledge_summary(company or "")
    aggregate = _aggregate_text(m, p)
    prompt = REASONING_PROMPT.format(
        company_name=company or "企业",
        days=days,
        aggregate=aggregate,
        knowledge_summary=knowledge_summary,
    )
    llm_json: dict = {}
    try:
        text = await chat(
            prompt,
            system=REASONING_SYSTEM,
            max_tokens=8000,
            response_format={"type": "json_object"},
        )
        llm_json = _parse_json(text) or {}
    except LLMNotConfiguredError as exc:
        logger.warning("reasoning LLM 未配置：%s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reasoning LLM 失败（报告降级为纯规则）：%s", str(exc)[:150])

    # 3. 合并：gap_matrix 以规则为准；LLM 只补文案
    actions = _validate_actions(llm_json.get("actions"))
    knowledge_gaps = _validate_gaps(llm_json.get("knowledge_gaps"))
    report = {
        "schema_version": "1.0",
        "source_scope": ["ai_answer"],
        "company": company,
        "period_days": days,
        "perception": llm_json.get("perception") or {"tags": p.get("tags", [])},
        "brand_overview": overview,  # 提及率%（我方 vs 竞品）
        "keywords": kw,  # 必备关键词（高频维度）
        "why_competitors_win": _validate_gaps(llm_json.get("why_competitors_win")),
        "capability_gap": llm_json.get("capability_gap") or {},
        "gap_matrix": [
            {
                "dimension": d["dimension"],
                "band": d["band"],
                "band_label": d["band_label"],
                "gap_type": d.get("gap_type"),
                "knowledge_has": d.get("knowledge_has"),
                "total_mentions": d["total_mentions"],
                "self_mentions": d["self_mentions"],
                "other_mentions": d["other_mentions"],
                "competitor_mentions": d["competitor_mentions"],
                "quotes": d.get("quotes") or [],  # 页面点开原话（含 evidence_id/brand）
                "support_refs": [q["evidence_id"] for q in d.get("quotes") or []],
            }
            for d in m["dimensions"]
        ],
        "missing": m.get("missing", []),
        "actions": actions,
        "knowledge_gaps": knowledge_gaps,
        "diagnosis": llm_json.get("diagnosis") or _rule_diagnosis(m),
        "model": f"geo-llm-v{PROMPT_VERSION}",
        "prompt_version": PROMPT_VERSION,
    }

    rec = repo.insert_report(
        {
            "company_name": company or "unknown",
            "period_start": date.today() - timedelta(days=days),
            "period_end": date.today(),
            "report_json": report,
            "model": report["model"],
            "prompt_version": PROMPT_VERSION,
            "schema_version": "1.0",
        }
    )
    logger.info("report generated: %s（%d 维度，%d 行动）", rec.get("id"), len(report["gap_matrix"]), len(actions))
    return report


def _validate_actions(actions: list | None) -> list:
    """无 refs 的 action 不产出（铁律 2）。"""
    out = []
    for a in actions or []:
        refs = a.get("support_refs") or []
        if not refs:
            continue
        out.append(
            {
                "priority": a.get("priority", len(out) + 1),
                "task": (a.get("task") or "").strip(),
                "angle": (a.get("angle") or "").strip(),
                "reason": (a.get("reason") or "").strip(),
                "support_refs": refs,
                "expected_effect": (a.get("expected_effect") or "").strip(),
            }
        )
    return out


def _validate_gaps(items: list | None) -> list:
    out = []
    for it in items or []:
        refs = it.get("support_refs") or []
        if not refs:
            continue
        out.append(it)
    return out


def _rule_diagnosis(m: dict) -> str:
    """无 LLM 时的规则诊断兜底（含证据，可溯源）。"""
    reds = [d for d in m["dimensions"] if d["band"] == "red"]
    greens = [d for d in m["dimensions"] if d["band"] == "green"]
    missing = len(m.get("missing") or [])
    parts = []
    if reds:
        hidden = [d["dimension"] for d in reds if d.get("knowledge_has")]
        miss = [d["dimension"] for d in reds if d.get("knowledge_has") is False]
        unknown = [d["dimension"] for d in reds if d.get("knowledge_has") is None]
        if hidden:
            parts.append(f"外界未感知但有能力的维度：{'、'.join(hidden)}")
        if miss:
            parts.append(f"竞品有但知识库无的维度：{'、'.join(miss)}")
        if unknown:
            parts.append(f"企业知识库暂不可达、能力缺口待核实的维度：{'、'.join(unknown)}")
    if greens:
        parts.append(f"外界已认知的维度：{'、'.join(d['dimension'] for d in greens)}")
    if missing:
        parts.append(f"AI 提到主体但未推荐 {missing} 次")
    return "；".join(parts) or "数据不足，暂无诊断结论"
