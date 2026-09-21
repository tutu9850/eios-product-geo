"""GEO 评分器（认知编译器 · 质量度量层）

生成后评分 4 个可量化维度 + 1 个启发式维度：
- 实体覆盖：企业知识库实体（画像 facts 核心词）在文本中的命中率
- 事实密度：企业知识库事实点（数字/时间/实体）出现数（复用 fact_checker）
- 问题覆盖：客户问题池条目在文本中的出现率
- 结构完整性：模板分节齐全度（5 节）
- 引用潜力：启发式加权（结构+事实+实体+问题）——标注"估算"，以上线后真实引用为准

建议：低分维度 → 具体补强建议（前端可一键重写）
"""
import re
from typing import Any

EXPECTED_SECTIONS = 5  # 模板分节：一句话回答/解决什么问题/对比表格/事实案例/FAQ

_ENTITY_CORE = re.compile(r"[A-Za-z\u4e00-\u9fff]{2,12}")
#: 纯编号/流水号（M-001、A12、2024…）：知识库把表格里的编号也抽成了实体，
#: 但它们不是「企业实体表述」，不该要求正文提到（实测建议里出现过「补充实体表述：M-001」）。
_CODE_CORE = re.compile(r"(?i)^[a-z]{0,4}[-_ ]?\d+$")


def _entity_cores(facts: list[dict], company_name: str = "") -> list[str]:
    """从画像事实提取实体核心词（canonical_name 主体，剥离企业名前缀——参数化，审计 P1-9）。"""
    prefix = company_name.strip()
    cores: list[str] = []
    for f in facts:
        name = f.get("canonical_name") or ""
        core = name
        if prefix and core.startswith(prefix):
            core = core[len(prefix):]
        elif prefix and prefix in core:
            core = core.replace(prefix, "", 1)
        core = core.strip()
        if len(core) >= 2 and not _CODE_CORE.match(core):
            cores.append(core)
    return list(dict.fromkeys(cores))[:15]


def score_geo_content(
    content: str,
    *,
    knowledge_facts: list[dict],
    pool_questions: list[dict],
    sections: dict | None = None,
    company_name: str = "",
    data_sources: list[dict] | None = None,
) -> dict[str, Any]:
    """GEO 评分。返回各维度分 + 总分 + 建议。"""
    # 1) 实体覆盖
    cores = _entity_cores(knowledge_facts, company_name)
    hit_entities = [c for c in cores if c in content] if cores else []
    entity_score = round(len(hit_entities) / len(cores), 2) if cores else 0.0

    # 2) 事实密度（复用 fact_checker）
    from services.content.fact_checker import score_fact_density

    # 2026-09-21（Owner：内容生成消费「文档切块 + 实体」）：
    # - **实体覆盖**只用实体名（``knowledge_facts`` 传名字、不带原文）；
    # - **事实密度**的数据点来自 ``data_sources``（正式事实 + 文档切块）——数字多存在
    #   原始资料里（经营月报/账号矩阵），正式事实往往是组织职责句。
    # 旧实现把「实体名 + 它所在的那段原文」当事实点，于是建议里出现
    # 「M-001（001、98000）」这种把表格单元格当企业事实的假数据点。
    fd = score_fact_density(content, list(data_sources or knowledge_facts))
    fact_score = fd["score"]

    # 3) 问题覆盖
    qs = [str(q.get("question") or "") for q in pool_questions if q.get("question")]
    hit_qs = [q for q in qs if q[:8] in content or q in content] if qs else []
    q_score = round(len(hit_qs) / len(qs), 2) if qs else 0.0

    # 4) 结构完整性
    sec_count = len(sections) if sections else 0
    struct_score = round(min(sec_count / EXPECTED_SECTIONS, 1.0), 2)

    # 5) 引用潜力（启发式加权；估算值）
    citation_potential = round(
        0.4 * struct_score + 0.3 * fact_score + 0.2 * entity_score + 0.1 * q_score, 2
    )

    total = round(
        0.35 * struct_score + 0.3 * fact_score + 0.2 * entity_score + 0.15 * q_score, 2
    )

    # 建议（低分维度 → 具体补强）
    suggestions: list[str] = []
    if fact_score < 0.6:
        suggestions.append(fd["suggestion"] or "补充带数字/时间的企业事实（当前事实密度不足）")
    if entity_score < 0.5 and cores:
        missing_ent = [c for c in cores if c not in content][:3]
        suggestions.append(f"补充实体表述：{'、'.join(missing_ent)}")
    if q_score < 0.4 and qs:
        suggestions.append(f"覆盖客户问题池：{'、'.join(qs[:2])}（生成式搜索入口是问题）")
    if struct_score < 0.8:
        suggestions.append("补充模板分节：直接回答/列表/对比表格/案例块/FAQ（可抽取结构更易被引用）")
    if not suggestions:
        suggestions.append("内容质量良好——发布后由监测回流验证真实引用率")

    return {
        "entity_coverage": entity_score,
        "fact_density": fact_score,
        "question_coverage": q_score,
        "structure_completeness": struct_score,
        "citation_potential": citation_potential,  # 启发式估算，非真实引用率
        "total": total,
        "hit_entities": hit_entities[:8],
        "hit_questions": hit_qs[:5],
        "sections_found": sec_count,
        "suggestions": suggestions,
    }
