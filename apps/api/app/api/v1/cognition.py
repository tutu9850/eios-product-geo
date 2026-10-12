"""认知汇总接口（S2 搬家，2026-08-19）：从 BFF 本地实现搬到 3002。

来源：yayuai-ui apps/api-nest geo.service.ts 的 6 个本地聚合方法
（coverage/health/portrait/reasons/competitors/sources）。逻辑照搬（词表/规则/
口径一致），数据源换成 3002 租户内数据（store + monitor history + cognition profile）。
口径红线（08-18）：无数据 → null/空态，不编 0 分；「未评估」≠「未认知」。
"""
import re

from fastapi import APIRouter

from app.core.envelope import ok
from app.services.store import get_store
from app.api.v1.monitor import (
    _analyze_answer,
    _load_history,
    _load_items,
    _mention_cands,
)

router = APIRouter(prefix="/api/v1/cognition", tags=["cognition"])

# ── 决策链 6 阶段词表（与 BFF 一致）──
STAGES = [
    {"key": "know", "label": "认知", "words": ["是什么", "有哪些", "怎么样", "了解", "介绍", "什么是", "干嘛的"]},
    {"key": "search", "label": "搜索", "words": ["怎么找", "去哪找", "哪家", "哪里有", "推荐"]},
    {"key": "compare", "label": "比较", "words": ["哪个好", "对比", "区别", "哪家强", "谁家好", "哪个品牌"]},
    {"key": "choose", "label": "选择", "words": ["怎么选", "选哪", "选什么", "选择"]},
    {"key": "decide", "label": "决策", "words": ["值得", "要不要", "该不该", "买不买", "合适吗", "能买吗"]},
    {"key": "trust", "label": "信任", "words": ["口碑", "评价", "靠谱", "可信", "案例", "真实", "靠谱吗"]},
]


def _stage_of(q: str) -> str:
    for s in STAGES:
        if any(w in q for w in s["words"]):
            return s["key"]
    return "other"


# 问题池自带的两套标签（geo_questions.data_json 里真有）→ 6 阶段。
# 2026-09-18 Owner 修复单：关键词规则把 31/49 条问题丢进 other（报告表 0 行），
# 而库里 intent/customer_stage 明明有值 —— 兜底用它，别再整段丢。
_INTENT_STAGE = {
    "认知": "know", "了解": "know", "awareness": "know",
    "搜索": "search", "search": "search",
    "对比": "compare", "比较": "compare", "comparison": "compare",
    "consideration": "compare",
    "使用": "choose", "选择": "choose", "choose": "choose",
    "采购": "decide", "决策": "decide", "购买": "decide", "decision": "decide",
    "信任": "trust", "口碑": "trust", "trust": "trust", "retention": "trust",
}


def _stage_with_intent(q: str, intent: str | None, customer_stage: str | None) -> str:
    """关键词优先；关键词判不出时用问题池自带标签兜底，仍判不出才是 other。"""
    s = _stage_of(q)
    if s != "other":
        return s
    for key in (intent, customer_stage):
        k = str(key or "").strip().lower()
        if k and k in _INTENT_STAGE:
            return _INTENT_STAGE[k]
    return "other"


def _brand_name_and_aliases() -> tuple[str | None, list[str]]:
    """只接受明确且唯一的企业配置；多个品牌对象不能靠列表顺序猜主体。"""
    configured: dict[str, set[str]] = {}
    for it in _load_items():
        if str(it.get("type")) != "brand" or it.get("status") in {"deleted", "inactive", "paused", "archived"}:
            continue
        cfg = it.get("config_json") or {}
        name = str(cfg.get("company") or "").strip()
        if not name:
            continue
        aliases = {str(a).strip() for a in (cfg.get("aliases") or []) if str(a).strip()}
        configured.setdefault(name, set()).update(aliases)
    if len(configured) != 1:
        return None, []
    name, aliases = next(iter(configured.items()))
    return name, sorted(aliases)


def _brand_entries() -> list[dict]:
    """启用中的企业品牌监测对象（各自的公司名与别名）。"""
    out: list[dict] = []
    for it in _load_items():
        if str(it.get("type")) != "brand" or it.get("status") in {"deleted", "inactive", "paused", "archived"}:
            continue
        cfg = it.get("config_json") or {}
        name = str(cfg.get("company") or it.get("entity") or "").strip()
        mid = str(it.get("monitor_id") or "")
        if not name or not mid:
            continue
        out.append({
            "monitor_id": mid,
            "name": name,
            "aliases": sorted({str(a).strip() for a in (cfg.get("aliases") or []) if str(a).strip()}),
        })
    return out


def _brand_options() -> list[dict]:
    return [{"monitor_id": e["monitor_id"], "name": e["name"]} for e in _brand_entries()]


def _subject_scope(monitor_id: str | None) -> dict:
    """前端「监测主体」选择 → 统计范围（与 monitor.overview 同一口径）。

    - 具体 monitor_id：只统计这个品牌对象；同账号里还有别的公司也不互相污染。
    - ``all``：全选，统计全部启用中的品牌对象。
    - 空：只有唯一公司配置时才认；否则要求先选，不猜第一个。
    """
    entries = _brand_entries()
    picked = str(monitor_id or "").strip()
    if picked and picked.lower() == "all":
        chosen, mode = entries, "all"
    elif picked:
        chosen, mode = [e for e in entries if e["monitor_id"] == picked], "selected"
        if not chosen:
            return {"mode": "invalid", "monitor_ids": set(), "names": [], "aliases": [],
                    "error": "选中的监测主体不在这件账号名下"}
    else:
        if len({e["name"] for e in entries}) != 1:
            return {"mode": "pending", "monitor_ids": set(), "names": [], "aliases": [],
                    "error": "主体待确认：缺少唯一明确的公司配置"}
        chosen, mode = entries, "single"
    return {
        "mode": mode,
        "monitor_ids": {e["monitor_id"] for e in chosen},
        "names": sorted({e["name"] for e in chosen}),
        "aliases": sorted({a for e in chosen for a in e["aliases"]}),
        "error": None,
    }


def _primary_brand_answers(batches: int | None = 1, scope: dict | None = None) -> list[dict]:
    """同一口径的品牌探针样本；主体不明确时不产出可判定样本。"""
    sc = scope if scope is not None else _subject_scope(None)
    if sc.get("error"):
        return []
    brand_mids = sc["monitor_ids"]
    return [a for a in _flat_answers(100000, batches=batches)
            if a.get("item_type") == "brand" and str(a.get("monitor_id") or "") in brand_mids]


def _sample_basis(scope: dict | None = None) -> dict:
    """本报告期的样本口径（诚实标注用）：多少问 × 多少家引擎、几家真有回答。

    2026-09-18 Owner 修复单：报告写「6 大引擎」，但 Kimi（余额欠费）与通义千问
    （账户被拒）本期 62/62 未返回任何回答；旧口径只对 mentioned 非空者算比例，
    等于把"没答的引擎"移出分母却不说明 —— 报告因此显得比事实更可信。
    """
    sc = scope if scope is not None else _subject_scope(None)
    if sc.get("error"):
        return {"subject_status": "pending", "subject": None, "note": f"{sc['error']}，当前不统计样本。"}
    brand_mids = sc["monitor_ids"]
    hist = _load_history()
    if not hist:
        return {}
    h = hist[-1]
    engines: dict[str, dict] = {}
    brand_questions = [q for q in (h.get("questions") or []) if str(q.get("monitor_id") or "") in brand_mids]
    question_total = len(brand_questions)
    latest_answers = _primary_brand_answers(batches=1, scope=sc)
    for row in latest_answers:
        name = str(row.get("engine") or "—")
        e = engines.setdefault(name, {"name": name, "asked": 0, "answered": 0, "mentioned": 0, "error": None})
        e["asked"] += 1
        if row.get("answered"):
            e["answered"] += 1
            if row.get("mentioned"):
                e["mentioned"] += 1
        if row.get("error") and not e["error"]:
            e["error"] = str(row["error"])[:100]
    rows = sorted(engines.values(), key=lambda x: (-x["answered"], x["name"]))
    effective = [e["name"] for e in rows if e["answered"] > 0]
    silent = [e["name"] for e in rows if e["answered"] == 0]
    return {
        "batch_at": h.get("created_at") or "",
        "subject_status": "confirmed",
        "subject": "、".join(sc["names"]),
        "question_total": question_total,
        "engine_total": len(rows),
        "engine_effective": len(effective),
        "engines": rows,
        "silent_engines": silent,
        "note": (
            f"本期 {question_total} 问 × {len(rows)} 家引擎；"
            f"{len(effective)} 家返回有效回答"
            + (f"，{len(silent)} 家本期未返回任何回答（{'、'.join(silent)}），已从分母剔除" if silent else "")
            + "。"
        ),
    }


def _flat_answers(limit: int = 100, batches: int | None = None, monitor_id: str | None = None) -> list[dict]:
    """拍平 monitor history → 逐探针 × 逐引擎回答（复刻 monitor.answers 口径）。

    2026-09-18 Owner 修复单：对**存下来的原始回答**用当前判定规则复算
    mentioned / recognition / sentiment。
    原因：历史行是旧规则写的（把"AI 明确说不认识"记成 mentioned=True），
    不复算的话报告 03（覆盖率）与 04（样本）会各说各话。同一份语料、同一套规则。
    """
    hist = _load_history()
    items = _load_items()
    out: list[dict] = []
    seen_batches = 0
    for h in reversed(hist):
        if batches is not None and seen_batches >= batches:
            break
        seen_batches += 1
        qs = h.get("questions")
        if not qs:
            continue
        for q in qs:
            mid = q.get("monitor_id")
            if not mid:
                continue
            if monitor_id and monitor_id.lower() != "all" and str(mid) != monitor_id:
                continue
            meta = next((x for x in items if x.get("monitor_id") == mid), None)
            itype = (meta or {}).get("type") or "question"
            # 每一行用**它自己那个监测对象**的公司名复算：同账号里多个品牌不再互相污染
            cfg = (meta or {}).get("config_json") or {}
            item_company = str(cfg.get("company") or (meta or {}).get("entity") or "").strip() or None
            item_aliases = list(cfg.get("aliases") or [])
            for ed in q.get("engine_detail") or []:
                answer = ed.get("answer") or ""
                mentioned = ed.get("mentioned")
                recognition = ed.get("recognition")
                sentiment = ed.get("sentiment")
                if answer and item_company:
                    parsed = _analyze_answer(item_company, answer, item_aliases)
                    mentioned = parsed["mentioned"]
                    recognition = parsed["recognition"]
                    sentiment = parsed["sentiment"]
                elif answer:
                    recognition = recognition or "unknown"
                else:
                    # 没有原文（历史只存了 snippet）→ 只能沿用落库时的标记
                    recognition = recognition or (
                        "unknown" if mentioned is None else "recognised" if mentioned else "not_mentioned"
                    )
                out.append({
                    "ts": h.get("created_at") or h.get("ts") or "",
                    "monitor_id": mid,
                    "item_type": itype,
                    "item_entity": str((meta or {}).get("entity") or ""),
                    "query": q.get("query") or q.get("question") or "",
                    "engine": ed.get("engine_name") or "",
                    "mentioned": mentioned,
                    "answered": mentioned is not None and bool(answer or ed.get("snippet")),
                    "recognition": recognition,
                    "rank_est": ed.get("rank_est"),
                    "sentiment": sentiment,
                    "subjects": ed.get("subjects"),
                    "snippet": ed.get("snippet") or "",
                    "answer": answer,
                    "error": ed.get("error"),
                })
        if len(out) >= limit:
            break
    return out[:limit]


# ── 场景覆盖矩阵（报告 03）──
@router.get("/coverage")
async def coverage(monitor_id: str | None = None):
    store = get_store()
    scope = _subject_scope(monitor_id)
    # 问题池和回答必须使用同一主体范围；否则选择某品牌后，回答是该品牌，
    # question_count 却把账号里其他品牌/产品的问题也算进来，阶段图的分子分母会错位。
    all_questions = store.load("questions")
    scoped_ids = scope["monitor_ids"]
    questions = [
        q for q in all_questions
        if str(q.get("monitor_id") or "") in scoped_ids
    ] if scoped_ids else []
    answers_list = _primary_brand_answers(scope=scope)
    q_count: dict[str, int] = {}
    q_other: list[str] = []
    for q in questions:
        text = str(q.get("question", ""))
        s = _stage_with_intent(text, q.get("intent"), q.get("customer_stage"))
        q_count[s] = q_count.get(s, 0) + 1
        if s == "other":
            q_other.append(text)
    a_probe: dict[str, int] = {}
    a_answered: dict[str, int] = {}
    a_mentioned: dict[str, int] = {}
    for a in answers_list:
        s = _stage_with_intent(str(a.get("query", "")), None, None)
        a_probe[s] = a_probe.get(s, 0) + 1
        if not a.get("answered"):
            continue
        a_answered[s] = a_answered.get(s, 0) + 1
        if a.get("mentioned"):
            a_mentioned[s] = a_mentioned.get(s, 0) + 1
    stages = []
    for s in STAGES:
        total = a_answered.get(s["key"], 0)
        mentioned = a_mentioned.get(s["key"], 0)
        cov = round(mentioned / total * 100) if total > 0 else None
        stages.append({
            "key": s["key"],
            "label": s["label"],
            "question_count": q_count.get(s["key"], 0),
            "coverage": cov,
            "decision_coverage": cov,
            "answered_count": total,
            "probe_count": a_probe.get(s["key"], 0),
        })
    classified = len(questions) - len(q_other)
    return ok({
        "scope": {
            "mode": scope["mode"],
            "scope_required": bool(scope.get("error")),
            "monitor_id": monitor_id,
            "subjects": scope["names"],
        },
        "stages": stages,
        "question_total": len(questions),
        "classified_count": classified,
        "unclassified_count": len(q_other),
        "unclassified_samples": q_other[:5],
        "note": (
            f"数据口径：阶段分类先用问题关键词规则，判不出时用问题池自带 intent/customer_stage 兜底"
            f"（已归类 {classified}/{len(questions)}）；"
            "我方覆盖 = 该阶段真实作答中被判定提及企业的占比；未作答引擎不进分母，"
            "提及判定已排除「AI 明确表示不认识该企业」的回答。"
            + (f"当前主体不可用：{scope['error']}。" if scope.get("error") else "")
        ),
    })


# ── 竞品分类（报告 05）──
_COMPETITOR_COLUMN_LIMIT = 6  # 矩阵最多列数（含"我"），避免 PDF 横向溢出


def _split_pair(entity: str) -> str:
    """监测对象 entity 形如「笔革家居 vs 岚亭装饰」→ 取竞品侧名字。"""
    n = str(entity or "").strip()
    if " vs " in n:
        return n.split(" vs ", 1)[1].strip()
    if "vs" in n.lower():
        parts = re.split(r"\s*vs\s*", n, flags=re.I)
        if len(parts) > 1:
            return parts[-1].strip()
    return n


def _pair_brand(entity: str) -> str:
    n = str(entity or "").strip()
    parts = re.split(r"\s*vs\s*", n, maxsplit=1, flags=re.I)
    return parts[0].strip() if len(parts) > 1 else ""


def _pct(part: int, whole: int) -> int | None:
    return round(part / whole * 100) if whole > 0 else None


def _avg(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 1) if vals else None


@router.get("/competitors")
async def competitors(monitor_id: str | None = None):
    items = get_store().load("monitor_items")
    scope = _subject_scope(monitor_id)
    own_names = set(scope["names"])
    subject_label = "、".join(scope["names"])

    def classify(name: str) -> dict:
        n = str(name or "")
        if re.search(r"住小帮|好好住|小红书|抖音|知乎|大众点评|B站|贴吧|微博|平台", n):
            return {"type": "platform", "label": "平台型", "note": "抢客户入口与流量"}
        if re.search(r"酷家乐|三维家|酷大师|草图大师|软件|工具|SAAS|SaaS", n):
            return {"type": "tool", "label": "工具型", "note": "解决客户决策中的某个环节"}
        if re.search(r"全屋定制|定制|DIY|自己动手|独立设计师", n):
            return {"type": "substitute", "label": "替代方案", "note": "客户换一种方式解决问题"}
        if re.search(r"博主|自媒体|测评|攻略|账号|内容", n):
            return {"type": "content", "label": "内容流量型", "note": "抢 AI 推荐权重"}
        return {"type": "direct", "label": "直接竞品", "note": "争夺同一批客户需求"}

    # 竞品指标来自**同一批竞品探针问题**下 subjects 的双主体判定（我方 vs 它）——
    # 不是把名字念一遍。2026-09-18 Owner 修复单：旧实现「对象」列把 5 个竞品
    # join('、') 塞进一格、差距列恒为「待数据」，而库里 2754 条 subjects 没人用。
    rows = _flat_answers(6000)

    comps = []
    for c in items:
        if str(c.get("type", "")) != "competitor":
            continue
        name = str(c.get("entity") or c.get("id") or "")
        short = _split_pair(name)
        mid = str(c.get("monitor_id") or "")
        mine = [
            r for r in rows
            if own_names
            and _pair_brand(name) in own_names
            and r.get("monitor_id") == mid
            and (r.get("subjects") or {}).get("company") is not None
        ]
        brand_hit = [r for r in mine if (r["subjects"]["company"] or {}).get("mentioned")]
        comp_hit = [r for r in mine if (r["subjects"].get("competitor") or {}).get("mentioned")]
        comp_sent = {"positive": 0, "neutral": 0, "negative": 0}
        for r in comp_hit:
            s = (r["subjects"].get("competitor") or {}).get("sentiment")
            if s in comp_sent:
                comp_sent[s] += 1
        brand_sent = {"positive": 0, "neutral": 0, "negative": 0}
        for r in brand_hit:
            s = (r["subjects"]["company"] or {}).get("sentiment")
            if s in brand_sent:
                brand_sent[s] += 1
        brand_rank = _avg([float((r["subjects"]["company"] or {}).get("rank_est")) for r in brand_hit
                           if (r["subjects"]["company"] or {}).get("rank_est")])
        comp_rank = _avg([float((r["subjects"].get("competitor") or {}).get("rank_est")) for r in comp_hit
                          if (r["subjects"].get("competitor") or {}).get("rank_est")])
        b_rate, c_rate = _pct(len(brand_hit), len(mine)), _pct(len(comp_hit), len(mine))
        b_pos_rate = _pct(brand_sent["positive"], len(mine))
        c_pos_rate = _pct(comp_sent["positive"], len(mine))
        gap = (b_rate - c_rate) if (b_rate is not None and c_rate is not None) else None
        # 提及覆盖率不能推导胜负或推荐结论。
        verdict = "不可判胜负；仅显示提及覆盖率"
        evidence = [
            {
                "query": r.get("query", ""),
                "engine": r.get("engine", ""),
                "comp_rank_est": (r["subjects"].get("competitor") or {}).get("rank_est"),
                "snippet": (r.get("snippet") or "")[:160],
            }
            for r in comp_hit[:2]
        ]
        comps.append({
            "id": c.get("id", ""),
            "name": name,
            "short_name": short or name,
            **classify(name),
            "samples": len(mine),
            "brand_mentioned": len(brand_hit),
            "brand_rate": b_rate,
            "brand_rank_avg": brand_rank,
            "brand_rank_n": sum(1 for r in brand_hit if (r["subjects"]["company"] or {}).get("rank_est") is not None),
            "competitor_mentioned": len(comp_hit),
            "competitor_rate": c_rate,
            "competitor_rank_avg": comp_rank,
            "competitor_rank_n": sum(1 for r in comp_hit if (r["subjects"].get("competitor") or {}).get("rank_est") is not None),
            "competitor_sentiment": comp_sent,
            "brand_sentiment": brand_sent,
            "brand_positive_rate": b_pos_rate,
            "competitor_positive_rate": c_pos_rate,
            "gap": None,
            "verdict": verdict,
            "evidence": evidence,
        })
    groups = [
        {"type": "direct", "label": "直接竞品", "items": [c for c in comps if c["type"] == "direct"]},
        {"type": "substitute", "label": "替代方案", "items": [c for c in comps if c["type"] == "substitute"]},
        {"type": "platform", "label": "平台型", "items": [c for c in comps if c["type"] == "platform"]},
        {"type": "tool", "label": "工具型", "items": [c for c in comps if c["type"] == "tool"]},
        {"type": "content", "label": "内容流量型", "items": [c for c in comps if c["type"] == "content"]},
    ]
    groups = [g for g in groups if g["items"]]

    # 对比矩阵：行 = 维度，列 = 对象（我 + 各竞品），满足"一个对象一列"
    cols = comps[:_COMPETITOR_COLUMN_LIMIT]
    matrix = None
    if cols:
        def cell(v, suffix: str = "") -> str:
            return "—" if v is None else f"{v}{suffix}"

        matrix = {
            "columns": [f"我（{subject_label or '本企业'}）"] + [c["short_name"] for c in cols],
            "rows": [
                {"label": "被提及率", "values": ["—"] + [cell(c["competitor_rate"], "%") for c in cols]},
                {"label": "正面描述率", "values": ["—"] + [cell(c["competitor_positive_rate"], "%") for c in cols]},
                {"label": "平均句序位（仅文本位置，不代表推荐顺序）", "values": ["—"] + [cell(c["competitor_rank_avg"]) + (f"（n={c['competitor_rank_n']}）" if c["competitor_rank_n"] else "") for c in cols]},
                {"label": "正面提及次数", "values": ["—"] + [str(c["competitor_sentiment"]["positive"]) for c in cols]},
                {"label": "被判定样本数", "values": ["—"] + [str(c["samples"]) for c in cols]},
                {"label": "我方 vs 它", "values": ["—"] + [c["verdict"] for c in cols]},
            ],
        }
        # 每个竞品对使用不同探针池，左侧我方汇总会跨问题、对象重复计数，故不合并。

    return ok({
        "subject": {
            "name": subject_label or None,
            "status": "pending" if scope["error"] else "confirmed",
            "error": scope["error"],
        },
        "subjects": _brand_options(),
        "groups": groups,
        "matrix": matrix,
        "note": (
            (f"主体：{subject_label}。" if subject_label else "主体待确认：缺少唯一明确的公司配置，竞品指标不可判定。")
            + "每个竞品对按各自探针池单独计算，不跨竞品汇总我方数据；不同探针池不可直接横向比较。"
            "「平均句序位」是回答文本中名称出现位置的均值，只对有位置记录的回答计算并标明 n，不代表推荐顺序；分类为名称关键词启发式。"
        ),
    })


# ── 信息来源贡献度（报告 06）：监测回答文本 URL/平台名统计 ──
_PLATFORMS = [
    {"key": "xiaohongshu", "label": "小红书", "re": re.compile(r"xiaohongshu\.com|小红书")},
    {"key": "zhihu", "label": "知乎", "re": re.compile(r"zhihu\.com|知乎")},
    {"key": "douyin", "label": "抖音", "re": re.compile(r"douyin\.com|抖音")},
    {"key": "dianping", "label": "大众点评", "re": re.compile(r"dianping\.com|大众点评|点评")},
    {"key": "wechat", "label": "微信公众号", "re": re.compile(r"weixin\.qq|wechat|公众号")},
    {"key": "weibo", "label": "微博", "re": re.compile(r"weibo\.com|微博")},
    {"key": "bilibili", "label": "B站", "re": re.compile(r"bilibili|哔哩")},
    {"key": "news", "label": "新闻媒体", "re": re.compile(r"news\.sina|163\.com|news\.qq|sohu\.com|thepaper|ifeng")},
]


@router.get("/sources")
async def sources(monitor_id: str | None = None):
    scope = _subject_scope(monitor_id)
    if scope["error"]:
        return ok({
            "items": [],
            "total": 0,
            "scope": {"mode": scope["mode"], "monitor_ids": sorted(scope["monitor_ids"]), "names": scope["names"]},
            "note": f"{scope['error']}；请选择一个监测主体后再看回答中的外部来源。",
        })
    answers_list = _flat_answers(
        100000,
        batches=1,
        monitor_id=monitor_id if monitor_id and monitor_id.lower() != "all" else None,
    )
    texts = "\n".join(f"{a.get('snippet', '')} {a.get('answer', '')}" for a in answers_list).lower()
    counts: dict[str, int] = {}
    for p in _PLATFORMS:
        m = p["re"].findall(texts)
        if m:
            counts[p["key"]] = len(m)
    total = sum(counts.values())
    items = [
        {**p, "count": counts[p["key"]], "share": round(counts[p["key"]] / total * 100)}
        for p in _PLATFORMS if counts.get(p["key"])
    ] if total > 0 else []
    items.sort(key=lambda x: -x["count"])
    return ok({
        "items": items,
        "total": total,
        "note": "数据口径：从监测回答文本提取的来源链接/平台名统计（非 LLM 精判）；官网来源需官网资料分析（见 AI 认知卡官网分析）。",
    })


# ── 认知画像（报告 02）：资料侧（内容资产）vs AI 侧（V2 matrix）+ 偏差 ──
_PROFILE_DIMS = [
    {"key": "business", "label": "业务定位", "words": ["专注", "定位", "成立于", "总部", "主营", "提供", "致力于"]},
    {"key": "product", "label": "产品能力", "words": ["产品", "服务", "方案", "系统", "功能", "设计", "技术"]},
    {"key": "customer", "label": "客户案例", "words": ["案例", "项目", "作品", "实景", "效果图", "客户", "合作"]},
    {"key": "finance", "label": "价格信息", "words": ["价格", "报价", "多少钱", "费用", "预算", "成本", "性价比"]},
    {"key": "organization", "label": "团队资质", "words": ["团队", "资质", "证书", "认证", "设计师", "工程师"]},
    {"key": "security", "label": "安全合规", "words": ["安全", "隐私", "合规", "保密", "数据保护"]},
]


async def _cognition_profile_v2() -> dict:
    """内部读 AI 认知评估 V2（distill/cognition/profile 同源，直接 await）。"""
    from app.api.v1.distill import cognition_profile_v2 as _cp

    try:
        r = await _cp()
        return r.get("data") or {} if isinstance(r, dict) else {}
    except Exception:
        return {}


# 真实资料源（企业自己上传 / 人工录入）。
# 2026-09-18 Owner 修复单：`generated` = 系统按缺口自动生成的文章，
# 不能算「企业已提供这份资料」。dev 真库 11 篇 kb 全是 generated、企业真资料 0 篇，
# 旧口径却按"关键词子串出现在任意 kb 全文"就写「资料已提供」→ 名不副实。
_REAL_SOURCE_TYPES = ("upload", "manual", "file", "document", "kb_upload", "enterprise")


def _kb_kind(m: dict) -> str:
    return str(m.get("source_type") or m.get("source") or "").strip().lower()


@router.get("/portrait")
async def portrait():
    materials = get_store().load("kb")
    real = [m for m in materials if _kb_kind(m) in _REAL_SOURCE_TYPES]
    generated = [m for m in materials if _kb_kind(m) == "generated"]
    texts = "\n".join(f"{m.get('title', '')} {m.get('content', '')}" for m in real)
    profile_v2 = await _cognition_profile_v2()
    matrix = profile_v2.get("matrix") or []
    ai_by_key = {str(r.get("key")): r for r in matrix}
    items = []
    for d in _PROFILE_DIMS:
        evidence = []
        for m in real:
            blob = f"{m.get('title', '')} {m.get('content', '')}"
            hits = [w for w in d["words"] if w in blob]
            if hits:
                evidence.append({
                    "title": str(m.get("title") or "(无标题)")[:70],
                    "source_type": _kb_kind(m),
                    "matched": hits[:3],
                })
            if len(evidence) >= 3:
                break
        provided = bool(evidence)
        # 2026-09-23 Owner 修复单：「资料已提供」是二值断言——命中一个宽词（"产品""客户"）
        # 就写成"这份资料提供过"，看起来比事实饱满。改成只报可核对的事实：命中几篇 + 命中词，
        # 明细（标题 / 命中词）仍随 evidence 一起返回。
        if not provided:
            profile = "暂无可核验内容资产"
        else:
            hit_words = "、".join(sorted({w for e in evidence for w in e["matched"]})[:3])
            profile = f"命中 {len(evidence)} 篇（{hit_words}）"
        ai = ai_by_key.get(d["key"])
        claims = int(ai.get("claims", 0) or 0) if ai else 0
        grounded = int(ai.get("grounded", 0) or 0) if ai else 0
        if not provided and claims == 0:
            # 旧口径在这里输出「一致」= 把"资料没有、AI 也没评估"（两个都没有）说成一致。
            # 无数据不是一致。
            deviation = "无数据"
        elif not provided:
            deviation = "AI 在说但资料没有"
        elif claims == 0:
            deviation = "AI 未评估"
        elif grounded == 0:
            deviation = "资料有但 AI 未认知"
        else:
            deviation = "一致"
        items.append({
            "key": d["key"],
            "label": d["label"],
            "profile": profile,
            "profile_basis": (
                "命中真实资料：" + "；".join(f"{e['title']}（{'/'.join(e['matched'])}）" for e in evidence)
                if evidence
                else "未在任何企业上传/录入资料里找到该维度的依据"
            ),
            "evidence_count": len(evidence),
            "evidence": evidence,
            "ai_status": str(ai.get("status", "未评估")) if ai else "未评估",
            "ai_grounded": grounded,
            "ai_claims": claims,
            "deviation": deviation,
        })
    return ok({
        "items": items,
        "materials": {
            "total": len(materials),
            "real": len(real),
            "generated": len(generated),
        },
        "ai_health": profile_v2.get("health"),
        "ai_total": profile_v2.get("total", 0),
        "evaluated_at": profile_v2.get("evaluated_at"),
        "material_count": len(materials),
        "note": (
            "数据口径：资料侧**只认企业上传/人工录入的正式正文**"
            f"（当前真实资料 {len(real)} 篇、系统自动生成文章 {len(generated)} 篇不计入）；"
            "「命中 N 篇」= 下面这些词出现在企业上传正文里（见每格的命中词与标题），"
            "只是命中，不代表该维度的资料齐全；"
            "AI 侧来自 AI 认知评估（监测回答语义分析）；资料与 AI 都没数据 = 「无数据」，不写成「一致」。"
            "监测结果和系统生成内容不代表企业知识库正式资料。"
        ),
    })


# ── 认知健康 8 维度（报告 01）──
@router.get("/health")
async def health(monitor_id: str | None = None):
    scope = _subject_scope(monitor_id)
    confirmed = scope["error"] is None
    profile_v2 = await _cognition_profile_v2()
    matrix = profile_v2.get("matrix") or []
    by_key = {str(r.get("key")): r for r in matrix}

    def grounded_pct(key: str) -> int | None:
        if int(profile_v2.get("total", 0) or 0) <= 0:
            return None
        m = by_key.get(key)
        if not m:
            return None
        claims = int(m.get("claims", 0) or 0)
        return round(int(m.get("grounded", 0) or 0) / claims * 100) if claims > 0 else None

    metrics = profile_v2.get("metrics") or {}
    answers_list = _primary_brand_answers(scope=scope) if confirmed else []
    answered_list = [a for a in answers_list if a.get("answered")]
    mentioned_count = sum(1 for a in answered_list if a.get("mentioned"))
    mention_rate = round(mentioned_count / len(answered_list) * 100) if answered_list else None

    trust_g, sec_g = grounded_pct("organization"), grounded_pct("security")
    trust = round((trust_g + sec_g) / 2) if trust_g is not None and sec_g is not None else trust_g or sec_g or None
    dims = [
        {"key": "brand", "label": "品牌认知", "score": metrics.get("awareness") if int(profile_v2.get("total", 0) or 0) > 0 else None,
         "basis": f"AI 认知评估：{metrics.get('awareness')}%" if metrics.get("awareness") is not None and int(profile_v2.get("total", 0) or 0) > 0 else "暂无有效认知评估；提及不等于正确认识"},
        {"key": "product", "label": "产品认知", "score": grounded_pct("product"), "basis": "产品能力 claim 已理解占比（AI 评估）"},
        {"key": "scene", "label": "场景覆盖", "score": None,
         "basis": "尚无按决策场景判定的有效样本；品牌提及率不能代表场景覆盖"},
        {"key": "trust", "label": "信任证据", "score": trust, "basis": "组织/安全合规 claim 已理解占比均值"},
        {"key": "case", "label": "案例覆盖", "score": grounded_pct("customer"), "basis": "客户案例 claim 已理解占比（AI 评估）"},
        {"key": "price", "label": "价格透明度", "score": grounded_pct("finance"), "basis": "价格信息 claim 已理解占比（AI 评估）"},
        {"key": "diff", "label": "差异化认知", "score": metrics.get("recommendation") if int(profile_v2.get("total", 0) or 0) > 0 else None,
         "basis": f"AI 推荐倾向 {metrics.get('recommendation')}%（正面推荐占比）" if metrics.get("recommendation") is not None else "暂无评估"},
        {"key": "defense", "label": "竞品防御力", "score": metrics.get("understanding") if int(profile_v2.get("total", 0) or 0) > 0 else None,
         "basis": f"AI 理解程度 {metrics.get('understanding')}%（回答与事实一致率）" if metrics.get("understanding") is not None else "暂无评估"},
    ]
    if not confirmed:
        for d in dims:
            d["score"] = None
            d["basis"] = f"{scope['error']}；请先在下方选择监测主体，再判定这 8 个维度"
    scored = [d for d in dims if d["score"] is not None]
    total = round(sum(d["score"] for d in scored) / len(scored)) if scored else None
    sample = _sample_basis(scope)
    return ok({
        "total": total,
        "dims": dims,
        "sample": sample,
        "sample_size": profile_v2.get("total", 0) if confirmed else 0,
        "subject_status": "confirmed" if confirmed else "pending",
        "subject_name": "、".join(scope["names"]) if confirmed else None,
        "subject_error": scope["error"],
        "scope_mode": scope["mode"],
        "subjects": _brand_options(),
        "evaluation_scope": "语义评估为历史聚合；现有评估记录不含监测对象 ID，不能与最近品牌批次逐条对齐。",
        "evaluated_at": profile_v2.get("evaluated_at"),
        "note": (
            "数据口径：主体由「监测主体」选择决定（可全选汇总），不再靠列表顺序猜；"
            "品牌认知与场景覆盖不用提及率代替。"
            f"总分为 {len(scored)}/8 个有数据维度的均值，无数据维度不计入。"
        ),
    })


# ── 推荐理由/证据链（报告 04）──
@router.get("/reasons")
async def reasons():
    # 名称子串识别不能证明回答说的是同一实体；现有数据没有可靠的实体消歧标注。
    # 因此不将同名或幻觉回答包装成「AI 为什么提到你」样本。
    reasons_out: list[dict] = []
    src_list: list[dict] = []
    try:
        from app.api.v1.monitor import sources as monitor_sources
        r = await monitor_sources()
        data = r.get("data") or {}
        src_list = data.get("sources") or []
    except Exception:
        src_list = []
    portrait_data = None
    try:
        portrait_data = (await portrait()).get("data") or {}
    except Exception:
        portrait_data = {}
    missing = [
        i["label"] for i in (portrait_data.get("items") or [])
        if i.get("deviation") == "资料有但 AI 未认知"
    ]
    return ok({
        "reasons": reasons_out,
        "sources": src_list[:6],
        "missing_evidence": missing,
        "note": (
            "名称匹配不能确认回答指向当前企业，实体消歧标注补齐前不展示「AI 为什么提到你」样本；"
            "缺失证据 = 资料有但 AI 未认知的维度。"
        ),
    })
