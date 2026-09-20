"""企业画像组装（认知编译器 · 第 1 层：企业理解层）

输入企业名 → 自动构建画像卡片：
  Kernel 事实（实体/数字/时间，带出处） + Kernel 关系（人话）
  + 本地问题池（客户在问什么） + 本地内容资产

原则：
- 全部读既有数据（Kernel search/relations + 本地 questions/kb），不从零 LLM 研究
- 归纳字段（行业/产品/客户/优势/竞争）用规则从 Kernel 事实提取；
  提取不到 → 「暂无记录」，绝不编造
"""
import logging
import re
from datetime import datetime, timezone

from adapters.eios import search_knowledge, search_relations

logger = logging.getLogger("eios.geo.profile")

# 归纳字段的 predicate/关键词 规则（从 Kernel 事实归类）
_RULES = {
    "industry": ["行业", "industry", "领域", "分类"],
    "products": ["产品", "产品线", "solution", "方案", "平台", "系统", "产品名称"],
    "customers": ["客户", "医院", "学校", "企业客户", "覆盖", "服务"],
    "advantages": ["优势", "领先", "首创", "首个", "认证", "专利", "奖项"],
    "competitors": ["竞争", "竞品", "对标"],
    "timeline": ["成立", "成立于", "创立", "上线", "发布", "中标", "签约", "202"],
    "people": ["负责", "对接", "职务", "担任", "负责人"],
}


def _classify(facts: list[dict]) -> dict[str, list[dict]]:
    """把 Kernel 事实按 predicate/名称 归类到画像字段。"""
    out: dict[str, list[dict]] = {k: [] for k in _RULES}
    for f in facts:
        pred = str(f.get("predicate") or "")
        name = str(f.get("canonical_name") or "")
        blob = f"{pred} {name}"
        for field, keywords in _RULES.items():
            if any(k.lower() in blob.lower() for k in keywords):
                out[field].append(f)
                break
    return out


def _pick_number_facts(facts: list[dict], top_n: int = 5) -> list[dict]:
    """优先挑带数字/时间的事实（实体+数字+时间 = 生成式引擎最爱引用的句子）。"""
    def _score(f):
        txt = f"{f.get('canonical_name')} {f.get('value')}"
        s = 0
        if re.search(r"\d", txt):
            s += 2
        if re.search(r"20\d{2}", txt):
            s += 2
        if f.get("evidence_ids"):
            s += 1
        return s

    scored = sorted(facts, key=_score, reverse=True)
    return scored[:top_n]


async def build_company_profile(
    company_name: str,
    tenant_id: str = "tenant_corp_01",
    top_facts: int = 20,
) -> dict:
    """组装企业画像（Kernel 事实 + 关系 + 本地问题池/资产）。"""
    # 空企业名直接返回空画像（防 "" in blob 恒 True 放过全部命中——审计 P0-2）
    if not company_name.strip():
        return {
            "company": company_name,
            "facts": [],
            "key_facts": [],
            "relations": [],
            "classified": {k: [] for k in _RULES},
            "questions": [],
            "assets": [],
            "built_at": datetime.now(timezone.utc).isoformat(),
            "sources": [],
            "empty": True,
        }

    facts: list[dict] = []
    relations: list[dict] = []
    kernel_ok = False
    kernel_error = None
    try:
        res = await search_knowledge(company_name, tenant_id=tenant_id, top_k=top_facts, include_candidates=False)
        items = res.get("results") or res.get("objects") or res.get("items") or []
        for it in items:
            if it.get("kind") != "chunk":
                # 相关性过滤：企业名须出现在 name/value/text（第二层：text 归属——
                # 审计 P1-6，防仅经 subject 挂靠的事实被丢弃）；空名已在入口短路
                blob = (
                    f"{it.get('canonical_name') or ''} {it.get('value') or ''} "
                    f"{str(it.get('text') or '')[:200]}"
                )
                if company_name not in blob:
                    continue
                facts.append(
                    {
                        "canonical_name": it.get("canonical_name"),
                        "predicate": it.get("predicate"),
                        "value": it.get("value"),
                        "text": str(it.get("text") or "")[:200],
                        "evidence_ids": it.get("evidence_ids") or [],
                    }
                )
        kernel_ok = True
    except Exception as e:  # noqa: BLE001
        logger.warning("profile: Kernel search 失败: %s", e)
        kernel_error = str(e)[:120]
    try:
        relations = await search_relations(company_name, tenant_id=tenant_id)
        # 相关性过滤：关系两端（source/target）须含企业名，防误召回
        relations = [
            rel
            for rel in relations
            if company_name
            in str(rel.get("source") or "") + str(rel.get("target") or "")
            + str(rel.get("source_name") or "") + str(rel.get("target_name") or "")
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("profile: Kernel relations 失败: %s", e)

    # 本地问题池 + 内容资产（按企业过滤——审计 P1-8，防跨企业素材污染）
    from app.services.store import get_store

    st = get_store()
    questions = [q for q in st.load("questions") if company_name and company_name in str(q.get("question", ""))]
    assets = [
        a for a in st.load("kb")
        if a.get("status") in ("stored", "vectorized")
        and company_name in f"{a.get('title') or ''} {a.get('content') or ''}"[:300]
    ][:8]

    classified = _classify(facts)
    key_facts = _pick_number_facts(facts, top_n=6)

    return {
        "company": company_name,
        "facts": facts[:top_facts],
        "key_facts": key_facts,          # 带数字/时间的核心事实（生成强制注入用）
        "relations": relations[:12],     # 人话关系（"陈砚舟 负责 华信精工"）
        "classified": {k: v[:6] for k, v in classified.items()},
        "questions": questions[:8],
        "assets": assets,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "sources": ["kernel_search", "kernel_relations", "geo_questions", "geo_kb"],
        "kernel_ok": kernel_ok,          # 审计 P1-7：Kernel 可用性（失败 ≠ 无数据）
        "kernel_error": kernel_error,
    }
