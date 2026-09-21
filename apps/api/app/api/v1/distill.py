"""内容蒸馏（关键词 → 问题智能 → FAQ / 知识缺口 / 内容计划）

第一阶段：Question Intelligence（问题智能层）
- 关键词/种子词 → AI 生成客户问题池（intent/customer_stage/priority/related_entities）
- questions.json 累积去重存储（与报告页批量监测问题池共用思路，独立文件）

保留：关键词挖掘（mine）、FAQ 提炼（faq）。
"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import ok

router = APIRouter(prefix="/api/v1/distill")

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
DATA_DIR.mkdir(exist_ok=True)
QUESTIONS_FILE = DATA_DIR / "geo_questions.json"

_INTENTS = ("认知", "对比", "采购", "信任", "使用")
_STAGES = ("awareness", "consideration", "decision", "retention")


class DistillIn(BaseModel):
    topic: str = ""
    keywords: list[str] = []  # 关键词模式（与 topic 二选一或叠加）
    count: int = 5


class QuestionsIn(BaseModel):
    seed_keywords: list[str] = []  # 种子词/行业关键词
    industry: str = ""  # 行业（可选，增强生成质量）
    count: int = 10


def _extract_json_array(text: str) -> list:
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return []


def _normalize_intent(value) -> str:
    for it in _INTENTS:
        if it in str(value):
            return it
    return "认知"


def _normalize_stage(value) -> str:
    v = str(value).strip().lower()
    for s in _STAGES:
        if s in v or v in s:
            return s
    return "awareness"


def _clamp_priority(value, default: int = 50) -> int:
    try:
        p = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, p))


def _normalize_question(q: str) -> str:
    """问题归一化：去标点/空白/语气词，用于去重比较"""
    return re.sub(r"[\s，。？！、；：""''（）!?,.;:'\"()]+", "", q)


def _load_questions() -> list[dict]:
    from app.services.store import get_store

    return get_store().load("questions")


async def _auto_keywords() -> list[str]:
    """从 Kernel 知识库自动提取企业关键词（产品/服务实体）

    用户要求：一切从知识库找，不预设。种子词为空时用企业真实产品/服务实体。
    """
    from adapters.eios import get_entities

    _BLOCK = (
        "官网", "诊断", "模板", "报告", "文档", "目录", "制度", "流程", "预算",
        "计划", "会议", "通知", "人员", "岗位", "案例包装边界", "交付SOP",
    )
    _COMPANY = ("有限公司", "集团", "股份", "有限责任公司", "工作室")
    _KEEP = ("系统", "服务", "方案", "产品", "包", "模型", "平台", "工具")
    try:
        ents = await get_entities()
    except Exception:  # noqa: BLE001
        return []
    keywords: list[str] = []
    seen = set()
    for e in ents or []:
        name = e.get("canonical_name") or e.get("name") or ""
        if not name or any(b in name for b in _BLOCK) or any(c in name for c in _COMPANY):
            continue
        if not any(k in name for k in _KEEP):
            continue
        clean = re.sub(r"[Vv]\d+(\.\d+)*", "", name).strip(" （）()·-_ ")
        if not clean or clean in seen:
            continue
        seen.add(clean)
        keywords.append(clean)
        if len(keywords) >= 6:
            break
    return keywords


def _save_questions(items: list[dict]) -> None:
    from app.services.store import get_store

    get_store().save("questions", items)


@router.post("/questions")
async def gen_questions(payload: QuestionsIn):
    """Question Intelligence：种子词 → 客户问题池（意图/阶段/优先级/关联实体）

    累积去重：question 相同（含已存在）不重复入库。
    priority 由 AI 综合打分（0-100），第一版展示排序用。
    """
    from adapters.llm import chat, LLMNotConfiguredError, LLMError

    seeds = [k.strip() for k in payload.seed_keywords if k and k.strip()]
    auto_source = False
    if not seeds:
        seeds = await _auto_keywords()
        auto_source = bool(seeds)
    if not seeds:
        return ok({"added": [], "total": 0, "error": "请提供种子词/行业关键词（知识库暂无可提取的企业关键词）"})

    industry_hint = f"行业：{payload.industry}。" if payload.industry else ""
    source_note = "（已从企业知识库自动提取）" if auto_source else ""
    prompt = (
        f"你是 GEO 问题分析师。{source_note}围绕{industry_hint}客户最常搜索/询问 AI 的关键词「{'、'.join(seeds)}」，"
        f"生成 {payload.count} 个客户真实会问的问题（中文，贴近真实搜索场景，如'xx多少钱''xx哪家好''xx安全吗'）。\n"
        "注意：客户询问的 AI 一律指国内主流 AI 助手（DeepSeek、豆包、文心一言、通义千问、Kimi、智谱清言），严禁出现国外大模型名称。\n"
        "每个问题标注：\n"
        "- intent：客户意图，只能是 认知/对比/采购/信任/使用 之一（认知=了解是什么，对比=比较选择，采购=准备购买，信任=验证可靠性，使用=使用维护）\n"
        "- customer_stage：客户阶段，只能是 awareness/consideration/decision/retention 之一\n"
        "- priority：该问题对企业的价值优先级，0-100 整数（综合考虑搜索频率、离成交距离、竞争程度）\n"
        "- related_entities：问题涉及的产品/实体名（字符串数组，从关键词和企业角度）\n"
        '严格按 JSON 数组输出，不要其他内容：\n'
        '[{"question": "储能电池寿命多久", "keyword": "储能电池", "intent": "使用", "customer_stage": "retention", "priority": 85, "related_entities": ["储能电池"]}]'
    )
    try:
        text = await chat(prompt, max_tokens=1600)
    except LLMNotConfiguredError as e:
        return ok({"added": [], "total": len(_load_questions()), "error": str(e)})
    except LLMError as e:
        return ok({"added": [], "total": len(_load_questions()), "error": e.message})

    raw = _extract_json_array(text)[: payload.count]
    items = _load_questions()
    existing_norm = {_normalize_question(str(q.get("question") or "")) for q in items}
    # 同关键词限流（AI 措辞漂移无法完全精确去重，防止同一主题无限膨胀）
    keyword_count = {}
    for q in items:
        kw = q.get("keyword") or ""
        keyword_count[kw] = keyword_count.get(kw, 0) + 1
    MAX_PER_KEYWORD = 20
    added = []
    now = datetime.now(timezone.utc).isoformat()
    for r in raw:
        q = str(r.get("question", "")).strip()
        if not q:
            continue
        if _normalize_question(q) in existing_norm:
            continue
        kw = str(r.get("keyword") or seeds[0]).strip() or seeds[0]
        if keyword_count.get(kw, 0) >= MAX_PER_KEYWORD:
            continue
        keyword_count[kw] = keyword_count.get(kw, 0) + 1
        entry = {
            "id": f"q_{uuid.uuid4().hex[:10]}",
            "question": q,
            "keyword": kw,
            "intent": _normalize_intent(r.get("intent")),
            "customer_stage": _normalize_stage(r.get("customer_stage")),
            "priority": _clamp_priority(r.get("priority"), 50),
            "related_entities": [str(e).strip() for e in (r.get("related_entities") or []) if str(e).strip()][:6],
            "source": "ai_analyze",
            "evidence_level": "C",  # 拍板证据等级：AI 生成 → C（无外部/企业记录 ID，待验证）
            # V1.1 数据可信字段：来源枚举 ai_generated / monitor_verified / user_input / knowledge_extracted
            "source_type": "ai_generated",
            "confidence": 0.65,  # AI 生成默认置信度（规则常量，非精判）
            "validated": False,  # 是否已监测验证
            "monitor_count": 0,  # 监测过的回答数（真实统计）
            "created_at": now,
            "status": "pending",
        }
        items.append(entry)
        added.append(entry)
        existing_norm.add(_normalize_question(q))
    _save_questions(items)
    return ok({"added": added, "total": len(items), "error": None, "auto_source": auto_source, "source_keywords": seeds if auto_source else []})


# 审计 B1：``evidence_level`` 的取值是知识判定结果（grounded / partial / none）。
# 一个问题是「grounded」= AI 回答这类问题时企业资料够用。**没判定过的问题不能被当成 0%**，
# 所以漏斗按「已判定的问题」算比例，一个都没判定时给 None（诚实空态），不给 0%。
_LEVELS = ("grounded", "partial", "none")
_STAGE_CN = {"awareness": "认知", "consideration": "比较", "decision": "决策", "retention": "留存", "purchase": "采购", "trust": "信任"}


def _funnel_rows(questions: list[dict]) -> list[dict]:
    """问题池 → 认知阶段漏斗（每阶段：问题数 / 已判定数 / 企业覆盖%）"""
    stages: dict[str, dict] = {}
    for q in questions:
        raw = (q.get("customer_stage") or "").strip()
        st = _STAGE_CN.get(raw.lower()) if raw else "其他"
        g = stages.setdefault(st, {"stage": st, "question_count": 0, "grounded_count": 0, "judged_count": 0})
        g["question_count"] += 1
        lv = q.get("evidence_level")
        if lv in _LEVELS:
            g["judged_count"] += 1
            if lv == "grounded":
                g["grounded_count"] += 1
    rows = []
    for g in stages.values():
        judged = g.pop("judged_count")
        covered = g.pop("grounded_count")
        g["judged_count"] = judged
        g["coverage_pct"] = round(covered / judged * 100) if judged else None
        rows.append(g)
    order = {"认知": 0, "比较": 1, "信任": 2, "采购": 3}
    rows.sort(key=lambda x: (order.get(x["stage"], 99), x["stage"]))
    return rows


@router.get("/cognition-map")
async def cognition_map():
    """蒸馏中心·客户认知地图：问题池按决策阶段聚合 + 企业覆盖

    企业覆盖 = 该阶段问题中 AI 回答有企业依据（evidence_level=grounded）的比例，
    纯规则聚合零调用；无数据阶段标 null（诚实空态）。
    """
    qs = _load_questions()
    rows = _funnel_rows(qs)
    return ok({
        "stages": rows,
        "note": "企业覆盖 = 该阶段**已做过知识判定**的问题里有企业依据（grounded）的比例；未判定为 null，不按 0% 计（规则估算）",
    })


@router.get("/questions")
async def list_questions(status: str | None = None, limit: int = 100, validated: str | None = None, stage: str | None = None, priority: str | None = None):
    items = _load_questions()
    if status:
        items = [q for q in items if q.get("status") == status]
    if validated == "true":
        items = [q for q in items if q.get("monitor_count", 0) > 0]
    elif validated == "false":
        items = [q for q in items if q.get("monitor_count", 0) == 0]
    if stage:
        items = [q for q in items if (q.get("customer_stage") or "").lower() == stage.lower()]
    if priority == "high":
        items = [q for q in items if (q.get("priority") or 0) >= 70]
    items = items[-limit:][::-1]

    # D3（0.4）：问题评分（规则估算，非 LLM 精判）——一次读历史算频率/可见度
    hist = []
    try:
        from app.services.store import get_store

        hist = get_store().load("monitor_history")
    except Exception:  # noqa: BLE001
        hist = []
    q_count: dict[str, int] = {}       # 这个问法在历史批次里被问到的次数
    q_answered: dict[str, int] = {}    # 真作答的回答条数（没配 key / 失败的引擎不算）
    q_mentioned: dict[str, int] = {}
    for h in hist:
        for q in h.get("questions") or []:
            qt = q.get("question") or q.get("query") or ""
            if not qt:
                continue
            q_count[qt] = q_count.get(qt, 0) + 1
            for ed in q.get("engine_detail") or []:
                # 2026-09-21 口径修正（Owner：「输出正常但不正确」）：
                # 旧实现把「批次号」当回答数、把「引擎条数」当分子 —— monitor_count 写着
                # 「真实监测回答数」其实是批次数；ai_visibility = 引擎条数 ÷ 批次数，
                # 一个问法在 2 个批次里被 6 个引擎提到就是 300%。没作答的引擎同样进了分母。
                if ed.get("mentioned") is None:
                    continue
                q_answered[qt] = q_answered.get(qt, 0) + 1
                if ed.get("mentioned"):
                    q_mentioned[qt] = q_mentioned.get(qt, 0) + 1
    # evidence_level → 企业覆盖（grounded 80 / partial 50 / none 20 / 未判定 null）
    _cov_map = {"grounded": 80, "partial": 50, "none": 20}
    for q in items:
        qt = q.get("question") or ""
        freq = q_count.get(qt, 0)          # 被问到的批次次数
        answered = q_answered.get(qt, 0)   # 真作答条数
        vis = round(q_mentioned.get(qt, 0) / answered * 100) if answered else None
        cov = _cov_map.get(q.get("evidence_level"))
        # 审计 B2：attention 以前兜底 50 —— 数据缺了就写 0 分是编造。没填 priority 就是 None。
        att = q.get("priority")
        opp = round((100 - cov) * att / 100) if (cov is not None and att is not None) else None
        q["attention"] = att
        q["ai_visibility"] = vis
        q["coverage"] = cov
        q["opportunity"] = opp
        q["frequency"] = freq
        q["score_source"] = "rule"
        # V1.1 可信字段：monitor_count = 真实监测回答条数（没作答的引擎不计）；
        # validated = 这个问法被真实监测过（不是「答案已验证」）；frequency = 被问到的批次次数。
        q["monitor_count"] = answered
        q["validated"] = freq > 0
        if freq > 0:
            q["source_type"] = "monitor_verified"
        else:
            q.setdefault("source_type", "ai_generated")
        q.setdefault("confidence", 0.65)
    return ok({"items": items, "total": len(items), "note": "评分为规则估算（优先级/监测词频/Kernel 依据），非 LLM 精判；monitor_count = 真实监测回答条数（没作答的引擎不计入），frequency = 该问法被问到的批次次数，ai_visibility = 真作答条数里被提及占比，validated = 这个问题被真实监测过（不是「答案已验证」）"})


@router.delete("/questions/{qid}")
async def delete_question(qid: str):
    items = _load_questions()
    target = next((q for q in items if q.get("id") == qid), None)
    if target is None:
        return ok({"removed": 0, "total": len(items), "error": "问题不存在"})
    qtext = str(target.get("question") or "").strip()
    kept = [q for q in items if q.get("id") != qid]
    removed = len(items) - len(kept)
    _save_questions(kept)
    # 审计 B12：删除问题要一并清理引用它的数据，否则计划/缺口里会留下指向已删问题的
    # 悬空 target_question。缺口是按问题粒度的知识缺口记录，问题没了即失效 → 删除；
    # 内容计划是用户的生产任务，不连坐删除，只清掉悬空的问题引用（topic/subitem 自描述）。
    cleaned = {"gaps": 0, "plans": 0}
    if qtext:
        gaps = _load_gaps()
        kept_gaps = [g for g in gaps if str(g.get("question") or "").strip() != qtext]
        if len(kept_gaps) != len(gaps):
            _save_gaps(kept_gaps)
            cleaned["gaps"] = len(gaps) - len(kept_gaps)
        plans = _load_plans()
        touched = 0
        for p in plans:
            if str(p.get("target_question") or "").strip() == qtext:
                p["target_question"] = ""
                touched += 1
        if touched:
            _save_plans(plans)
            cleaned["plans"] = touched
    return ok({"removed": removed, "total": len(kept), "cleaned_refs": cleaned})


@router.get("/questions/{qid}/platforms")
async def question_platforms(qid: str):
    """P0：单个问题的 6 平台监测明细（对齐竞品"用户意图图"平台列）

    从监测 history 精确匹配问题文本（单次 check + 批量明细都算），
    聚合每引擎：mentioned / rank_est（估算）/ sentiment（规则）。
    无监测记录 → items 空数组（前端显示"未监测"，诚实）。
    """
    items = _load_questions()
    q = next((x for x in items if x.get("id") == qid), None)
    if not q:
        return ok({"error": "问题不存在", "items": []})
    question = q.get("question", "")

    from app.api.v1.monitor import _load_history

    history = _load_history()
    per_engine: dict[str, dict] = {}
    for h in history:
        # 单次 check
        if h.get("question") == question and not h.get("batch"):
            for er in h.get("engine_detail") or []:
                name = er.get("engine_name")
                if not name:
                    continue
                e = per_engine.setdefault(name, {"platform": name, "mentioned": 0, "configured": 0, "rank_ests": [], "sentiments": []})
                if er.get("mentioned") is not None:
                    e["configured"] += 1
                    if er.get("mentioned"):
                        e["mentioned"] += 1
                if er.get("rank_est") is not None:
                    e["rank_ests"].append(er["rank_est"])
                if er.get("sentiment"):
                    e["sentiments"].append(er["sentiment"])
        # 批量明细
        if h.get("batch"):
            for qi in h.get("questions") or []:
                if qi.get("question") != question:
                    continue
                for er in qi.get("engine_detail") or []:
                    name = er.get("engine_name")
                    if not name:
                        continue
                    e = per_engine.setdefault(name, {"platform": name, "mentioned": 0, "configured": 0, "rank_ests": [], "sentiments": []})
                    if er.get("mentioned") is not None:
                        e["configured"] += 1
                        if er.get("mentioned"):
                            e["mentioned"] += 1
                    if er.get("rank_est") is not None:
                        e["rank_ests"].append(er["rank_est"])
                    if er.get("sentiment"):
                        e["sentiments"].append(er["sentiment"])

    out = []
    for name, e in per_engine.items():
        ranks = e["rank_ests"]
        sents = e["sentiments"]
        pos = sum(1 for s in sents if s == "positive")
        neg = sum(1 for s in sents if s == "negative")
        neutral = sum(1 for s in sents if s == "neutral")
        out.append(
            {
                "platform": name,
                "mentioned": e["mentioned"],
                "configured": e["configured"],
                "recommend_pct": round(e["mentioned"] / e["configured"] * 100) if e["configured"] else 0,
                "rank_avg": round(sum(ranks) / len(ranks), 1) if ranks else None,
                "sentiment": {"positive": pos, "negative": neg, "neutral": neutral},
            }
        )
    # 平台顺序稳定：我方 6 引擎优先，其余按出现顺序
    order = {"DeepSeek": 0, "豆包": 1, "文心一言": 2, "通义千问": 3, "Kimi": 4, "智谱": 5}
    out.sort(key=lambda x: (order.get(x["platform"], 99), x["platform"]))
    return ok({"question": question, "items": out, "monitored": len(out) > 0})


# ── 保留：FAQ 提炼（faq） ─────────────────────────────────
@router.post("/faq")
async def faq(payload: DistillIn):
    """FAQ 提炼：主题/关键词 → 客户常问的问答对（带 Knowledge Grounding 三态）

    每个问题先查 Kernel：
    - 🟢 grounded（有企业依据）→ 基于知识库事实回答（不编造）
    - 🟡 partial（有相关但不足）→ 输出"知识库记录不明确"+ 建议补充，不冒充企业能力
    - 🔴 none（完全无依据）→ 输出"知识库暂无相关记录"+ 建议补充资料，禁止编造企业能力
    """
    from adapters.llm import chat, LLMNotConfiguredError, LLMError

    keywords = [k.strip() for k in payload.keywords if k and k.strip()]
    topic = payload.topic.strip()
    if not topic and not keywords:
        return ok({"topic": topic, "keywords": keywords, "items": [], "error": None})

    source = topic or "、".join(keywords[:5])
    keyword_hint = f"\n重点覆盖这些搜索词/问题词：{'、'.join(keywords)}" if keywords else ""
    # 第一步：只生成客户问题列表（不生成回答——回答必须过 Grounding）
    prompt = (
        f"你是 GEO 内容助手。围绕「{source}」{keyword_hint}，"
        f"生成 {payload.count} 个客户最常问的问题（只要问题，不要回答）。\n"
        '严格按以下 JSON 数组格式输出，不要输出其他内容：\n'
        '["问题1", "问题2", "问题3"]'
    )
    try:
        text = await chat(prompt, max_tokens=800)
    except LLMNotConfiguredError as e:
        return ok({"topic": topic, "keywords": keywords, "items": [], "error": str(e)})
    except LLMError as e:
        return ok({"topic": topic, "keywords": keywords, "items": [], "error": e.message})

    questions = _extract_json_array(text)[: payload.count]
    # 第二步：每个问题 Grounding（Kernel 检索，客观判定）
    items = []
    for q in questions:
        qtext = q if isinstance(q, str) else (q.get("q") or q.get("question") or "")
        if not qtext:
            continue
        kc = await _knowledge_check(qtext, keywords)
        level = kc["level"]
        if level == "grounded":
            refs_text = "\n".join(
                f"- {r['name']}（{r.get('predicate') or '属性'}：{r.get('value') or ''}）" for r in kc["refs"]
            )
            aprompt = (
                f"你是 GEO 内容助手。客户问：「{qtext}」。\n"
                f"企业知识库中已有以下相关内容（必须基于这些事实回答，不得编造任何企业能力）：\n{refs_text}\n"
                "生成 FAQ 回答：简洁准确，只陈述知识库中的事实，不补充未知能力。"
                '严格按 JSON 输出：{"a": "回答"}'
            )
            try:
                atext = await chat(aprompt, max_tokens=400)
            except LLMNotConfiguredError:
                # 审计 B12：LLMNotConfiguredError 不是 LLMError 的子类，
                # 只捕 LLMError 会让「模型未配置」冒成 500。这里降级为空回答（下面兜底文案）。
                atext = ""
            except LLMError:
                atext = ""
            m = re.search(r"\{[\s\S]*\}", atext or "")
            answer = ""
            if m:
                try:
                    answer = (json.loads(m.group(0)) or {}).get("a") or ""
                except Exception:  # noqa: BLE001
                    answer = ""
            if not answer:
                answer = "（企业知识库中已有相关内容，请查阅知识库详情。）"
            basis = "enterprise"
        elif level == "partial":
            # 有相关但不足：不冒充企业能力，提示补充
            answer = "企业知识库中仅有少量相关记录，暂不足以完整回答该问题。建议补充相关企业资料后再生成正式回答。"
            basis = "partial"
        else:
            answer = "当前企业知识库暂无该问题的相关记录，建议补充企业资料（如产品说明、技术文档、认证信息等）后再生成正式回答。"
            basis = "general"
        items.append({
            "q": qtext,
            "a": answer,
            "status": level,          # grounded / partial / none
            "basis": basis,
            "knowledge": {"level": level, "best_score": kc["best_score"], "refs": kc["refs"]},
        })
    return ok({"topic": topic, "keywords": keywords, "items": items, "error": None})


# ── 阶段 3：Kernel 知识匹配（已有/缺失判定，默认阈值 0.5） ──
def _infer_intent(question: str) -> str:
    """从问题文本规则推断意图（采购/信任/使用/对比/认知），供充分性检测定位信息要求。

    诚实：规则关键词映射，非 LLM 精判。命中即返回该类，未命中兜底"认知"。
    """
    q = question or ""
    pairs = [
        ("对比", ["区别", "对比", "差异", "哪家", "和.*比", "比较", "哪个好", "怎么选"]),
        ("信任", ["认证", "资质", "检测报告", "环保", "甲醛", "安全", "证书", "工厂", "自有", "代工", "代加工", "可信", "靠谱", "正规"]),
        ("使用", ["售后", "保修", "质保", "维修", "塌陷", "开线", "保养", "怎么用", "几年", "多久"]),
        ("采购", ["多少钱", "价格", "报价", "费用", "收费", "预算", "元", "量尺", "安装", "上门"]),
    ]
    import re as _re
    for intent, kws in pairs:
        for kw in kws:
            if _re.search(kw, q):
                return intent
    return "认知"


#: 问题里的疑问词/虚词：算「内容词」时要先去掉，否则「哪些/怎么」这类词会自己造出命中。
_QUESTION_STOPWORDS = (
    "是什么样的", "是什么", "是做什么的", "做什么", "怎么样", "怎样", "什么样", "哪些", "哪家", "哪个",
    "什么", "怎么", "多少", "如何", "是否", "有没有", "请问", "应该", "可以", "需要", "以及",
    "我们", "你们", "他们", "这个", "那个", "的话", "还是", "或者", "和", "与", "的", "吗", "呢", "吧",
)


def _content_bigrams(text: str) -> set[str]:
    """问题 → 内容词二元组（规则实现，不接模型）。

    中文没有空格，直接用整句找子串会「问什么都命中」；改用去疑问词后的二元组集合，
    和命中文本求交，交集大小才是「这段知识是不是在讲这件事」的度量。
    """
    import re as _re

    t = str(text or "")
    for w in _QUESTION_STOPWORDS:
        t = t.replace(w, "")
    t = _re.sub(r"[？?，,。.：:；;、（）()【】\[\]\s+]+", "", t)
    if len(t) < 2:
        return set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


async def _knowledge_check(question: str, entities: list[str] | None = None, intent: str | None = None) -> dict:
    """问题 → **企业知识库**（EIOS :8040）检索 → 企业是否已有相关知识

    2026-09-21 修（Owner：「什么知识缺口到底是不是本地知识库缺的」）：
    读的确实是本地企业知识库（`adapters.eios.search_knowledge`，只读、带出站票），
    但**相关性判定原来是错的**：只判「实体名是否出现在任一命中片段里」。企业知识库里
    几乎每张表都写着公司名，于是这一条恒为真 —— 实测：
      ·「今天天气怎么样？」→ PARTIAL（缺「产品介绍」）
      ·「全案定制在成都都有哪些公司在做？」→ COVERED
      ·「2026年国内AI知识库市场最新动态是什么？」→ COVERED（知识库不可能有未来市场动态）
      ·「GEO+知识库系统价格多少？」→ UNRELATED（知识库里明明有产品价格表）→ 反向漏判
    现在相关性 = **问题内容二元组与命中文本的交集 ≥ 2**（见 `_content_bigrams`），
    并且如实回报 `judge_basis`：判定本来要的是「主体+属性+值」事实三元组，而本机知识库
    返回的是**文档分块**（predicate=None、value=整张表文本）时标 `document_text`，
    让上层能如实说「这次只按文档文本推断，不是按事实三元组判定」。

    **待 Owner 复核**：这条判定语义改动过（原实现恒真），已按「修 bug」处理，未新增 Authority。
    """
    from adapters.eios import search_knowledge

    queries = [question] + [e for e in (entities or [])[:3] if e and e not in question]
    top: list[dict] = []
    seen = set()
    reachable = 0  # 成功到达 Kernel 的查询数（0 = Kernel 不可达，区别于「无知识」）
    for q in queries[:3]:
        try:
            res = await search_knowledge(q, top_k=5, include_candidates=False)
            reachable += 1
        except Exception:  # noqa: BLE001
            continue
        for h in (res.get("hits") or []):
            try:
                sc = float(h.get("score", 0))
            except (TypeError, ValueError):
                sc = 0.0
            name = h.get("canonical_name") or h.get("name") or ""
            key = (name, h.get("predicate"), h.get("value"))
            if not name or key in seen:
                continue
            seen.add(key)
            top.append({"score": round(sc, 2), "name": name, "predicate": h.get("predicate"), "value": h.get("value")})
    top.sort(key=lambda x: -x["score"])
    best = top[0] if top else {"score": 0.0, "name": "", "predicate": "", "value": ""}
    # 主体相关性（2026-09-21 重做，见函数 docstring）：
    # 命中文本里必须真的有这段知识在讲的问题（内容二元组交集 ≥ 2），
    # 而不是「实体名在表里出现过」——后者在企业知识库里恒为真。
    blob_all_hits = " ".join(f"{r.get('name') or ''}{r.get('predicate') or ''}{r.get('value') or ''}" for r in top)
    q_bigrams = _content_bigrams(question)
    overlap = {g for g in q_bigrams if g in blob_all_hits}
    related = len(overlap) >= 2
    # 判定依据如实交代：有 predicate 才是「主体+属性+值」三元组，否则只是文档文本
    judge_basis = "fact_triple" if any((r.get("predicate") or "").strip() for r in top) else "document_text"
    # ── 问题理解：意图 -> 信息要求维度（规则映射，诚实"规则分类"） ──
    eff_intent = intent or _infer_intent(question)
    _REQUIRED_BY_INTENT = {
        "认知": [{"dim": "产品介绍", "anchor": ["是什么", "做什么", "产品", "服务", "介绍", "主营"]}],
        "对比": [{"dim": "对比/差异信息", "anchor": ["区别", "对比", "差异", "哪家", "怎么选", "比较"]}],
        "采购": [{"dim": "价格体系", "anchor": ["价格", "多少钱", "报价", "费用", "收费", "预算", "元", "价格体系", "报价规则"]},
                  {"dim": "含配套服务", "anchor": ["量尺", "安装", "上门", "包括", "包含"]}],
        "信任": [{"dim": "资质/认证", "anchor": ["认证", "资质", "检测", "报告", "标配", "证书", "环保", "甲醛", "安全", "检测报告"]},
                  {"dim": "生产/工厂证明", "anchor": ["工厂", "自有", "代工", "代加工", "生产", "周期", "产线", "生产线"]}],
        "使用": [{"dim": "售后/保修", "anchor": ["售后", "保修", "质保", "维修", "塌陷", "开线", "处理", "几年", "多久"]},
                  {"dim": "使用/保养说明", "anchor": ["保养", "怎么用", "使用", "维护", "清洁"]}],
    }
    required = _REQUIRED_BY_INTENT.get(eff_intent, [{"dim": "产品介绍/详情", "anchor": ["产品", "介绍", "详情", "规格", "参数"]}])

    # ── 实质事实：pred/value 非空才是实质，实体名命中≠能回答 ──
    substantive = [r for r in top if bool((r.get('predicate') or '').strip()) or bool((r.get('value') or '').strip())]

    # ── 充分性判定：逐信息要求维度比对 refs，缺失维度为 PARTIAL/GAP 依据 ──
    blob_all = " ".join(f"{r.get('name') or ''}{r.get('predicate') or ''}{r.get('value') or ''}".lower() for r in substantive)
    missing = [req["dim"] for req in required if not any(a.lower() in blob_all for a in req["anchor"] if a)]

    # 4 级判定（2026-08-18）：COVERED / PARTIAL / GAP / UNRELATED
    subject_found = bool(best.get("name")) and related
    if not reachable:
        status = "UNRELATED"; missing = []   # Kernel 不可达，不可判定（防"宕机当缺知识"）
    elif subject_found and len(missing) == 0 and substantive:
        status = "COVERED"
    elif subject_found:
        status = "PARTIAL"                    # ← 企业知识库最常见：有主体但缺客户要的属性
    elif substantive:
        status = "UNRELATED"                  # 有实质命中，但主体相关性不足
    else:
        status = "GAP"                        # 主体找不到、也无实质事实 → 明确缺知识

    has = status == "COVERED"
    level = "grounded" if status == "COVERED" else ("partial" if status == "PARTIAL" else "none")

    return {
        "has_knowledge": has,
        "level": level,
        "status": status,
        "intent": eff_intent,
        "required_facts": [r["dim"] for r in required],
        "missing_dimensions": missing,
        "best_score": best["score"],
        "refs": top[:3],
        "kernel_down": reachable == 0,  # 知识库不可达（≠ 企业无知识）
        "judge_basis": judge_basis,     # fact_triple=按事实三元组判；document_text=只按文档文本判
        "matched_terms": sorted(overlap)[:6],  # 判定时真正命中的问题内容词（可复盘）
    }


# ── 阶段 2：FAQ 生成升级（带知识依据，禁止无依据自由生成） ──
class FaqUpgradedIn(BaseModel):
    question: str
    intent: str = ""
    related_entities: list[str] = []
    keywords: list[str] = []


@router.post("/faq/upgraded")
async def faq_upgraded(payload: FaqUpgradedIn):
    """FAQ 升级版：单问题 → 知识检查 → 基于企业知识回答（无依据标注通用）

    返回：q/a + intent + related_entities + knowledge(已有/缺失/引用) + basis(enterprise/general)
    """
    from adapters.llm import chat, LLMNotConfiguredError, LLMError

    question = payload.question.strip()
    if not question:
        return ok({"question": "", "error": "请提供问题"})
    kc = await _knowledge_check(question, payload.related_entities or payload.keywords)

    if kc["level"] == "grounded":
        refs_text = "\n".join(
            f"- {r['name']}（{r.get('predicate') or '属性'}：{r.get('value') or ''}）" for r in kc["refs"]
        )
        prompt = (
            f"你是 GEO 内容助手。客户问：「{question}」。\n"
            f"企业知识库中已有以下相关内容（必须基于这些事实回答，不得编造任何企业能力）：\n{refs_text}\n"
            "生成 FAQ 回答：简洁准确，只陈述知识库中的事实，不补充未知能力（不虚构加密方式、认证、SLA、团队规模等）。"
            '严格按 JSON 输出：{"q": "问题", "a": "回答"}'
        )
    elif kc["level"] == "partial":
        prompt = (
            f"你是 GEO 内容助手。客户问：「{question}」。\n"
            "企业知识库中仅有少量相关记录，不足以完整回答该问题。\n"
            "回答要求：明确说明「企业知识库暂未记录完整的相关资料」，并列出建议补充的资料方向；"
            "严禁以本企业名义陈述任何未在企业知识库中出现的能力（如具体加密算法、合规认证、SLA 承诺、数据存储位置、团队规模等）。"
            '严格按 JSON 输出：{"q": "问题", "a": "回答"}'
        )
    else:
        prompt = (
            f"你是 GEO 内容助手。客户问：「{question}」。\n"
            "企业知识库中**没有**与该问题直接相关的企业资料。\n"
            "回答要求：明确说明「当前企业知识库暂无该问题的相关记录」，并给出建议补充的资料方向（如产品说明、技术文档、认证信息等）；"
            "严禁以本企业名义陈述任何企业能力（包括但不限于：加密技术、安全认证、合规资质、SLA/赔偿承诺、团队规模、数据存储位置）——"
            "宁可只说「暂无记录」，也不许编造或套用行业模板冒充企业事实。"
            '严格按 JSON 输出：{"q": "问题", "a": "回答"}'
        )
    try:
        text = await chat(prompt, max_tokens=600)
    except LLMNotConfiguredError as e:
        return ok({"question": question, "error": str(e)})
    except LLMError as e:
        return ok({"question": question, "error": e.message})
    item = {}
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            item = json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            item = {}
    return ok({
        "q": item.get("q") or question,
        "a": item.get("a") or "",
        "intent": _normalize_intent(payload.intent),
        "related_entities": payload.related_entities,
        "knowledge": kc,
        "status": kc["level"],  # grounded / partial / none（可信度标签）
        "basis": "enterprise" if kc["level"] == "grounded" else ("partial" if kc["level"] == "partial" else "general"),
        "error": None,
    })


# ── 阶段 4：Knowledge Gap Detector（知识缺口检测） ──
GAPS_FILE = DATA_DIR / "geo_gaps.json"


def _load_gaps() -> list[dict]:
    from app.services.store import get_store

    return get_store().load("gaps")


def _save_gaps(items: list[dict]) -> None:
    from app.services.store import get_store

    get_store().save("gaps", items)


def _impact_by_priority(p: int) -> str:
    if p >= 85:
        return "high"
    if p >= 70:
        return "medium"
    return "low"


@router.post("/gaps")
async def detect_gaps(limit: int = 30):
    """知识缺口检测：问题池 → 逐个 Kernel 匹配 → 无知识的问题生成缺口

    缺口 = 客户问题需要的信息 − 企业已有知识。
    missing_information 由 LLM 批量分析；impact 按优先级映射（≥85 high / ≥70 medium / low）。
    """
    from adapters.llm import chat, LLMNotConfiguredError, LLMError

    questions = _load_questions()[-limit:]
    if not questions:
        return ok({"added": [], "total": 0, "error": "问题池为空，先分析问题"})

    # 48 认知子项（用户拍板 2026-08-19：缺口按子项粒度展示，替代粗规则模板）
    try:
        from app.api.v1.enterprise_profile import _load_items as _ep_load_items, _match_question

        ep_items = _ep_load_items()
    except Exception:  # noqa: BLE001
        ep_items = []

    existing_q = {g.get("question") for g in _load_gaps()}
    added = []
    now = datetime.now(timezone.utc).isoformat()
    mi_map: dict[str, str] = {}
    # 审计 B1/B2：问题的 evidence_level 此前**没有任何地方写过**（gen_questions 只写 "C"），
    # 而认知漏斗/认知地图/PDF 报告都按 `== "grounded"` 统计 → 恒 0%，还被当成结论展示。
    # 这里把已经算出来的知识判定结果如实写回问题本行：grounded / partial / none（同一批 kc，不重查）。
    levels: dict[str, str] = {}
    for q in questions:
        qtext = str(q.get("question") or "").strip()
        if not qtext:
            continue
        has_gap = q.get("question") in existing_q
        already_leveled = q.get("evidence_level") in ("grounded", "partial", "none")
        # 已有缺口且已判定过 → 不重查（省 Kernel 调用）。**不能因为「已有缺口」就跳过判定**：
        # 老问题正是这样被漏掉的——库存问题永远拿不到 evidence_level，漏斗恒 0%。
        if has_gap and already_leveled:
            continue
        intent = str(q.get("intent") or "")
        entities = q.get("related_entities") or []
        kc = await _knowledge_check(qtext, entities)
        if kc.get("kernel_down"):
            continue  # Kernel 不可达 → 不判缺口（防「宕机」被当成「缺知识」），也不写 level
        levels[qtext] = kc.get("level") or "none"
        if has_gap or kc["has_knowledge"]:
            continue  # 已有缺口 / 企业已有知识 → 不重复建缺口
        # 子项粒度：该问题命中哪些 48 子项 → 缺的就是这些子项的信息
        hit_items = [
            it for it in ep_items
            if _match_question(qtext, it.get("question_match_rules") or [], intent, entities)
        ]
        added.append({
            "question": qtext,
            "entity": (entities or [None])[0] or q.get("keyword") or "",
            "priority": q.get("priority", 50),
            "intent": intent,
            "kc": kc,  # V1.1 证据链：Kernel 检索结果随缺口落库
            "subitems": [it["id"] for it in hit_items],
            "subitem_names": [it["name"] for it in hit_items],
        })
        existing_q.add(qtext)

    # LLM 批量分析缺失信息
    if added:
        lines = "\n".join(f"- {a['question']}（意图：{a['intent']}）" for a in added[:15])
        prompt = (
            "以下问题是客户高频询问但企业知识库中暂无依据的问题。对每个问题分析："
            "企业要回答它需要补充哪类信息（missing_information，如'安全认证和测试数据''价格体系和报价单''产品寿命测试报告'）。\n"
            f"{lines}\n"
            '严格按 JSON 数组输出（与上面问题一一对应）：[{"question": "原问题", "missing_information": "需要的企业信息"}]'
        )
        try:
            text = await chat(prompt, max_tokens=800)
        except (LLMNotConfiguredError, LLMError):
            text = ""
        mi_map = {}
        if text:
            for it in _extract_json_array(text):
                mi_map[str(it.get("question", "")).strip()] = str(it.get("missing_information", "")).strip()

    gaps = _load_gaps()
    # V1.1 证据链：intent → 信息需求规则分类（纯规则，诚实标"规则分类"；LLM missing_information 仅作建议）
    _CAP_TEMPLATE = {
        "采购": ["价格体系", "套餐说明", "采购案例", "ROI 证明"],
        "信任": ["认证资料", "客户案例", "部署方案", "安全说明"],
        "安全": ["数据存储位置", "私有化部署方案", "权限管理机制", "安全认证", "客户案例"],
        "风险": ["风险说明", "应急预案", "合规材料"],
        "对比": ["产品对比资料", "差异化说明", "行业方案"],
        "认知": ["产品介绍", "行业解决方案", "应用场景"],
        "使用": ["操作文档", "培训方案", "常见问题"],
        "实施": ["实施指南", "部署周期", "服务支持"],
        "了解": ["行业科普", "产品介绍"],
    }
    for a in added:
        kc = a.get("kc") or {"best_score": 0.0, "level": "none", "refs": [], "has_knowledge": False}
        # 2026-08-18：优先实测缺失维度（kc.missing_dimensions，回答充分性检测）；兜底静态规则模板
        measured = (kc.get("missing_dimensions") or [])
        # 2026-08-19 用户拍板：缺口粒度 = 48 认知子项（命中子项名），比粗规则模板更可行动；
        # 未命中任何子项的问题回退旧规则
        sub_names = a.get("subitem_names") or []
        caps = sub_names or measured or _CAP_TEMPLATE.get(a["intent"], ["产品介绍", "客户案例", "详细说明"])
        gaps.append({
            "id": f"g_{uuid.uuid4().hex[:10]}",
            "question": a["question"],
            "entity": a["entity"],
            # 2026-09-21 修：原来这里兜底成 `a["question"]` —— 模型没答上来时
            # （本机就没配模型 key），「缺什么」直接变成「问题原文」，
            # 页面上看着有值、实际是句废话（实测 dev 库几条缺口的 missing_information
            # 就等于 question 本身）。现在如实留空，由页面写「尚未判明」。
            "missing_information": mi_map.get(a["question"]) or None,
            # V1.1 证据链：为什么认为缺（**企业知识库**检索实测）+ 缺什么（子项粒度/规则分类）
            # 2026-09-21：「kernel_search」是换知识源之前的老名字 —— 知识源早就换成 EIOS
            # 企业知识库（:8040）了，页面却还打印「来源：kernel_search」。改真名。
            "source": "enterprise_knowledge_base",
            # 判定依据如实落库：fact_triple=按事实三元组；document_text=知识库只给了文档分块
            "judge_basis": kc.get("judge_basis") or "document_text",
            "matched_terms": kc.get("matched_terms") or [],
            "retrieval_score": round(kc.get("best_score", 0.0), 2),
            "matched_refs": kc.get("refs") or [],
            "missing_capabilities": caps,  # 48 子项粒度缺失清单（命中子项）/实测缺失维度/规则兜底
            "subitems": a.get("subitems") or [],
            "subitem_names": sub_names,
            "cap_source": "subitem" if sub_names else "rule",
            "assessment": kc.get("status", "GAP"),  # 2026-08-18 4级判定：PARTIAL/GAP/UNRELATED
            "evidence": "回答充分性检测：" + str(kc.get("status", "GAP")) + "——命中主体但缺失信息维度，或检索无实质知识",
            "evidence_level": "C",  # 拍板：缺口吃 AI 问题池 → 产出只能 C（禁止标「已验证」）
            "impact": _impact_by_priority(a["priority"]),
            "priority": a["priority"],
            "status": "open",
            "created_at": now,
        })
    _save_gaps(gaps)
    if levels:
        all_questions = _load_questions()
        changed = False
        for q in all_questions:
            lv = levels.get(str(q.get("question") or "").strip())
            if lv and q.get("evidence_level") != lv:
                q["evidence_level"] = lv
                changed = True
        if changed:
            _save_questions(all_questions)
    # 内容计划不再由缺口直译生成（2026-08-19 拍板：旧「补齐:xxx」直译被内容计划算法取代，
    # 由 POST /distill/content-plan 按 48 认知子项压力统一输出：待生产/待补知识）
    return ok({"added": len(added), "total": len(gaps), "plans_added": 0, "error": None})


@router.get("/gaps")
async def list_gaps(status: str | None = None, limit: int = 100):
    items = _load_gaps()
    if status:
        items = [g for g in items if g.get("status") == status]
    items = items[-limit:][::-1]
    # D4（0.4）：缺口条目加强（纯规则映射，零 LLM）
    _stars = {"high": 5, "medium": 3, "low": 1}
    _ctype = {
        "信任": "客户案例+白皮书",
        "采购": "价格指南",
        "认知": "品牌介绍",
        "对比": "产品对比文章",
        "风险": "安全部署指南",
        "实施": "实施指南",
        "了解": "行业科普",
    }
    for g in items:
        imp = (g.get("impact") or "").lower()
        g["impact_stars"] = _stars.get(imp, 2)
        # V1.1 证据链透出：检索分/匹配引用；缺少清单 = 规则分类优先，LLM 建议兜底
        g["retrieval_score"] = g.get("retrieval_score")
        g["matched_refs"] = g.get("matched_refs") or []
        caps = g.get("missing_capabilities") or []
        mi = g.get("missing_information") or ""
        if caps:
            g["missing_checklist"] = caps
            g["checklist_source"] = "rule"
        elif mi and mi.strip() != (g.get("question") or "").strip():
            parts = [p.strip() for p in re.split(r"[，,；;、/。]", mi) if p.strip()]
            g["missing_checklist"] = parts or [mi]
            g["checklist_source"] = "llm"
        else:
            g["missing_checklist"] = []
            g["checklist_source"] = None
        intent = g.get("intent") or "认知"
        g["recommended_content_type"] = _ctype.get(intent, "文章")
        g["evidence"] = {"question": g.get("question"), "intent": intent, "priority": g.get("priority")}
        g["score_source"] = "rule"
    return ok({"items": items, "total": len(items), "note": "影响度/建议类型为规则映射（非 LLM 精判）"})


def _attach_factor_notes(items: list[dict]) -> None:
    """机会列表刷新时重查竞品缺口标注（跟随最新 factor-gaps 与监测对标关系）

    真实匹配：factor-gaps left（竞品被夸因子）× 监测对象对标产品（用户配置）
    只标产品类（source_type=material）；无匹配清空（数据变化后旧标注失效）。
    """
    try:
        from services.intelligence.cognition import factor_gaps
        from collections import defaultdict
        from app.services.store import get_store

        left = (factor_gaps(company=None, days=30).get("left") or [])
        comp_factors: dict[str, list[dict]] = defaultdict(list)
        for g in left:
            comp_factors[str(g.get("competitor_leader") or "")].append(g)
        comp_products: dict[str, set[str]] = defaultdict(set)
        for it in get_store().load("monitor_items"):
            if it.get("type") == "competitor":
                cfg = it.get("config_json") or {}
                for c in cfg.get("competitor") or []:
                    comp_products[c].update(cfg.get("product") or [])
        for p in items:
            if p.get("source") != "capability" or p.get("source_type") != "material":
                continue
            obj = p.get("source_object") or ""
            notes: list[str] = []
            for comp, factors in comp_factors.items():
                if not comp:
                    continue
                prods = comp_products.get(comp, set())
                # 命名不一致（知识对象「云启视界」vs 监测产品全名「云启视界·AI工业质检平台」）→ 包含判定
                if not prods or not (obj in prods or any(obj in cp or cp in obj for cp in prods)):
                    continue
                for g in factors:
                    notes.append(f"{g.get('factor')} ×{g.get('competitor_mentions') or 1}")
            if notes:
                p["factor_notes"] = " · ".join(notes[:4])
                p["reason"] = f"竞品被夸而你没被夸（{p['factor_notes']}）——重点围绕这些点写内容，让 AI 推荐你"
            else:
                p.pop("factor_notes", None)  # 数据变化后旧标注失效 → 清空
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("eios.distill").exception("刷新竞品缺口标注失败")


async def _self_company_names() -> list[str]:
    """自家公司名（动态，不写死）：brand 对象（用户自动配置时勾选确认的）→ 无则 Kernel company 类引用频次最高兜底。

    2026-08-11 修复：旧代码写死「云启」（虚构测试集品牌），换真实公司（亚宇臻隆）后
    企业介绍类内容机会全被跳过。改为读用户确认过的数据，换公司资料无需改代码。
    """
    from app.services.store import get_store

    names: list[str] = []
    for b in get_store().load("monitor_items"):
        if b.get("type") != "brand" or b.get("status") != "active":
            continue
        cfg = b.get("config_json") or {}
        if cfg.get("company"):
            names.append(str(cfg["company"]).strip())
        for a in (cfg.get("aliases") or []):
            s = str(a).strip()
            if s:
                names.append(s)
        if names:
            break
    if names:
        return names
    # 兜底：Kernel company 类实体按引用频次取最高（与 detect 自家判定同一思路）
    try:
        from adapters.eios import get_entities

        ents = await get_entities()
        comps = sorted(
            (
                ((e.get("canonical_name") or "").strip(), len(e.get("evidence_ids") or []))
                for e in ents if e.get("object_type") == "company"
            ),
            key=lambda x: -x[1],
        )
        if comps and comps[0][0]:
            return [comps[0][0]]
    except Exception:  # noqa: BLE001
        pass
    return []


@router.post("/opportunities")
async def gen_opportunities(limit: int = 15):
    """内容机会（V2）：知识资产 → 可直接生产 + 知识缺口 → 建议补充

    - 来源 A（可直接生产）：企业知识对象（material 产品/服务、project 项目、company 我方）
      → 内容机会，带知识依据（纯规则，安全类型白名单，不碰财务/会议纪要/客户内部资料）
    - 来源 B（建议补充）：知识缺口（gaps）→ 先补资料（保留 V1 逻辑，改标注）

    复用 plans 表；target_question/topic 去重；只出计划不生成文章。
    """
    plans = _load_plans()
    existing_tq = {p.get("target_question") for p in plans}
    existing_topic = {p.get("topic") for p in plans}
    now = datetime.now(timezone.utc).isoformat()
    added: list[dict] = []

    # ── 来源 A：企业知识对象 → 可直接生产（收敛：产品去版本、项目限 5、总数 ≤30）──
    try:
        from adapters.eios import get_entities

        ents = await get_entities()
        # 安全类型白名单：产品/服务(material)、项目(project)、我方公司(company)
        # 排除：person/department/policy/procedure/supplier（内部组织与供应商，不外发）
        _CT_MAP = {
            "material": [("产品白皮书", "白皮书"), ("产品 FAQ", "FAQ"), ("产品介绍", "文章")],
            "project": [("客户案例", "案例")],
            "company": [("企业介绍", "文章")],
        }
        seen_names: set[str] = set()
        proj_count = 0
        # 自家公司（动态）：brand 对象确认的 → Kernel 频次兜底；不再写死「云启」
        self_names = await _self_company_names()
        for e in ents:
            obj_t = e.get("object_type") or e.get("type") or ""
            name = (e.get("canonical_name") or e.get("name") or "").strip()
            if obj_t not in _CT_MAP or not name or name in seen_names:
                continue
            # company 只保留自家（排除客户/外部公司：笔革家居、华夏君成、ChatGPT 等）
            if obj_t == "company":
                is_self = any(
                    n and (n == name or (len(n) >= 3 and len(name) >= 3 and (n in name or name in n)))
                    for n in self_names
                )
                if not is_self:
                    continue
            # material 去版本实体：含版本号（v4.0 / v3.2 / 1.0）跳过，只留产品级（防重复）
            if obj_t == "material" and re.search(r"v?\d+\.\d+|版本", name):
                continue
            # project 只保留前 5 个（66 个项目全出 = 噪音）
            if obj_t == "project":
                if proj_count >= 5:
                    continue
                proj_count += 1
            seen_names.add(name)
            for suffix, ctype in _CT_MAP[obj_t]:
                topic = f"{name}{suffix}"
                if topic in existing_topic:
                    continue
                plans.append({
                    "id": f"p_{uuid.uuid4().hex[:10]}",
                    "topic": topic,
                    "reason": f"企业知识库已有「{name}」资料（{obj_t}），可基于真实能力对外生产",
                    "target_question": "",
                    "recommended_content_type": ctype,
                    "priority": 70 if obj_t == "material" else 60,
                    "gap_id": "",
                    "source_object": name,  # 来源对象名（竞品对标匹配用）
                    "source_type": obj_t,  # 来源对象类型（标注只对产品类）
                    "generation_reason": f"知识对象 {name}（{obj_t}）→ 规则生成内容任务",
                    "source": "capability",  # 能力来源：可直接生产
                    "evidence_level": "B",
                    "status": "planned",
                    "created_at": now,
                })
                added.append(plans[-1])
                existing_topic.add(topic)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("eios.distill").exception("gen_opportunities 来源A（知识对象）失败，继续缺口来源")

    # ── 竞品缺口标注：对标竞品被夸的因子 → 机会条目（真实匹配：监测对象对标关系 + factor-gaps 实测因子）──
    _attach_factor_notes(plans)
    _save_plans(plans)
    return ok({"added": len(added), "total": len(plans), "error": None})


# ── B4：蒸馏总览（机会总览首屏聚合，纯规则零 LLM） ──
@router.get("/overview")
async def distill_overview():
    """蒸馏总览：认知漏斗 + 验证状态 + TOP 缺口 + 机会数

    全部来自现有数据聚合（问题池/缺口/计划），无新增计算口径。
    """
    qs = _load_questions()
    verified = sum(1 for q in qs if (q.get("monitor_count") or 0) > 0)
    unverified = len(qs) - verified
    gaps = [g for g in _load_gaps() if g.get("status") == "open"]
    top_gaps = sorted(gaps, key=lambda g: -(g.get("priority") or 0))[:5]
    plans = _load_plans()
    # 审计 B12：机会数以前 = len(plans)，把 archived/published/completed 也算进去。
    # 只数「在办」的机会（未归档、未发布、未完成）。
    open_plans = [p for p in plans if p.get("status") not in ("archived", "published", "completed")]
    # 认知漏斗（口径见 _funnel_rows：只按「已判定过的问题」算，未判定给 null）
    funnel = _funnel_rows(qs)
    # 最大机会阶段：覆盖最低且有问题（未判定 = 不在此列，不拿 0% 当结论）
    ai_judgment = None
    with_cov = [s for s in funnel if s["coverage_pct"] is not None]
    if with_cov:
        worst = min(with_cov, key=lambda s: s["coverage_pct"])
        if worst["coverage_pct"] < 50:
            samples = [q.get("question") for q in qs if _STAGE_CN.get((q.get("customer_stage") or "").lower(), "其他") == worst["stage"]][:3]
            ai_judgment = {
                "stage": worst["stage"],
                "coverage_pct": worst["coverage_pct"],
                "reason": f"客户已进入「{worst['stage']}」阶段，{worst['judged_count']} 个已判定问题里只有 {worst['coverage_pct']}% 有企业资料可引用",
                "samples": samples,
            }
    return ok({
        "funnel": funnel,
        "ai_judgment": ai_judgment,
        "verified_questions": verified,
        "unverified_questions": unverified,
        "top_gaps": top_gaps,
        "opportunities_count": len(open_plans),
        "note": "总览为现有数据聚合（问题池/缺口/计划），无 AI 猜测；企业覆盖只按已判定过的问题算，未判定为 null",
    })


# ── B5：AI 认知覆盖矩阵（5 维，规则词频，来源监测回答） ──
@router.get("/cognition-profile")
async def cognition_profile():
    """企业 AI 认知覆盖矩阵：AI 回答里企业在 5 个维度的被提及率

    维度：品牌认知/产品能力/案例证明/价格信息/安全保障。
    规则：监测回答文本中维度词出现比例（词频估算，非 LLM 精判）。
    诚实：无监测数据的维度 = null；无监测历史整卡空态。
    2026-08-12 幻觉修复：旧版词频不绑定企业实体——泛谈行业的回答（"AI数字员工平台
    有几类"）含"AI/平台"就计为产品能力 100% 提及，45% 回答根本没提本企业。新版：
    先过滤只提到本企业的回答（_self_company_names），维度词频只在这些回答里统计。
    """
    try:
        from app.services.store import get_store

        hist = get_store().load("monitor_history")
    except Exception:  # noqa: BLE001
        hist = []
    dims = [
        # 品牌认知（2026-08-12 修复：旧词表 公司/企业/平台 命中企业名自带字眼——"亚宇臻隆科技有限公司"
        # 含"公司" → 提到企业名就恒 100%，无区分度。换成业务描述词：AI 介绍企业"专注/主营/提供…"才算认知）
        {"key": "brand", "label": "品牌认知", "words": ["专注", "主营", "定位", "业务", "成立于", "总部", "提供服务", "服务内容", "解决方案提供商", "致力于", "一站式"]},
        {"key": "product", "label": "产品能力", "words": ["产品", "系统", "软件", "功能", "方案", "部署", "技术", "AI"]},
        {"key": "case", "label": "案例证明", "words": ["案例", "客户", "落地", "实施", "应用", "合作", "项目", "场景"]},
        {"key": "price", "label": "价格信息", "words": ["价格", "多少钱", "报价", "成本", "费用", "预算", "性价比"]},
        {"key": "security", "label": "安全保障", "words": ["安全", "隐私", "认证", "合规", "权限", "保密", "数据保护"]},
    ]
    answers: list[str] = []
    for h in hist:
        for q in h.get("questions") or []:
            for ed in q.get("engine_detail") or []:
                txt = (ed.get("answer") or ed.get("snippet") or "").strip()
                if txt:
                    answers.append(txt)
    # 幻觉修复：只统计提到本企业的回答（泛谈行业的不算"提到你"）
    try:
        self_names = await _self_company_names()
    except Exception:  # noqa: BLE001
        self_names = []
    # 2026-08-12 二次修复：AI 对公开信息少的企业，回答多为"无法判断/建议核实/查工商信息"
    # ——复述问题含企业名但等于没回答。这类无效回答不计入任何维度（不算"提到"）。
    _USELESS = ["无法判断", "无法直接", "无法回答", "无法给出", "建议你", "建议您", "建议通过",
                "查工商", "查询工商", "天眼查", "企查查", "公示系统", "核实", "公开信息有限",
                "公开信息较少", "没有相关信息", "暂未找到", "未找到", "不太清楚", "不清楚",
                "不确定", "无法提供", "没有更多信息", "信息有限", "我无法"]
    if self_names:
        company_answers = [
            a for a in answers
            if any(cn and cn in a for cn in self_names) and not any(w in a for w in _USELESS)
        ]
    else:
        company_answers = answers  # 无企业名配置时退回全量（诚实标注见 note）
    # 无效回答计数（诚实展示：被排除的"提到但没实际回答"条数）
    if self_names:
        useless_count = sum(
            1 for a in answers
            if any(cn and cn in a for cn in self_names) and any(w in a for w in _USELESS)
        )
    else:
        useless_count = 0
    total = len(company_answers)
    rows = []
    for d in dims:
        if total == 0:
            rows.append({**d, "mention_rate": None, "gap_level": None})
            continue
        hit = sum(1 for a in company_answers if any(w in a for w in d["words"]))
        rate = round(hit / total * 100)
        gap_level = "严重" if rate < 10 else ("高" if rate < 30 else ("中" if rate < 60 else "低"))
        rows.append({**d, "mention_rate": rate, "gap_level": gap_level})
    note = (
        f"维度提及率 = AI 回答提到本企业（{('、'.join(self_names[:2])) if self_names else '企业名'}）"
        f"且含维度关键词的比例（规则估算，非 LLM 精判）"
        + (f"；已排除 {useless_count} 条「无法判断/建议核实」类无效回答" if useless_count else "")
        + "；AI 对公开信息少的企业常基于名称猜测，提及≠真实认知，仅供参考"
        if self_names
        else "维度提及率为监测回答词频估算（规则）；未配置企业名时未过滤泛谈回答，仅供参考"
    )
    return ok({
        "dims": rows,
        "total_answers": total,
        "note": note,
    })


# ══════════════════════════════════════════════════════════════
# AI 认知评估 V2（2026-08-12 用户拍板修正版）：
# 从"关键词命中统计"升级为"AI 企业认知评估"——LLM 批处理语义评估
# ══════════════════════════════════════════════════════════════

_CT_CN = {
    "business": "业务定位",
    "product": "产品能力",
    "customer": "客户案例",
    "finance": "财务融资",
    "organization": "组织架构",
    "security": "安全合规",
}


@router.post("/cognition/evaluate")
async def cognition_evaluate():
    """AI 认知评估 V2 · 批处理评估：monitor_history 回答 → LLM 语义评估 → 存 cognition_evaluations

    每回答输出：mention_status（主动提及/复述问题）/ question_contains_company /
    claims（最多5条，claim_type + status: grounded|partial|hallucination）/ recommendation。
    企业知识摘要（get_entities + search_knowledge）注入 prompt 做事实依据。
    复用 _knowledge_check 的三态思路，但批量交给 LLM 一次判（省 token）。
    """
    from app.services.store import get_store
    from adapters.llm import chat
    from adapters.eios import get_entities, search_knowledge

    store = get_store()
    # 审计 B9：旧代码「先清空旧评估 → 再逐批调 LLM」，任一批失败就提前退出，
    # 用户看到「部分成功」，但历史评估已经全没了。改为「全部算完再替换」：
    # 旧数据在本函数末尾、确认全部批次成功之后才删除。
    previous = store.load("cognition_evaluations")
    hist = store.load("monitor_history")
    # 收集回答（去 engine_detail 缺失的）
    answers: list[dict] = []
    for h in hist:
        for q in h.get("questions") or []:
            qt = q.get("question") or ""
            for ed in q.get("engine_detail") or []:
                txt = (ed.get("answer") or ed.get("snippet") or "").strip()
                if not txt:
                    continue
                answers.append({
                    "answer_id": f"a_{uuid.uuid4().hex[:10]}",
                    # 修复（审计 H8）：engine_detail 字段名是 engine_name，旧代码读 ed.get("engine")
                    # 恒为 None → 评估结果引擎全显示 unknown
                    "engine": str(ed.get("engine_name") or ed.get("engine") or "unknown"),
                    "question": qt,
                    "answer_text": txt[:800],
                })
    if not answers:
        return ok({"evaluated": 0, "error": "暂无监测回答（先跑监测）"})

    # 企业知识摘要（实体 + 关键事实）
    try:
        ents = await get_entities()
    except Exception:  # noqa: BLE001
        ents = []
    kb_lines = []
    for e in (ents or [])[:25]:
        nm = (e.get("canonical_name") or e.get("name") or "").strip()
        t = e.get("object_type") or e.get("type") or ""
        if nm:
            kb_lines.append(f"- {nm}（{t}）")
    kb_summary = "\n".join(kb_lines) or "（知识库暂无实体）"
    fact_lines: list[str] = []
    try:
        self_names = await _self_company_names()
    except Exception:  # noqa: BLE001
        self_names = []
    for sn in self_names[:2]:
        try:
            res = await search_knowledge(sn, top_k=5, include_candidates=False)
        except Exception:  # noqa: BLE001
            continue
        for h in (res.get("hits") or [])[:5]:
            name = h.get("canonical_name") or h.get("name") or ""
            if name and f"- {name}" not in fact_lines:
                val = (h.get("value") or h.get("predicate") or "").strip()
                fact_lines.append(f"- {name}: {val[:80]}" if val else f"- {name}")

    # 分批（≤10 条/批——大 prompt 会退化 DeepSeek 输出质量，小批更稳）LLM 评估
    batch_size = 10
    results: list[dict] = []
    for i in range(0, len(answers), batch_size):
        batch = answers[i : i + batch_size]
        lines = "\n".join(
            f"[{a['answer_id']}] 引擎={a['engine']} 问题={a['question'][:60]}\n回答: {a['answer_text'][:600]}"
            for a in batch
        )
        system = (
            "你是企业AI认知评估器。下面是多个AI助手对某企业的回答片段 + 企业知识摘要。\n"
            "对每条回答输出 JSON：\n"
            "{\"items\": [{\n"
            "  \"answer_id\": \"a_xxx\",\n"
            "  \"mention_status\": \"mentioned | not_mentioned\",  // 主动介绍/讨论企业=mentioned；复述问题或建议查工商=not_mentioned\n"
            "  \"question_contains_company\": true,                // 问题文本本身是否含企业名\n"
            "  \"claims\": [{\"claim\": \"企业主营XXX\", \"claim_type\": \"business|product|customer|finance|organization|security\", \"status\": \"grounded|partial|hallucination\"}],\n"
            "  \"recommendation\": \"positive|neutral|negative|null\"\n"
            "}],\n"
            "}\n"
            "规则：\n"
            "1. claims 提取关于企业的实质声明（业务/产品/客户/财务/组织/安全），每条来自回答原文；\n"
            "   只要回答包含对企业或其产品的描述/断言/对比，就必须抽 1-5 条（不得为空）；完全没有企业声明才允许空。\n"
            "2. status: grounded=知识摘要支持该声明；partial=摘要只有部分相关或回答用了不确定措辞（可能/或许/大概/看起来/应该）；\n"
            "   hallucination=回答以肯定语气断言（无不确定措辞）且知识摘要完全无此事实（AI 编造）。\n"
            "3. 无法确认但回答是猜测性措辞 = partial（不算幻觉）；只有肯定式断言 + 摘要无依据才算 hallucination。\n"
            "4. mention_status: 回答在介绍/评价/对比企业 = mentioned；只说\"建议查工商\"\"没有信息\"或纯复述问题 = not_mentioned。\n"
        )
        user = (
            "企业知识摘要（实体）:\n" + kb_summary + "\n\n"
            "企业关键事实:\n" + ("\n".join(fact_lines[:15]) or "（暂无）") + "\n\n"
            "待评估回答:\n" + lines
        )
        try:
            out_str = await chat(
                user,
                system=system,
                max_tokens=3000,
                response_format={"type": "json_object"},
            )
            try:
                out = json.loads(out_str or "{}")
            except Exception:  # noqa: BLE001
                out = {}
            # 空结果重试 1 次（DeepSeek 长输出偶发截断/退化）
            if not (out or {}).get("items") and len(batch) > 1:
                out_str = await chat(
                    user,
                    system=system,
                    max_tokens=4000,
                    response_format={"type": "json_object"},
                )
                try:
                    out = json.loads(out_str or "{}")
                except Exception:  # noqa: BLE001
                    out = {}
        except Exception as e:  # noqa: BLE001
            # 审计 B9：失败时不落半份结果——保留上一轮完整评估（previous 未被删除）。
            return ok({
                "evaluated": 0,
                "total_answers": len(answers),
                "previous_kept": len(previous),
                "error": f"LLM 调用失败（第 {i//batch_size+1} 批）: {e}；已保留上一轮评估，未覆盖",
            })
        items = (out or {}).get("items") or []
        results.extend(items)

    # 全部批次成功后，才原子替换旧评估（先删后插；此时已拿到完整新结果）
    for old in previous:
        store.delete("cognition_evaluations", old.get("id") or old.get("answer_id") or "")
    saved = 0
    for item in results:
        aid = item.get("answer_id") or ""
        src = next((a for a in answers if a["answer_id"] == aid), None)
        if not src:
            continue
        record = {
            "answer_id": aid,
            "engine": src["engine"],
            "question": src["question"],
            "question_contains_company": bool(item.get("question_contains_company")),
            "answer_text": src["answer_text"],
            "mention_status": str(item.get("mention_status") or "not_mentioned"),
            "claims": item.get("claims") or [],
            "recommendation": item.get("recommendation"),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        store.insert("cognition_evaluations", record)
        saved += 1
    return ok({
        "evaluated": saved,
        "total_answers": len(answers),
        "note": "批处理 LLM 语义评估完成（mention_status + claims 三态 + recommendation）",
    })


@router.get("/cognition/profile")
async def cognition_profile_v2():
    """AI 认知评估 V2 · 聚合结果：读 cognition_evaluations → 健康度/四指标/维度矩阵/错误认知

    - Awareness（认识程度）= 主动提到企业（问题不带企业名）的回答占比
    - Understanding（理解程度）= grounded claims / 全部 claims
    - Hallucination（幻觉风险）= hallucination claims / 全部 claims
    - 健康度 = grounded×1 + partial×0.5（hallucination 记 0）加权
    - 矩阵：按 claim_type 聚合 已理解/部分理解/未理解/幻觉风险（一条断言都没有的类 = 暂无此类断言，不当成未理解）
    - 错误认知：hallucination claims 明细（claim + 引擎 + 问题，可溯源）
    """
    from app.services.store import get_store

    evals = get_store().load("cognition_evaluations")
    if not evals:
        return ok({
            "total": 0,
            "health": None,
            "metrics": {"awareness": None, "understanding": None, "hallucination": None, "recommendation": None},
            "matrix": [],
            "errors": [],
            "note": "暂无评估——先跑「AI 认知评估」（监测回答批处理分析）",
        })

    # Awareness：问题不带企业名的回答里，主动提到企业的占比
    valid = [e for e in evals if not e.get("question_contains_company")]
    mentioned = [e for e in valid if e.get("mention_status") == "mentioned"]
    awareness = round(len(mentioned) / len(valid) * 100) if valid else None

    # claims 三态聚合
    all_claims = [c for e in evals for c in (e.get("claims") or [])]
    g = [c for c in all_claims if c.get("status") == "grounded"]
    p = [c for c in all_claims if c.get("status") == "partial"]
    h = [c for c in all_claims if c.get("status") == "hallucination"]
    understanding = round(len(g) / len(all_claims) * 100) if all_claims else None
    hallucination_risk = round(len(h) / len(all_claims) * 100) if all_claims else None
    health = round((len(g) * 1.0 + len(p) * 0.5 + len(h) * 0.0) / len(all_claims) * 100) if all_claims else None

    # 推荐倾向（positive 占比）
    recs = [e.get("recommendation") for e in evals if e.get("recommendation")]
    rec_pos = round(recs.count("positive") / len(recs) * 100) if recs else None

    # 矩阵：按 claim_type 聚合
    matrix = []
    for t, cn in _CT_CN.items():
        cs = [c for c in all_claims if c.get("claim_type") == t]
        if not cs:
            # 2026-09-21：「未理解」是给「模型提到了但没对上」用的。这一类一条断言都没有时
            # 写「未理解」，用户会读成「AI 完全不懂这一块」，实际只是这次没提取到这类断言。
            matrix.append({"key": t, "label": cn, "claims": 0, "grounded": 0, "partial": 0, "hallucination": 0, "status": "暂无此类断言"})
            continue
        cg = sum(1 for c in cs if c.get("status") == "grounded")
        cp = sum(1 for c in cs if c.get("status") == "partial")
        ch = sum(1 for c in cs if c.get("status") == "hallucination")
        status = "已理解" if cg == len(cs) else ("部分理解" if cg > 0 or cp > 0 else ("幻觉风险" if ch > 0 else "未理解"))
        matrix.append({"key": t, "label": cn, "claims": len(cs), "grounded": cg, "partial": cp, "hallucination": ch, "status": status})

    # 错误认知（hallucination 明细，可溯源）
    errors = [
        {
            "claim": c.get("claim"),
            "type": _CT_CN.get(c.get("claim_type"), c.get("claim_type") or ""),
            "engine": e.get("engine"),
            "question": e.get("question"),
        }
        for e in evals
        for c in (e.get("claims") or [])
        if c.get("status") == "hallucination"
    ]

    return ok({
        "total": len(evals),
        "health": health,
        "metrics": {
            "awareness": awareness,
            "understanding": understanding,
            "hallucination": hallucination_risk,
            "recommendation": rec_pos,
        },
        "matrix": matrix,
        "errors": errors[:20],
        "note": "LLM 语义评估：理解 = 有企业依据的声明占比；幻觉 = 无依据编造占比（可溯源到回答）",
    })


# ── 阶段 5：内容规划输出（Content Plan，先计划后生产） ──
PLANS_FILE = DATA_DIR / "geo_content_plans.json"


def _load_plans() -> list[dict]:
    from app.services.store import get_store

    return get_store().load("content_plans")


def _save_plans(items: list[dict]) -> None:
    from app.services.store import get_store

    get_store().save("content_plans", items)


@router.post("/plans")
async def gen_plans(limit: int = 15):
    """内容规划：知识缺口 → 运营内容计划（topic/reason/推荐类型/优先级）

    只出计划不生成文章——运营确认后再去内容页执行。
    """
    from adapters.llm import chat, LLMNotConfiguredError, LLMError

    gaps = [g for g in _load_gaps() if g.get("status") == "open"][-limit:]
    if not gaps:
        return ok({"added": [], "total": 0, "error": "没有待规划的知识缺口"})

    existing_topic = {p.get("target_question") for p in _load_plans()}
    lines = "\n".join(f"- {g['question']}（缺口：{g['missing_information']}，影响：{g['impact']}）" for g in gaps)
    prompt = (
        "以下是企业知识缺口对应的客户问题。为每个问题生成一条内容生产计划（运营下一步该做什么内容，"
        "让 AI 以后回答这类问题时能引用企业）。\n"
        f"{lines}\n"
        "每条计划：topic（内容主题，具体可执行）、reason（为什么做，一句话）、"
        "recommended_content_type（推荐内容类型，如 FAQ+案例文章 / 行业解决方案 / 产品对比文章 / 白皮书 / 新闻动态）、priority（0-100）。\n"
        '严格按 JSON 数组输出：'
        '[{"target_question": "原问题", "topic": "主题", "reason": "理由", "recommended_content_type": "类型", "priority": 90}]'
    )
    try:
        text = await chat(prompt, max_tokens=1200)
    except LLMNotConfiguredError as e:
        return ok({"added": [], "total": len(_load_plans()), "error": str(e)})
    except LLMError as e:
        return ok({"added": [], "total": len(_load_plans()), "error": e.message})

    plans = _load_plans()
    added = []
    now = datetime.now(timezone.utc).isoformat()
    for it in _extract_json_array(text):
        tq = str(it.get("target_question", "")).strip()
        if not tq or tq in existing_topic:
            continue
        gap = next((g for g in gaps if g["question"] == tq), {})
        plans.append({
            "id": f"p_{uuid.uuid4().hex[:10]}",
            "topic": str(it.get("topic", "")).strip() or tq,
            "reason": str(it.get("reason", "")).strip(),
            "target_question": tq,
            "recommended_content_type": str(it.get("recommended_content_type", "")).strip() or "FAQ+案例文章",
            "priority": _clamp_priority(it.get("priority"), gap.get("priority", 60)),
            "gap_id": gap.get("id"),
            "source_question_id": next((str(q.get("id")) for q in _load_questions() if str(q.get("question") or "") == tq), None),
            "evidence_level": "C",  # 拍板：LLM 生成计划 → C（reason 为 AI 策略建议，待验证）
            "status": "planned",
            "created_at": now,
        })
        added.append(plans[-1])
        existing_topic.add(tq)
    _save_plans(plans)
    return ok({"added": len(added), "total": len(plans), "error": None})


class AnalyzeIn(BaseModel):
    """Content Analyzer 输入：内容或资产 id"""
    content: str = ""
    title: str = ""
    asset_id: str | None = None
    add_gaps: bool = False  # True 时缺失问题写入知识缺口（默认不自动写，防污染）


@router.post("/analyze")
async def analyze_content(payload: AnalyzeIn):
    """Content Analyzer：内容覆盖分析（问题池 vs 内容）

    判断一篇内容（生成文章/FAQ 资产）覆盖了客户问题池的哪些问题：
    - covered：内容能回答的问题（related_entities / keyword 出现在内容中）
    - missing：内容没覆盖的问题（GEO 曝光缺口）
    - coverage_pct：覆盖率

    add_gaps=True 时（前端手动确认后），缺失问题写入知识缺口。
    """
    content = payload.content
    if not content.strip() and payload.asset_id:
        try:
            from app.api.v1.knowledge import _load as _load_kb

            for m in _load_kb():
                if m.get("id") == payload.asset_id:
                    content = m.get("content") or ""
                    break
        except Exception:  # noqa: BLE001
            pass
    if not content.strip():
        return ok({"error": "内容为空", "covered": [], "missing": [], "coverage_pct": 0, "gaps_added": 0})

    questions = _load_questions()
    if not questions:
        return ok({"error": "问题池为空：先去蒸馏页生成客户问题", "covered": [], "missing": [], "coverage_pct": 0, "gaps_added": 0})

    _DROPS = set("吗怎么什么多少哪家哪好为啥为什么会是应该要不要能不能怎么选哪个谁等？?。，、！!· ")
    # 意图词变体：问题意图词 + 文章里常见的同义表达（防止"提到实体就判覆盖"的虚高）
    _VERB_VARIANTS = {
        "多少钱": ("价格", "费用", "元", "报价", "收费", "多少钱"),
        "哪家好": ("哪家", "推荐", "怎么选", "选择", "对比", "哪家好"),
        "是什么": ("是什么", "介绍", "了解", "定义", "概念"),
        "区别": ("区别", "对比", "不同", "差异"),
        "适合": ("适合", "适用", "场景", "哪些企业"),
        "安全": ("安全", "隐私", "合规", "数据"),
        "效果": ("效果", "提升", "增长", "案例"),
        "怎么用": ("怎么用", "如何使用", "部署", "使用指南", "教程"),
        "支持": ("支持", "集成", "对接"),
        "优势": ("优势", "好处", "价值", "优点"),
    }

    def _intent_hit(qtext: str, content: str) -> bool:
        for k, variants in _VERB_VARIANTS.items():
            if k in qtext:
                return any(v in content for v in variants)
        return True  # 无已知意图词 → 仅实体判定

    covered: list[dict] = []
    missing: list[dict] = []
    for q in questions:
        qtext = (q.get("question") or "").strip()
        if not qtext:
            continue
        # 匹配词：related_entities + keyword + 去停用字的问题核心串
        cands = [e for e in (q.get("related_entities") or []) if isinstance(e, str) and len(e) >= 2]
        if q.get("keyword"):
            cands.append(str(q["keyword"]))
        core = "".join(c for c in qtext if c not in _DROPS)
        if 2 <= len(core) <= 12:
            cands.append(core)
        # 实体命中（粗筛）AND 意图命中（精筛）
        hit = any(c in content for c in cands if c) and _intent_hit(qtext, content)
        item = {"question": qtext, "keyword": q.get("keyword"), "priority": q.get("priority", 0), "intent": q.get("intent", "")}
        (covered if hit else missing).append(item)

    coverage_pct = round(len(covered) / len(questions) * 100) if questions else 0
    gaps_added = 0
    if payload.add_gaps and missing:
        gaps = _load_gaps()
        existing = {(g.get("missing_information") or "").split("：")[-1] for g in gaps}
        for m in missing[:6]:
            gi = f"内容未覆盖客户问题：「{m['question']}」（覆盖分析）"
            if gi in existing:
                continue
            gaps.append({
                "id": f"g_{uuid.uuid4().hex[:10]}",
                "question": m["question"],
                "missing_information": gi,
                "impact": f"该问题未被内容覆盖，AI 回答时无据可依（优先级 {m['priority']}）",
                "priority": m["priority"],
                "status": "open",
                "source": "coverage_analysis",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            gaps_added += 1
        _save_gaps(gaps)

    return ok({
        "total": len(questions),
        "covered": covered,
        "missing": missing,
        "coverage_pct": coverage_pct,
        "gaps_added": gaps_added,
        "error": None,
    })


class PlanManualIn(BaseModel):
    """AI 对话建议 → 内容计划（geo-plan 块协议）"""
    topic: str
    reason: str = ""
    target_question: str = ""
    recommended_content_type: str = "FAQ+案例文章"
    priority: int = 60


class CustomerGapPlanIn(BaseModel):
    """Customer Agent P6 冻结载荷；不得扩成客户画像或 Kernel 写入。"""
    gap_id: str
    question: str
    evidence: dict = {}
    frequency: int = 1
    source_message_ids: list[str] = []


@router.post("/loop/run")
async def loop_run(limit: int = 5):
    """自动闭环（2026-08-15）：planned 计划 → 自动生产内容 → 存资产 → 验证。

    生产=自动（过 Fact Gate）；发布=人工（红线：AI 不自动上线）。
    也可由每日调度自动触发（监测+蒸馏后）。
    """
    from services.loop import run_loop

    return ok(await run_loop(limit=limit))


@router.post("/plans/manual")
async def add_plan_manual(payload: PlanManualIn):
    """手动/AI 写入单条内容计划（去重：同 target_question 或同 topic 跳过）"""
    topic = payload.topic.strip()
    if not topic:
        return ok({"added": False, "total": len(_load_plans()), "error": "topic 必填"})
    plans = _load_plans()
    for p in plans:
        if p.get("topic") == topic or (payload.target_question and p.get("target_question") == payload.target_question):
            return ok({"added": False, "total": len(plans), "error": None, "dup": True})
    plans.append({
        "id": f"p_{uuid.uuid4().hex[:10]}",
        "topic": topic,
        "reason": payload.reason.strip(),
        "target_question": payload.target_question.strip(),
        "recommended_content_type": payload.recommended_content_type.strip() or "FAQ+案例文章",
        "priority": _clamp_priority(payload.priority, 60),
        "gap_id": None,
        "status": "planned",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "assistant",  # AI 助手对话建议
        "evidence_level": "C",  # 拍板：助手建议无外部/企业记录 ID → C（待验证）
    })
    _save_plans(plans)
    return ok({"added": True, "total": len(plans), "error": None, "dup": False})


@router.post("/plans/customer-gap")
async def add_plan_from_customer_gap(payload: CustomerGapPlanIn):
    """P6 薄接收口：客服知识缺口 → 现有内容计划；不生产、不发布、不写 Kernel。"""
    gap_id = payload.gap_id.strip()
    question = payload.question.strip()
    if not gap_id or not question:
        return ok({"added": False, "plan_id": None, "error": "gap_id/question 必填"})
    plans = _load_plans()
    for p in plans:
        if p.get("customer_gap_id") == gap_id:
            return ok({"added": False, "duplicated": True, "plan_id": p.get("id"), "error": None})
    source_ids = list(dict.fromkeys(x.strip() for x in payload.source_message_ids if x and x.strip()))
    plan = {
        "id": f"p_{uuid.uuid4().hex[:10]}",
        "topic": f"补齐客服问题：{question}",
        "reason": f"客户已询问 {max(1, payload.frequency)} 次，企业知识暂时无法回答",
        "target_question": question,
        "recommended_content_type": "FAQ+案例文章",
        "priority": min(100, 60 + min(max(payload.frequency, 1), 10) * 4),
        "gap_id": None,
        "customer_gap_id": gap_id,
        "source_message_ids": source_ids,
        "evidence": payload.evidence,
        "frequency": max(1, payload.frequency),
        "source": "customer_agent_gap",
        "evidence_level": "A" if source_ids else "C",
        "status": "planned",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    plans.append(plan)
    _save_plans(plans)
    return ok({"added": True, "duplicated": False, "plan_id": plan["id"], "error": None})


class FromGapsIn(BaseModel):
    """报告页薄弱榜 → 内容计划（S0）"""
    questions: list[str] = []
    batch_id: str | None = None  # 拍板证据等级：薄弱问题绑最近批量监测 ID → A


@router.post("/plans/from-gaps")
async def plans_from_weak(payload: FromGapsIn):
    """薄弱问题一键生成内容计划（纯规则不调 LLM，省 token）

    报告页薄弱榜 → 蒸馏页推荐内容；去重 = target_question 已存在跳过。
    """
    questions = [q.strip() for q in payload.questions if q and q.strip()]
    if not questions:
        return ok({"added": 0, "duplicated": 0, "total": len(_load_plans()), "error": "没有待规划的问题"})
    plans = _load_plans()
    existing = {p.get("target_question") for p in plans}
    added = 0
    duplicated = 0
    now = datetime.now(timezone.utc).isoformat()
    for q in questions:
        if q in existing:
            duplicated += 1
            continue
        plans.append({
            "id": f"p_{uuid.uuid4().hex[:10]}",
            "topic": f"补齐：{q}",
            "reason": f"监测发现 AI 回答「{q}」时未提及企业，需生产内容补齐曝光",
            "target_question": q,
            "recommended_content_type": "FAQ+案例文章",
            "priority": 85,
            "gap_id": None,
            "source": "monitor_weak",
            "batch_id": payload.batch_id,  # 拍板证据等级 A：关联最近批量监测 ID
            "evidence_level": "A",  # 外部事实（监测薄弱 → 可追溯到 batch）
            "status": "planned",
            "created_at": now,
        })
        existing.add(q)
        added += 1
    _save_plans(plans)
    return ok({"added": added, "duplicated": duplicated, "total": len(plans), "error": None})


# ── S0：三维打分（效果/薄弱/优先级，可解释加权，不落库） ──
# 数据源已迁移 SQLite（2026-08-15 修复：此前读已删 JSON 文件，weak/effect 恒空）
def _latest_weak_set() -> set[str]:
    """最近一次批量监测的薄弱问题集（计划 weak 维度数据源）"""
    from app.services.store import get_store

    history = get_store().load("monitor_history")
    batches = [h for h in history if h.get("batch")]
    if not batches:
        return set()
    return set(batches[-1].get("summary", {}).get("weak_questions") or [])


def _effect_score_for_question(q: str, materials: list[dict], history: list[dict]) -> tuple[bool, int, str]:
    """(available, score, reason)：该问题关联已发布素材的发布后提到率（取最优素材）"""
    related = [m for m in materials if m.get("published_at") and q in (m.get("coverage_questions") or [])]
    if not related:
        return False, 0, "该问题暂无已发布内容资产"
    best_ratio: float | None = None
    best_title = ""
    for m in related:
        published_at = m["published_at"]
        hits = []
        for h in history:
            ts = h.get("created_at", "")
            if ts < published_at:
                continue
            if h.get("question") == q:
                sm = h.get("summary") or {}
                hits.append((ts, sm.get("mentioned", 0), sm.get("mentioned", 0) + sm.get("not_mentioned", 0)))
            if h.get("batch"):
                for qi in h.get("questions") or []:
                    if qi.get("question") == q:
                        hits.append((ts, qi.get("mentioned_count", 0), qi.get("configured_count", 0)))
        if hits:
            hits.sort(key=lambda x: x[0])
            latest = hits[-1]
            ratio = latest[1] / latest[2] if latest[2] else 0.0
            if best_ratio is None or ratio > best_ratio:
                best_ratio = ratio
                best_title = m.get("title", "")
    if best_ratio is None:
        return False, 0, "已发布但暂无监测数据"
    # S2：引用加权——被 AI 引用的素材是比"提到"更强的有效信号（effect 维度显著提升）
    cite_count = 0
    related_ids = {m["id"] for m in related}
    for h in history:
        for c in h.get("citations") or []:
            if c.get("material_id") in related_ids:
                cite_count += c.get("count", 0)
    score = round(best_ratio * 100)
    reason = f"《{best_title}》发布后提到率 {score}%"
    if cite_count:
        score = max(score, 85)
        reason += f"，被 AI 引用 {cite_count} 次"
    return True, score, reason


def _attach_score(p: dict, weak_set: set, materials: list[dict], history: list[dict]) -> None:
    """给计划附加 score + score_breakdown（可解释加权，effect 无数据时权重分给 weak）"""
    priority = _clamp_priority(p.get("priority"), 60)
    q = p.get("target_question") or ""
    weak_available = bool(q)
    weak_score = 100 if q in weak_set else 0
    weak_reason = "出现在最近一次批量监测薄弱榜" if weak_score else ("未在薄弱榜" if weak_available else "无目标问题")
    eff_avail, eff_score, eff_reason = _effect_score_for_question(q, materials, history) if q else (False, 0, "无目标问题")
    if eff_avail:
        score = round(0.4 * eff_score + 0.4 * weak_score + 0.2 * priority)
    else:
        score = round(0.6 * weak_score + 0.4 * priority)
    p["score"] = score
    p["score_breakdown"] = {
        "effect": {"available": eff_avail, "score": eff_score, "reason": eff_reason},
        "weak": {"available": weak_available, "score": weak_score, "reason": weak_reason},
        "priority": priority,
    }


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: str):
    """删除内容计划（用户拍板：计划只加不减不行，每条可删）

    审计 B12：连带清理引用该计划的复测记录（content_impacts.plan_id），
    否则复测页会留下指向已删计划的孤儿记录。
    """
    plans = _load_plans()
    kept = [p for p in plans if p.get("id") != plan_id]
    if len(kept) == len(plans):
        return ok({"deleted": False, "total": len(kept), "error": "计划不存在"})
    _save_plans(kept)
    impacts_removed = 0
    try:
        from app.services.store import get_store

        store = get_store()
        impacts = [i for i in store.load("content_impacts") if str(i.get("plan_id") or "") == plan_id]
        for i in impacts:
            if i.get("id"):
                store.delete("content_impacts", i["id"])
                impacts_removed += 1
    except Exception:  # noqa: BLE001
        impacts_removed = 0
    return ok({"deleted": True, "total": len(kept), "impacts_removed": impacts_removed, "error": None})


@router.get("/plans")
async def list_plans(status: str | None = None, limit: int = 100, sort: str = "priority"):
    """内容计划列表（S0 起支持三维排序：priority/weak/effect；分数可解释，不落库）"""
    all_plans = _load_plans()
    items = all_plans
    if status:
        items = [p for p in items if p.get("status") == status]
    items = items[-limit:][::-1]

    if sort in ("weak", "effect"):
        weak_set = _latest_weak_set()
        from app.services.store import get_store

        materials = get_store().load("kb")
        history = get_store().load("monitor_history")
        for p in items:
            _attach_score(p, weak_set, materials, history)
        if sort == "weak":
            items.sort(key=lambda p: (-p["score_breakdown"]["weak"]["score"], -p.get("priority", 0)))
        else:
            items.sort(key=lambda p: (-p["score"], -p.get("priority", 0)))
    # 审计 B10：读接口不得写库。原实现在 GET 里 `_attach_factor_notes(all_plans)`
    # + `_save_plans(all_plans)`：并发下整表互相覆盖（后写的把先写的整体顶掉，
    # 甚至复活已删除的行）。现在只对本次返回的 items 即时标注，不落库；
    # 竞品缺口标注的落库只发生在写入型接口（POST /opportunities）。
    _attach_factor_notes(items)
    return ok({"items": items, "total": len(items)})


# ══════════════════════════════════════════════════════════════════
# 阶段 7：内容计划算法（2026-08-19 用户拍板）
# 总目标：用最少的内容，解决最多的高价值 AI 认知缺口。
# 简化分层评分（等权相加，不搞加权公式——数据未积累，防伪精确）：
#   问题价值(Value) × AI缺口(Gap) → 问题优先级 → 压到 48 认知子项 → 子项压力
#   → Kernel 知识检查 → 待生产 / 待补知识 → 内容计划 Top N
# 链路：客户问题 → AI 检测 → 问题缺口 → 商业价值 → 问题优先级
#      → 48 认知子项映射 → 认知节点压力 → 知识缺口检测 → 候选内容 → 内容优先级
# ══════════════════════════════════════════════════════════════════

_CTYPE_BY_CAT = {
    "enterprise": "品牌介绍",
    "product": "产品介绍/参数文章",
    "customer": "行业科普/FAQ",
    "capability": "资质/实力证明文章",
    "case": "客户案例+白皮书",
    "sop": "服务流程指南",
    "brand": "品牌故事/卖点文章",
    "external": "外部渠道内容",
}


def _question_monitor_stats(qtext: str) -> dict:
    """问题真实监测统计（monitor_history）：频率/提及率/正向评价率/平均排名。

    诚实口径：无监测 → freq=0，各率 None（不编 0%）。
    """
    from app.services.store import get_store

    freq = mentioned = positive = 0
    ranks: list[float] = []
    try:
        hist = get_store().load("monitor_history")
    except Exception:  # noqa: BLE001
        hist = []
    for h in hist:
        for q in h.get("questions") or []:
            if str(q.get("question") or q.get("query") or "") != qtext:
                continue
            for ed in q.get("engine_detail") or []:
                freq += 1
                if ed.get("mentioned"):
                    mentioned += 1
                if (ed.get("sentiment") or "") == "positive":
                    positive += 1
                r = ed.get("rank_est")
                if isinstance(r, (int, float)) and r and r > 0:
                    ranks.append(float(r))
    return {
        "freq": freq,
        "mention_rate": round(mentioned / freq * 100) if freq else None,
        "positive_rate": round(positive / freq * 100) if freq else None,
        "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
    }


def _score_question(q: dict, stats: dict) -> dict:
    """问题打分（简化分层，等权相加）。

    QuestionValue（0~1）：priority 分层（≥85=1 / ≥70=0.6 / 其余 0.3）
                          + 真实监测验证 +0.2 + 商业意图（采购/对比 +0.3，信任/使用 +0.2）
    QuestionGap（0~1）：3 项等权（提及 / 正向评价 / 排名），每项 0=不缺 0.5=未监测中性 1=缺；
                        accuracy/completeness 暂无逐题数据，不参与（诚实）。
    优先级 = Value × Gap（gap=0 → 0：AI 答得好就不占资源）。
    """
    p = int(q.get("priority") or 50)
    value = 0.0
    value += 1.0 if p >= 85 else 0.6 if p >= 70 else 0.3
    if (stats["freq"] or 0) > 0:
        value += 0.2
    intent = str(q.get("intent") or "")
    if intent in ("采购", "对比"):
        value += 0.3
    elif intent in ("信任", "使用"):
        value += 0.2
    value = round(min(1.0, value), 3)

    gap_raw = 0.0
    if not stats["freq"]:
        gap_raw += 0.5  # 未监测：中性
    else:
        mr = stats["mention_rate"] or 0
        gap_raw += 0.0 if mr >= 50 else 0.5 if mr > 0 else 1.0
    if not stats["freq"]:
        gap_raw += 0.5
    else:
        pr = stats["positive_rate"] or 0
        gap_raw += 0.0 if pr >= 30 else 0.5 if pr > 0 else 1.0
    if stats["avg_rank"] is None:
        gap_raw += 0.5
    else:
        gap_raw += 0.0 if stats["avg_rank"] <= 2 else 1.0
    gap = round(gap_raw / 3.0, 3)

    return {
        "value": value,
        "gap": gap,
        "priority_score": round(value * gap, 4),
        "stats": stats,
    }


async def _subitem_knowledge(questions: list[dict], items: list[dict]) -> dict:
    """48 子项 → 本地知识支撑判定（复用 enterprise_profile._assess_item：
    子项相关问题 → _knowledge_check 逐题判定（内存+SQLite 缓存，唯一判定数≈问题池大小）。

    has_knowledge：该子项至少一个问题被知识支撑（COVERED 或 PARTIAL 均可 → 有事实可写）
    **或素材库（geo_kb）有内容命中该子项知识规则**（2026-08-19 用户拍板：
    "本地有" = Kernel 事实 ∪ 素材库内容，两者任一即视为可生产）；
    全 GAP/UNRELATED 且无素材 → False（归知识缺口）。
    """
    from app.api.v1.enterprise_profile import _assess_item
    from app.api.v1.knowledge import _load as _load_materials

    materials = _load_materials()
    out: dict[str, dict] = {}
    for it in items:
        try:
            a = await _assess_item(it, questions)
        except Exception:  # noqa: BLE001
            a = {}
        covered = (a.get("covered_count") or 0) + len(a.get("partial_questions") or [])
        # 素材命中判定：子项 knowledge_rules.keywords 命中任一素材标题/正文
        kr = it.get("knowledge_rules") or {}
        kws = [str(k) for k in (kr.get("keywords") or []) if k]
        has_material = False
        if kws:
            for m in materials:
                blob = f"{m.get('title') or ''} {m.get('content') or ''}"
                if any(k and k in blob for k in kws):
                    has_material = True
                    break
        out[it["id"]] = {
            "has_knowledge": covered > 0 or has_material,
            "coverage_pct": a.get("coverage_pct"),
            "covered_count": a.get("covered_count") or 0,
            "partial_count": len(a.get("partial_questions") or []),
            "has_material": has_material,
        }
    return out


@router.post("/content-plan")
async def gen_content_plan(limit: int = 10):
    """内容计划算法（V1 规则版）：问题池 × AI 监测 → 48 子项压力 → 内容计划 Top N。

    输出每条计划（plans 表，兼容旧字段 + 新字段）：
      topic/priority/recommended_content_type/status（兼容）
      subitem/subitem_name/subitem_pressure/covered_questions/state/before_snapshot（新增）
    state：待生产（Kernel 有事实，可生成）/ 待补知识（Kernel 无事实，先进企业信息采集，不生成）。
    重复惩罚：同子项已有 planned 计划 → 跳过（防止为 N 个问题写 N 篇重复内容）。
    返回：{"items": [...], "total": n, "note": ...}
    """
    from app.api.v1.enterprise_profile import _load_items, _match_question

    questions = _load_questions()
    if not questions:
        return ok({"items": [], "total": 0, "error": "问题池为空：先跑监测蒸馏生成问题"})
    items = _load_items()
    if not items:
        return ok({"items": [], "total": 0, "error": "48 认知子项未初始化"})

    # 1. 每问题：Value × Gap + 命中子项（三通道规则；无子项映射的问题不进内容计划）
    scored: list[dict] = []
    for q in questions:
        qtext = str(q.get("question") or "").strip()
        if not qtext:
            continue
        stats = _question_monitor_stats(qtext)
        s = _score_question(q, stats)
        hit = [
            it["id"] for it in items
            if _match_question(qtext, it.get("question_match_rules") or [], str(q.get("intent") or ""), q.get("related_entities"))
        ]
        if not hit:
            continue
        s.update({"question": qtext, "hit_subitems": hit, "intent": str(q.get("intent") or "")})
        scored.append(s)

    # 2. 子项压力：问题优先级均分到命中子项（总量守恒——10 个问题共依赖同一节点时该节点压力最大）
    pressure: dict[str, dict] = {}
    for s in scored:
        if not s["hit_subitems"]:
            continue
        share = s["priority_score"] / len(s["hit_subitems"])
        for sid in s["hit_subitems"]:
            bucket = pressure.setdefault(sid, {"pressure": 0.0, "questions": []})
            bucket["pressure"] += share
            bucket["questions"].append({"question": s["question"], "priority_score": s["priority_score"], "intent": s["intent"]})

    # 3. 企业知识支撑判定（复用企业资料总揽：子项相关问题 → 企业知识库逐题判定，带缓存；
    #    失败 → 状态可能误判「待补知识」，note 标注，重跑恢复）
    #    2026-09-21：变量名/文案里的 Kernel 是换知识源之前的老名字，知识源现在是 EIOS 企业知识库。
    kernel_note = ""
    try:
        known = await _subitem_knowledge(questions, items)
    except Exception as e:  # noqa: BLE001
        logger = __import__("logging").getLogger("eios.distill")
        logger.warning("content-plan enterprise knowledge check failed: %s", str(e)[:150])
        known = {}
        kernel_note = "企业知识库检索失败，状态可能误判为「待补知识」（重跑监测后恢复）"

    # 4. 子项 → 计划（用户拍板 2026-08-19：内容计划只体现「本地已有」——有知识支撑的子项；
    #    无知识的子项不生成计划，全部由知识缺口承载（见 /gaps 子项粒度）。）
    #    旧版「待补知识」计划（status=knowledge_required）一并归档，不再展示/推荐。
    by_id = {it["id"]: it for it in items}
    existing = _load_plans()
    existing_subitems = {
        p.get("subitem") for p in existing if p.get("status") not in ("archived", "completed")
    }
    archived_old = 0
    for p in existing:
        if p.get("status") == "knowledge_required" and p.get("state") == "待补知识":
            p["status"] = "archived"
            archived_old += 1
    if archived_old:
        _save_plans(existing)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    top_n = sorted(pressure.items(), key=lambda kv: -kv[1]["pressure"])[: max(1, limit)]
    for sid, bucket in top_n:
        it = by_id.get(sid)
        if not it:
            continue
        if sid in existing_subitems:
            continue  # 重复惩罚：同一认知节点已有在建计划，不重复推荐
        k = known.get(sid) or {}
        has_knowledge = bool(k.get("has_knowledge"))
        if not has_knowledge:
            # 本地没有 → 不进内容计划（归知识缺口），仅统计
            continue
        qs = bucket["questions"]
        qs_sorted = sorted(qs, key=lambda x: -x["priority_score"])
        top_q = qs_sorted[0]["question"] if qs_sorted else ""
        rows.append({
            "id": f"p_{uuid.uuid4().hex[:10]}",
            "topic": f"建设「{it['name']}」内容（覆盖 {len(qs)} 个高价值问题）",
            "reason": (
                f"认知节点压力 {round(bucket['pressure'], 2)}："
                f"「{it['name']}」被 {len(qs)} 个客户问题共同依赖（如「{top_q}」），"
                f"企业本地已有相关事实/素材可支撑——建设一个节点解决多题"
            ),
            "target_question": top_q,
            "recommended_content_type": _CTYPE_BY_CAT.get(it.get("category", ""), "文章"),
            "priority": min(100, round(bucket["pressure"] * 100)),
            "gap_id": None,
            "source": "subitem_pressure",  # 认知子项压力算法（内容计划 V1）
            "evidence_level": "C",  # 规则估算（压力来自真实监测统计 + 规则映射），待效果验证
            "status": "planned",
            "state": "待生产",
            "subitem": sid,
            "subitem_name": it["name"],
            "category": it.get("category", ""),
            "subitem_pressure": round(bucket["pressure"], 3),
            "covered_questions": len(qs),
            "coverage_pct": k.get("coverage_pct"),  # 该子项问题被知识支撑的覆盖率（总揽同口径）
            "top_questions": [x["question"] for x in qs_sorted[:3]],
            # 发布前基线（复测对比用：发布后重算同一批问题的监测分数 → 差值 = 内容效果）
            "before_snapshot": {
                "questions": [x["question"] for x in qs],
                "pressure": round(bucket["pressure"], 3),
            },
            "created_at": now,
        })
        if len(rows) >= max(1, limit):
            break

    if rows:
        # 相对归一化：优先级 = 该子项压力 / 最大压力 × 100（top1=100，其余按比例递减，不封顶失真）
        max_p = max(r["subitem_pressure"] for r in rows)
        if max_p > 0:
            for r in rows:
                r["priority"] = min(100, max(1, round(r["subitem_pressure"] / max_p * 100)))
        plans = _load_plans()
        plans.extend(rows)
        _save_plans(plans)

    note = (
        "内容计划 V1（规则版）：问题价值×AI缺口→48 认知子项压力→本地知识检查。"
        "优先级 = 子项压力（越多高价值问题依赖、缺口越大 → 越靠前）；"
        "只输出「本地已有」（企业知识库事实或素材库命中）的子项——本地没有的全部在知识缺口（按 48 子项粒度），"
        "不再生成「待补知识」计划；旧「待补知识」计划已归档。"
    )
    if kernel_note:
        note += kernel_note
    return ok({"items": rows, "total": len(rows), "note": note})


class PublishIn(BaseModel):
    plan_id: str = ""
    # Owner 2026-09-21：发布登记要能记「发到哪、什么时候发的」——没有这两项，
    # 复测只能靠计划内基线，无法回头核对这篇到底发在哪。
    published_url: str = ""
    published_at: str = ""  # ISO 时间；留空 = 用登记时刻


@router.post("/content-publish")
async def content_publish(payload: PublishIn):
    """发布日志（效果反哺闭环第一步）：计划 → 已发布。

    记录发布时的 before_snapshot（基线）+ 发布时间；发布动作本身在内容页人工执行，
    这里只登记（AI 不自动上线，红线不变）。
    """
    plans = _load_plans()
    target = next((p for p in plans if p.get("id") == payload.plan_id), None)
    if not target:
        return ok({"error": f"计划不存在: {payload.plan_id}", "published": False})
    if target.get("status") == "published":
        return ok({"published": True, "dup": True, "plan_id": payload.plan_id})
    now = datetime.now(timezone.utc).isoformat()
    published_url = (payload.published_url or "").strip()
    if published_url and not published_url.lower().startswith(("http://", "https://")):
        return ok({"error": "发布链接需以 http:// 或 https:// 开头", "published": False})
    published_at = now
    raw_at = (payload.published_at or "").strip()
    if raw_at:
        try:
            parsed = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        except ValueError:
            return ok({"error": "发布时间格式无法识别，请用 ISO（如 2026-09-21 或 2026-09-21T10:30:00+08:00）", "published": False})
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        published_at = parsed.astimezone(timezone.utc).isoformat()
    target["status"] = "published"
    target["state"] = "已发布"
    target["published_at"] = published_at
    if published_url:
        target["published_url"] = published_url
    snap = target.setdefault("before_snapshot", {})
    snap["published_at"] = published_at
    # 审计 B8：复测要算「差值」，就必须在**发布这一刻**把基线逐问存下来。
    # 旧实现只存了 questions 列表，复测时无基线可比 → delta 恒 null，impact 退化成
    # 「发布后的绝对正向率分档」，和发布前什么样无关。
    base_questions = [q for q in (snap.get("questions") or []) if q] or [target.get("target_question") or ""]
    snap["stats"] = {q: _question_monitor_stats(q) for q in base_questions if q}
    _save_plans(plans)
    return ok({
        "published": True,
        "plan_id": payload.plan_id,
        "published_at": published_at,
        "published_url": published_url or None,
        "baseline_questions": len(snap["stats"]),
        "note": "已记录发布时间/链接 + 发布时基线（逐问监测统计），复测按基线算差值",
    })


class RecheckIn(BaseModel):
    plan_id: str = ""


@router.post("/content-recheck")
async def content_recheck(payload: RecheckIn):
    """复测对比（效果反哺第二步，手动触发）：已发布计划 → 重算覆盖问题监测分数 → 对比发布前基线。

    impact 规则映射（真实差值，非 LLM）：
      提及率提升 ≥20% → high；>0 → medium；无变化 → neutral；下降 → negative。
    结果落 content_impacts 表（store），供后续算法反哺 HistoricalContentEffect。
    """
    from app.services.store import get_store

    plans = _load_plans()
    target = next((p for p in plans if p.get("id") == payload.plan_id), None)
    if not target:
        return ok({"error": f"计划不存在: {payload.plan_id}", "impact": None})
    if target.get("status") != "published":
        return ok({"error": "计划未发布，先 POST /distill/content-publish", "impact": None})

    before = target.get("before_snapshot") or {}
    before_stats = before.get("stats") or {}
    qs = before.get("questions") or [target.get("target_question") or ""]
    after_questions: list[dict] = []
    deltas: list[float] = []
    for qtext in qs:
        if not qtext:
            continue
        stats = _question_monitor_stats(qtext)
        if not stats["freq"]:
            continue  # 复测后仍无监测 → 跳过（不编造）
        base = before_stats.get(qtext)
        delta = None
        if base and base.get("freq"):
            delta = round((stats["mention_rate"] or 0) - (base["mention_rate"] or 0), 1)
            deltas.append(delta)
        after_questions.append({
            "question": qtext,
            "mention_rate": stats["mention_rate"],
            "positive_rate": stats["positive_rate"],
            "baseline_mention_rate": (base or {}).get("mention_rate"),
            "delta_mention_rate": delta,
        })
    # 审计 B8：impact 用**发布前基线算出的真实差值**；没有基线就不许编结论。
    if not after_questions:
        impact = {"level": "unknown", "note": "复测后仍无监测数据——先跑一轮监测再复测", "delta": None}
    elif not deltas:
        impact = {
            "level": "unknown",
            "note": "缺发布时基线（该计划发布早于基线记录功能）——重发一次或重新发布打点后可比",
            "delta": None,
            "measured": 0,
        }
    else:
        avg_delta = round(sum(deltas) / len(deltas), 1)
        level = "high" if avg_delta >= 20 else "medium" if avg_delta > 0 else "neutral" if avg_delta == 0 else "negative"
        impact = {
            "level": level,
            "delta": avg_delta,  # 平均提及率变化（百分点）
            "measured": len(deltas),
            "note": "与发布时基线相比的平均提及率变化（百分点）",
        }

    store = get_store()
    # 幂等：同一计划反复复测只保留最新一条（旧实现每次追加一行，表里会堆重复记录）
    for old_row in store.load("content_impacts"):
        if old_row.get("plan_id") == payload.plan_id and old_row.get("id"):
            store.delete("content_impacts", old_row["id"])
    store.insert("content_impacts", {
        "plan_id": payload.plan_id,
        "subitem": target.get("subitem"),
        "topic": target.get("topic"),
        "published_at": target.get("published_at"),
        "rechecked_at": datetime.now(timezone.utc).isoformat(),
        "before": {"questions": before.get("questions"), "stats": before_stats},
        "after": after_questions,
        "impact": impact,
    })
    return ok({
        "impact": impact,
        "after": after_questions,
        "note": "impact = 复测提及率 − 发布时基线提及率（真实监测差值）；无基线则如实报 unknown",
    })
