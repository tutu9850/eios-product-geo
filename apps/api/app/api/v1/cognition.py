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
from app.api.v1.monitor import _load_history, _load_items

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


def _flat_answers(limit: int = 100) -> list[dict]:
    """拍平 monitor history → 逐探针 × 逐引擎回答（复刻 monitor.answers 口径）。"""
    hist = _load_history()
    items = _load_items()
    out: list[dict] = []
    for h in reversed(hist):
        qs = h.get("questions")
        if not qs:
            continue
        for q in qs:
            mid = q.get("monitor_id")
            if not mid:
                continue
            meta = next((x for x in items if x.get("monitor_id") == mid), None)
            itype = (meta or {}).get("type") or "question"
            for ed in q.get("engine_detail") or []:
                out.append({
                    "ts": h.get("created_at") or h.get("ts") or "",
                    "monitor_id": mid,
                    "item_type": itype,
                    "query": q.get("query") or q.get("question") or "",
                    "engine": ed.get("engine_name") or "",
                    "mentioned": ed.get("mentioned"),
                    "rank_est": ed.get("rank_est"),
                    "sentiment": ed.get("sentiment"),
                    "snippet": ed.get("snippet") or "",
                    "answer": ed.get("answer") or "",
                })
        if len(out) >= limit:
            break
    return out[:limit]


# ── 场景覆盖矩阵（报告 03）──
@router.get("/coverage")
async def coverage():
    store = get_store()
    questions = store.load("questions")
    answers_list = _flat_answers(100)
    q_count: dict[str, int] = {}
    for q in questions:
        s = _stage_of(str(q.get("question", "")))
        q_count[s] = q_count.get(s, 0) + 1
    a_total: dict[str, int] = {}
    a_mentioned: dict[str, int] = {}
    for a in answers_list:
        s = _stage_of(str(a.get("query", "")))
        a_total[s] = a_total.get(s, 0) + 1
        if a.get("mentioned"):
            a_mentioned[s] = a_mentioned.get(s, 0) + 1
    stages = []
    for s in STAGES:
        total = a_total.get(s["key"], 0)
        mentioned = a_mentioned.get(s["key"], 0)
        cov = round(mentioned / total * 100) if total > 0 else None
        stages.append({
            "key": s["key"],
            "label": s["label"],
            "question_count": q_count.get(s["key"], 0),
            "coverage": cov,
            "decision_coverage": cov,
            "answered_count": total,
        })
    return ok({
        "stages": stages,
        "note": "数据口径：阶段分类基于问题关键词规则；我方覆盖 = 该阶段监测回答中被提及占比；问题数来自客户问题池。",
    })


# ── 竞品分类（报告 05）──
@router.get("/competitors")
async def competitors():
    items = get_store().load("monitor_items")

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

    comps = []
    for c in items:
        if str(c.get("type", "")) != "competitor":
            continue
        name = str(c.get("entity") or c.get("id") or "")
        comps.append({"id": c.get("id", ""), "name": name, **classify(name)})
    groups = [
        {"type": "direct", "label": "直接竞品", "items": [c for c in comps if c["type"] == "direct"]},
        {"type": "substitute", "label": "替代方案", "items": [c for c in comps if c["type"] == "substitute"]},
        {"type": "platform", "label": "平台型", "items": [c for c in comps if c["type"] == "platform"]},
        {"type": "tool", "label": "工具型", "items": [c for c in comps if c["type"] == "tool"]},
        {"type": "content", "label": "内容流量型", "items": [c for c in comps if c["type"] == "content"]},
    ]
    groups = [g for g in groups if g["items"]]
    return ok({
        "groups": groups,
        "note": "分类基于名称关键词启发式规则（可后续用 LLM 精判）；平台/工具/内容型抢的是入口、环节和权重，直接竞品抢的是同一批客户。",
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
async def sources():
    answers_list = _flat_answers(100)
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


@router.get("/portrait")
async def portrait():
    materials = get_store().load("kb")
    texts = "\n".join(f"{m.get('title', '')} {m.get('content', '')}" for m in materials)
    profile_v2 = await _cognition_profile_v2()
    matrix = profile_v2.get("matrix") or []
    ai_by_key = {str(r.get("key")): r for r in matrix}
    items = []
    for d in _PROFILE_DIMS:
        provided = any(w in texts for w in d["words"])
        profile = "资料已提供" if provided else "资料未提供"
        ai = ai_by_key.get(d["key"])
        claims = int(ai.get("claims", 0) or 0) if ai else 0
        grounded = int(ai.get("grounded", 0) or 0) if ai else 0
        # 2026-09-21 修（Owner：「输出正常但不正确」）：
        # 原来「资料未提供 + AI 也没说过」判成「一致」——可这一格根本没有可比对的东西，
        # 页面上却是一个 ✓「一致」（实测：六行全是「资料未提供 / 未评估 0/0 / ✓一致」）。
        # 本文件开头的红线就是「无数据 → 空态，不编 0 分；未评估 ≠ 未认知」，所以先判 claims == 0。
        if claims == 0:
            deviation = "未评估"
        elif not provided:
            deviation = "AI 在说但资料没有"
        elif grounded == 0:
            deviation = "资料有但 AI 未认知"
        else:
            deviation = "一致"
        items.append({
            "key": d["key"],
            "label": d["label"],
            "profile": profile,
            "ai_status": str(ai.get("status", "未评估")) if ai else "未评估",
            "ai_grounded": grounded,
            "ai_claims": claims,
            "deviation": deviation,
        })
    return ok({
        "items": items,
        "ai_health": profile_v2.get("health"),
        "ai_total": profile_v2.get("total", 0),
        "note": "数据口径：资料侧来自已上传内容资产；AI 侧来自 AI 认知评估（监测回答语义分析）",
    })


# ── 认知健康 8 维度（报告 01）──
@router.get("/health")
async def health():
    profile_v2 = await _cognition_profile_v2()
    matrix = profile_v2.get("matrix") or []
    by_key = {str(r.get("key")): r for r in matrix}

    def grounded_pct(key: str) -> int | None:
        m = by_key.get(key)
        if not m:
            return None
        claims = int(m.get("claims", 0) or 0)
        return round(int(m.get("grounded", 0) or 0) / claims * 100) if claims > 0 else None

    metrics = profile_v2.get("metrics") or {}
    answers_list = _flat_answers(100)
    mentioned_count = sum(1 for a in answers_list if a.get("mentioned"))
    mention_rate = round(mentioned_count / len(answers_list) * 100) if answers_list else None

    trust_g, sec_g = grounded_pct("organization"), grounded_pct("security")
    trust = round((trust_g + sec_g) / 2) if trust_g is not None and sec_g is not None else trust_g or sec_g or None
    dims = [
        {"key": "brand", "label": "品牌认知", "score": metrics.get("awareness") or mention_rate or None,
         "basis": f"AI 认识程度 {metrics.get('awareness')}%（主动提到企业占比）" if metrics.get("awareness") is not None else f"监测回答提及率 {mention_rate or 0}%"},
        {"key": "product", "label": "产品认知", "score": grounded_pct("product"), "basis": "产品能力 claim 已理解占比（AI 评估）"},
        {"key": "scene", "label": "场景覆盖", "score": mention_rate or None,
         "basis": f"监测回答被提及占比（{mentioned_count}/{len(answers_list)} 问）" if answers_list else "暂无监测回答"},
        {"key": "trust", "label": "信任证据", "score": trust, "basis": "组织/安全合规 claim 已理解占比均值"},
        {"key": "case", "label": "案例覆盖", "score": grounded_pct("customer"), "basis": "客户案例 claim 已理解占比（AI 评估）"},
        {"key": "price", "label": "价格透明度", "score": grounded_pct("finance"), "basis": "价格信息 claim 已理解占比（AI 评估）"},
        {"key": "diff", "label": "差异化认知", "score": metrics.get("recommendation") or None,
         "basis": f"AI 推荐倾向 {metrics.get('recommendation')}%（正面推荐占比）" if metrics.get("recommendation") is not None else "暂无评估"},
        {"key": "defense", "label": "竞品防御力", "score": metrics.get("understanding") or None,
         "basis": f"AI 理解程度 {metrics.get('understanding')}%（回答与事实一致率）" if metrics.get("understanding") is not None else "暂无评估"},
    ]
    scored = [d for d in dims if d["score"] is not None]
    total = round(sum(d["score"] for d in scored) / len(scored)) if scored else None
    return ok({
        "total": total,
        "dims": dims,
        "note": f"数据口径：全部基于已上传资料与 AI 监测回答计算（不搜外部）；每维可溯源到评估 claim 或监测回答。总分为 {len(scored)}/8 个有数据维度的均值，无数据维度不计入（不编 0 分）。",
    })


# ── 推荐理由/证据链（报告 04）──
@router.get("/reasons")
async def reasons():
    answers_list = _flat_answers(100)
    reasons_out = [
        {"query": a.get("query", ""), "engine": a.get("engine", ""), "snippet": a.get("snippet", ""), "rank": a.get("rank_est")}
        for a in answers_list if a.get("mentioned") and a.get("snippet")
    ][:5]
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
        "note": "推荐理由 = 监测回答中提到企业的真实样本；缺失证据 = 资料有但 AI 未认知的维度。",
    })
