"""GEO 内容生成（草稿，不自动发布）— 平台化完整版

蓝本：GEO优化系统 content-generator（PLATFORM_CONFIGS / SEO_PLATFORM_CONFIGS / 双 prompt 模板）
适配：企业资料自动读取（Kernel）、模型走 GEO 专用模型（服务端转发）、不自动发布。
流程：企业知识(自动) + 用户问题 + 内容目标/类型 + 平台 → GEO Prompt 编译 → 生成
"""
from adapters.eios import get_entities, search_knowledge
from adapters.llm import chat
import re

_SYSTEM = (
    "你是一名 GEO（生成式引擎优化）内容专家。你的任务是帮企业产出【容易被 AI 搜索引擎正确引用和推荐】的内容。\n"
    "GEO 写作规则：\n"
    "1. 明确企业身份：开头清晰交代企业是谁、做什么（名称/行业/定位）。\n"
    "2. 只使用提供的企业事实，禁止编造数据、案例、客户。\n"
    "3. 有事实就亮事实：产品、服务、优势、可验证的细节（来源为企业知识库）。\n"
    "4. 内容结构清晰（小标题/列表/FAQ），让 AI 摘要能直接截取关键句。\n"
    "5. 语气符合平台要求；字数接近目标；中文输出。\n"
    "6. 不要写营销空话；每个论断尽量有企业知识库里的依据支撑。\n"
    "7. 只提国内大模型（DeepSeek、豆包、文心一言、通义千问、Kimi、智谱清言），涉及 AI 搜索场景统一说'国内主流 AI 助手'；严禁出现任何国外大模型名称（ChatGPT、Perplexity、Gemini、Claude、GPT 等）和国外搜索引擎（Google、Bing 等）。"
)

# ============ 蓝本配置（原样复制自 GEO优化系统 generator.js） ============
PLATFORM_CONFIGS = {
    "zhihu": {"id": "zhihu", "name": "知乎", "wordCount": [500, 8000], "style": "professional",
              "features": "专业问答社区风格：深度分析、观点鲜明、数据/案例支撑；先给结论再论证；语言克制理性、不浮夸；结尾可抛出开放问题引导讨论；行文像认真回答一个专业问题，避免营销腔"},
    "xiaohongshu": {"id": "xiaohongshu", "name": "小红书", "wordCount": [600, 1000], "style": "casual",
                    "features": "种草笔记风格：生活化口语化、有真实体验感；多用短句和 emoji；标题带关键词+场景（如'成都装修避坑'）；分段短、留白多；结尾引导点赞收藏关注"},
    "toutiao": {"id": "toutiao", "name": "头条号", "wordCount": [3000, 5000], "style": "news",
                "features": "信息流资讯风格：标题吸睛（悬念/数字/对比/痛点，如'装修报价水多深？'）；内容通俗易懂、节奏快；每段尽量短；信息密度大；结尾引导评论互动；平台按推荐量分发，开头三行就要抓住读者"},
    "weixin": {"id": "weixin", "name": "微信公众号", "wordCount": [2000, 5000], "style": "professional",
               "features": "品牌深度长文风格：有温度有观点；故事化/场景化开头；正文层次分明、小标题清晰；金句收尾；文末自然引导关注与转发；体现品牌调性但不硬广"},
    "baijiahao": {"id": "baijiahao", "name": "百家号", "wordCount": [1500, 3000], "style": "news",
                  "features": "百度系资讯聚合风格：SEO 友好，核心关键词前置（标题+首段）；信息丰富、事实清楚、原创性强；小标题分段利于收录；结尾可加相关阅读/延伸问题"},
    "netease": {"id": "netease", "name": "网易", "wordCount": [1200, 3000], "style": "professional",
                "features": "门户深度观察风格：客观理性、有分析深度；标题有信息量不标题党；观点中肯、数据说话；结构像深度报道；适合被转载与长尾搜索收录"},
    "sohu": {"id": "sohu", "name": "搜狐", "wordCount": [1000, 2500], "style": "news",
             "features": "门户资讯风格：权威、客观、新闻化表述；结构严谨（导语-正文-小结）；信息系统化、条理清楚；语言正式规范，利于搜索引擎收录"},
    "weibo": {"id": "weibo", "name": "微博", "wordCount": [500, 2000], "style": "casual",
              "features": "实时热点风格：短内容、快节奏、互动性强；开头点明话题；带话题标签；口语化表达；结尾引导转发评论"},
}

SEO_PLATFORM_CONFIGS = {
    "seo_article": {"id": "seo_article", "name": "SEO文章", "wordCount": [1500, 3000],
                    "features": "SEO优化、关键词布局、搜索引擎友好、结构化内容",
                    "description": "适用于企业官网、博客站点的SEO优化文章"},
    "seo_landing": {"id": "seo_landing", "name": "落地页文案", "wordCount": [800, 1500],
                    "features": "转化导向、关键词优化、清晰的CTA、说服力强",
                    "description": "适用于产品落地页、活动页面的转化型内容"},
    "seo_product": {"id": "seo_product", "name": "产品介绍页", "wordCount": [1000, 2000],
                    "features": "产品特点突出、SEO友好、用户痛点解决、信任背书",
                    "description": "适用于产品详情页、服务介绍页的SEO内容"},
    "seo_news": {"id": "seo_news", "name": "新闻稿/软文", "wordCount": [800, 1500],
                 "features": "新闻格式、客观陈述、品牌植入自然、易于收录",
                 "description": "适用于新闻发布、软文推广的SEO内容"},
    "seo_blog": {"id": "seo_blog", "name": "博客文章", "wordCount": [1500, 3000],
                 "features": "深度内容、长尾关键词、内链布局、持续引流",
                 "description": "适用于企业博客、个人博客的长效SEO内容"},
    "seo_qa": {"id": "seo_qa", "name": "问答/帮助文档", "wordCount": [500, 1000],
               "features": "FAQ结构、精准解答、长尾词覆盖、结构化数据",
               "description": "适用于帮助中心、FAQ页面的SEO内容"},
}

ALL_PLATFORMS = {**PLATFORM_CONFIGS, **SEO_PLATFORM_CONFIGS}

# 默认生成 Prompt（新媒体平台，原样复制）
_DEFAULT_GENERATE_PROMPT = """你是一个专业的{platform}内容创作者，擅长撰写高质量、有吸引力的原创文章。

## 任务
请根据以下信息，为{platform}平台撰写一篇高质量文章。

## 平台特点
{platform}的内容特点：{platformFeatures}

## 文章要求
1. 文章风格：{style}
2. 目标字数：{wordCount}字左右
3. 自然融入品牌信息：{brandName}
4. 文章要有吸引力的标题（适合{platform}平台）
5. 内容要有实际价值，能解决用户问题
6. 使用小标题分段，结构清晰

## 内容方向
内容目标：{goalLine}
内容类型：{typeLine}
用户问题/主题：{question}

## 企业信息
{companyBlock}

## 输出格式
请按以下格式输出：

【标题】
（在这里写标题）

【正文】
（在这里写文章正文）"""

# SEO 生成 Prompt（原样复制，适配企业事实注入）
_SEO_GENERATE_PROMPT = """你是一个专业的SEO内容优化专家，擅长撰写搜索引擎友好且对用户有价值的高质量内容。

## 任务
请根据以下信息，撰写一篇针对搜索引擎优化的{contentType}。

## 内容类型
{contentType}：{contentDescription}

## SEO优化要求
1. 目标关键词：{targetKeywords}
2. 长尾关键词：{longTailKeywords}
3. 关键词密度：约{keywordDensity}%（自然融入，避免堆砌）
4. 内容调性：{contentTone}
5. 目标受众：{targetAudience}
6. 品牌名称：{brandName}

## 结构要求
1. 标题（H1）：包含主要关键词，吸引点击，50-60字符为佳
2. Meta描述建议：150-160字符，包含关键词和行动号召
3. 段落适中，每段3-5句话
4. 目标字数：{wordCount}字左右

## 关键词布局策略
- 标题（H1）：必须包含主要关键词
- 首段（前100字）：自然出现1-2次主要关键词
- 小标题（H2/H3）：合理分布关键词变体
- 正文：均匀分布，密度控制在{keywordDensity}%左右
- 结尾：再次强调主要关键词

## 内容方向
内容目标：{goalLine}
用户问题/主题：{question}

## 企业信息
{companyBlock}

## 输出格式
请按以下格式输出：

【SEO标题】
（包含主关键词的标题，50-60字符）

【Meta描述】
（150-160字符的页面描述，包含关键词和行动号召）

【正文】
（使用Markdown格式，包含H2/H3标题结构）"""

# 内容目标 → Prompt 要点
_GOAL_PROMPTS = {
    "提升AI推荐概率": "让内容更容易被 AI 搜索在回答用户问题时引用和推荐（信息准确、结构清晰、覆盖常见问法）。",
    "推广产品": "突出产品/服务本身：是什么、解决什么问题、有什么优势，并给出清晰的行动引导。",
    "建立行业权威": "展现企业在该行业的专业深度：行业洞察、方法论、独到观点，让 AI 视为可信来源。",
    "回答客户问题": "围绕客户真实疑问给出直接、准确、可引用的答案。",
    "对抗竞品": "客观对比中突出本企业优势（不贬低对手，用事实说话）。",
    "发布企业动态": "以新闻稿口吻发布企业最新动态（产品发布/合作/荣誉等），事实清楚、时间明确。",
}

# 内容类型 → 结构要求
_TYPE_PROMPTS = {
    "企业介绍": "标准企业介绍：企业是谁 → 核心业务 → 产品服务 → 优势 → 适用场景 → 联系方式/行动引导。",
    "行业解决方案": "面向行业客户的解决方案：行业痛点 → 解决方案 → 实施方式 → 价值与案例。",
    "FAQ问答": "FAQ 形式：开头一段概述，然后是 5-8 个问答对（问题用客户真实问法，回答简洁准确可引用）。",
    "对比文章": "对比文章：对比维度 → 客观对比 → 结论（突出本企业优势但保持客观）。",
    "客户案例": "客户案例：背景 → 挑战 → 解决方案 → 效果（只使用企业知识库中真实存在的案例）。",
    "新闻动态": "新闻稿：标题 → 导语（时间地点事件） → 详情 → 企业背景简介。",
}

# ============ 意图解析（AI 自动配置表单） ============
_PLATFORM_NAME_TO_ID = {p["name"]: pid for pid, p in ALL_PLATFORMS.items()}

_PARSE_SYSTEM = """你是 GEO 内容配置助手。用户会用一句话描述内容需求，你要把它解析成结构化的 GEO 配置。

可选值（必须从中选择，不能自创）：
- goal（内容目标）：提升AI推荐概率 / 推广产品 / 建立行业权威 / 回答客户问题 / 对抗竞品 / 发布企业动态
- content_type（内容类型）：企业介绍 / 行业解决方案 / FAQ问答 / 对比文章 / 客户案例 / 新闻动态
- style（风格）：专业权威 / 技术专家 / 营销转化 / 新闻报道 / 白皮书
- length（长度）：500 / 1500 / 3000
- platform（输出平台，不明确就 null）：知乎 / 小红书 / 头条号 / 公众号 / 百家号 / 网易 / 搜狐 / 微博 / SEO文章 / 落地页 / 产品页 / 新闻稿 / 博客 / 问答帮助
- question（用户问题/主题）：把用户需求提炼成一句"AI 用户会怎么问"的问题（客户搜索场景）
- industry（行业场景，没提到就 null）：需求提到的行业

严格只输出 JSON，不要输出任何其他内容：
{"goal":"...","content_type":"...","style":"...","length":"1500","platform":"...或null","question":"...","industry":"...或null"}"""


def _normalize(value: str | None, options: list[str], default: str) -> str:
    """把 LLM 输出归一到合法枚举（包含匹配优先，否则默认）"""
    if not value:
        return default
    v = str(value).strip()
    if v in options:
        return v
    for opt in options:
        if opt in v or v in opt:
            return opt
    return default


async def parse_intent(text: str) -> dict:
    """把自然语言需求解析成 GEO 配置（goal/类型/风格/长度/平台/问题/行业）"""
    import json
    import re

    prompt = f"用户需求：{text}\n\n请解析成 GEO 配置 JSON。"
    out = await chat(prompt, system=_PARSE_SYSTEM, max_tokens=600)
    m = re.search(r"\{[\s\S]*\}", out)
    if not m:
        raise ValueError(f"解析失败：模型未返回 JSON（{out[:100]}）")
    try:
        raw = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        raise ValueError(f"解析失败：JSON 不合法（{m.group(0)[:100]}）")

    platform_raw = raw.get("platform")
    platform = None
    if platform_raw:
        pid = str(platform_raw).strip()
        if pid in ALL_PLATFORMS:
            platform = pid
        elif pid in _PLATFORM_NAME_TO_ID:
            platform = _PLATFORM_NAME_TO_ID[pid]
        elif "通用" in pid or pid in ("null", "None", ""):
            platform = None
        else:
            # 包含匹配（如"SEO文章"→seo_article）
            for name, pid2 in _PLATFORM_NAME_TO_ID.items():
                if name in pid or pid in name:
                    platform = pid2
                    break

    return {
        "goal": _normalize(raw.get("goal"), list(_GOAL_PROMPTS.keys()), "提升AI推荐概率"),
        "content_type": _normalize(raw.get("content_type"), list(_TYPE_PROMPTS.keys()), "企业介绍"),
        "style": _normalize(raw.get("style"), ["专业权威", "技术专家", "营销转化", "新闻报道", "白皮书"], "专业权威"),
        "length": _normalize(str(raw.get("length") or "1500"), ["500", "1500", "3000"], "1500"),
        "platform": platform,
        "question": str(raw.get("question") or "").strip(),
        "industry": str(raw.get("industry") or "").strip() or None,
    }


# ============ GEO 质量检测（生成后评分） ============
_QUALITY_SYSTEM = """你是 GEO 内容质量评审专家。评审一段内容是否"容易被 AI 搜索引擎正确引用和推荐"。

评分项（每项 0-20，共 100 分）：
- keyword_coverage（关键词覆盖）：是否覆盖目标关键词/用户问题（问题里的关键概念是否都出现）
- structure（结构清晰度）：小标题/分段/FAQ 结构是否清晰，AI 摘要能否直接截取
- fact_density（事实密度）：是否使用具体事实（产品、服务、数据、案例）而非空话
- citable（易引用度）：是否有可直接引用的清晰表述（定义式、结论式句子）
- brand_clarity（品牌身份）：企业名/行业定位是否明确交代

严格只输出 JSON，不要输出其他内容：
{"keyword_coverage": 0-20, "structure": 0-20, "fact_density": 0-20, "citable": 0-20, "brand_clarity": 0-20, "notes": {"keyword_coverage": "一句话说明", "structure": "...", "fact_density": "...", "citable": "...", "brand_clarity": "..."}, "suggestions": ["改进建议1", "改进建议2", "改进建议3"]}"""

_QUALITY_KEYS = ["keyword_coverage", "structure", "fact_density", "citable", "brand_clarity"]
_QUALITY_NAMES = {
    "keyword_coverage": "关键词覆盖",
    "structure": "结构清晰度",
    "fact_density": "事实密度",
    "citable": "易引用度",
    "brand_clarity": "品牌身份",
}


async def quality(content: str, question: str = "", company_name: str | None = None) -> dict:
    """GEO 质量检测：内容 → 5 项评分 + 建议"""
    import json
    import re

    prompt = (
        f"目标关键词/用户问题：{question or '（未提供，按内容主题判断）'}\n"
        f"企业名：{company_name or '（未提供）'}\n\n"
        f"待评审内容：\n{content[:4000]}"
    )
    out = await chat(prompt, system=_QUALITY_SYSTEM, max_tokens=800)
    m = re.search(r"\{[\s\S]*\}", out)
    if not m:
        raise ValueError(f"评审失败：模型未返回 JSON（{out[:100]}）")
    raw = json.loads(m.group(0))

    checks = []
    total = 0
    for key in _QUALITY_KEYS:
        try:
            score = int(raw.get(key, 0))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(score, 20))
        total += score
        note = (raw.get("notes") or {}).get(key, "")
        checks.append({"key": key, "name": _QUALITY_NAMES[key], "score": score, "max": 20, "note": note})
    suggestions = [str(s) for s in (raw.get("suggestions") or [])[:4]]

    return {"score": min(total, 100), "checks": checks, "suggestions": suggestions}


async def _auto_company(tenant_id: str) -> tuple[str | None, list[str]]:
    """从 Kernel 自动识别企业：找企业实体 → 检索相关企业资料

    返回 (企业名, 资料列表)
    """
    try:
        entities = await get_entities()
    except Exception:  # noqa: BLE001
        return None, []
    # 企业实体：优先 有限公司/集团/科技 等企业全称特征；排除 官网/诊断/模板 等非企业实体
    _BLOCK = ("官网", "诊断", "模板", "报告", "文档", "目录", "制度", "流程", "预算", "计划", "会议", "通知")
    company_names = []
    for e in entities or []:
        name = e.get("canonical_name") or e.get("name") or ""
        if any(b in name for b in _BLOCK):
            continue
        if any(k in name for k in ("有限公司", "有限责任公司", "集团", "股份")):
            company_names.append(name)
    if not company_names:
        for e in entities or []:
            name = e.get("canonical_name") or e.get("name") or ""
            if any(b in name for b in _BLOCK):
                continue
            if any(k in name for k in ("公司", "科技", "企业", "有限", "工作室")):
                company_names.append(name)
    # 2026-08-15 修复：找不到企业实体时返回 None（不再"取第一个实体"兜底——
    # Kernel 实体首条常是产品名（如 PostgreSQL），会被误当企业名导致生成内容张冠李戴）
    if not company_names:
        return None, []
    company_name = company_names[0]
    materials: list[str] = []
    try:
        res = await search_knowledge(company_name, tenant_id=tenant_id, top_k=8, include_candidates=False)
        items = res.get("results") or res.get("objects") or res.get("items") or []
        for it in items[:8]:
            name = it.get("canonical_name") or it.get("name") or ""
            val = str(it.get("value") or it.get("summary") or "")[:200]
            if name and val:
                materials.append(f"- {name}: {val}")
            elif name:
                materials.append(f"- {name}")
    except Exception:  # noqa: BLE001
        pass
    return company_name, materials


# ============ Content Context Builder（P0.5：内容生成引用层） ============
# 聚合 Kernel 事实 + FAQ 资产 + 历史素材 + 客户问题池 → 可追溯上下文
# 原则：知识库与内容资产保持隔离；每条带来源标注；无资产时纯 Kernel 路径
# 素材/问题池统一读 SQLite store（kb/questions），不再读 geo_kb.json / geo_questions.json 残留文件

# ============ Fact Gate（事实闸门）：用户声明 vs 企业事实边界 ============
# 设计：Kernel=唯一事实源；用户输入里的"声明性语句"（获得/通过/认证…）必须经过验证：
#   kernel（强：Kernel 检索命中）→ material（中：内容资产素材命中）→ none（弱：无依据）
# 三种模式：strict（严谨：无依据拒绝生成）/ creative（创作：生成但标注待核验）/ draft（草稿：完全开放标注非事实）
_FACT_VERBS = ("获得", "通过", "荣获", "评为", "入选", "认证", "取得", "达到", "拥有", "成为", "获评", "认定", "获批", "授予", "拿下", "中标")


def _extract_fact_claims(text: str) -> list[str]:
    """从用户输入提取声明性语句（事实候选）"""
    if not text:
        return []
    claims = []
    for sent in re.split(r"[。！？!?\n；;]", text):
        sent = sent.strip()
        # 截掉请求尾巴（"，请帮我们写…"等），只留声明本身
        for kw in ["，请", "，帮", "，麻烦", "请帮我们", "请帮我", "帮我", "，写", "，制作", "，生成", "，出", "，做"]:
            i = sent.find(kw)
            if i > 0:
                sent = sent[:i].strip()
                break
        if any(v in sent for v in _FACT_VERBS) and 6 <= len(sent) <= 80:
            claims.append(sent)
    return claims[:5]


async def _fact_gate(text: str) -> dict:
    """事实闸门：多路验证用户声明（Kernel 强依据 / 内容资产素材 中依据 / 无依据）"""
    claims = _extract_fact_claims(text or "")
    if not claims:
        return {"claims": [], "unverified": [], "verified": []}
    # 内容资产素材全量文本（中依据源——用户上传的素材文件也算证据；统一读 SQLite store.kb，删 JSON 残留路径）
    asset_blob = ""
    try:
        from app.services.store import get_store

        asset_blob = " ".join((m.get("content") or "") for m in get_store().load("kb"))
    except Exception:  # noqa: BLE001
        asset_blob = ""
    results = []
    for c in claims:
        best, hit_name, hit_blob = 0.0, "", ""
        try:
            res = await search_knowledge(c, top_k=3, include_candidates=False)
            hits = res.get("hits") or []
            for h in hits:
                try:
                    sc = float(h.get("score", 0))
                except (TypeError, ValueError):
                    sc = 0.0
                if sc > best:
                    best, hit_name = sc, h.get("canonical_name") or ""
                    hit_blob = f"{h.get('canonical_name') or ''}{h.get('predicate') or ''}{h.get('value') or ''}"
        except Exception:  # noqa: BLE001
            best = 0.0
        # 实体相关性：命中知识必须与声明实质相关（防"认证→智能体部署"式向量虚高）
        claim_core = c.replace("我们", "").replace("本公司", "").replace("公司", "").replace("企业", "").replace("刚", "").replace("已", "").replace("了", "")
        related = bool(hit_name and (hit_name in c or claim_core[:12] in hit_blob))
        if best >= 0.5 and related:
            results.append({"claim": c, "level": "kernel", "score": round(best, 2), "evidence": hit_name})
            continue
        core = c.replace("我们", "").replace("公司", "").replace("企业", "").replace("本公司", "")
        if core and core in asset_blob:
            results.append({"claim": c, "level": "material", "score": 0.0, "evidence": "内容资产素材"})
            continue
        results.append({"claim": c, "level": "none", "score": round(best, 2), "evidence": ""})
    unverified = [r for r in results if r["level"] == "none"]
    verified = [r for r in results if r["level"] != "none"]
    return {"claims": results, "unverified": unverified, "verified": verified}


def _overlap_score(a: str, b: str) -> int:
    """简单相关性：字符重叠计数（第一版，不引入 embedding）"""
    if not a or not b:
        return 0
    return sum(1 for ch in a if ch in b and not ch.isspace())


async def build_context(
    *,
    question: str = "",
    company_name: str | None = None,
    tenant_id: str = "tenant_corp_01",
    max_faq: int = 3,
    max_assets: int = 2,
    max_pool: int = 5,  # 问题池串联（认知编译器）：相关性排序取前 N，按类型分组
) -> dict:
    """Content Context Builder：按权重聚合内容生成上下文

    1. Kernel 事实知识（最高权重，带出处）
    2. GEO FAQ 资产（store.kb source_type=faq，按相关性）
    3. 历史内容资产（source_type=generated/text/url）
    4. 客户问题池（store.questions，客户在问什么 → 文章结构参考）

    返回 {"company_name", "materials", "faq_assets", "other_assets", "pool_questions", "context_sources"}
    """
    auto_name: str | None = company_name
    materials: list[str] = []
    if company_name:
        # 2026-08-19 用户拍板：GEO 消息来源含部门库浅抽深抽的 candidate（未发布也算），
        # 显式包含候选——此前写死 False 导致候选知识读不到
        res = await search_knowledge(company_name, tenant_id=tenant_id, include_candidates=True)
        items = res.get("results") or res.get("objects") or res.get("items") or []
        for it in items[:8]:
            name = it.get("canonical_name") or it.get("name") or ""
            val = str(it.get("value") or "")[:200]
            materials.append(f"- {name}: {val}" if val else f"- {name}")
    else:
        auto_name, materials = await _auto_company(tenant_id)

    # FAQ 资产 + 历史素材（按问题相关性排序，第一版字符重叠；统一读 SQLite store.kb）
    try:
        from app.services.store import get_store

        assets = get_store().load("kb")
    except Exception:  # noqa: BLE001
        assets = []
    faq_assets = [a for a in assets if a.get("source_type") == "faq"]
    other_assets = [a for a in assets if a.get("source_type") in ("generated", "text", "url")]
    faq_assets.sort(key=lambda a: _overlap_score(question, str(a.get("title") or "")), reverse=True)
    other_assets.sort(key=lambda a: _overlap_score(question, str(a.get("title") or "")), reverse=True)
    faq_assets = faq_assets[:max_faq]
    other_assets = other_assets[:max_assets]

    # 客户问题池（相关性排序 + 类型分组：用户会问 / 对比 / 决策 —— 生成式搜索入口；统一读 store.questions）
    try:
        from app.services.store import get_store

        pool = get_store().load("questions")
    except Exception:  # noqa: BLE001
        pool = []
    pool.sort(key=lambda q: _overlap_score(question, str(q.get("question") or "")), reverse=True)
    pool_questions = pool[:max_pool]
    for q in pool_questions:
        qtext = str(q.get("question") or "")
        if any(k in qtext for k in ("对比", "区别", "vs", "还是")):
            q["pool_type"] = "对比"
        elif any(k in qtext for k in ("怎么样", "靠谱", "安全", "值得", "好不好", "适合")):
            q["pool_type"] = "决策"
        else:
            q["pool_type"] = "用户会问"

    context_sources = [
        {"kind": "kernel", "label": "企业知识库（Kernel）", "items": materials[:6]},
        {"kind": "faq_asset", "label": "FAQ 内容资产", "items": [
            {"title": a.get("title"), "id": a.get("id"), "content": str(a.get("content") or "")[:200]} for a in faq_assets
        ]},
        {"kind": "asset", "label": "历史内容资产", "items": [
            {"title": a.get("title"), "id": a.get("id"), "content": str(a.get("content") or "")[:150]} for a in other_assets
        ]},
        {"kind": "question_pool", "label": "客户问题池", "items": [
            {"question": q.get("question"), "priority": q.get("priority")} for q in pool_questions
        ]},
    ]
    return {
        "company_name": auto_name,
        "materials": materials,
        "faq_assets": faq_assets,
        "other_assets": other_assets,
        "pool_questions": pool_questions,
        "context_sources": context_sources,
    }


async def generate(
    *,
    goal: str = "提升AI推荐概率",
    content_type: str = "企业介绍",
    question: str = "",
    company_name: str | None = None,
    style: str = "专业权威",
    length: str = "1500",
    industry: str | None = None,
    platform: str | None = None,  # 平台 id（zhihu/seo_article/...），空 = 通用
    seo: dict | None = None,  # SEO 配置 {target_keywords, long_tail_keywords, keyword_density, content_tone, target_audience}
    tenant_id: str = "tenant_corp_01",
    mode: str = "creative",  # Fact Gate 模式：strict（严谨）/ creative（创作，默认）/ draft（草稿）
    structure: str = "free",  # 认知编译器：free（自由长文，默认）/ geo（可抽取结构模板）
    materials_extra: list[dict] | None = None,  # H19：外部个人素材并入生成上下文
) -> dict:
    # 0) Fact Gate：提取用户声明 → 多路验证（Kernel 强 / 素材 中 / 无依据）
    fg = await _fact_gate(question)
    if fg["unverified"] and mode == "strict":
        return {
            "ok": False,
            "error": (
                "严谨模式下，以下声明未在企业知识库或内容资产中找到依据，已拒绝生成：\n"
                + "\n".join(f"- {u['claim']}" for u in fg["unverified"])
                + "\n\n如该事实真实存在，请先补充资料到知识库/内容资产后再生成。"
            ),
            "unverified_facts": fg["unverified"],
        }
    # 1) Content Context Builder：聚合 Kernel 事实 + FAQ 资产 + 历史素材 + 问题池
    ctx = await build_context(question=question, company_name=company_name, tenant_id=tenant_id)
    auto_name = ctx["company_name"]
    materials = ctx["materials"]
    # H19：外部素材（如 yayu BFF 个人空间上传）并入上下文——个人素材对生成可见
    if materials_extra:
        materials = list(materials) + [
            {"id": m.get("id") or f"extra_{i}", "title": m.get("title") or "", "content": m.get("content") or ""}
            for i, m in enumerate(materials_extra)
        ]
    if not auto_name:
        # H21：区分「知识库为空」与「填了公司名但没识别」——给用户可行动的提示
        if company_name and company_name.strip():
            hint = f"未识别到企业名称「{company_name.strip()}」：企业知识库（Kernel）中暂无该企业实体（含「有限公司/集团」等企业特征）。请先在企业知识库上传/登记企业资料，或检查知识库是否被清空。"
        else:
            hint = "未识别到企业名称：请在生成时填写公司名称，或先在企业知识库建立公司实体（含「有限公司/集团」等企业特征）。当前企业知识库为空——先补充企业资料后重试。"
        return {
            "ok": False,
            "error": hint,
            "unverified_facts": [],
        }

    # 认知编译器（structure=geo）：企业画像提前构建——材料与 fact_check 同源（审计 P1-4），只查一次 Kernel
    profile = None
    if structure == "geo":
        from app.services.company_profile import build_company_profile

        profile = await build_company_profile(auto_name or "", tenant_id=tenant_id)
        if profile.get("facts"):
            extra = [
                f"- {f.get('canonical_name')}: {f.get('value')}"
                for f in profile["facts"]
                if f.get("value")
            ]
            materials = materials + [m for m in extra if m not in materials]

    goal_line = _GOAL_PROMPTS.get(goal, _GOAL_PROMPTS["提升AI推荐概率"])
    type_line = _TYPE_PROMPTS.get(content_type, _TYPE_PROMPTS["企业介绍"])

    company_block = f"企业名称：{auto_name or '（未识别到企业，请用「某企业」占位，不编造具体企业信息）'}"
    if industry:
        company_block += f"\n行业场景：{industry}"
    company_block += "\n企业事实（来自企业知识库，唯一事实来源，禁止编造）：\n"
    company_block += "\n".join(materials) if materials else "（知识库暂无该企业资料，只能写通用内容，明确告知读者这是通用介绍）"

    # 内容资产引用层（FAQ/历史素材 → 补充素材；问题池 → 文章结构参考）
    asset_lines = []
    if ctx["faq_assets"]:
        asset_lines.append("GEO FAQ 资产（已有问答，可复用其答案，来源：内容资产）：")
        for a in ctx["faq_assets"]:
            asset_lines.append(f"- Q：{a.get('title')}\n  A：{str(a.get('content') or '')[:300]}")
    if ctx["other_assets"]:
        asset_lines.append("历史内容素材（来源：内容资产，可参考不可照抄）：")
        for a in ctx["other_assets"]:
            asset_lines.append(f"- {a.get('title')}：{str(a.get('content') or '')[:150]}")
    if ctx["pool_questions"]:
        asset_lines.append("客户问题池（客户正在问这些，文章结构应尽量覆盖，来源：GEO 问题池）：")
        for q in ctx["pool_questions"]:
            asset_lines.append(f"- {q.get('question')}（优先级 {q.get('priority')}）")
    if asset_lines:
        company_block += "\n\n## 内容资产引用（补充素材，不得作为企业事实编造）\n" + "\n".join(asset_lines)

    # 3) Fact Gate 模式约束：未验证声明按模式处理（写进 prompt）
    if fg["unverified"]:
        if mode == "creative":
            company_block += (
                "\n\n## 用户提供的声明（未经企业知识库验证）\n"
                + "\n".join(
                    f"- {u['claim']}（只能作为用户宣传素材引用，正文须标注「据企业宣传」，不得写成已验证事实）" for u in fg["unverified"]
                )
            )
        elif mode == "draft":
            company_block += (
                "\n\n## 草稿构思（非企业事实）\n"
                + "\n".join(f"- {u['claim']}（草稿模式：AI 构思内容，不代表企业已确认事实）" for u in fg["unverified"])
            )

    # 2) 平台化 Prompt 编译
    is_seo = platform in SEO_PLATFORM_CONFIGS
    if platform and platform in ALL_PLATFORMS:
        p = ALL_PLATFORMS[platform]
        if is_seo:
            seo = seo or {}
            word_count = length if length in ("500", "1500", "3000") else str(p["wordCount"][0])
            prompt = _SEO_GENERATE_PROMPT.format(
                contentType=p["name"],
                contentDescription=p.get("description", ""),
                targetKeywords=seo.get("target_keywords") or question or "（核心关键词）",
                longTailKeywords=seo.get("long_tail_keywords") or "（长尾关键词）",
                keywordDensity=seo.get("keyword_density", 3),
                contentTone=seo.get("content_tone") or "professional",
                targetAudience=seo.get("target_audience") or "（目标受众）",
                brandName=auto_name or "（企业名）",
                wordCount=word_count,
                goalLine=goal_line,
                question=question or "（未提供具体问题，按内容类型自行组织）",
                companyBlock=company_block,
            )
        else:
            word_count = length if length in ("500", "1500", "3000") else str(p["wordCount"][0])
            prompt = _DEFAULT_GENERATE_PROMPT.format(
                platform=p["name"],
                platformFeatures=p["features"],
                style=style,
                wordCount=word_count,
                brandName=auto_name or "（企业名）",
                goalLine=goal_line,
                typeLine=type_line,
                question=question or "（未提供具体问题，按内容类型自行组织）",
                companyBlock=company_block,
            )
    else:
        # 通用（无平台）：保留原逻辑
        prompt = f"""请基于以下信息生成一篇 GEO（生成式引擎优化）内容草稿。

## 内容目标
{goal_line}

## 内容类型与结构要求
{type_line}

## 用户问题 / 主题
{question or "（未提供具体问题，按内容目标与类型自行组织）"}

## 企业信息
{company_block}

## 风格
{style}

## 长度
{length} 字

## 输出要求
1. 先给出【标题】，再给正文（Markdown 格式）。
2. 正文严格遵守 GEO 写作规则（企业身份明确、只用给定事实、结构清晰、易被 AI 摘要引用）。
3. 知识库没有的事实不得编造；没有案例就说没有。"""

    # 认知编译器：GEO 可抽取结构模板（structure="geo"）——追加结构指令
    if structure == "geo":
        from services.content.templates import STRUCTURE_GEO_INSTRUCTION

        prompt += STRUCTURE_GEO_INSTRUCTION.format(length=length)

    # 生成（失败自动重试 1 次：瞬时限流/网络抖动降级）
    from adapters.llm import LLMError as _LLMError

    try:
        text = await chat(prompt, system=_SYSTEM, max_tokens=3000)
    except _LLMError:
        text = await chat(prompt, system=_SYSTEM, max_tokens=3000)

    title = ""
    first_line = text.strip().split("\n")[0] if text.strip() else ""
    if first_line.startswith("#"):
        title = first_line.lstrip("#").strip()
    elif first_line.startswith("**") and first_line.endswith("**"):
        title = first_line.strip("*").strip()
    elif first_line.startswith("【标题】") or first_line.startswith("【SEO标题】"):
        lines = text.strip().split("\n")
        if len(lines) > 1:
            title = lines[1].strip()

    # 认知编译器：结构解析 + 事实密度校验（structure="geo" 时）
    sections = None
    fact_check = None
    if structure == "geo":
        from services.content.fact_checker import score_fact_density
        from services.content.templates import parse_sections

        sections = parse_sections(text)
        # 复用已构建的 profile（与 prompt 材料同源——审计 P1-4）
        profile = profile or {}
        fact_check = score_fact_density(text, profile.get("facts", []))

    return {
        "ok": True,
        "title": title or question or content_type,
        "content": text,
        "company_name": auto_name,
        "materials_used": len(materials),
        "context_sources": ctx["context_sources"],
        "goal": goal,
        "content_type": content_type,
        "question": question,
        "style": style,
        "length": length,
        "platform": platform,
        "mode": mode,
        "structure": structure,
        "sections": sections,          # GEO 结构分节（前端分节渲染）
        "fact_check": fact_check,      # 事实密度 {score, needs_rewrite, suggestion}
        "unverified_facts": fg["unverified"],
        "keywords": [],
        "geo_score": None,
        "status": "draft",
    }
