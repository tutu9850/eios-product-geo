"""cognition.py — AI 认知模型（方案 V2 阶段 1：数据重组，不动 LLM）

底层三层（不冻结，可配置）：
1. Raw Factor → Semantic Factor（归类规则表）
2. Semantic Factor → Dimension（默认 7 维视图）
3. Dimension → Scenario（按 intent 切片）

认知层级（从 brand_mention + intent 规则推算）：
  mention → considered → shortlisted → recommended → reason → trust

认知状态（7 态，规则判定）：
  strong_positive / weak_positive / neutral / weak_negative
  / strong_negative / no_cognition / wrong
"""
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from services.intelligence import aggregator, repo

logger = logging.getLogger("eios.intelligence.cognition")

DEFAULT_TENANT = "tenant_corp_01"

# ── Raw Factor → Semantic Factor + Dimension（可配置映射表）────────────────
# 每行：{ raw_factor -> {"semantic": str, "dimension": str} }
# 未匹配的 factor 归入 "其他" 维度，保留原词作 semantic factor

FACTOR_CLASSIFICATION: dict[str, dict[str, str]] = {
    # ── 品牌认知 ──
    "品牌影响": {"semantic": "品牌认知", "dimension": "品牌认知"},
    "品牌知名度": {"semantic": "品牌知名度", "dimension": "品牌认知"},
    "知名度": {"semantic": "品牌知名度", "dimension": "品牌认知"},
    "大厂": {"semantic": "品牌规模", "dimension": "品牌认知"},
    "巨头": {"semantic": "品牌规模", "dimension": "品牌认知"},
    "口碑": {"semantic": "品牌口碑", "dimension": "品牌认知"},
    "知名": {"semantic": "品牌知名度", "dimension": "品牌认知"},
    "综合AI平台型巨头": {"semantic": "品牌定位", "dimension": "品牌认知"},
    "非知名巨头": {"semantic": "品牌知名度", "dimension": "品牌认知"},
    "名称通用": {"semantic": "品牌识别度", "dimension": "品牌认知"},
    "存在同名公司": {"semantic": "品牌混淆", "dimension": "品牌认知"},
    "常见注册名": {"semantic": "品牌识别度", "dimension": "品牌认知"},
    "信息不足": {"semantic": "信息可得性", "dimension": "品牌认知"},
    "未作具体评价": {"semantic": "信息可得性", "dimension": "品牌认知"},
    "需自行核实": {"semantic": "信息可信度", "dimension": "品牌认知"},
    "需核实": {"semantic": "信息可信度", "dimension": "品牌认知"},
    "需严格审查": {"semantic": "信任门槛", "dimension": "品牌认知"},
    "业务不明确": {"semantic": "品牌定位", "dimension": "品牌认知"},
    # ── 产品能力 ──
    "AI能力": {"semantic": "AI能力", "dimension": "产品能力"},
    "AI": {"semantic": "AI能力", "dimension": "产品能力"},
    "智能": {"semantic": "AI能力", "dimension": "产品能力"},
    "大模型": {"semantic": "大模型", "dimension": "产品能力"},
    "智能体": {"semantic": "AI Agent", "dimension": "产品能力"},
    "自动化": {"semantic": "自动化", "dimension": "产品能力"},
    "功能完整性": {"semantic": "功能完整性", "dimension": "产品能力"},
    "功能": {"semantic": "功能完整性", "dimension": "产品能力"},
    "算法门槛低": {"semantic": "易用性", "dimension": "产品能力"},
    "小样本学习": {"semantic": "算法能力", "dimension": "产品能力"},
    "定制化模型": {"semantic": "定制能力", "dimension": "产品能力"},
    "工业数据专家": {"semantic": "数据能力", "dimension": "产品能力"},
    "技术实力强": {"semantic": "技术能力", "dimension": "产品能力"},
    "数据处理能力": {"semantic": "数据能力", "dimension": "产品能力"},
    "应用广泛": {"semantic": "应用广度", "dimension": "产品能力"},
    "行业应用": {"semantic": "行业覆盖", "dimension": "产品能力"},
    "落地案例多": {"semantic": "落地案例", "dimension": "产品能力"},
    "落地案例": {"semantic": "落地案例", "dimension": "产品能力"},
    "案例丰富": {"semantic": "落地案例", "dimension": "产品能力"},
    "案例": {"semantic": "落地案例", "dimension": "产品能力"},
    "客户数": {"semantic": "客户规模", "dimension": "产品能力"},
    "用户量": {"semantic": "用户规模", "dimension": "产品能力"},
    "企业客户": {"semantic": "企业客户", "dimension": "产品能力"},
    "落地": {"semantic": "落地案例", "dimension": "产品能力"},
    "服务了": {"semantic": "服务规模", "dimension": "产品能力"},
    # ── 技术叙事 ──
    "技术积累": {"semantic": "技术积累", "dimension": "技术叙事"},
    "生态完善": {"semantic": "生态建设", "dimension": "技术叙事"},
    "生态": {"semantic": "生态建设", "dimension": "技术叙事"},
    "集成": {"semantic": "集成能力", "dimension": "技术叙事"},
    "打通": {"semantic": "系统打通", "dimension": "技术叙事"},
    "一体化": {"semantic": "一体化平台", "dimension": "技术叙事"},
    "全家桶": {"semantic": "产品矩阵", "dimension": "技术叙事"},
    "互通": {"semantic": "系统互通", "dimension": "技术叙事"},
    "软硬协同强": {"semantic": "软硬一体", "dimension": "技术叙事"},
    "软硬协同": {"semantic": "软硬一体", "dimension": "技术叙事"},
    "云边端协同": {"semantic": "边缘计算", "dimension": "技术叙事"},
    "重工业表现突出": {"semantic": "行业适配", "dimension": "技术叙事"},
    "成熟稳定": {"semantic": "成熟度", "dimension": "技术叙事"},
    "成熟": {"semantic": "成熟度", "dimension": "技术叙事"},
    "稳定": {"semantic": "稳定性", "dimension": "技术叙事"},
    "完善": {"semantic": "完善度", "dimension": "技术叙事"},
    "可靠": {"semantic": "可靠性", "dimension": "技术叙事"},
    "多年": {"semantic": "行业积累", "dimension": "技术叙事"},
    "老牌": {"semantic": "行业积累", "dimension": "技术叙事"},
    # ── 风险信任 ──
    "安全可信": {"semantic": "安全性", "dimension": "风险信任"},
    "安全": {"semantic": "安全性", "dimension": "风险信任"},
    "合规": {"semantic": "合规性", "dimension": "风险信任"},
    "认证": {"semantic": "认证", "dimension": "风险信任"},
    "可信": {"semantic": "可信度", "dimension": "风险信任"},
    "数据安全": {"semantic": "数据安全", "dimension": "风险信任"},
    "隐私": {"semantic": "隐私保护", "dimension": "风险信任"},
    "数据与隐私安全": {"semantic": "隐私保护", "dimension": "风险信任"},
    "合同与资质审查": {"semantic": "合规审查", "dimension": "风险信任"},
    "技术依赖与可持续性": {"semantic": "技术依赖风险", "dimension": "风险信任"},
    "售后与技术支持": {"semantic": "售后保障", "dimension": "风险信任"},
    "知识产权": {"semantic": "IP风险", "dimension": "风险信任"},
    # ── 价格价值 ──
    "免费": {"semantic": "免费模式", "dimension": "价格价值"},
    "便宜": {"semantic": "价格优势", "dimension": "价格价值"},
    "性价比": {"semantic": "性价比", "dimension": "价格价值"},
    "价格优势": {"semantic": "价格优势", "dimension": "价格价值"},
    "价格": {"semantic": "价格因素", "dimension": "价格价值"},
    "成本低": {"semantic": "成本优势", "dimension": "价格价值"},
    "优惠": {"semantic": "促销优惠", "dimension": "价格价值"},
    # ── 服务体验 ──
    "服务": {"semantic": "服务质量", "dimension": "服务体验"},
    "售后": {"semantic": "售后", "dimension": "服务体验"},
    "支持": {"semantic": "客户支持", "dimension": "服务体验"},
    "响应": {"semantic": "响应速度", "dimension": "服务体验"},
    "文档": {"semantic": "文档质量", "dimension": "服务体验"},
    "好用": {"semantic": "易用性", "dimension": "服务体验"},
    "响应时效": {"semantic": "响应速度", "dimension": "服务体验"},
    # ── 其他常见因子（观察区里的长尾语义）──
    "承认信息局限": {"semantic": "信息透明度", "dimension": "品牌认知"},
    "建议用户自行查证": {"semantic": "信息可得性", "dimension": "品牌认知"},
}

_KNOWN_DIMENSIONS = ["品牌认知", "产品能力", "技术叙事", "案例落地", "价格价值", "风险信任", "服务体验"]

# 认知层级
COGNITION_LEVEL_ORDER = ["mention", "considered", "shortlisted", "recommended", "reason", "trust"]

# 认知状态标签
COGNITION_STATE_LABELS: dict[str, str] = {
    "strong_positive": "强正向",
    "weak_positive": "弱正向",
    "neutral": "中性",
    "weak_negative": "弱负面",
    "strong_negative": "强负面",
    "no_cognition": "无认知",
    "wrong": "错误认知",
}


def _classify(factor: str) -> dict[str, str]:
    """raw factor → {semantic, dimension}。未匹配归入 '其他'。"""
    f = factor.strip()
    if f in FACTOR_CLASSIFICATION:
        return FACTOR_CLASSIFICATION[f]
    # 模糊匹配：LLM 常输出“高端真皮材质”等组合短语，不能只做精确匹配。
    for raw, classified in sorted(FACTOR_CLASSIFICATION.items(), key=lambda item: -len(item[0])):
        if len(raw) >= 2 and (raw in f or (len(f) >= 2 and f in raw)):
            return classified
    return {"semantic": f, "dimension": "其他"}


# ── 战略维度（认知层级聚合：业务维度 → 战略维度）────────────────────────
# GPT 评审采纳（05 方案 D1）：老板要看"我输在信任还是技术"，6 个业务维度
# 聚合成 4 大战略维度，页面按战略维度分组展示。
STRATEGY_DIMENSIONS = ["品牌信任", "技术实力", "行业理解", "商业价值", "其他"]

DIMENSION_TO_STRATEGY: dict[str, str] = {
    "品牌认知": "品牌信任",
    "风险信任": "品牌信任",
    "产品能力": "技术实力",
    "技术叙事": "技术实力",
    "服务体验": "商业价值",
    "价格价值": "商业价值",
    "其他": "其他",
}

# 战略维度：关键词优先判定（LLM 提取的因子五花八门，精确匹配会掉"其他"），
# 再按业务维度映射表兜底。判定顺序：行业理解（最特异）→ 技术实力 → 品牌信任 → 商业价值。
_STRATEGY_HINTS: dict[str, tuple[str, ...]] = {
    "行业理解": ("行业", "场景", "垂直", "本地化", "产线", "领域", "工厂", "制造现场", "家装", "家具", "空间", "户型"),
    "技术实力": ("算法", "AI", "技术", "研发", "专利", "积累", "模型", "数据", "智能", "自动化", "功能", "案例", "落地", "能力", "工艺", "材料", "材质", "真皮", "环保", "质量", "品质", "施工"),
    "品牌信任": ("成熟", "稳定", "大厂", "巨头", "生态", "口碑", "知名", "品牌", "规模", "信任", "审查", "实力", "背书", "可信", "安全", "保障", "认证", "评价"),
    "商业价值": ("性价比", "价格", "成本", "报价", "定制", "服务", "售后", "响应", "交付", "灵活", "价值", "体验", "舒适", "质保", "周期"),
}


def _strategy_of(dimension: str, factor: str) -> str:
    """raw factor → 战略维度（关键词优先，业务维度映射兜底）"""
    f = factor or ""
    for strategy, kws in _STRATEGY_HINTS.items():
        if any(kw in f for kw in kws):
            return strategy
    return DIMENSION_TO_STRATEGY.get(dimension, "其他")


def _mention_level(mention_type: str) -> str:
    """mention_type → 最低认知层级。"""
    if mention_type == "trust":
        return "trust"
    if mention_type == "reason":
        return "reason"
    # missing / other → mention（提到了但非推荐）
    return "mention"


def _cognition_state(mention_type: str, intent: str, quote: str | None = None) -> str:
    """规则判定认知状态（V1 简化：mention_type + intent → 态）。

    - reason + recommendation → strong_positive
    - trust → strong_positive
    - reason + awareness → weak_positive（审查建议/风险提醒，不是推荐）
    - missing → weak_negative
    - mention only → no_cognition
    """
    mt = (mention_type or "").lower()
    it = (intent or "").lower()
    if mt == "trust":
        return "strong_positive"
    if mt == "reason":
        if it in ("recommendation", "comparison", "trust"):
            return "strong_positive"
        # awareness / other 场景的 reason → 弱正向（非推荐场景的理由）
        return "weak_positive"
    if mt == "missing":
        # 提到但未推荐 → 弱负面
        q = (quote or "").lower()
        if any(w in q for w in ("推荐", "首选", "优势", "领先", "可靠")):
            return "neutral"  # missing 但有正向语
        return "weak_negative"
    return "neutral"


def _cognition_levels(
    mentions: list[dict], intents: dict[str, str]
) -> dict[str, int]:
    """给一个主体在一个维度下的所有 mentions，算出认知层级计数。

    mention   = 该主体被提到的 evidence 数（去重 evidence_id）
    considered = intent 为 recommendation/comparison 的 evidence 中主体被提到
    shortlisted = intent 为 recommendation 且有 reason/trust 的
    recommended = shortlisted 的进一步要求（>= reason 层级）
    reason = mention_type=reason 的 evidence 数
    trust = mention_type=trust 的 evidence 数
    """
    ev_ids = {m["evidence_id"] for m in mentions}
    levels: dict[str, int] = {k: 0 for k in COGNITION_LEVEL_ORDER}
    levels["mention"] = len(ev_ids)

    # considered: 对比/推荐 intent 的 evidence 中该主体被提
    considered_evs = {
        eid for eid in ev_ids if intents.get(eid) in ("recommendation", "comparison")
    }
    levels["considered"] = len(considered_evs)

    # reason / trust: 按 mention_type 计数（去重 evidence），但只算推荐/对比场景——
    # awareness 场景的 reason（如"使用云启需审查资质"）是风险提示，不是推荐理由（被提及≠被推荐）
    REC_INTENTS = ("recommendation", "comparison", "trust")
    reason_evs = {
        m["evidence_id"]
        for m in mentions
        if m["mention_type"] == "reason" and intents.get(m["evidence_id"]) in REC_INTENTS
    }
    trust_evs = {
        m["evidence_id"]
        for m in mentions
        if m["mention_type"] == "trust" and intents.get(m["evidence_id"]) in REC_INTENTS
    }
    levels["reason"] = len(reason_evs)
    levels["trust"] = len(trust_evs)

    # shortlisted: recommendation intent + reason/trust
    levels["shortlisted"] = len(
        {eid for eid in (reason_evs | trust_evs) if intents.get(eid) == "recommendation"}
    )

    # recommended: shortlisted + reason（至少 reason 层级才算推荐）
    levels["recommended"] = levels["shortlisted"]

    return levels


def compare(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    min_level: str = "mention",
    tenant: str = DEFAULT_TENANT,
) -> dict:
    """认知总表：维度 × 主体 × 认知层级 × 认知状态 + 证据引用。

    参数：
    - min_level：统计的最浅认知层级（"mention" = 全部，"recommended" = 只看被推荐）
    """
    since_dt = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    ev_ids = aggregator._succeeded_evidence_ids(since_dt, company, source_type, tenant)
    mentions = aggregator._load_mentions(ev_ids, tenant)
    # D0：竞品范围过滤（与 matrix 同规则：我方 + 监测清单内品牌）
    mentions = aggregator._filter_mentions(mentions, company, tenant)
    intents = aggregator._evidence_intents(ev_ids)

    # ── 按维度 × 主体分组 ──
    # dim_map[dimension][brand] = [{evidence_id, mention_type, factor, quote, intent}...]
    dim_map: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    all_brands: set[str] = set()
    for m in mentions:
        if m["mention_type"] == "missing":
            # missing（提到但未推荐）也是曝光：必须进品牌表，否则曝光率/样本量算错
            # （云启 18 条提及全是 missing → 之前被跳过 → 商业概览曝光 0%）
            f = m.get("factor") or "被提及但未推荐"
            cls = _classify(f)
        else:
            cls = _classify(m.get("factor") or "")
        dim = cls["dimension"]
        semantic = cls["semantic"]
        brand = m["brand_name"]
        all_brands.add(brand)
        intent = intents.get(m["evidence_id"], "other")
        dim_map[dim][brand].append(
            {
                "evidence_id": m["evidence_id"],
                "mention_type": m["mention_type"],
                "factor": m.get("factor") or "",
                "semantic": semantic,
                "quote": m.get("evidence_quote") or "",
                "intent": intent,
                "subject_company": m.get("subject_company") or "",
            }
        )

    # 我方判定
    subject = company or ""
    if not subject:
        sub_counts: dict[str, int] = {}
        for m in mentions:
            sc = m.get("subject_company") or ""
            if sc:
                sub_counts[sc] = sub_counts.get(sc, 0) + 1
        if sub_counts:
            subject = max(sub_counts, key=sub_counts.get)

    # ── 构建认知矩阵 ──
    matrix_rows: list[dict] = []
    total_brand_stats: dict[str, dict] = {}

    # 标准维度 + "其他"（LLM 提取的具体因子如"检测精度"多落"其他"，必须进矩阵，
    # 否则 factor_gaps 的 quotes 拿不到 → 竞品有·我没有 / 我该做什么 全空）
    _matrix_dims = _KNOWN_DIMENSIONS + sorted(d for d in dim_map if d not in _KNOWN_DIMENSIONS)
    for dim_name in _matrix_dims:
        if dim_name not in dim_map:
            # 所有主体在此维度无认知
            row = {
                "dimension": dim_name,
                "strategy": _strategy_of(dim_name, dim_name),
                "subjects": {},
                "industry_baseline": None,  # 阶段 2 预留
            }
            matrix_rows.append(row)
            continue

        subjects_data: dict[str, dict] = {}
        for brand in all_brands:
            brand_mentions = dim_map[dim_name].get(brand, [])
            levels = _cognition_levels(brand_mentions, intents)

            # min_level 过滤：level < min_level 的数据不算
            min_idx = COGNITION_LEVEL_ORDER.index(min_level) if min_level in COGNITION_LEVEL_ORDER else 0
            visible = any(
                levels[COGNITION_LEVEL_ORDER[i]] > 0
                for i in range(min_idx, len(COGNITION_LEVEL_ORDER))
            )

            # 认知状态：取该维度下该主体的最高层级来判态
            top_level = max(
                (COGNITION_LEVEL_ORDER.index(_mention_level(m["mention_type"]))
                 for m in brand_mentions),
                default=-1,
            )
            if top_level >= 0:
                top_mt = COGNITION_LEVEL_ORDER[top_level]
                # 取对应 mention 的 intent
                rep_intent = next((intents.get(m["evidence_id"], "other") for m in brand_mentions), "other")
                state = _cognition_state(top_mt, rep_intent)
            elif levels["mention"] > 0:
                state = "neutral"
            else:
                state = "no_cognition"

            subject_info = {
                "brand": brand,
                "is_self": aggregator._is_self(brand, subject),
                "cognition_state": state,
                "cognition_state_label": COGNITION_STATE_LABELS.get(state, state),
                "levels": levels,
                "total_mentions": sum(levels.values()),
                "visible": visible,
                "quotes": [
                    {"quote": m["quote"], "factor": m["factor"], "semantic": m["semantic"],
                     "mention_type": m["mention_type"], "intent": m["intent"],
                     "evidence_id": m["evidence_id"]}
                    for m in brand_mentions
                ][:5],  # 最多 5 条原话
            }
            subjects_data[brand] = subject_info

            # 全局品牌统计
            if brand not in total_brand_stats:
                total_brand_stats[brand] = {
                    "name": brand,
                    "is_self": aggregator._is_self(brand, subject),
                    "all_mentions": [],
                }
            total_brand_stats[brand]["all_mentions"].extend(brand_mentions)

        row = {
            "dimension": dim_name,
            "strategy": _strategy_of(dim_name, dim_name),
            "subjects": subjects_data,
            "industry_baseline": None,  # 阶段 2 预留
        }
        matrix_rows.append(row)

    # 全局品牌认知概览
    brand_overviews = []
    all_ev = len(ev_ids)
    # 兜底：未归类到标准维度的 factor（dimension="其他"）也要进品牌概览——
    # 否则 total_brand_stats 缺该品牌，下方 brand_overviews 循环 KeyError（云启视界 bug 根因）
    for extra_dim, brands in dim_map.items():
        if extra_dim in _KNOWN_DIMENSIONS:
            continue
        for _brand, _ms in brands.items():
            _st = total_brand_stats.setdefault(
                _brand,
                {"name": _brand, "is_self": aggregator._is_self(_brand, subject), "all_mentions": []},
            )
            _st["all_mentions"].extend(_ms)
    for brand in sorted(all_brands):
        if brand not in total_brand_stats:
            continue  # 防御：无任何统计的品牌跳过（不应发生）
        brand_mentions_list = total_brand_stats[brand]["all_mentions"]
        levels = _cognition_levels(brand_mentions_list, intents)
        # 认知状态（取最高态）
        states = [_cognition_state(_mention_level(m["mention_type"]),
                                   intents.get(m["evidence_id"], "other"))
                  for m in brand_mentions_list]
        dom_state = _dominant_state(states) if states else "no_cognition"
        # 热门因子（semantic 聚合 + 传播强度 = 去重 evidence 数）
        factor_prop: dict[str, dict] = {}
        for m in brand_mentions_list:
            if (m.get("factor") or "") == "__missing__":
                continue
            cls = _classify(m.get("factor") or "")
            sem = cls["semantic"]
            fp = factor_prop.setdefault(sem, {"semantic": sem, "dimension": cls["dimension"], "propagation": 0})
            fp["propagation"] += 1
        brand_overviews.append(
            {
                "brand": brand,
                "is_self": total_brand_stats[brand]["is_self"],
                "cognition_state": dom_state,
                "cognition_state_label": COGNITION_STATE_LABELS.get(dom_state, dom_state),
                "total_mention_evidence": levels["mention"],
                "recommended_evidence": levels["recommended"],
                "mention_sample": levels["mention"],  # 样本量（公平分母标注）
                "recommended_sample": levels["recommended"],
                "exposure_rate": round(levels["mention"] / all_ev * 100, 1) if all_ev else 0.0,
                "recommendation_rate": round(levels["recommended"] / all_ev * 100, 1) if all_ev else 0.0,
                # 提及内推荐率（GPT 评审 D2："被提及≠被推荐"——AI 知道你但不主动选你）
                "recommend_in_mention": round(levels["recommended"] / levels["mention"] * 100, 1) if levels["mention"] else 0.0,
                "factors": sorted(factor_prop.values(), key=lambda x: -x["propagation"]),
                "semantic_factors": [f["semantic"] for f in sorted(factor_prop.values(), key=lambda x: -x["propagation"])],
            }
        )

    return {
        "company": company,
        "subject": subject,
        "total_evidence": all_ev,
        "dimensions": _KNOWN_DIMENSIONS,
        "matrix": matrix_rows,
        "brands": brand_overviews,
        "cognition_levels": COGNITION_LEVEL_ORDER,
        "min_level": min_level,
        "sample_note": _sample_note(all_ev),
    }


def _dominant_state(states: list[str]) -> str:
    """取最高优先级认知状态。"""
    order = ["strong_positive", "weak_positive", "neutral",
             "weak_negative", "strong_negative", "no_cognition", "wrong"]
    for s in order:
        if s in states:
            return s
    return "no_cognition"


def _sample_note(total: int) -> dict:
    """样本量与可信度标注。"""
    if total >= 50:
        level, note = "高", "结论可靠"
    elif total >= 20:
        level, note = "中", "基本可靠，部分结论可能随样本增加而调整"
    elif total >= 5:
        level, note = "低", f"样本不足（{total} 条），建议 ≥20 条后结论可靠"
    else:
        level, note = "极低", "数据严重不足，当前展示仅供参考"
    return {"total": total, "reliability": level, "note": note}


# ══════════════════════════════════════════════════════════════
# 阶段 2：GEO Action Score + 证据链
# ══════════════════════════════════════════════════════════════

_LEVEL_VALUE = {k: i for i, k in enumerate(COGNITION_LEVEL_ORDER)}  # mention=0 ... trust=5

# 具体证据信号：数字/百分比/具体行业/认证（判断证据强度）
_EVIDENCE_STRONG = re.compile(r"(\d+%|¥|￥|\d+年|\d+家|3C|汽车|钢铁|化工|认证|白皮书|专利|案例|部署|落地|私有化)")


def _dimension_stats(c: dict) -> dict[str, dict]:
    """从 compare 结果提取每维度的聚合统计（我方 vs 竞品）。"""
    out: dict[str, dict] = {}
    for row in c["matrix"]:
        dim = row["dimension"]
        self_lv = -1
        comp_levels: list[tuple[str, int]] = []  # (brand, level_value)
        self_quotes: list[str] = []
        comp_quotes: list[dict] = []
        self_factors: set[str] = set()
        comp_factors: set[str] = set()
        for brand, s in row["subjects"].items():
            lv = max(
                (_LEVEL_VALUE[l] for l in COGNITION_LEVEL_ORDER if s["levels"].get(l, 0) > 0),
                default=-1,
            )
            if s["is_self"]:
                self_lv = lv
                self_quotes = [q["quote"] for q in s.get("quotes") or []]
                self_factors |= {q["semantic"] for q in s.get("quotes") or []}
            else:
                comp_levels.append((brand, lv))
                comp_quotes.extend(s.get("quotes") or [])
                comp_factors |= {q["semantic"] for q in s.get("quotes") or []}
        comp_quotes = comp_quotes[:5]
        out[dim] = {
            "dimension": dim,
            "self_level": self_lv,
            "comp_levels": comp_levels,
            "comp_max_level": max((lv for _, lv in comp_levels), default=-1),
            "self_quotes": self_quotes,
            "comp_quotes": comp_quotes,
            "self_factors": sorted(self_factors),
            "comp_factors": sorted(comp_factors),
        }
    return out


def strategies(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str = DEFAULT_TENANT,
    knowledge_probe: bool = True,
) -> dict:
    """内容策略（GEO Action Score，纯规则无 LLM）。

    Score = 用户需求权重 × 认知差距 × 可改变性 × 证据强度 × 竞争重要性

    - 用户需求权重(0-10)：该维度总提及 / 全维度提及（用户问题围绕的维度）
    - 认知差距(0-10)：竞品最高认知层级 − 我方层级（无认知=10 差距最大）
    - 可改变性(0-1)：我方有该维度素材 0.8 / 企业知识库有对应能力 1.0 / 否则 0.5
    - 证据强度(0-1)：竞品原话含具体证据（数字/案例/认证）1.0，否则 0.5
    - 竞争重要性(0-10)：竞品在该维度的提及占竞品总提及比例
    """
    c = compare(company=company, days=days, source_type=source_type, tenant=tenant)
    stats = _dimension_stats(c)
    if not stats:
        return {"company": company, "strategies": [], "sample_note": c["sample_note"]}

    total_dim_mentions = sum(
        (s["comp_max_level"] + 1) + (s["self_level"] + 1)
        for s in stats.values()
        if s["comp_max_level"] >= 0 or s["self_level"] >= 0
    ) or 1
    total_comp_mentions = sum(
        max(s["comp_max_level"] + 1, 0) for s in stats.values()
    ) or 1

    # 企业知识库对照（可改变性：我方是否有能力素材）——每维度查一次
    knowledge_has: dict[str, bool | None] = {}
    if knowledge_probe:
        import asyncio

        from services.intelligence.reasoning import _knowledge_has as kh

        async def _probe_all():
            for dim in stats:
                knowledge_has[dim] = await kh(dim)

        try:
            asyncio.run(_probe_all())
        except Exception:  # noqa: BLE001
            pass

    out: list[dict] = []
    for dim, s in stats.items():
        # 只处理竞品领先或我方无认知的维度
        if s["comp_max_level"] < 0:
            continue
        if s["self_level"] >= s["comp_max_level"]:
            continue  # 我方不落后 → 不生成策略

        # 用户需求权重
        dim_mentions = (s["comp_max_level"] + 1) + (s["self_level"] + 1)
        demand = round(dim_mentions / total_dim_mentions * 10, 1)

        # 认知差距（竞品层级 - 我方层级，无认知按 -1 算差距最大）
        gap_raw = s["comp_max_level"] - s["self_level"]
        gap = min(10.0, max(1.0, (gap_raw + 1) * 2.0))  # 封顶 10，最低 1

        # 可改变性
        if knowledge_has.get(dim):
            change = 1.0
        elif s["self_quotes"]:
            change = 0.8
        else:
            change = 0.5

        # 证据强度（竞品原话是否含具体证据）
        comp_quote_text = " ".join(q["quote"] for q in s["comp_quotes"])
        evidence = 1.0 if _EVIDENCE_STRONG.search(comp_quote_text) else 0.5

        # 竞争重要性（竞品在该维度的提及占比）
        comp_share = (s["comp_max_level"] + 1) / total_comp_mentions
        importance = min(10.0, comp_share * 20)

        score = round(demand * gap * change * evidence * importance, 1)

        # 建议选题模板（规则生成，基于差距类型，不编造 AI 会推荐你）
        if s["self_level"] < 0:
            topic_tpl = (
                f"建立「{dim}」认知：发布公开可引用的{dim}内容"
                "（技术方案/白皮书/案例），覆盖竞品占据的关键词"
            )
        elif gap_raw >= 3:
            topic_tpl = f"强化「{dim}」：现有素材升级为可引用的证据型内容（带数字/案例/认证）"
        else:
            topic_tpl = f"补齐「{dim}」差距：对标竞品叙事，补齐缺失因子"

        out.append(
            {
                "dimension": dim,
                "score": score,
                "priority": "P1" if score >= 60 else "P2" if score >= 30 else "P3",
                "formula": {
                    "demand": demand,
                    "gap": gap,
                    "changeability": change,
                    "evidence": evidence,
                    "importance": importance,
                },
                "self_level": s["self_level"],
                "self_level_label": COGNITION_STATE_LABELS.get(
                    _state_from_level(s["self_level"]), "无认知"
                ),
                "competitor_leader": s["comp_levels"][0][0] if s["comp_levels"] else "",
                "comp_quotes": [
                    {"quote": q["quote"], "brand": q.get("brand") or "", "factor": q["factor"], "semantic": q["semantic"]}
                    for q in s["comp_quotes"]
                ][:3],
                "comp_factors": s["comp_factors"],
                "self_factors": s["self_factors"],
                "topic": topic_tpl,
                "keywords": (s["comp_factors"] + s["self_factors"])[:10],
                "evidence_note": "竞品原话含具体证据（数字/案例/认证）" if evidence == 1.0 else "竞品原话暂无量化证据，需自行验证",
            }
        )

    out.sort(key=lambda x: -x["score"])
    return {
        "company": company,
        "strategies": out,
        "sample_note": c["sample_note"],
        "score_formula": "用户需求 × 认知差距 × 可改变性 × 证据强度 × 竞争重要性",
    }


def gap_analysis(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str = DEFAULT_TENANT,
    knowledge_probe: bool = True,
) -> dict:
    """知识缺口两种分离（方案 V2 §八）：

    - Knowledge Gap（内部）：竞品领先维度 + 企业知识库无此能力条目 →
      需人工确认是「补齐能力」还是「放弃此维度」（AI 无法知道没有记录的能力）
    - Evidence/GEO Gap（外部）：能力已在 企业知识库（内部知道）+ 外部无公开证据 →
      AI 仍不知道 → 发内容/案例/认证建立公开证据

    诚实红线：不编造"真实能力"——Knowledge Gap 一律标注"需人工确认"。
    """
    c = compare(company=company, days=days, source_type=source_type, tenant=tenant)
    stats = _dimension_stats(c)

    knowledge_has: dict[str, bool | None] = {}
    if knowledge_probe:
        import asyncio

        from services.intelligence.reasoning import _knowledge_has as kh

        async def _probe_all():
            for dim in stats:
                knowledge_has[dim] = await kh(dim)

        try:
            asyncio.run(_probe_all())
        except Exception:  # noqa: BLE001
            pass

    knowledge_gaps: list[dict] = []
    evidence_gaps: list[dict] = []
    for dim, s in stats.items():
        if s["comp_max_level"] < 0:
            continue
        if s["self_level"] >= s["comp_max_level"]:
            continue
        comp_factors = s["comp_factors"]
        leader = s["comp_levels"][0][0] if s["comp_levels"] else ""
        item = {
            "dimension": dim,
            "competitor_leader": leader,
            "comp_factors": comp_factors,
            "comp_quotes": [
                {"quote": q["quote"], "brand": q.get("brand") or ""}
                for q in s["comp_quotes"]
            ][:2],
        }
        if knowledge_has.get(dim):
            item["action"] = "发内容：能力已在知识库，补齐外部公开证据（技术文档/白皮书/案例/认证）"
            item["gap_type"] = "evidence_gap"
            evidence_gaps.append(item)
        else:
            item["action"] = "人工确认：知识库无此维度能力条目——补齐能力 or 放弃此维度"
            item["gap_type"] = "knowledge_gap"
            knowledge_gaps.append(item)

    return {
        "company": company,
        "knowledge_gaps": knowledge_gaps,
        "evidence_gaps": evidence_gaps,
        "sample_note": c["sample_note"],
        "note": "Knowledge Gap=能力无记录（补知识库或放弃）；Evidence Gap=能力有记录但外部无证据（发内容）",
    }


def factor_gaps(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str = DEFAULT_TENANT,
) -> dict:
    """因子级左右对比（低维度，海尔冰箱例子：竞品优点 vs 我方缺点）。

    - left（竞品有·我方无）：AI 回答里夸了竞品、没提我方的因子——要补的优点
    - right（我方有·竞品无）：AI 只夸了我方、没提竞品的因子——我方优势，保持/强化
    - both（双方都有）：同因子双方都被提——竞争焦点
    每个因子带原话证据 + 传播强度，可下钻到证据链。
    """
    c = compare(company=company, days=days, source_type=source_type, tenant=tenant)
    left: list[dict] = []
    right: list[dict] = []
    both: list[dict] = []

    # semantic factor → {self: [mentions], comps: {brand: [mentions]}}
    factor_map: dict[str, dict] = {}
    risk_notes: list[dict] = []  # awareness 场景提到我方的因子（AI 风险提示，非推荐）
    for row in c["matrix"]:
        for brand, s in (row.get("subjects") or {}).items():
            is_self = s["is_self"]
            for q in s.get("quotes") or []:
                sem = q.get("semantic") or q.get("factor") or ""
                intent = q.get("intent") or ""
                if not sem or sem == "__missing__":
                    continue
                if is_self and intent not in ("recommendation", "comparison", "trust"):
                    # 我方在非推荐场景的提及（审查建议/风险提示）——单列，不算"优势"
                    risk_notes.append(
                        {"factor": sem, "dimension": row["dimension"],
                         "quote": q.get("quote") or "", "mention_type": q.get("mention_type") or "",
                         "intent": intent}
                    )
                    continue
                fm = factor_map.setdefault(sem, {"dimension": row["dimension"], "self": [], "comps": {}})
                entry = {"brand": brand, "quote": q.get("quote") or "", "mention_type": q.get("mention_type") or "",
                         "intent": intent, "evidence_id": q.get("evidence_id") or ""}
                if is_self:
                    fm["self"].append(entry)
                else:
                    fm["comps"].setdefault(brand, []).append(entry)

    for sem, fm in factor_map.items():
        dim = fm["dimension"]
        self_n = len(fm["self"])
        comps_n = sum(len(v) for v in fm["comps"].values())
        top_comp = max(fm["comps"], key=lambda b: len(fm["comps"][b])) if fm["comps"] else ""
        item = {
            "factor": sem,
            "dimension": dim,
            "self_mentions": self_n,
            "competitor_mentions": comps_n,
            "competitor_leader": top_comp,
            "quotes": [q for lst in fm["comps"].values() for q in lst][:3],
            "self_quotes": fm["self"][:2],
        }
        if self_n == 0 and comps_n > 0:
            # 竞品有·我方无 → 要补的优点（left）
            item["missing_note"] = f"AI 回答中未见我方在该因子的提及（{top_comp} 被提 {comps_n} 次）"
            left.append(item)
        elif self_n > 0 and comps_n == 0:
            # 我方有·竞品无 → 我方优势
            right.append(item)
        elif self_n > 0 and comps_n > 0:
            both.append(item)

    left.sort(key=lambda x: -x["competitor_mentions"])
    right.sort(key=lambda x: -x["self_mentions"])
    both.sort(key=lambda x: -(x["self_mentions"] + x["competitor_mentions"]))
    # risk_notes 去重（同 factor 只留一条代表性原话）
    seen_risk: set[str] = set()
    risk_out: list[dict] = []
    for rn in risk_notes:
        if rn["factor"] in seen_risk:
            continue
        seen_risk.add(rn["factor"])
        risk_out.append(rn)
    return {
        "company": company,
        "left": left,
        "right": right,
        "both": both,
        "risk_notes": risk_out,
        "sample_note": c["sample_note"],
        "note": "left=竞品有·我方无（要补）；right=我方有·竞品无（优势）；both=双方竞争焦点；risk_notes=AI 对我方的风险提示（非推荐场景，可转为信任建设素材）",
    }


def humanize(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str = DEFAULT_TENANT,
) -> dict:
    """商业化翻译层：把 compare/strategies/factor-gaps 翻译成老板能看的人话。

    输出（纯规则生成，全部引用真实数据，不编造）：
    - headline：一句话结论（最扎心的那个事实）
    - metrics：三数字（曝光率/推荐率/落后能力点）
    - left/right：左右列人话（竞品有·我没有 / 我有的·竞品没有）
    - actions：行动清单人话（优先级 + 干什么 + 为什么）
    - risk_notes：AI 风险提示（可转信任建设素材）
    """
    c = compare(company=company, days=days, source_type=source_type, tenant=tenant)
    s = strategies(company=company, days=days, source_type=source_type, tenant=tenant, knowledge_probe=False)
    f = factor_gaps(company=company, days=days, source_type=source_type, tenant=tenant)

    # 我方品牌（取 is_self）
    self_b = next((b for b in c.get("brands") or [] if b["is_self"]), None)
    exposure = (self_b or {}).get("exposure_rate", 0.0)
    recommend = (self_b or {}).get("recommendation_rate", 0.0)
    # 2026-09-21 口径修正（Owner：「输出正常但不正确」）：`all_ev = 0` 时
    # exposure_rate 落在 0.0 是「分母没有」，不是「AI 没提到我们」。旧实现直接走
    # `elif exposure == 0` 分支，页面就会断言一句没发生过的结论：
    # 「AI 回答里还没提到过你」——而监测里明明 6/17 条回答提到了我方。
    sample_total = int((c.get("sample_note") or {}).get("total") or 0)
    left = f.get("left") or []
    risk = f.get("risk_notes") or []
    strategies_list = s.get("strategies") or []

    # ── ① 一句话结论（按优先级选最扎心的真实事实）──
    headline: dict = {"main": "", "sub": "", "tone": "danger"}
    if sample_total == 0:
        headline = {
            "main": "还没有可判断的解析样本",
            "sub": "先把监测回答做一轮解析，认知洞察才有依据；样本为 0 不代表 AI 没提到你",
            "tone": "warning",
        }
    elif len(left) > 0 and recommend == 0:
        top = left[0]
        headline = {
            "main": f"推荐/对比类回答中，我方有 {len(left)} 个表达因子未出现",
            "sub": f"样本中「{top['factor']}」由 {top['competitor_leader']} 出现 {top['competitor_mentions']} 次，我方 0 次；这是模型抽取结果，需结合原文验证",
            "tone": "danger",
        }
    elif exposure == 0:
        headline = {
            "main": "AI 回答里还没提到过你",
            "sub": "先让 AI 知道你：发内容建立曝光，再看差距",
            "tone": "warning",
        }
    elif len(risk) > 0:
        r0 = risk[0]
        headline = {
            "main": f"回答中出现与「{r0['factor']}」相关的风险提示",
            "sub": f"AI 原话：{r0['quote'][:50]}… 可评估是否需要补充合规、安全或解释材料",
            "tone": "ok",
        }
    elif len(left) > 0:
        headline = {
            "main": f"发现 {len(left)} 个待验证的表达差异点",
            "sub": f"竞品回答中出现而我方未出现：{left[0]['factor']}、{left[1]['factor'] if len(left) > 1 else left[0]['factor']}",
            "tone": "warning",
        }
    else:
        headline = {"main": "当前样本未发现明显表达差异", "sub": "继续积累监测样本，避免把暂未发现理解为没有差异", "tone": "ok"}

    # ── ② 三数字 ──
    metrics = {
        # 0 样本时给 null（前端显示「—」）：0% 会被读成「回答里一次都没出现」。
        "exposure_rate": None if sample_total == 0 else exposure,
        "recommendation_rate": None if sample_total == 0 else recommend,
        "gap_count": len(left),
        "gap_dimensions": sorted({x["dimension"] for x in left}),
    }

    # ── ③ 行动人话 ──
    actions = []
    for st in strategies_list:
        actions.append(
            {
                "priority": st["priority"],
                "score": st["score"],
                "what": st["topic"],
                "why": f"「{st['dimension']}」样本中，{st['competitor_leader']} 出现推荐性表达，而我方未出现",
                "keywords": st["keywords"],
            }
        )

    return {
        "company": company,
        "headline": headline,
        "metrics": metrics,
        "left": [
            {
                "factor": x["factor"],
                "dimension": x["dimension"],
                "competitor": x["competitor_leader"],
                "count": x["competitor_mentions"],
                "quote": (x["quotes"] or [{}])[0].get("quote", ""),
            }
            for x in left[:10]
        ],
        "right": [
            {"factor": x["factor"], "dimension": x["dimension"], "count": x["self_mentions"]}
            for x in (f.get("right") or [])[:6]
        ],
        "risk_notes": risk[:5],
        "actions": actions[:5],
        "sample_note": c["sample_note"],
    }


def _state_from_level(level_value: int) -> str:
    if level_value >= _LEVEL_VALUE["reason"]:
        return "strong_positive"
    if level_value >= _LEVEL_VALUE["mention"]:
        return "weak_positive"
    return "no_cognition"


def evidence_chain(
    factor: str,
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str = DEFAULT_TENANT,
    limit: int = 10,
) -> dict:
    """证据链：某因子被 AI 提到的所有原话 + 传播强度 + 关联因子。

    - 传播强度 = 去重 evidence 数（多少条回答提到该因子）
    - 来源 = 每条 evidence 的平台/引擎 + 时间
    - 关联因子 = 同一维度下的其他因子
    """
    since_dt = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    ev_ids = aggregator._succeeded_evidence_ids(since_dt, company, source_type, tenant)
    mentions = aggregator._load_mentions(ev_ids, tenant)

    cls = _classify(factor)
    matched = [
        m for m in mentions
        if (m.get("factor") or "") == factor
        or (m.get("factor") or "") == cls["semantic"]
    ]
    # 也把语义相同的归入
    if not matched:
        matched = [m for m in mentions if _classify(m.get("factor") or "")["semantic"] == cls["semantic"]]

    ev_ids_set = {m["evidence_id"] for m in matched}

    # 来源信息（从 evidence 表取 platform + observed_at）
    sources: list[dict] = []
    for m in matched[:limit]:
        ev = repo.get_evidence(m["evidence_id"])
        sources.append(
            {
                "evidence_id": m["evidence_id"],
                "platform": (ev or {}).get("platform") or "unknown",
                "observed_at": str((ev or {}).get("observed_at") or "")[:19],
                "mention_type": m["mention_type"],
                "intent": m.get("intent") or "",
                "quote": m.get("evidence_quote") or "",
                "brand": m.get("brand_name") or "",
            }
        )

    # 关联因子：同维度下的其他 factor
    related: dict[str, int] = {}
    for m in mentions:
        mc = _classify(m.get("factor") or "")
        if mc["dimension"] == cls["dimension"] and (m.get("factor") or "") != factor:
            sem = mc["semantic"]
            related[sem] = related.get(sem, 0) + 1

    return {
        "factor": factor,
        "semantic": cls["semantic"],
        "dimension": cls["dimension"],
        "propagation": len(ev_ids_set),  # 传播强度：多少条回答提到
        "sources": sources,
        "related_factors": [
            {"factor": f, "mentions": n} for f, n in sorted(related.items(), key=lambda kv: -kv[1])[:8]
        ],
    }
