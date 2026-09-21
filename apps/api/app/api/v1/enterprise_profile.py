"""企业资料总揽（Enterprise Profile）——企业知识对 GEO 客户问题的支撑能力评估。

数据链（用户 2026-08-18 拍板）：
  48 子项 ─┬─ question_match_rules → 客户问题池 → 相关问题
           └─ knowledge_match_rules → 企业知识库知识 → 相关知识
                         ↓
              GEO 覆盖判断（复用 distill._knowledge_check 4级）
                         ↓
              足够(≥70%) / 部分(≥30%) / 太少(<30%)   + 两层状态（有/暂无相关问题）

原则：
- 全部读既有数据（企业知识库 + 问题池），不从零 LLM 研究
- 覆盖状态与关联状态分开：`太少|0/5`（真缺口）≠ `太少|暂无相关问题`（问题池没覆盖）
- 覆盖率 = COVERED×1 + PARTIAL×0.5 加权（规则估算，诚实标注）
"""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from app.core.envelope import ok

logger = logging.getLogger("eios.geo.enterprise_profile")

router = APIRouter(prefix="/api/v1/enterprise-profile")

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
ITEMS_FILE = DATA_DIR / "enterprise_profile_items.json"

# ══════════════════════════════════════════════════════════════════
# 48 子项种子定义（8 大类 × 6 项）
# question_match_rules : 什么客户问题属于我（关键词/正则）
# knowledge_match_rules: 什么知识属于我（object_type / predicate / 关键词）
# ══════════════════════════════════════════════════════════════════
_CATEGORIES = [
    ("enterprise", "企业"),
    ("product", "产品与服务"),
    ("customer", "客户与市场"),
    ("capability", "企业能力"),
    ("case", "案例与成果"),
    ("sop", "SOP 与方法论"),
    ("brand", "品牌定位"),
    ("external", "外部资料"),
]

# 子项: (id, name, description, question_rules, knowledge_rules)
# question_rules: 关键词列表（任一命中即相关问题）
# knowledge_rules: {object_types: [], predicates: [], keywords: []} 任一命中即相关知识
_SEED_ITEMS = [
    # ── 1. 企业 ──
    ("enterprise", "company_overview", "企业概况", "公司基本情况与主营业务",
     ["公司是做什么", "企业是做什么", "主营业务", "公司简介", "企业简介", "什么公司"],
     {"object_types": ["company"], "predicates": [], "keywords": ["主营业务", "简介", "成立于"]}),
    ("enterprise", "company_brand", "品牌信息", "企业品牌名称与品牌归属",
     ["品牌是", "哪个公司的品牌", "品牌叫什么", "品牌属于"],
     {"object_types": ["company", "brand"], "predicates": [], "keywords": ["品牌"]}),
    ("enterprise", "company_intro", "企业简介", "企业整体介绍",
     ["介绍一下", "公司介绍", "企业介绍", "你们是", "你们公司"],
     {"object_types": ["company"], "predicates": [], "keywords": ["介绍", "简介"]}),
    ("enterprise", "company_contact", "联系方式", "电话、地址、邮箱等联系方式",
     ["怎么联系", "联系方式", "电话", "地址在哪", "在哪", "怎么找到"],
     {"object_types": ["company"], "predicates": ["contact", "phone", "address", "地址", "电话"], "keywords": ["联系", "电话", "地址"]}),
    ("enterprise", "company_website", "官网/官方账号", "官网与官方社媒账号",
     ["官网", "网站", "公众号", "官方账号", "抖音号", "官方"],
     {"object_types": ["company"], "predicates": ["website", "官网", "公众号"], "keywords": ["官网", "网站", "公众号", "账号"]}),
    ("enterprise", "company_scale", "企业规模", "员工人数、规模、产能",
     ["多少人", "员工", "规模", "多大", "产能", "几个工厂"],
     {"object_types": ["company"], "predicates": ["员工", "规模", "人数", "产能"], "keywords": ["员工", "规模", "人数"]}),

    # ── 2. 产品与服务 ──
    ("product", "product_overview", "产品", "产品线与产品概览",
     ["有什么产品", "产品有哪些", "主要产品", "做什么产品", "卖什么"],
     {"object_types": ["product"], "predicates": [], "keywords": ["产品"]}),
    ("product", "product_service", "服务", "提供的服务项目",
     ["提供什么服务", "有哪些服务", "服务项目", "服务内容", "能做什么"],
     {"object_types": ["service"], "predicates": [], "keywords": ["服务"]}),
    ("product", "product_params", "产品参数", "产品规格、参数、技术指标",
     ["参数", "规格", "尺寸", "配置", "技术指标", "材质", "面料"],
     {"object_types": ["product", "material"], "predicates": ["参数", "规格", "尺寸", "材质"], "keywords": ["参数", "规格", "尺寸", "材质"]}),
    ("product", "product_price", "价格", "产品与服务价格、报价",
     ["多少钱", "价格", "报价", "费用", "收费", "预算", "贵不贵"],
     {"object_types": ["product", "service"], "predicates": ["价格", "报价", "费用", "price"], "keywords": ["价格", "报价", "费用", "元"]}),
    ("product", "product_flow", "服务流程", "服务流程、下单流程、定制流程",
     ["流程", "步骤", "怎么定制", "怎么下单", "流程是什么", "过程"],
     {"object_types": [], "predicates": ["流程", "步骤", "process"], "keywords": ["流程", "步骤", "定制"]}),
    ("product", "product_aftersale", "售后", "售后服务、保修、维修政策",
     ["售后", "保修", "质保", "维修", "坏了", "塌陷", "开线", "多久能修"],
     {"object_types": [], "predicates": ["售后", "保修", "质保", "aftersale"], "keywords": ["售后", "保修", "质保", "维修"]}),

    # ── 3. 客户与市场 ──
    ("customer", "customer_target", "目标客户", "目标客户群体画像",
     ["适合什么人", "目标客户", "面向谁", "给谁用", "谁适合"],
     {"object_types": ["customer"], "predicates": ["客户", "目标", "受众"], "keywords": ["客户", "受众", "适用"]}),
    ("customer", "customer_need", "客户需求", "客户需求洞察",
     ["客户需要", "客户需求", "大家买", "为什么买"],
     {"object_types": [], "predicates": ["需求", "need"], "keywords": ["需求"]}),
    ("customer", "customer_pain", "客户痛点", "客户痛点与问题",
     ["痛点", "烦恼", "困扰", "常见问题", "担心"],
     {"object_types": [], "predicates": ["痛点", "pain"], "keywords": ["痛点"]}),
    ("customer", "customer_scene", "使用场景", "产品使用场景",
     ["场景", "用在", "适合放", "放在哪里", "怎么用"],
     {"object_types": [], "predicates": ["场景", "scene"], "keywords": ["场景", "适用"]}),
    ("customer", "customer_faq", "客户常见问题", "客户高频问题问答",
     ["常见问题", "FAQ", "问得最多", "经常问"],
     {"object_types": [], "predicates": ["faq", "问答"], "keywords": ["常见问题"]}),
    ("customer", "customer_competitor", "竞争对手", "竞争品牌与差异化",
     ["竞品", "竞争对手", "别家", "对比", "哪家好", "区别", "和.*比"],
     {"object_types": ["competitor"], "predicates": ["竞争", "竞品"], "keywords": ["竞品", "竞争", "对比", "区别"]}),

    # ── 4. 企业能力 ──
    ("capability", "capability_advantage", "核心优势", "企业核心优势与卖点",
     ["优势", "强在哪", "好在哪", "凭什么", "核心优势", "亮点"],
     {"object_types": [], "predicates": ["优势", "advantage"], "keywords": ["优势", "领先", "首创"]}),
    ("capability", "capability_tech", "技术能力", "技术实力与研发",
     ["技术", "研发", "专利", "技术能力", "什么技术"],
     {"object_types": [], "predicates": ["技术", "研发", "tech"], "keywords": ["技术", "研发"]}),
    ("capability", "capability_team", "团队", "团队与创始人",
     ["团队", "创始人", "老板", "谁负责", "团队多少人"],
     {"object_types": ["person", "department"], "predicates": ["团队", "创始人", "负责"], "keywords": ["团队", "创始人", "负责人"]}),
    ("capability", "capability_experience", "行业经验", "行业积累与年限",
     ["经验", "做了多久", "几年", "行业积累", "深耕"],
     {"object_types": [], "predicates": ["经验", "年限"], "keywords": ["经验", "深耕", "年"]}),
    ("capability", "capability_cert", "资质认证", "资质证书与认证",
     ["资质", "认证", "证书", "检测报告", "环保", "甲醛", "标准"],
     {"object_types": [], "predicates": ["资质", "认证", "cert"], "keywords": ["资质", "认证", "证书", "检测"]}),
    ("capability", "capability_honor", "荣誉/专利", "荣誉奖项与专利",
     ["荣誉", "奖项", "专利", "获奖", "得奖"],
     {"object_types": [], "predicates": ["荣誉", "专利", "honor"], "keywords": ["荣誉", "奖项", "专利"]}),

    # ── 5. 案例与成果 ──
    ("case", "case_customer", "客户案例", "客户合作案例",
     ["案例", "客户案例", "合作过", "做过谁", "哪些客户"],
     {"object_types": ["customer"], "predicates": ["案例", "客户"], "keywords": ["案例", "客户"]}),
    ("case", "case_project", "项目", "代表性项目",
     ["项目", "做过什么项目", "项目案例"],
     {"object_types": [], "predicates": ["项目", "project"], "keywords": ["项目"]}),
    ("case", "case_solution", "解决方案", "行业解决方案",
     ["解决方案", "方案", "怎么解决", "解决什么"],
     {"object_types": [], "predicates": ["方案", "solution"], "keywords": ["方案", "解决"]}),
    ("case", "case_process", "实施过程", "项目实施过程",
     ["实施", "落地", "交付过程", "怎么实施"],
     {"object_types": [], "predicates": ["实施", "落地"], "keywords": ["实施", "落地"]}),
    ("case", "case_result", "项目成果", "项目成果与成效",
     ["成果", "效果", "成效", "提升", "增长"],
     {"object_types": [], "predicates": ["成果", "效果"], "keywords": ["成果", "效果", "提升"]}),
    ("case", "case_review", "客户评价", "客户评价与口碑",
     ["评价", "口碑", "好评", "用户说", "怎么样"],
     {"object_types": [], "predicates": ["评价", "口碑"], "keywords": ["评价", "口碑"]}),

    # ── 6. SOP 与方法论 ──
    ("sop", "sop_sales", "销售SOP", "销售流程与方法",
     ["销售流程", "怎么卖", "销售SOP", "谈单"],
     {"object_types": [], "predicates": ["销售", "SOP"], "keywords": ["销售", "谈单"]}),
    ("sop", "sop_service", "服务SOP", "服务流程标准",
     ["服务流程", "服务标准", "服务SOP"],
     {"object_types": [], "predicates": ["服务", "SOP"], "keywords": ["服务流程", "服务标准"]}),
    ("sop", "sop_delivery", "交付SOP", "交付流程标准",
     ["交付流程", "交付SOP", "怎么交付"],
     {"object_types": [], "predicates": ["交付", "SOP"], "keywords": ["交付"]}),
    ("sop", "sop_aftersale", "售后SOP", "售后流程标准",
     ["售后流程", "售后SOP", "退换货流程"],
     {"object_types": [], "predicates": ["售后", "SOP"], "keywords": ["售后流程"]}),
    ("sop", "sop_tech", "技术标准", "技术标准与规范",
     ["技术标准", "规范", "国标", "执行标准"],
     {"object_types": [], "predicates": ["标准", "规范"], "keywords": ["标准", "规范"]}),
    ("sop", "sop_method", "行业方法论", "行业方法论",
     ["方法论", "行业方法", "怎么做的"],
     {"object_types": [], "predicates": ["方法论"], "keywords": ["方法论"]}),

    # ── 7. 品牌定位 ──
    ("brand", "brand_position", "品牌定位", "品牌市场定位",
     ["品牌定位", "定位", "什么档次", "中高端"],
     {"object_types": [], "predicates": ["定位"], "keywords": ["定位", "档次"]}),
    ("brand", "brand_concept", "品牌理念", "品牌理念与价值观",
     ["理念", "价值观", "品牌理念", "追求"],
     {"object_types": [], "predicates": ["理念", "价值观"], "keywords": ["理念", "价值观"]}),
    ("brand", "brand_story", "品牌故事", "品牌创立故事",
     ["品牌故事", "创立故事", "怎么来的", "创始人故事"],
     {"object_types": [], "predicates": ["故事"], "keywords": ["故事", "创立"]}),
    ("brand", "brand_selling", "核心卖点", "产品核心卖点",
     ["卖点", "核心卖点", "主打", "亮点是什么"],
     {"object_types": [], "predicates": ["卖点"], "keywords": ["卖点", "主打"]}),
    ("brand", "brand_value", "核心价值", "品牌核心价值",
     ["价值", "核心价值", "带来什么价值"],
     {"object_types": [], "predicates": ["价值"], "keywords": ["价值"]}),
    ("brand", "brand_diff", "差异化定位", "与竞品的差异化",
     ["差异化", "不同", "独特", "跟别人不一样"],
     {"object_types": [], "predicates": ["差异化"], "keywords": ["差异化", "独特"]}),

    # ── 8. 外部资料 ──
    ("external", "external_website", "官网", "企业官网资料",
     ["官网", "网站"],
     {"object_types": [], "predicates": ["官网", "website"], "keywords": ["官网"]}),
    ("external", "external_media", "新闻媒体", "媒体报道",
     ["新闻", "报道", "媒体报道", "上过"],
     {"object_types": [], "predicates": ["新闻", "报道"], "keywords": ["新闻", "报道"]}),
    ("external", "external_platform", "行业平台", "行业平台收录",
     ["行业平台", "收录", "协会"],
     {"object_types": [], "predicates": ["行业"], "keywords": ["行业平台"]}),
    ("external", "external_xhs", "小红书", "小红书内容",
     ["小红书", "种草"],
     {"object_types": [], "predicates": [], "keywords": ["小红书"]}),
    ("external", "external_douyin", "抖音", "抖音内容",
     ["抖音", "短视频"],
     {"object_types": [], "predicates": [], "keywords": ["抖音"]}),
    ("external", "external_wechat", "微信公众号", "微信公众号内容",
     ["公众号", "微信"],
     {"object_types": [], "predicates": [], "keywords": ["公众号"]}),
    ("external", "external_wechatvideo", "视频号", "微信视频号内容",
     ["视频号"],
     {"object_types": [], "predicates": [], "keywords": ["视频号"]}),
    ("external", "external_thirdparty", "其他第三方平台", "其他平台资料",
     ["第三方", "其他平台", "点评", "百度百科"],
     {"object_types": [], "predicates": [], "keywords": ["第三方", "百科"]}),
]


# ══════════════════════════════════════════════════════════════════
# 子项存取（SQLite store，首次自动种子）
# ══════════════════════════════════════════════════════════════════
def _load_items() -> list[dict]:
    from app.services.store import get_store

    items = get_store().load("enterprise_profile_items")
    if not items:
        items = _seed_items()
    return items


# 三通道补充规则（2026-08-18：关键词 + 意图 + 实体）
# intent:xxx = 问题的意图命中；entity:xxx = 问题的 related_entities 命中
_EXTRA_QUESTION_RULES: dict[str, list[str]] = {
    "company_overview": ["intent:认知", "entity:亚宇臻隆科技"],
    "company_brand": ["entity:亚宇臻隆科技"],
    "company_intro": ["intent:认知", "entity:亚宇臻隆科技"],
    "product_overview": ["entity:GEO+知识库系统", "entity:AI数字员工", "intent:认知"],
    "product_service": ["entity:AI数字员工", "entity:内容营销获客服务", "intent:认知"],
    "product_params": ["entity:GEO+知识库系统"],
    "product_price": ["intent:采购", "intent:对比"],
    "product_flow": ["intent:采购"],
    "product_aftersale": ["intent:使用"],
    "customer_target": ["entity:亚宇臻隆科技"],
    "customer_scene": ["intent:使用"],
    "customer_competitor": ["intent:对比", "entity:DeepSeek", "entity:豆包", "entity:文心一言", "entity:通义千问", "entity:Kimi", "entity:智谱"],
    "capability_advantage": ["intent:对比"],
    "capability_tech": ["entity:GEO+知识库系统", "intent:信任"],
    "capability_experience": ["intent:信任"],
    "capability_cert": ["intent:信任"],
    "capability_honor": ["intent:信任"],
    "case_customer": ["intent:信任"],
    "case_solution": ["entity:GEO+知识库系统"],
    "case_process": ["intent:采购", "intent:信任"],
    "case_review": ["intent:信任", "intent:对比"],
    "sop_service": ["intent:使用"],
    "sop_delivery": ["intent:采购"],
    "sop_aftersale": ["intent:使用"],
    "sop_tech": ["intent:信任"],
    "brand_position": ["intent:对比"],
    "brand_selling": ["intent:对比", "intent:采购"],
    "brand_diff": ["intent:对比"],
}


def _merged_question_rules(iid: str, q_rules: list[str]) -> list[str]:
    """合并基础关键词规则 + 三通道补充规则（去重）。"""
    merged = list(q_rules)
    for e in _EXTRA_QUESTION_RULES.get(iid, []):
        if e not in merged:
            merged.append(e)
    return merged


def _seed_items() -> list[dict]:
    """首次种子：48 子项写入 store。已有子项保留（可扩展第 49 项）。"""
    from app.services.store import get_store

    store = get_store()
    existing = store.load("enterprise_profile_items")
    existing_ids = {i["id"] for i in existing}
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for it in _SEED_ITEMS:
        cat, iid, name, desc, q_rules, k_rules = it
        if iid in existing_ids:
            continue
        store.insert("enterprise_profile_items", {
            "id": iid,
            "category": cat,
            "name": name,
            "description": desc,
            "question_match_rules": _merged_question_rules(iid, q_rules),
            "knowledge_match_rules": k_rules,
            "status": "active",
            "created_at": now,
        })
        added += 1
    if added:
        logger.info("enterprise_profile_items 种子 %d 项", added)
    return store.load("enterprise_profile_items")


def _category_of(item_id: str) -> str:
    """按 seed 定义查所属大类（显式字段，不用除法）。"""
    for it in _SEED_ITEMS:
        if it[1] == item_id:
            return it[0]
    return "enterprise"


# ══════════════════════════════════════════════════════════════════
# 问题匹配：问题池 → 子项相关问题（三通道：关键词 + 意图 + 实体）
# ══════════════════════════════════════════════════════════════════
def _match_question(qtext: str, rules: list[str], intent: str = "", entities: list[str] | None = None) -> bool:
    """问题命中子项的判定。rules 支持三通道：
    - 纯关键词/正则（兼容旧规则）
    - "intent:xxx" 前缀 = 意图通道（问题的 intent 命中）
    - "entity:xxx" 前缀 = 实体通道（问题的 related_entities 命中）
    任一通道命中即相关（一个问题可命中多个子项）。
    """
    if not rules:
        return False
    intent_hit = False
    entity_hit = False
    for rule in rules:
        if not rule:
            continue
        if rule.startswith("intent:"):
            if intent and rule[7:] == intent:
                intent_hit = True
            continue
        if rule.startswith("entity:"):
            ent = rule[7:]
            if ent and any(ent in (e or "") for e in (entities or [])):
                entity_hit = True
            continue
        # 关键词/正则通道
        try:
            if re.search(rule, qtext):
                return True
        except re.error:
            if rule in qtext:
                return True
    return intent_hit or entity_hit


# ══════════════════════════════════════════════════════════════════
# 知识匹配：企业知识库知识 → 子项相关知识
# ══════════════════════════════════════════════════════════════════
#: 48 子项 knowledge_match_rules.object_types 写的类型词表来自换知识源前的旧适配器
#: （company/product/service/material/customer/competitor/person/...）。
#: EIOS 知识对象只有 ``entity`` / ``fact`` 两种类型（2026-09-21 实测 171/29），
#: 拿旧词表当硬约束 → 每个子项的「已有资料」恒为 0（审计 B3/B5）。
_KNOWN_OBJECT_TYPES = frozenset({
    "company", "product", "service", "material", "project", "brand",
    "customer", "competitor", "person", "department", "policy", "procedure",
    "supplier", "external",
})


def _match_knowledge(knowledge: list[dict], rules: dict) -> list[dict]:
    """按 object_type/predicate/关键词 从知识列表筛出属于该子项的知识。

    匹配语义：类型命中 AND（predicate 命中 OR 关键词命中）——
    predicates/keywords 是"或"（任一内容维度沾边即归入）。

    类型词表不在 EIOS 词汇表里时（``entity`` / ``fact``）不再硬排除：
    改为只用 predicate/关键词 判定，并在 ``match_basis`` 上如实标注
    「按内容关键词归类，非类型断言」。若知识本身没有类型断言、又不含子项关键词，
    仍然不归入（不猜）。
    """
    if not knowledge or not rules:
        return []
    object_types = rules.get("object_types") or []
    predicates = rules.get("predicates") or []
    keywords = rules.get("keywords") or []
    out = []
    for k in knowledge:
        ktype = k.get("object_type") or k.get("type") or ""
        pred = k.get("predicate") or ""
        name = k.get("canonical_name") or k.get("name") or ""
        val = k.get("value") or ""
        blob = f"{name} {pred} {val}"
        typed = ktype in _KNOWN_OBJECT_TYPES
        if object_types and typed and ktype not in object_types:
            continue  # 有类型断言且与子项不符 → 不归入
        hit_pred = (not predicates) or any(p and p in pred for p in predicates)
        hit_kw = (not keywords) or any(kw and kw in blob for kw in keywords)
        # predicates/keywords 任一命中即算内容沾边（两者都空=不限内容）
        if (predicates or keywords) and not (hit_pred or hit_kw):
            continue
        item = dict(k)
        item["match_basis"] = "object_type" if (object_types and typed) else "content_keywords"
        out.append(item)
    return out


# ══════════════════════════════════════════════════════════════════
# 覆盖判定：子项 → 相关问题 → _knowledge_check → 覆盖率/档位
# ══════════════════════════════════════════════════════════════════
# 问题→判定结果 缓存：内存一级 + SQLite 持久层（页面刷新/进程重启不重算）
_kcheck_cache: dict[str, dict] = {}
_eval_loaded = False

_EVAL_TABLE = "enterprise_profile_eval"


def _eval_key(question: str, entities: list[str] | None, intent: str | None) -> str:
    return f"{question}||{','.join(entities or [])}||{intent or ''}"


def _load_eval_cache() -> None:
    """启动/首次调用时从 SQLite 载入已持久化的判定结果。"""
    global _eval_loaded
    if _eval_loaded:
        return
    try:
        from app.services.store import get_store

        rows = get_store().load(_EVAL_TABLE)
        for r in rows:
            k = r.get("_eval_key") or r.get("id") or ""
            if k and isinstance(r.get("result"), dict):
                _kcheck_cache[k] = r["result"]
    except Exception as e:
        logger.warning("load eval cache failed: %s", e)
    _eval_loaded = True


def _save_eval(key: str, result: dict) -> None:
    """持久化单条判定结果（幂等：先删同 key 再插）。"""
    try:
        from app.services.store import get_store

        store = get_store()
        store.delete(_EVAL_TABLE, key)
        store.insert(_EVAL_TABLE, {"id": key, "_eval_key": key, "result": result})
    except Exception as e:
        logger.warning("save eval failed: %s", e)


def _clear_cache() -> None:
    global _knowledge_cache, _knowledge_cache_at, _eval_loaded
    _kcheck_cache.clear()
    _knowledge_cache = None
    _knowledge_cache_at = 0.0
    _eval_loaded = False
    try:
        from app.services.store import get_store

        store = get_store()
        store.save(_EVAL_TABLE, [])            # 清空持久化判定
        store.save(_KNOWLEDGE_TABLE, [])       # 清空持久化知识
    except Exception as e:
        logger.warning("clear eval table failed: %s", e)


async def _cached_knowledge_check(question: str, entities: list[str] | None, intent: str | None) -> dict:
    key = _eval_key(question, entities, intent)
    if key in _kcheck_cache:
        return _kcheck_cache[key]
    _load_eval_cache()  # 首次调用时载入持久层（含进程重启后的恢复）
    if key in _kcheck_cache:
        return _kcheck_cache[key]
    from app.api.v1.distill import _knowledge_check
    try:
        kc = await _knowledge_check(question, entities, intent)
    except Exception:
        kc = {"status": "UNRELATED"}
    _kcheck_cache[key] = kc
    _save_eval(key, kc)
    return kc


async def _assess_item(item: dict, questions: list[dict]) -> dict:
    """对单子项做 GEO 覆盖评估。返回带状态/覆盖率/问题清单的 dict。"""
    q_rules = item.get("question_match_rules") or []
    related = [
        q for q in questions
        if _match_question(q.get("question") or "", q_rules, q.get("intent") or "", q.get("related_entities") or [])
    ]

    covered_qs = []   # COVERED
    partial_qs = []   # PARTIAL
    uncovered_qs = [] # GAP / UNRELATED
    weight_sum = 0.0
    for q in related:
        qt = q.get("question") or ""
        if not qt:
            continue
        kc = await _cached_knowledge_check(qt, q.get("related_entities") or [], q.get("intent") or None)
        st = kc.get("status", "UNRELATED")
        if st == "COVERED":
            covered_qs.append({"question": qt, "status": st})
            weight_sum += 1.0
        elif st == "PARTIAL":
            partial_qs.append({"question": qt, "status": st})
            weight_sum += 0.5
        else:
            uncovered_qs.append({"question": qt, "status": st})

    n_related = len(related)
    coverage = round(weight_sum / n_related * 100) if n_related else None
    # 档位：有相关问题 → 按覆盖率；无相关问题 → 太少（关联状态区分）
    if n_related == 0:
        level = "太少"
        related_state = "none"   # 暂无相关客户问题
        reason = "暂无相关客户问题，暂无法验证 GEO 支撑能力"
    elif coverage is None:
        level = "太少"
        related_state = "has"
        reason = "无法评估（企业知识库读取失败）"
    elif coverage >= 70:
        level = "足够"
        related_state = "has"
        reason = f"GEO 支撑能力较强（{coverage}% 相关问题可被知识支撑）"
    elif coverage >= 30:
        level = "部分"
        related_state = "has"
        reason = f"GEO 支撑能力一般（{coverage}% 相关问题可被知识支撑，仍有缺口）"
    else:
        level = "太少"
        related_state = "has"
        reason = f"GEO 支撑能力弱（{coverage}% 相关问题可被知识支撑，明确知识缺口）"

    return {
        "id": item["id"],
        "name": item["name"],
        "category": item.get("category"),
        "description": item.get("description"),
        "level": level,
        "related_state": related_state,
        "reason": reason,
        "coverage_pct": coverage,
        "related_count": n_related,
        "covered_count": len(covered_qs),
        "covered_questions": covered_qs,
        "partial_questions": partial_qs,
        "uncovered_questions": uncovered_qs,
    }


# ══════════════════════════════════════════════════════════════════
# 知识加载：企业知识库全量知识（带 60s 缓存，refresh 清空）
# ══════════════════════════════════════════════════════════════════
_knowledge_cache: dict | None = None
_knowledge_cache_at: float = 0.0
_KNOWLEDGE_TTL = 60.0
_KNOWLEDGE_TABLE = "enterprise_profile_knowledge"


async def _load_knowledge() -> dict:
    """拉 企业知识库全量知识（实体 + 事实 + 关系），供已有资料归类。失败返回空。

    只读 active（对外契约）；relations 按企业实体名逐个查（空查询 企业知识库返回空）。
    三级缓存：内存(60s) → SQLite(持久化，进程重启恢复) → 企业知识库拉取。
    refresh 时 _clear_cache 清空。
    """
    import time as _time

    global _knowledge_cache, _knowledge_cache_at
    now = _time.time()

    # 1) 内存缓存
    if _knowledge_cache is not None and now - _knowledge_cache_at < _KNOWLEDGE_TTL:
        return _knowledge_cache

    # 2) SQLite 持久缓存（内存 miss 时读库；进程重启后秒恢复）
    try:
        from app.services.store import get_store

        rows = get_store().load(_KNOWLEDGE_TABLE)
        if rows:
            row = rows[0]
            cached = row.get("data")
            cached_at = row.get("cached_at") or 0
            if isinstance(cached, dict) and now - cached_at < 300:  # 5 分钟 TTL
                _knowledge_cache = cached
                _knowledge_cache_at = now
                return _knowledge_cache
    except Exception as e:
        logger.warning("load knowledge cache failed: %s", e)

    # 3) 拉 企业知识库
    from adapters.eios import get_entities, hits_of, search_knowledge, search_relations

    entities: list[dict] = []
    facts: list[dict] = []
    relations: list[dict] = []
    try:
        entities = await get_entities()
        # 只读 active（get_entities 可能混入 deprecated）
        entities = [e for e in entities if (e.get("status") or "active") == "active"]
    except Exception as e:
        logger.warning("get_entities failed: %s", e)
    # 事实型知识：EIOS 只有 entity / fact 两种对象类型，``fact`` 对象的 canonical_name
    # 本身就是一句事实（如「成都演示间 负责 StoryClaw终端」）。旧实现走空查询检索，
    # 而空查询返回的是对象目录（value 恒空）→ facts 过滤条件恒不成立 → 「事实 0」（审计 B5）。
    facts = [
        {
            "canonical_name": e.get("canonical_name") or e.get("name") or "",
            "object_type": e.get("object_type") or e.get("type") or "",
            "predicate": None,
            "value": "",
            "evidence_ids": list(e.get("evidence_ids") or []),
        }
        for e in entities
        if (e.get("object_type") or e.get("type")) == "fact"
    ]
    # relations：按企业/核心实体名查询（空查询不可靠）
    try:
        names = [e.get("canonical_name") or e.get("name") for e in entities[:20] if e.get("canonical_name") or e.get("name")]
        for nm in names[:10]:
            try:
                rels = await search_relations(nm)
                relations.extend(rels or [])
            except Exception:
                continue
        # 去重
        seen = set()
        uniq = []
        for r in relations:
            key = (r.get("source_id"), r.get("relation_type"), r.get("target_id"))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
        relations = uniq
    except Exception as e:
        logger.warning("search_relations failed: %s", e)

    _knowledge_cache = {"entities": entities, "facts": facts, "relations": relations}
    _knowledge_cache_at = now

    # 写 SQLite 持久缓存
    try:
        from app.services.store import get_store

        store = get_store()
        store.save(_KNOWLEDGE_TABLE, [
            {"id": "all", "_key": "all", "data": _knowledge_cache, "cached_at": now}
        ])
    except Exception as e:
        logger.warning("save knowledge cache failed: %s", e)

    return _knowledge_cache


# ══════════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════════
@router.get("/overview")
async def profile_overview():
    """总体健康度：企业资料覆盖率 + 足够/部分/太少 计数。"""
    from app.api.v1.distill import _load_questions

    items = _load_items()
    questions = _load_questions()
    assessed = []
    for it in items:
        try:
            assessed.append(await _assess_item(it, questions))
        except Exception as e:
            logger.warning("assess %s failed: %s", it.get("id"), e)
    n = len(assessed)
    enough = [a for a in assessed if a["level"] == "足够"]
    partial = [a for a in assessed if a["level"] == "部分"]
    too_little = [a for a in assessed if a["level"] == "太少"]
    # 总体覆盖率 = 全部有效问题中可被支撑的比例（跨子项去重问题）
    # 2026-09-21 修正：分母只数**真的参与判定**的问题。旧实现把没有正文的问题也留在分母里
    # （循环里 continue 掉、却仍除以 len(questions)），覆盖率会被莫名拉低。
    all_questions = [q for q in questions if (q.get("question") or "").strip()]
    if all_questions:
        total_w = 0.0
        for q in all_questions:
            qt = q.get("question")
            kc = await _cached_knowledge_check(qt, q.get("related_entities") or [], q.get("intent") or None)
            st = kc.get("status", "UNRELATED")
            total_w += 1.0 if st == "COVERED" else (0.5 if st == "PARTIAL" else 0.0)
        overall = round(total_w / len(all_questions) * 100)
    else:
        overall = None
    return ok({
        "overall_coverage_pct": overall,
        "total_items": n,
        "enough_count": len(enough),
        "partial_count": len(partial),
        "too_little_count": len(too_little),
        "note": "总体覆盖率 = 全部客户问题中可被知识支撑的比例（COVERED=1/部分=0.5，规则估算）；三档 = 子项相关问题覆盖率 ≥70% 足够 / ≥30% 部分 / <30% 太少",
    })


@router.get("/categories")
async def profile_categories():
    """8 大类 + 子项 + 档位/关联状态（左大纲树数据）。"""
    from app.api.v1.distill import _load_questions

    items = _load_items()
    questions = _load_questions()
    cats: dict[str, dict] = {}
    for it in items:
        cat = it.get("category") or "other"
        g = cats.setdefault(cat, {"category": cat, "items": []})
        try:
            a = await _assess_item(it, questions)
            g["items"].append({
                "id": a["id"], "name": a["name"], "level": a["level"],
                "related_state": a["related_state"], "coverage_pct": a["coverage_pct"],
                "related_count": a["related_count"],
            })
        except Exception as e:
            logger.warning("assess %s failed: %s", it.get("id"), e)
    # 按 _CATEGORIES 顺序输出
    order = [c[0] for c in _CATEGORIES]
    rows = []
    for cat, g in cats.items():
        g["name"] = next((cn for cid, cn in _CATEGORIES if cid == cat), cat)
        rows.append(g)
    rows.sort(key=lambda x: order.index(x["category"]) if x["category"] in order else 99)
    return ok({"categories": rows})


@router.get("/items/{item_id}")
async def profile_item(item_id: str):
    """单子项详情：已有资料 + 已覆盖/未覆盖问题 + 知识来源。

    已有资料 = 结构化知识（实体/事实/关系，knowledge_match_rules 归类）
             + 相关文档块（按子项关键词语义检索，补足结构化缺失的盲区）。
    summary 为规则拼装的可读摘要（零 LLM）。
    """
    from app.api.v1.distill import _load_questions

    items = _load_items()
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        return ok({"error": f"子项不存在: {item_id}", "item": None})

    questions = _load_questions()
    a = await _assess_item(item, questions)

    # 已有资料：knowledge_match_rules 归类（结构化）
    knowledge = await _load_knowledge()
    k_rules = item.get("knowledge_match_rules") or {}
    k_entities = _match_knowledge(knowledge.get("entities") or [], k_rules)
    k_facts = _match_knowledge(knowledge.get("facts") or [], k_rules)
    k_relations = _match_knowledge(knowledge.get("relations") or [], k_rules)

    # 相关文档块：按子项关键词语义检索（补结构化盲区）
    doc_chunks: list[dict] = []
    try:
        from adapters.eios import search_knowledge

        kws = (k_rules.get("keywords") or [])[:2]
        if kws:
            res = await search_knowledge(" ".join(kws), top_k=8)
            seen = set()
            for h in hits_of(res):
                # 审计 B5：命中里放正文的是 ``value``/``snippet``（``_map_hit`` 的字段），
                # 旧代码读 ``text``/``content`` → 相关文档块恒空。
                txt = (h.get("value") or h.get("snippet") or "").strip()
                if not txt or txt in seen:
                    continue
                seen.add(txt)
                doc_chunks.append({
                    "text": txt[:160],
                    "score": round(float(h.get("score") or 0), 2),
                    "source": h.get("document_id") or h.get("source") or "",
                })
    except Exception as e:
        logger.warning("search doc chunks failed: %s", e)

    n_ent = len(k_entities)
    n_fac = len(k_facts)
    n_rel = len(k_relations)
    n_doc = len(doc_chunks)
    total = n_ent + n_fac + n_rel + n_doc

    # 可读摘要（规则拼装，零 LLM）
    if total == 0:
        summary = "暂无归类的知识资料——这正是潜在的知识缺口，建议补充相关资料。"
    else:
        parts = []
        if n_ent:
            names = [str(e.get("canonical_name") or e.get("name") or "") for e in k_entities[:3]]
            names = [n for n in names if n]
            parts.append(f"知识库有 {n_ent} 个相关实体（{'、'.join(names)}…）")
        if n_fac:
            parts.append(f"{n_fac} 条相关事实")
        if n_rel:
            parts.append(f"{n_rel} 条相关关系")
        if n_doc:
            parts.append(f"{n_doc} 段相关文档文本")
        if n_ent == 0 and n_fac == 0 and n_rel == 0 and n_doc > 0:
            summary = f"暂无结构化知识对象，但有 {n_doc} 段相关文档文本可支撑检索。"
        else:
            summary = "；".join(parts) + "。"

    return ok({
        "item": {
            **a,
            "knowledge": {
                "entities": k_entities,
                "facts": k_facts,
                "relations": k_relations,
                "doc_chunks": doc_chunks,
                "summary": summary,
                "counts": {
                    "entities": n_ent,
                    "facts": n_fac,
                    "relations": n_rel,
                    "doc_chunks": n_doc,
                },
            },
        }
    })


@router.post("/items/{item_id}/plans")
async def item_to_plans(item_id: str):
    """太少/部分子项 → 一键生成内容计划（对接蒸馏页 plans）。

    取该子项的未覆盖 + 部分覆盖问题，生成「补齐：{问题}」内容计划（纯规则零 LLM）。
    去重：同 target_question 已存在跳过。返回新增/重复数。
    """
    from app.api.v1.distill import _load_questions, _load_plans, _save_plans

    items = _load_items()
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        return ok({"error": f"子项不存在: {item_id}", "added": 0, "total": 0})

    questions = _load_questions()
    a = await _assess_item(item, questions)

    # 收集需要补齐的问题（未覆盖 + 部分覆盖，均需生产内容）
    need = [q["question"] for q in (a.get("uncovered_questions") or [])]
    need += [q["question"] for q in (a.get("partial_questions") or [])]
    # 去重
    seen = set()
    need = [q for q in need if not (q in seen or seen.add(q))]

    if not need:
        return ok({"added": 0, "duplicated": 0, "total": len(_load_plans()), "error": "该子项无未覆盖问题"})

    plans = _load_plans()
    existing = {p.get("target_question") for p in plans}
    added = 0
    duplicated = 0
    now = datetime.now(timezone.utc).isoformat()
    for q in need:
        if q in existing:
            duplicated += 1
            continue
        plans.append({
            "id": f"p_{uuid.uuid4().hex[:10]}",
            "topic": f"补齐：{q}",
            "reason": f"企业资料总揽：子项「{item['name']}」知识不足，AI 无法支撑该客户问题，需生产内容补齐",
            "target_question": q,
            "recommended_content_type": "FAQ+案例文章",
            "priority": 85,
            "gap_id": None,
            "source": "enterprise_profile_gap",  # 企业资料总揽知识缺口 → 内容计划
            "evidence_level": "C",  # 拍板：规则判定缺口 → C（待验证）
            "status": "planned",
            "created_at": now,
        })
        existing.add(q)
        added += 1
    _save_plans(plans)
    return ok({
        "added": added,
        "duplicated": duplicated,
        "total": len(plans),
        "error": None,
        "item_name": item["name"],
        "questions_count": len(need),
    })


@router.get("/export")
async def profile_export():
    """导出 Word（python-docx，九章结构）。

    企业资料总揽 → .docx：总体情况 + 8 大类每子项（状态/GEO覆盖/已有资料/已覆盖/未覆盖问题）。
    """
    import io

    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    from app.api.v1.distill import _load_questions

    items = _load_items()
    questions = _load_questions()

    doc = Document()
    # 标题
    title = doc.add_heading("企业资料总揽", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(
        "基于企业知识库与客户问题池，评估企业资料对 GEO 问题的支撑能力。\n"
        "状态口径：足够=≥70%相关问题可被知识支撑 / 部分=≥30% / 太少=<30%；"
        "「暂无相关客户问题」= 问题池未覆盖该资料项（≠知识库无资料）。"
    ).alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 一、总体情况
    assessed = []
    for it in items:
        try:
            assessed.append(await _assess_item(it, questions))
        except Exception:
            continue
    n = len(assessed)
    enough = sum(1 for a in assessed if a["level"] == "足够")
    partial = sum(1 for a in assessed if a["level"] == "部分")
    too_little = sum(1 for a in assessed if a["level"] == "太少")
    # 总体覆盖率
    total_w = 0.0
    for q in questions:
        qt = q.get("question") or ""
        if not qt:
            continue
        kc = await _cached_knowledge_check(qt, q.get("related_entities") or [], q.get("intent") or None)
        st = kc.get("status", "UNRELATED")
        total_w += 1.0 if st == "COVERED" else (0.5 if st == "PARTIAL" else 0.0)
    overall = round(total_w / len(questions) * 100) if questions else None

    doc.add_heading("一、总体情况", level=1)
    doc.add_paragraph(f"企业资料覆盖率：{overall}%（全部客户问题中可被知识支撑的比例）")
    doc.add_paragraph(f"足够 {enough} 项 · 部分 {partial} 项 · 太少 {too_little} 项（共 {n} 个资料子项）")

    # 二~九、各大类
    cat_order = {c[0]: c[1] for c in _CATEGORIES}
    by_cat: dict[str, list[dict]] = {}
    for a in assessed:
        by_cat.setdefault(a["category"], []).append(a)

    for idx, (cat_id, cat_name) in enumerate(_CATEGORIES, start=2):
        cat_items = by_cat.get(cat_id, [])
        doc.add_heading(f"{'一二三四五六七八九'[idx-2]}、{cat_name}", level=1)
        if not cat_items:
            doc.add_paragraph("（无子项）")
            continue
        for a in cat_items:
            doc.add_heading(f"{cat_name} · {a['name']}", level=2)
            doc.add_paragraph(f"状态：{a['level']}　GEO 覆盖：{a['coverage_pct'] if a['coverage_pct'] is not None else '—'}%（{a.get('covered_count', 0)}/{a['related_count'] or 0} 问题）")
            doc.add_paragraph(f"判定说明：{a['reason']}")
            # 已有资料摘要
            try:
                k = await _load_knowledge()
                k_rules = next((it.get("knowledge_match_rules") or {} for it in items if it["id"] == a["id"]), {})
                k_ent = _match_knowledge(k.get("entities") or [], k_rules)
                k_fac = _match_knowledge(k.get("facts") or [], k_rules)
                k_rel = _match_knowledge(k.get("relations") or [], k_rules)
                doc.add_paragraph(f"已有资料：实体 {len(k_ent)} · 事实 {len(k_fac)} · 关系 {len(k_rel)}")
                for e in k_ent[:5]:
                    doc.add_paragraph(f"　· {e.get('canonical_name') or e.get('name')}", style="List Bullet")
            except Exception:
                pass
            # 已覆盖问题
            if a.get("covered_questions"):
                doc.add_paragraph("已覆盖问题：")
                for q in a["covered_questions"][:5]:
                    doc.add_paragraph(f"　✓ {q['question']}", style="List Bullet")
            # 未覆盖问题
            if a.get("uncovered_questions") or a.get("partial_questions"):
                doc.add_paragraph("未覆盖/部分覆盖问题（内容生产机会）：")
                for q in (a.get("uncovered_questions") or [])[:5]:
                    doc.add_paragraph(f"　! {q['question']}", style="List Bullet")
                for q in (a.get("partial_questions") or [])[:3]:
                    doc.add_paragraph(f"　~ {q['question']}", style="List Bullet")

    # 输出 docx
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    from starlette.responses import StreamingResponse

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="enterprise_profile.docx"'},
    )


@router.post("/refresh")
async def profile_refresh():
    """刷新：清缓存重算（种子补齐 + 返回最新总览）。"""
    _clear_cache()
    _seed_items()
    from app.api.v1.distill import _load_questions

    items = _load_items()
    questions = _load_questions()
    assessed = []
    for it in items:
        try:
            assessed.append(await _assess_item(it, questions))
        except Exception as e:
            logger.warning("refresh assess %s failed: %s", it.get("id"), e)
    n = len(assessed)
    enough = sum(1 for a in assessed if a["level"] == "足够")
    partial = sum(1 for a in assessed if a["level"] == "部分")
    too_little = sum(1 for a in assessed if a["level"] == "太少")
    return ok({
        "refreshed": True,
        "total_items": n,
        "enough_count": enough,
        "partial_count": partial,
        "too_little_count": too_little,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
