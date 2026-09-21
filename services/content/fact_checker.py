"""事实密度检查器（认知编译器 · 事实强制注入层）

生成后校验：文本必须含 ≥N 个来自企业知识库的数据点（数字/实体/时间），
缺则返回 needs_rewrite + 缺失建议（前端可一键重写）。

算法（启发式但可解释）：
- 知识对象 → 提取「数字/年份锚点」（词边界匹配）——**只有数字/年份命中才算该事实注入**
- 实体名（企业名等）仅作辅助展示，**不单独计 hit**（防"正文只提企业名"刷绿）
- 密度分 = min(命中事实数 / 期望数, 1.0)；期望数 = min(TARGET, 含数字锚点的事实数)

2026-09-21 修复（用户可见标签）：
知识库命中里的 ``value`` 是「这条对象出现在哪段原文里」（实测一张表 502 字），
不是「事实值」。旧实现把 ``canonical_name + value[:60]`` 当标签，于是前端
「补充以下企业事实」列表里出现的是被截断的表格原文。现在标签只用
实体名 + 命中的数字锚点，永不回吐原文。
"""
import re
from typing import Any

TARGET_FACTS = 3  # 最低企业知识库事实点

#: 用户可见标签的长度上限（实体名 + 数字锚点，绝不放原文）
LABEL_MAX = 48

# 数字锚点：词边界（防 "21" in "2021" 假阳性），单位可选
_NUM_PAT = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)\s*[个家%万人元项次款种台版期年]?")
_YEAR_PAT = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
# 纯企业名/占位词（不参与密度计分——正文必然出现，不能当事实注入证据）
_BANNED_NAMES = {
    "华信精工", "云启智能", "云启智能科技有限公司", "明辉医药", "星河康养",
    "公司", "企业", "客户", "产品", "员工", "合作",
}


def _anchors_in(text: str) -> list[str]:
    """一段文本里的数字/年份锚点（词边界匹配 + 去重）。"""
    anchors = [m.group(1) for m in _NUM_PAT.finditer(text)]
    anchors += [m.group(1) for m in _YEAR_PAT.finditer(text)]
    return list(dict.fromkeys(anchors))


def _own_evidence(fact: dict) -> str:
    """这条对象**自己那一行**的原文。

    知识库命中的 ``value`` 是整段原文（一张表 = 20 个实体共用同一段），
    整段里的数字属于表里**别的行**。所以先找含实体名的那一行；找不到才退回整段。
    """
    value = str(fact.get("value") or "")
    if not value:
        return ""
    name = _one_line(fact.get("canonical_name") or fact.get("name"))
    if name and "\n" in value:
        for line in value.splitlines():
            if name in line:
                return line
    return value


def _extract_anchors(fact: dict) -> tuple[list[str], str]:
    """提取 (数字/年份锚点, 实体名锚点)。数字锚点词边界匹配。"""
    num_anchors = _anchors_in(_own_evidence(fact))
    name = (fact.get("canonical_name") or "").strip()
    if name in _BANNED_NAMES or len(name) < 2:
        name = ""
    return num_anchors, name


def _one_line(text: Any) -> str:
    """压成单行：换行/表格都塌成一个空格，防把多行原文当一句话用。"""
    return " ".join(str(text or "").split())


def _fact_label(fact: dict, anchors: list[str]) -> str:
    """人话标签 = 实体名 + 命中的数字锚点（如「抖音（98000）」）。

    ``value`` 是「这条知识对象出现在哪段原文里」，不是「这条事实是什么」，
    所以只在 **连名字都没有、且原文本来就是一句话**时才用它，否则退回出处资料名。

    2026-09-21（Owner：内容生成消费「文档切块 + 实体」）：**文档切块**自己就是材料，
    它的标签用资料名 + 数据点个数 —— 一张表里有几十个数字，逐个列出来是噪音。
    """
    if fact.get("kind") == "document_chunk":
        doc = _one_line(fact.get("canonical_name") or fact.get("document_title"))
        if not doc:
            return ""
        return (f"{doc}（{len(anchors)} 个数据点）" if anchors else doc)[:LABEL_MAX]
    name = _one_line(fact.get("canonical_name") or fact.get("name"))
    tail = "、".join(a for a in anchors[:3])
    if name and tail:
        return f"{name}（{tail}）"[:LABEL_MAX]
    if name:
        return name[:LABEL_MAX]
    # 连名字都没有：原文本身是一句话才用，否则退回出处资料名（空标签由调用方丢弃）
    value = str(fact.get("value") or "")
    if value and "\n" not in value.strip() and "|" not in value:
        return _one_line(value)[:LABEL_MAX]
    return _one_line(fact.get("document_title"))[:LABEL_MAX]


def _num_hit(text: str, num_anchors: list[str]) -> bool:
    """数字锚点词边界命中（防 "21" 命中 "2021"）。"""
    return any(re.search(rf"(?<!\d){re.escape(a)}(?!\d)", text) for a in num_anchors)


def score_fact_density(text: str, knowledge_facts: list[dict]) -> dict[str, Any]:
    """计算文本的 企业知识库事实密度。返回 {score, hit_facts, missing_facts, needs_rewrite, suggestion}"""
    eligible = [f for f in knowledge_facts if _extract_anchors(f)[0]]
    if not eligible:
        # 2026-09-21：分两种「没数据」——知识库压根没有事实，vs 有事实但都不带数字。
        # 后者在 GEO 现在的口径下很常见（正式事实多是组织/职责句，数字在原始文档切块里），
        # 一律说成「暂无该企业带数据的内容」是不准确的。
        suggestion = (
            "企业知识库里的正式事实都不含数字/时间，本维度无法注入具体数据"
            if knowledge_facts
            else "企业知识库里暂无该企业带数据的内容（数字/年份），无法注入具体数据（内容只能通用介绍）"
        )
        return {
            "score": 0.0,
            "hit_facts": [],
            "missing_facts": [],
            "needs_rewrite": True,
            "suggestion": suggestion,
        }
    hits: list[str] = []
    miss: list[str] = []
    for f in eligible:
        num_anchors, _name = _extract_anchors(f)
        matched = _num_hit(text, num_anchors)
        label = _fact_label(f, num_anchors)
        (hits if matched else miss).append(label)
    # 同一份原文会带出多个实体（M-001/抖音/吴鑫宇…），去重防刷屏
    hits = list(dict.fromkeys(h for h in hits if h))
    miss = list(dict.fromkeys(m for m in miss if m))
    # 分母自适应：期望数不超过可用事实池（仅 1 条带数字事实时命中即达标）
    denom = min(TARGET_FACTS, len(eligible))
    score = min(len(hits) / denom, 1.0)
    needs_rewrite = len(hits) < denom
    suggestion = ""
    if needs_rewrite and miss:
        suggestion = "把企业知识库里的这些数据写进内容（带数字/时间最易被 AI 引用）：\n" + "\n".join(
            f"- {m}" for m in miss[:5]
        )
    elif needs_rewrite:
        suggestion = "补充更多带数字/时间的企业数据（当前数据点不足）"
    return {
        "score": round(score, 2),
        "hit_facts": hits[:8],
        "missing_facts": miss[:8],
        "needs_rewrite": needs_rewrite,
        "suggestion": suggestion,
    }
