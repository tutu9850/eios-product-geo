"""事实密度检查器（认知编译器 · 事实强制注入层）

生成后校验：文本必须含 ≥N 个来自 Kernel 的事实点（数字/实体/时间），
缺则返回 needs_rewrite + 缺失建议（前端可一键重写）。

算法（启发式但可解释）：
- Kernel 事实 → 提取「数字/年份锚点」（词边界匹配）——**只有数字/年份命中才算该事实注入**
- 实体名（企业名等）仅作辅助展示，**不单独计 hit**（防"正文只提企业名"刷绿）
- 密度分 = min(命中事实数 / 期望数, 1.0)；期望数 = min(TARGET, 含数字锚点的事实数)
"""
import re
from typing import Any

TARGET_FACTS = 3  # 最低 Kernel 事实点

# 数字锚点：词边界（防 "21" in "2021" 假阳性），单位可选
_NUM_PAT = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)\s*[个家%万人元项次款种台版期年]?")
_YEAR_PAT = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
# 纯企业名/占位词（不参与密度计分——正文必然出现，不能当事实注入证据）
_BANNED_NAMES = {
    "华信精工", "云启智能", "云启智能科技有限公司", "明辉医药", "星河康养",
    "公司", "企业", "客户", "产品", "员工", "合作",
}


def _extract_anchors(fact: dict) -> tuple[list[str], str]:
    """提取 (数字/年份锚点, 实体名锚点)。数字锚点词边界匹配。"""
    blob = f"{fact.get('canonical_name') or ''} {fact.get('value') or ''}"
    num_anchors = [m.group(1) for m in _NUM_PAT.finditer(blob)]
    num_anchors += [m.group(1) for m in _YEAR_PAT.finditer(blob)]
    name = (fact.get("canonical_name") or "").strip()
    if name in _BANNED_NAMES or len(name) < 2:
        name = ""
    return list(dict.fromkeys(num_anchors)), name


def _num_hit(text: str, num_anchors: list[str]) -> bool:
    """数字锚点词边界命中（防 "21" 命中 "2021"）。"""
    return any(re.search(rf"(?<!\d){re.escape(a)}(?!\d)", text) for a in num_anchors)


def score_fact_density(text: str, kernel_facts: list[dict]) -> dict[str, Any]:
    """计算文本的 Kernel 事实密度。返回 {score, hit_facts, missing_facts, needs_rewrite, suggestion}"""
    eligible = [f for f in kernel_facts if _extract_anchors(f)[0]]
    if not eligible:
        return {
            "score": 0.0,
            "hit_facts": [],
            "missing_facts": [],
            "needs_rewrite": True,
            "suggestion": "知识库暂无该企业的带数据事实（数字/年份），无法注入具体数据（内容只能通用介绍）",
        }
    hits: list[str] = []
    miss: list[str] = []
    for f in eligible:
        num_anchors, name = _extract_anchors(f)
        matched = _num_hit(text, num_anchors)
        label = f"{f.get('canonical_name') or ''} {f.get('value') or ''}".strip()
        (hits if matched else miss).append(label[:60])
    # 分母自适应：期望数不超过可用事实池（仅 1 条带数字事实时命中即达标）
    denom = min(TARGET_FACTS, len(eligible))
    score = min(len(hits) / denom, 1.0)
    needs_rewrite = len(hits) < denom
    suggestion = ""
    if needs_rewrite and miss:
        suggestion = "补充以下企业事实（带数字/时间）到内容中：\n" + "\n".join(f"- {m}" for m in miss[:5])
    elif needs_rewrite:
        suggestion = "补充更多带数字/时间的企业事实（当前事实点不足）"
    return {
        "score": round(score, 2),
        "hit_facts": hits[:8],
        "missing_facts": miss[:8],
        "needs_rewrite": needs_rewrite,
        "suggestion": suggestion,
    }
