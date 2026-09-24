"""Pure domain helpers for distillation/question intelligence."""
import json
import re

_INTENTS = ("认知", "对比", "采购", "信任", "使用")
_STAGES = ("awareness", "consideration", "decision", "retention")

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

