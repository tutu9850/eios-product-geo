"""企业画像组装（认知编译器 · 第 1 层：企业理解层）

输入企业名 → 自动构建画像卡片：
  正式企业事实（Knowledge 的 active ``fact``，原样）+ 检索命中对象（实体/数字，带出处）
  + 知识库关系（人话）+ 本地问题池（客户在问什么） + 本地内容资产

原则（Owner 2026-09-21 拍板）：
- Knowledge 里的 active fact **就是正式企业事实**，GEO 只读、只展示、给生成消费；
  **不创建、不改写**（事实原文一律原样带出）。
- fact 的画像归类**只依据权威语义**（Knowledge 对象上的 ``semantic_object_id`` 前缀：
  ``atr_`` = 属性、``rel_`` = 关系），**不再用 GEO 自己维护的关键词表硬分类**；
  没有权威关联就不要塞进七类，统一保留在「企业事实」里等人（或上游）判定。
- 七类归纳（行业/产品/客户/优势/竞争/大事记/人物）今天**只可能由权威语义填**：
  本部署 371 条企业可见对象里 ``semantic_object_id`` 全为空，所以七类如实为空
  （不是「没读到」，是「还没有可依据的权威语义」）。
- 全部读既有数据，不从零 LLM 研究；读不到 → 「暂无记录」，绝不编造
"""
import logging
import re
from datetime import datetime, timezone

from adapters.eios import hits_of, search_knowledge, search_relations

logger = logging.getLogger("eios.geo.profile")

# 画像七类：**只允许由权威语义填**。键名固定，前端按它取。
_PROFILE_FIELDS = ("industry", "products", "customers", "advantages", "competitors", "timeline", "people")

#: 权威语义前缀（eios.knowledge_object/v1 的 semantic_object_id 家族）→ 事实种类。
#: 这是**读上游给的字段**，不是 GEO 自建的分类规则。
_SEMANTIC_KINDS = {
    "atr_": "attribute",
    "rel_": "relation",
    "cpt_": "concept",
    "met_": "metric",
    "ent_": "entity_object",
    "trm_": "term",
    "rul_": "rule",
}
_GROUP_LABELS = {
    "attribute": "属性事实（Semantic 属性）",
    "relation": "关系事实（Semantic 关系）",
    "concept": "概念事实（Semantic 概念）",
    "metric": "指标事实（Semantic 指标）",
    "entity_object": "对象事实（Semantic 实体）",
    "term": "术语事实（Semantic 术语）",
    "rule": "规则事实（Semantic 规则）",
    "enterprise_fact": "企业事实（尚未关联 Semantic）",
}


def _fact_group(fact: dict) -> str:
    """权威分组：只认 Knowledge 对象上的 ``semantic_object_id`` 前缀；没有就进企业事实。"""
    sid = str(fact.get("semantic_object_id") or "").strip()
    for prefix, kind in _SEMANTIC_KINDS.items():
        if sid.startswith(prefix):
            return kind
    return "enterprise_fact"


def _one_line(text, limit: int = 120) -> str:
    """压成单行、限长——展示给用户的字段绝不放整段多行原文。"""
    return " ".join(str(text or "").split())[:limit]


def _fact_display(hit: dict) -> str:
    """前端「企业画像」用的单行人话标签。

    2026-09-21：知识库检索命中里的 ``value`` 是这条对象**出现在哪段原文里**
    （``adapters/eios._map_hit`` 把 snippet 放 value，predicate 恒为 None），
    实测一张账号矩阵表就是 502 字。旧前端直接 ``name：value`` 打印，于是画像卡里
    出现整段表格。现在：有 predicate 的真事实 → 「名：值」；只有名字的实体 →
    「名 · 来自《资料名》」。
    """
    name = _one_line(hit.get("canonical_name"), 40)
    doc = _one_line(hit.get("document_title"), 40)
    if hit.get("predicate"):
        return _one_line(f"{name}：{hit.get('value')}", 120)
    if name and doc:
        return f"{name} · 来自《{doc}》"
    return name or doc or "（这条知识对象没有可读内容）"


def _classify(facts: list[dict]) -> dict[str, list[dict]]:
    """七类归纳：**只由权威语义填**（Owner 2026-09-21）。

    旧实现用 GEO 自己维护的关键词表（「负责/产品/客户…」）把事实硬塞进七类 ——
    那是 GEO 自造的事实分类体系，已按拍板删除。现在只有带权威 ``semantic_object_id``
    且能确定落到哪一类的事实（``profile_field``）才会进这里；本部署还没有这种关联，
    因此返回七类空表，前端如实显示「暂无记录」。
    """
    out: dict[str, list[dict]] = {k: [] for k in _PROFILE_FIELDS}
    for f in facts:
        field = str(f.get("profile_field") or "")
        if field in out:
            out[field].append(f)
    return out


def _has_number_or_time(fact: dict) -> bool:
    """这条事实是否带数字/时间（生成式引擎最爱引用「有数字」的句子）。"""
    return bool(re.search(r"\d", f"{fact.get('canonical_name')} {fact.get('value')}"))


def _pick_number_facts(facts: list[dict], top_n: int = 5) -> list[dict]:
    """优先挑带数字/时间的事实（实体+数字+时间 = 生成式引擎最爱引用的句子）。

    注意：这是**排序**不是**筛选** —— 一条都没有数字时会退化成「按证据强度取前几条」。
    因此调用方必须用 ``key_facts_basis`` 如实告诉用户这一批到底是不是带数字的，
    不能一律贴「带数字/时间」（2026-09-21 浏览器验收发现的「输出正常但不正确」）。
    """
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
    """组装企业画像（知识库正式事实 + 检索对象 + 关系 + 本地问题池/资产）。"""
    # 空企业名直接返回空画像（防 "" in blob 恒 True 放过全部命中——审计 P0-2）
    if not company_name.strip():
        return {
            "company": company_name,
            "facts": [],
            "knowledge_chunks": [],
            "key_facts": [],
            "key_facts_basis": None,
            "relations": [],
            "knowledge_facts": [],
            "fact_groups": {},
            "classified": {k: [] for k in _PROFILE_FIELDS},
            "classified_basis": "semantic_linkage",
            "questions": [],
            "assets": [],
            "built_at": datetime.now(timezone.utc).isoformat(),
            "sources": [],
            "empty": True,
        }

    # ── 正式企业事实：Knowledge 的 active fact（Owner 2026-09-21 拍板：GEO 应当消费）──
    # 走对象目录而不是检索：事实的 canonical_name 是一句三元组，通常不含企业名，
    # 用企业名检索永远搜不到（实测 77 条 fact 里 0 条含企业名）。
    knowledge_facts: list[dict] = []
    facts_error: str | None = None
    try:
        from adapters.eios import list_enterprise_facts

        for f in await list_enterprise_facts():
            raw_name = str(f.get("canonical_name") or "").strip()
            if not raw_name:
                continue
            group = _fact_group(f)
            knowledge_facts.append(
                {
                    # 原样带出，不改写事实（GEO 不是事实的作者）
                    "canonical_name": raw_name,
                    "display": _one_line(raw_name, 160),
                    "object_type": f.get("object_type"),
                    "object_id": f.get("object_id"),
                    "semantic_object_id": f.get("semantic_object_id"),
                    "authority_level": f.get("authority_level"),
                    "object_scope": f.get("object_scope"),
                    "evidence_ids": f.get("evidence_ids") or [],
                    "fact_group": group,
                    "fact_group_label": _GROUP_LABELS.get(group, group),
                }
            )
    except Exception as e:  # noqa: BLE001 — 读不到就如实标错，不假装没有事实
        logger.warning("profile: 正式事实读取失败: %s", e)
        facts_error = str(e)[:120]

    facts: list[dict] = []
    # 文档切块：同一条命中 = 一个知识对象 + 它出现的切块；一张表会被多条命中重复带回，
    # 按 chunk_id 去重（Owner 2026-09-21：内容生成消费「文档切块 + 实体」）。
    knowledge_chunks: list[dict] = []
    relations: list[dict] = []
    knowledge_ok = False
    knowledge_error = None
    try:
        res = await search_knowledge(company_name, tenant_id=tenant_id, top_k=top_facts, include_candidates=False)
        items = hits_of(res)
        for it in items:
            # 相关性过滤：企业名须出现在 name/value/text（第二层：text 归属——
            # 审计 P1-6，防仅经 subject 挂靠的事实被丢弃）；空名已在入口短路
            # 2026-09-21：旧实现在这里判 ``it.get("kind") != "chunk"`` —— 检索契约里
            # 根本没有 ``kind`` 字段（命中的是知识对象，切块挂在 ``snippet`` 上），
            # 该条件恒真、等于没写。删掉死条件，保留真正的企业名相关性过滤。
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
                    # 2026-09-21：知识库对象类型（entity/fact）与出处，供前端
                    # 如实区分「实体提及」与「结构化事实」；display 是单行人话标签。
                    "object_type": it.get("object_type"),
                    "document_title": it.get("document_title"),
                    "display": _fact_display(it),
                    "evidence_ids": it.get("evidence_ids") or [],
                }
            )
        for it in items:
            chunk_id = str(it.get("chunk_id") or "").strip()
            text = str(it.get("snippet") or it.get("value") or "").strip()
            if chunk_id and text and all(c["chunk_id"] != chunk_id for c in knowledge_chunks):
                knowledge_chunks.append(
                    {
                        "kind": "document_chunk",
                        "chunk_id": chunk_id,
                        "document_id": it.get("document_id"),
                        "document_title": it.get("document_title") or "",
                        "text": text,
                    }
                )
        knowledge_ok = True
    except Exception as e:  # noqa: BLE001
        logger.warning("profile: 知识库检索失败: %s", e)
        knowledge_error = str(e)[:120]
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
        logger.warning("profile: 知识库关系读取失败: %s", e)

    # 本地问题池 + 内容资产（按企业过滤——审计 P1-8，防跨企业素材污染）
    from app.services.store import get_store

    st = get_store()
    questions = [q for q in st.load("questions") if company_name and company_name in str(q.get("question", ""))]
    assets = [
        a for a in st.load("kb")
        if a.get("status") in ("stored", "vectorized")
        and company_name in f"{a.get('title') or ''} {a.get('content') or ''}"[:300]
    ][:8]

    classified = _classify(knowledge_facts)
    key_facts = _pick_number_facts(knowledge_facts, top_n=6) or _pick_number_facts(facts, top_n=6)
    # 这批到底是不是「带数字/时间」——如实回给前端，避免把排序结果说成筛选结果
    key_facts_basis = "number_or_time" if any(_has_number_or_time(f) for f in key_facts) else "evidence_strength"

    fact_groups: dict[str, int] = {}
    for f in knowledge_facts:
        g = str(f.get("fact_group") or "enterprise_fact")
        fact_groups[g] = fact_groups.get(g, 0) + 1

    return {
        "company": company_name,
        "facts": facts[:top_facts],
        # 正式企业事实：Knowledge 的 active fact，原样；generation 消费这一批
        "knowledge_facts": knowledge_facts,
        "knowledge_chunks": knowledge_chunks,  # 去重后的文档切块（评分的数据点来源）
        "fact_groups": fact_groups,
        "facts_error": facts_error,
        "key_facts": key_facts,          # 生成优先引用的核心事实（已随正式事实整体注入）
        "key_facts_basis": key_facts_basis,  # number_or_time / evidence_strength（前端照实说明）
        "relations": relations[:12],     # 人话关系（"陈砚舟 负责 华信精工"）
        "classified": {k: v[:6] for k, v in classified.items()},
        # 七类只由权威语义填：本部署 semantic_object_id 全空 → 七类空，如实说明
        "classified_basis": "semantic_linkage",
        "classification_note": (
            "画像七类只依据 Knowledge 对象上的权威 Semantic 关联（semantic_object_id）。"
            f"当前读到 {len(knowledge_facts)} 条正式企业事实，其中带 Semantic 关联的 "
            f"{sum(1 for f in knowledge_facts if f.get('semantic_object_id'))} 条 —— "
            "没有权威关联的事实一律保留在「企业事实」里，不按关键词硬塞进七类。"
        ),
        "questions": questions[:8],
        "assets": assets,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "sources": ["knowledge_search", "knowledge_relations", "geo_questions", "geo_kb", "enterprise_facts"],
        "knowledge_ok": knowledge_ok,    # 审计 P1-7：知识库可用性（失败 ≠ 无数据）
        "knowledge_error": knowledge_error,
    }
