"""GEO 内容生成（草稿，不自动发布）— 平台化完整版

蓝本：GEO优化系统 content-generator（PLATFORM_CONFIGS / SEO_PLATFORM_CONFIGS / 双 prompt 模板）
适配：企业资料自动读取（EIOS 企业知识库）、模型走 EIOS 统一模型入口（服务端转发）、不自动发布。
流程：企业知识(自动) + 用户问题 + 内容目标/类型 + 平台 → GEO Prompt 编译 → 生成
"""
import json
import hashlib
import logging
import re
from contextvars import ContextVar

from adapters.eios import hits_of, search_knowledge
from adapters.llm import chat

_SYSTEM = (
    "你是一名 GEO（生成式引擎优化）内容专家。你的任务是帮企业产出【容易被 AI 搜索引擎正确引用和推荐】的内容。\n"
    "GEO 写作规则：\n"
    "1. 明确企业身份：开头清晰交代企业是谁、做什么（名称/行业/定位）。\n"
    "2. 只使用提供的企业事实，禁止编造数据、案例、客户。\n"
    "3. 有资料就使用相关细节；必须保留其来源属性，知识库正式事实与企业自行提供的素材不能混称。\n"
    "4. 内容结构清晰（小标题/列表/FAQ），让 AI 摘要能直接截取关键句。\n"
    "5. 语气符合平台要求；字数接近目标；中文输出。\n"
    "6. 不要写营销空话；每个论断尽量回指本轮提供的相关资料选段，未检索到不能说企业没有。\n"
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

{topicRule}

## 企业资料（用来支撑上面的题目，不是文章主角）
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

{topicRule}

## 企业资料（用来支撑上面的题目，不是文章主角）
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


def _target_word_count(length: str, platform_cfg: dict) -> int:
    """平台字数区间 → 目标字数（审计 A4）。

    旧实现 `length if length in ("500","1500","3000") else p["wordCount"][0]`：
    length 由表单/parse_intent 归一后**永远**是这三个值之一 → 平台自带区间是死代码
    （小红书配 600–1000 字，实际按 1500 字下单）。现在按平台区间把请求长度夹进去。
    """
    try:
        want = int(str(length).strip())
    except (TypeError, ValueError):
        want = 0
    rng = platform_cfg.get("wordCount") or []
    lo = int(rng[0]) if len(rng) >= 1 and rng[0] else 0
    hi = int(rng[1]) if len(rng) >= 2 and rng[1] else 0
    if want <= 0:
        want = lo or 1500
    if lo and want < lo:
        want = lo
    if hi and want > hi:
        want = hi
    return want

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


#: 内容生成材料的上限。实测「亚宇臻隆科技」一次检索 61 条命中只对应 **5 个不同文档切块**，
#: 旧实现把 61 条命中里前 8 条按「实体名: 切片」拼出来 —— 同一张工作表被重复喂 8 遍。
_MAX_CHUNKS = 6
_MAX_ENTITIES = 12
_CHUNK_CHARS = 800


def _materials_from_hits(hits: list[dict]) -> tuple[list[str], list[str]]:
    """检索命中 →（文档切块材料, 实体名）。

    Owner 2026-09-21 拍板：内容生成消费「**知识库的文档切块内容 + 实体**」——
    只吃实体和语义，现阶段知识库还没那么精准，切块更合适。

    实测一条命中的结构 = 一个知识对象（实体）+ 它出现的**文档切块**
    （``snippet`` 与知识库 ``/documents/{id}/chunks`` 返回的 ``content`` 逐字相同，已实测比对）。
    因此这里按 ``chunk_id`` 去重、只留切块原文（带文档名），实体名单独成行：
    既不重复喂同一张表，也不再把「实体名」当成切片标题。
    """
    chunks: dict[str, str] = {}
    entities: list[str] = []
    for hit in hits or []:
        # Only governed Knowledge hits may be presented as formal enterprise material.
        # Candidate/material layer is useful elsewhere, but is not an approved fact source.
        if str(hit.get("layer") or "").strip().lower() != "governed":
            continue
        text = " ".join(str(hit.get("snippet") or hit.get("value") or "").split())
        chunk_id = str(hit.get("chunk_id") or "").strip()
        if chunk_id and text and chunk_id not in chunks:
            title = " ".join(str(hit.get("document_title") or "").split())
            label = f"《{title}》" if title else "（知识库未标文档名）"
            chunks[chunk_id] = f"- 文档切块 {label}：{text[:_CHUNK_CHARS]}"
        name = " ".join(str(hit.get("canonical_name") or hit.get("name") or "").split())
        if name and name not in entities:
            entities.append(name)
    return list(chunks.values())[:_MAX_CHUNKS], entities[:_MAX_ENTITIES]


def _entity_line(entities: list[str]) -> list[str]:
    """实体名合成一行（供 prompt 用；没有实体就没有这一行，不写「无」占位）。"""
    return [f"- 知识库实体：{'、'.join(entities)}"] if entities else []


def _chunk_lines_from_snapshot(question: str, *, need: int) -> list[str]:
    """GEO 同步时从知识库带回来、存在**自己柜里**的文档切块（台账 ``kind=chunks``）。

    Owner 2026-09-22：「应该同步知识库的时候就能看得到一并带过来存起来啊」。切块确实是
    同步时带回来的，但生成这条路一直只走实时检索，从没读过自己那份台账 —— 检索不给切块
    正文时，面板就恒显「知识库文档切块（原文）0 条」。这里按与问题的相关度取前几段。

    正本仍在知识库；GEO 读的是自己同步时留下的快照，不冒充权威。
    """
    if need <= 0:
        return []
    try:
        from app.services.knowledge_snapshot import all_chunks

        rows = [row for row in all_chunks(limit=2000)
                if str(row.get("layer") or "").strip().lower() == "governed"]
    except Exception:  # noqa: BLE001 — 台账读不到 ≠ 没有资料，如实为空
        return []
    if not rows:
        return []
    # ``_relevance_order`` 按 ``id`` 配对分数，台账里的键叫 ``chunk_id`` —— 这里对齐字段名。
    docs = [
        {
            "id": str(c.get("chunk_id") or ""),
            "title": " ".join(str(c.get("document_title") or "").split()),
            "content": " ".join(str(c.get("text") or "").split()),
        }
        for c in rows
    ]
    out: list[str] = []
    for c in _relevance_order(question or "", docs, "title")[:need]:
        text = c["content"]
        if not text:
            continue
        label = f"《{c['title']}》" if c["title"] else "（知识库未标文档名）"
        out.append(f"- 文档切块 {label}：{text[:_CHUNK_CHARS]}")
    return out


async def _resolve_self_company(tenant_id: str) -> str | None:
    """认出「本公司」的名字（认不出来就 None，绝不猜）。"""
    from services.company_identity import resolve_self_company

    resolved = await resolve_self_company(tenant_id)
    return resolved.get("name")


async def _auto_company(tenant_id: str) -> tuple[str | None, list[str]]:
    """识别「本公司」→ 检索相关企业资料，返回 (企业名, 资料列表)。

    2026-09-21 修正（Owner：「输出正常但不正确」）：旧实现在实体名单里**只按关键词挑第一个**，
    只要名字里带「企业」就认 —— 实测把素材标题「企业AI获客入口改造」当成公司名，内容生成
    因此张冠李戴、评分还把这条错名字标成「画像已解析」。现在统一交给
    ``services.company_identity``（用户点选确认的档案 → brand 对象 → 严格公司名规则），
    认不出来就返回 None，由上游如实说「未识别到企业名称」。
    """
    company_name = await _resolve_self_company(tenant_id)
    if not company_name:
        return None, []
    materials: list[str] = []
    # 资料检索照旧：拿认定的公司名去知识库捞，捞到几条就带几条（捞不到不是错，如实为空）。
    # 2026-09-21：材料口径与 build_context 统一为「文档切块 + 实体」（Owner 拍板），
    # 不再把「实体名: 整段切片」拼成一条。
    try:
        res = await search_knowledge(company_name, tenant_id=tenant_id, top_k=8, include_candidates=False)
        chunks, entities = _materials_from_hits(hits_of(res))
        materials = [*chunks, *_entity_line(entities)]
    except Exception:  # noqa: BLE001
        pass
    return company_name, materials


# ============ Content Context Builder（P0.5：内容生成引用层） ============
# 聚合 企业知识库（文档切块 + 实体 + 正式事实）+ FAQ 资产 + 历史素材 + 客户问题池 → 可追溯上下文
# 原则：知识库与内容资产保持隔离；每条带来源标注；无资产时纯知识库路径
# 素材/问题池统一读 SQLite store（kb/questions），不再读 geo_kb.json / geo_questions.json 残留文件

# ============ Fact Gate（事实闸门）：用户声明 vs 企业事实边界 ============
# 设计：企业知识库=唯一事实源；用户输入里的"声明性语句"（获得/通过/认证…）必须经过验证：
#   knowledge（强：知识库检索命中）→ material（中：内容资产素材命中）→ none（弱：无依据）
# 三种模式：strict（严谨：无依据拒绝生成）/ creative（创作：生成但标注待核验）/ draft（草稿：完全开放标注非事实）
_FACT_VERBS = ("获得", "通过", "荣获", "评为", "入选", "认证", "取得", "达到", "拥有", "成为", "获评", "认定", "获批", "授予", "拿下", "中标")
# 审计 B12：原截尾词表只有中文，英文/口语化输入提取不到声明。补英文动词与请求尾词。
_FACT_VERBS_EN = (
    "obtained", "certified", "certification", "awarded", "accredited", "achieved",
    "holds", "has obtained", "has passed", "won", "ranked", "recognized", "registered",
    "passed", "selected", "partnered", "authorized", "qualified",
)
_CLAIM_TAIL_KEYWORDS = (
    "，请", "，帮", "，麻烦", "请帮我们", "请帮我", "帮我", "，写", "，制作", "，生成", "，出", "，做",
    ", please", " and write", " please write", " please help", " write a", " write an",
    " create a", " create an", " produce a", " generate a", " make a",
)


def _extract_fact_claims(text: str) -> list[str]:
    """从用户输入提取声明性语句（事实候选）

    审计 B12：原实现只在中文标点分句（`.` 不分句）+ 只有中文动词/截尾词，
    英文或口语化输入提取不到声明。现在补齐英文分句与英文声明动词。
    """
    if not text:
        return []
    claims = []
    # 分句：中英文标点 + 换行；英文句号只在后接空白/结尾时算边界（不切 3.5 / v1.0）
    for sent in re.split(r"[。！？!?；;\n]+|\.(?=\s|$)", text):
        sent = (sent or "").strip().strip("．.,，;；：:")
        # 截掉请求尾巴（"，请帮我们写…" / ", please write…"），只留声明本身
        for kw in _CLAIM_TAIL_KEYWORDS:
            i = sent.find(kw)
            if i > 0:
                sent = sent[:i].strip()
                break
        if not sent:
            continue
        has_verb = any(v in sent for v in _FACT_VERBS) or any(
            v in sent.lower() for v in _FACT_VERBS_EN
        )
        if has_verb and 6 <= len(sent) <= 80:
            claims.append(sent)
    return claims[:5]


async def _fact_gate(text: str) -> dict:
    """事实闸门：多路验证用户声明（知识库强依据 / 内容资产素材 中依据 / 无依据）"""
    claims = _extract_fact_claims(text or "")
    if not claims:
        return {"claims": [], "unverified": [], "verified": []}
    # 内容资产素材全量文本（中依据源——用户上传的素材文件也算证据；统一读 SQLite store.kb，删 JSON 残留路径）
    asset_blob = ""
    try:
        from app.services.store import get_store

        source_assets = get_store().load("kb")
        asset_blob = " ".join(
            str(m.get("content") or "") for m in source_assets
            if m.get("source_type") in ("file", "text", "url")
        )
    except Exception:  # noqa: BLE001
        asset_blob = ""
    results = []
    for c in claims:
        best, hit_name, hit_blob = 0.0, "", ""
        try:
            res = await search_knowledge(c, top_k=3, include_candidates=False)
            for h in hits_of(res):
                try:
                    sc = float(h.get("score") or 0)
                except (TypeError, ValueError):
                    sc = 0.0
                if sc >= best:
                    best, hit_name = sc, h.get("canonical_name") or ""
                    hit_blob = f"{h.get('canonical_name') or ''}{h.get('predicate') or ''}{h.get('value') or ''}"
        except Exception:  # noqa: BLE001
            best = 0.0
        # 实体相关性：命中知识必须与声明实质相关（防"认证→智能体部署"式向量虚高）
        # 审计 B7：旧条件 ``best >= 0.5`` 是按旧知识库的 0–1 分定的；EIOS 的 score 是
        # 排序分（实测 13.5~14.0），该条件恒真、等于没有。真正把关的是下面的 related。
        claim_core = c.replace("我们", "").replace("本公司", "").replace("公司", "").replace("企业", "").replace("刚", "").replace("已", "").replace("了", "")
        related = bool(hit_name and (hit_name in c or claim_core[:12] in hit_blob))
        if hit_name and related:
            results.append({"claim": c, "level": "knowledge", "score": round(best, 2), "evidence": hit_name})
            continue
        core = c.replace("我们", "").replace("公司", "").replace("企业", "").replace("本公司", "")
        if core and core in asset_blob:
            results.append({"claim": c, "level": "material", "score": 0.0, "evidence": "内容资产素材"})
            continue
        results.append({"claim": c, "level": "none", "score": round(best, 2), "evidence": ""})
    unverified = [r for r in results if r["level"] == "none"]
    verified = [r for r in results if r["level"] != "none"]
    return {"claims": results, "unverified": unverified, "verified": verified}


def _relevance_order(query: str, docs: list[dict], text_key: str) -> list[dict]:
    """按问句相关性重排文档（审计 A5）。

    旧实现 `_overlap_score` 只比对 title 的**字符重叠计数**：共用常用字越多分越高，
    不看向量也不看正文。改为复用 services/embed 的 n-gram 打分（与素材页
    /knowledge/materials/search 的 hybrid_search 同一主路径口径：核心词 2-gram，
    标题 2x + 正文 1x）。无命中（含 query 为空）→ 保持原顺序，稳定退化。
    """
    docs = list(docs)
    if not query or not docs:
        return docs
    try:
        from services.embed import n_gram_scores

        scores = n_gram_scores(query, docs, title_key=text_key, content_key="content")
    except Exception:  # noqa: BLE001
        return docs
    if not scores:
        return docs
    return sorted(docs, key=lambda d: -scores.get(str(d.get("id") or ""), 0.0))


def _asset_excerpt(question: str, asset: dict, limit: int) -> dict:
    """这份素材该注入哪一段（Owner 2026-09-21：「内容生成注入最相关的几段」）。

    切过块 → 取问句最贴的那一段（并带上它在素材里的序号，来源面板能指回「第几段」）；
    没切块（老素材）→ 退回整篇开头 ``limit`` 字，如实不带段号。
    """
    text = str(asset.get("content") or "")
    out = {"text": text[:limit], "chunk_id": None, "chunk_ordinal": None}
    try:
        from services.embed import best_chunk

        chunk = best_chunk(question, asset)
    except Exception:  # noqa: BLE001 — 取不到段不该让生成失败
        return out
    if chunk is None:
        return out
    chunk_text = str(chunk.get("text") or "")
    if not chunk_text:
        return out
    return {"text": chunk_text[:limit], "chunk_id": chunk.get("id"), "chunk_ordinal": chunk.get("ordinal")}


_MAX_FILE_CHUNKS = 8
_MAX_FILE_CHARS = 9000


def _question_queries(question: str, pool_questions: list[dict] | None = None) -> list[str]:
    """Split multi-part prompts into focused queries without inventing fallback topics."""
    parts = re.split(r"[？?。；;\n]+|以及|同时|另外|还有", str(question or ""))
    queries = [p.strip(" ，,、") for p in parts if p.strip(" ，,、")]
    for item in pool_questions or []:
        q = str(item.get("question") or "").strip()
        if q and q not in queries:
            queries.append(q)
    return queries or ([str(question).strip()] if str(question or "").strip() else [])


def _selected_file_chunks(question: str, asset: dict, queries: list[str]) -> list[dict]:
    """Return only positively related complete chunks, ranked across each sub-question."""
    from services.embed import material_chunks, n_gram_scores

    chunks = material_chunks(asset)
    if not chunks:
        text = str(asset.get("content") or "").strip()
        return ([{"id": None, "ordinal": None, "text": text}] if text and any(
            _asset_relevance(q, str(asset.get("title") or ""), text) > 0 for q in queries
        ) else [])
    docs = [{"id": str(c.get("id") or i), "title": "", "content": str(c.get("text") or "")}
            for i, c in enumerate(chunks)]
    scores: dict[str, float] = {}
    for query in queries:
        scores_for_query = n_gram_scores(query, docs, title_key="title", content_key="content")
        for cid, score in scores_for_query.items():
            scores[cid] = max(scores.get(cid, 0.0), score)
    ranked = [(scores.get(str(c.get("id") or i), 0.0), i, c) for i, c in enumerate(chunks)]
    return [dict(c, ordinal=c.get("ordinal", i), _score=score) for score, i, c in
            sorted((row for row in ranked if row[0] > 0), key=lambda row: (-row[0], row[1]))[:_MAX_FILE_CHUNKS]]


def _asset_relevance(query: str, title: str, content: str) -> float:
    from services.embed import n_gram_scores

    return n_gram_scores(query, [{"id": "a", "title": title, "content": content}]).get("a", 0.0)


def _file_material_selection(question: str, assets: list[dict], queries: list[str] | None = None) -> tuple[list[str], list[dict]]:
    """Build one bounded source set shared by generation and improve."""
    from services.embed import n_gram_scores

    queries = queries or _question_queries(question)
    selected_ids: list[str] = []
    sources: list[dict] = []
    used_chars = 0
    for asset in assets:
        chunks = _selected_file_chunks(question, asset, queries)
        chosen = []
        for chunk in chunks:
            text = str(chunk.get("text") or "")
            if not text or used_chars + len(text) > _MAX_FILE_CHARS:
                continue
            chosen.append(chunk)
            used_chars += len(text)
        if not chosen:
            continue
        asset_id = str(asset.get("id") or "")
        if asset_id:
            selected_ids.append(asset_id)
        source = {"kind": "uploaded_material", "label": "用户上传资料（相关原文选段，未经独立核验）", "items": []}
        for chunk in chosen:
            text = str(chunk["text"])
            source["items"].append({
                "id": asset_id, "title": asset.get("title"), "source_type": "file",
                "chunk_id": chunk.get("id"), "chunk_ordinal": chunk.get("ordinal"),
                "content": text, "source_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            })
        sources.append(source)
    return selected_ids, sources


def _source_material_prompt(sources: list[dict]) -> str:
    lines = []
    for source in sources:
        for item in source.get("items") or []:
            where = f"（第 {int(item['chunk_ordinal']) + 1} 段）" if item.get("chunk_ordinal") is not None else ""
            lines.append(f"- [用户上传资料：{item.get('title')}{where}] {item.get('content')}")
    return "\n".join(lines)


TOPIC_RULE_HEADER = "## 主题纪律（最高优先级）"


def topic_rule(question: str, company_name: str | None) -> str:
    """主题纪律块：题目是文章的主角，企业资料只是支撑（Owner 2026-09-22）。

    为什么单独立一条规则：提示词里原本只有「企业事实（唯一事实来源）」，没有一句说
    「题目才是要写的东西」。实测结果是模型把用户输入的题目改写成那家企业的介绍 ——
    问「笔革家居整套全屋定制要多久」，正文通篇是另一家公司。规则把这件事写在最前面。
    """
    topic = (question or "").strip()
    if not topic:
        return ""
    lines = [
        TOPIC_RULE_HEADER,
        f"- 这篇文章围绕「{topic}」写；标题应简短提炼主题，不要把整段要求原样抄成标题。",
        "- 下面的企业资料只用来支撑这个题目：提供事实、口径与细节，**它本身不是文章的主题**。",
        "- 除非题目本身就是在介绍这家企业，否则不要写「X 是一家……」这类企业介绍式开头，",
        "  也不要把与题目无关的企业信息写进正文。",
        "- **不得把资料里的事实安到题目问的另一个对象身上**：资料讲的是哪家/哪个产品，就只能"
        "挂在哪家/哪个产品上。",
        "- 先检索并阅读本轮提供的全部相关选段。若本轮检索到的资料没有提及所问内容，只能说「本轮检索到的资料未提及」，不能推断企业没有这项服务或信息。",
    ]
    if company_name:
        lines.append(
            f"- 上面的「企业资料」来自「{company_name}」；如果题目问的不是它，就以题目问的对象为准，"
            f"「{company_name}」的资料只能当参考，不得拿来回答另一个对象。"
        )
    return "\n".join(lines)


def _asset_source_item(question: str, asset: dict, limit: int) -> dict:
    """来源面板里的一条素材：注入的是哪一段，就如实报哪一段。"""
    excerpt = _asset_excerpt(question, asset, limit)
    return {
        "title": asset.get("title"),
        "id": asset.get("id"),
        "chunk_id": excerpt["chunk_id"],
        "chunk_ordinal": excerpt["chunk_ordinal"],
        "content": excerpt["text"],
    }


#: 主题相关时最多注入多少条正式事实（原实现是「库里前 30 条」）。
_MAX_TOPIC_FACTS = 8
#: 事实进上下文的最低相关分（与 ``_relevance_order`` 同一套 n-gram 口径）。
_FACT_MIN_SCORE = 2.0
_fact_context_status: ContextVar[tuple[str, list[str]]] = ContextVar(
    "geo_content_fact_context_status", default=("empty", [])
)


async def _official_fact_context(question: str = "", limit: int = _MAX_TOPIC_FACTS) -> tuple[list[str], str, list[str]]:
    """正式企业事实（Knowledge ``type=fact`` 的 active 对象）→ 生成用的一行一句。

    为什么必须单独拉：事实的 ``canonical_name`` 是一句三元组，通常不含企业名，
    用企业名检索永远搜不到（实测 77 条 fact 里 0 条含企业名），只能走对象目录。
    读不到就返回空 —— 由 ``context_sources`` 如实体现「这轮没有正式事实」，
    绝不用通用话术顶替。GEO 不创建、不改写这些事实（Owner 2026-09-21）。

    **按主题选，不按库里的顺序取前 N 条**（Owner 2026-09-22「我输入的什么主题，就是什么主题，
    不能根据公司名字来回答」）。原实现是 ``[:30]`` —— 一次内容生成把库里前 30 条企业事实
    整包塞进 prompt，模型看到「唯一事实来源」全是这家公司，于是把用户问的另一个主题改写成
    了这家公司的介绍（实测：问「笔革家居整套全屋定制要多久」，正文通篇 亚宇臻隆）。
    与主题无关的事实不是「更多材料」，是**另一个题目的材料**，进来只会把文章拽走，所以不进。
    主题为空时（用户没给题目）没有可对照的主题，仍按目录顺序取前 ``limit`` 条。
    """
    try:
        from adapters.eios import list_enterprise_facts

        facts = [str(f.get("canonical_name") or "").strip() for f in await list_enterprise_facts()]
        facts = [name for name in facts if name]
        if not facts:
            return [], "empty", []

        topic = (question or "").strip()
        if not topic:
            selected = [f"- [正式事实] {name}" for name in facts[:limit]]
            return selected, ("available" if selected else "empty"), []

        try:
            from services.embed import n_gram_scores

            docs = [{"id": str(i), "title": name, "content": name} for i, name in enumerate(facts)]
            scores = n_gram_scores(topic, docs, title_key="title", content_key="content")
        except Exception:  # noqa: BLE001 — 打分不可用时不猜相关性，宁可一条不给
            logging.getLogger("eios.geo.content").warning("事实相关性打分不可用，本轮不注入正式事实")
            return [], "unavailable", ["official_facts_relevance_unavailable"]

        ranked = sorted(
            ((scores.get(str(i), 0.0), name) for i, name in enumerate(facts)),
            key=lambda pair: -pair[0],
        )
        selected = [f"- [正式事实] {name}" for score, name in ranked if score >= _FACT_MIN_SCORE][:limit]
        return selected, ("available" if selected else "empty"), []
    except Exception as e:  # noqa: BLE001 — 读不到 ≠ 没有事实，由来源面板如实体现
        logging.getLogger("eios.geo.content").warning("正式事实读取失败: %s", e)
        return [], "unavailable", ["official_facts_read_failed"]


async def _official_fact_lines(question: str = "", limit: int = _MAX_TOPIC_FACTS) -> list[str]:
    """Compatibility wrapper for existing callers that consume only the fact lines."""
    lines, status, warnings = await _official_fact_context(question, limit)
    _fact_context_status.set((status, warnings))
    return lines


async def build_context(
    *,
    question: str = "",
    company_name: str | None = None,
    tenant_id: str | None = None,
    max_faq: int = 3,
    max_assets: int = 2,
    max_pool: int = 5,  # 问题池串联（认知编译器）：相关性排序取前 N，按类型分组
    source_material_ids: list[str] | None = None,
) -> dict:
    """Content Context Builder：按权重聚合内容生成上下文

    1. 正式企业事实 + 知识库文档切块 + 知识库实体（最高权重，带出处）
    2. GEO FAQ 资产（store.kb source_type=faq，按相关性）
    3. 原始内容资产（text/url）及用户上传资料（file）；历史生成稿不作事实
    4. 客户问题池（store.questions，客户在问什么 → 文章结构参考）

    返回 {"company_name", "materials", "faq_assets", "other_assets", "pool_questions", "context_sources"}
    """
    # 账号分柜（Owner 2026-09-22）：没显式指定就跟随**当前请求的柜**，不写死默认柜。
    if not tenant_id:
        from app.services.store import current_tenant

        tenant_id = current_tenant() or "tenant_corp_01"
    auto_name: str | None = company_name
    chunk_lines: list[str] = []
    entity_names: list[str] = []
    # 正式企业事实（Knowledge 的 active fact）：Owner 2026-09-21 拍板「fact 接进内容生成」。
    # 原样注入、排在切块之前 —— 事实是权威给的句子，GEO 不改写。
    official_facts = await _official_fact_lines(question)
    fact_status, fact_warnings = _fact_context_status.get()
    knowledge_status = fact_status
    context_warnings = list(fact_warnings)
    # 切块是从哪读到的不许含糊：实时检索给的 vs GEO 同步时存下的快照 —— 后者要在面板上说出来。
    chunks_from_snapshot = False
    if company_name:
        # 内容草稿的企业依据只取 governed；候选仍由原治理流程负责。
        try:
            res = await search_knowledge(company_name, tenant_id=tenant_id, include_candidates=False)
            chunk_lines, entity_names = _materials_from_hits(hits_of(res))
            context_warnings.extend(str(w) for w in (res.get("warnings") or []))
            if res.get("provenance") or res.get("layers"):
                has_knowledge = bool(chunk_lines or entity_names or official_facts)
                knowledge_status = (
                    "partial" if fact_status == "unavailable" and has_knowledge
                    else "unavailable" if fact_status == "unavailable"
                    else "available" if has_knowledge else "empty"
                )
        except Exception as exc:  # Knowledge unavailable must remain distinct from an empty result.
            logging.getLogger("eios.geo.content").warning("知识检索失败: %s", exc)
            knowledge_status = "partial" if official_facts else "unavailable"
            context_warnings.append("knowledge_search_failed")
    else:
        # 没给企业名时先认出「本公司」，再按同一口径取材料（切块 + 实体）。
        auto_name = await _resolve_self_company(tenant_id)
        if auto_name:
            try:
                res = await search_knowledge(auto_name, tenant_id=tenant_id, include_candidates=False)
                chunk_lines, entity_names = _materials_from_hits(hits_of(res))
                context_warnings.extend(str(w) for w in (res.get("warnings") or []))
                if res.get("provenance") or res.get("layers"):
                    has_knowledge = bool(chunk_lines or entity_names or official_facts)
                    knowledge_status = (
                        "partial" if fact_status == "unavailable" and has_knowledge
                        else "unavailable" if fact_status == "unavailable"
                        else "available" if has_knowledge else "empty"
                    )
            except Exception:  # noqa: BLE001 — 读不到 ≠ 没有资料
                knowledge_status = "partial" if official_facts else "unavailable"
                context_warnings.append("knowledge_search_failed")
                chunk_lines, entity_names = [], []
    # 实时检索没给够切块正文时，补上**同步时已经存进 GEO 自己柜**的那些（Owner 2026-09-22）。
    if len(chunk_lines) < _MAX_CHUNKS:
        seen_text = {line.split("：", 1)[-1] for line in chunk_lines}
        for line in _chunk_lines_from_snapshot(question, need=_MAX_CHUNKS - len(chunk_lines)):
            body = line.split("：", 1)[-1]
            if body in seen_text:
                continue
            seen_text.add(body)
            chunk_lines.append(line)
            chunks_from_snapshot = True
    materials = [*official_facts, *chunk_lines, *_entity_line(entity_names)]

    # FAQ 资产 + 历史素材（按问题相关性排序，第一版字符重叠；统一读 SQLite store.kb）
    try:
        from app.services.store import get_store

        assets = get_store().load("kb")
    except Exception:  # noqa: BLE001
        assets = []
    faq_assets = [a for a in assets if a.get("source_type") == "faq"]
    # generated 是历史生成稿，不是独立企业事实来源；只让明确的原始资产进入取材。
    other_assets = [a for a in assets if a.get("source_type") in ("text", "url")]
    file_assets = [a for a in assets if a.get("source_type") == "file"]
    if source_material_ids is not None:
        requested = list(dict.fromkeys(str(mid).strip() for mid in source_material_ids if str(mid).strip()))
        by_id = {str(a.get("id") or ""): a for a in file_assets}
        missing = [mid for mid in requested if mid not in by_id]
        if missing:
            raise ValueError("所选资料不存在、已失效或不在当前素材柜")
        file_assets = [by_id[mid] for mid in requested]
    else:
        file_assets = _relevance_order(question, file_assets, "title")
    faq_assets = _relevance_order(question, faq_assets, "title")[:max_faq]
    other_assets = _relevance_order(question, other_assets, "title")[:max_assets]

    # 客户问题池（相关性排序 + 类型分组：用户会问 / 对比 / 决策 —— 生成式搜索入口；统一读 store.questions）
    try:
        from app.services.store import get_store

        pool = get_store().load("questions")
    except Exception:  # noqa: BLE001
        pool = []
    pool_questions = _relevance_order(question, pool, "question")[:max_pool]
    for q in pool_questions:
        qtext = str(q.get("question") or "")
        if any(k in qtext for k in ("对比", "区别", "vs", "还是")):
            q["pool_type"] = "对比"
        elif any(k in qtext for k in ("怎么样", "靠谱", "安全", "值得", "好不好", "适合")):
            q["pool_type"] = "决策"
        else:
            q["pool_type"] = "用户会问"

    queries = _question_queries(question, pool_questions)
    selected_material_ids, uploaded_sources = _file_material_selection(question, file_assets, queries)
    file_prompt = _source_material_prompt(uploaded_sources)
    if file_prompt:
        materials.append("## 用户上传资料（企业提供口径，原文选段）\n" + file_prompt)

    # 市场现状信号（审计 A6 · Owner 2026-09-21 拍板）：AI 现在怎么答 / 引用过什么 /
    # 编造过什么 / 竞品被夸在哪 / 周期报告结论。只读自己的库，不写、不调 LLM。
    try:
        from services.content.signals import build_market_signals

        signals = await build_market_signals(question=question, tenant_id=tenant_id)
    except Exception:  # noqa: BLE001
        signals = {"ai_answers": [], "citations": [], "hallucinations": [], "competitor_edges": [],
                   "report_findings": [], "available": False}

    context_sources = [
        {"kind": "enterprise_fact", "label": "正式企业事实（与主题相关的部分）", "items": [
            {"fact": line.lstrip("- ").strip()} for line in official_facts[:30]
        ]},
        {"kind": "document_chunk", "label": (
            "知识库文档切块（原文 · 取自 GEO 同步的快照）" if chunks_from_snapshot
            else "知识库文档切块（原文）"
        ), "items": [
            {"chunk": line} for line in chunk_lines
        ]},
        {"kind": "entity", "label": "知识库实体（命中对象）", "items": [
            {"name": name} for name in entity_names
        ]},
        {"kind": "faq_asset", "label": "FAQ 内容资产", "items": [
            _asset_source_item(question, a, 300) for a in faq_assets
        ]},
        {"kind": "asset", "label": "原始内容资产", "items": [
            _asset_source_item(question, a, 400) for a in other_assets
        ]},
        *uploaded_sources,
        {"kind": "question_pool", "label": "客户问题池", "items": [
            {"question": q.get("question"), "priority": q.get("priority")} for q in pool_questions
        ]},
        # 只列**真有数据**的信号（2026-09-22 修）：这五行原来写死，没跑过监测也显示「5 条」，
        # 页面上的「本篇引用的上下文来源」于是恒报一个假的 5。空就是空，如实显示 0 条。
        {"kind": "market_signal", "label": "市场现状（监测 / 认知评估）", "items": [
            row
            for row in (
                {"signal": "AI 当前回答", "count": len(signals.get("ai_answers") or [])},
                {"signal": "AI 引用过的内容", "count": len(signals.get("citations") or [])},
                {"signal": "AI 编造过的说法", "count": len(signals.get("hallucinations") or [])},
                {"signal": "竞品被夸因子", "count": len(signals.get("competitor_edges") or [])},
                {"signal": "周期报告结论", "count": len(signals.get("report_findings") or [])},
            )
            if row["count"]
        ]},
    ]
    return {
        "company_name": auto_name,
        "materials": materials,
        "faq_assets": faq_assets,
        "other_assets": other_assets,
        "pool_questions": pool_questions,
        "context_sources": context_sources,
        "source_material_ids": selected_material_ids,
        "uploaded_sources": uploaded_sources,
        "knowledge_status": knowledge_status,
        "warnings": context_warnings,
        "signals": signals,
    }


_IMPROVE_SYSTEM = (
    "你是 GEO 内容编辑。你的唯一任务是**按用户给的修改要求改这份稿子**，"
    "不是重写、不是另外写一篇。不得新增企业事实、数据、案例。"
)

#: 改稿时喂给模型的正文上限（再长就截断，避免把整个上下文顶爆）
_IMPROVE_CONTENT_LIMIT = 12000


async def improve(
    *,
    title: str = "",
    content: str,
    instruction: str,
    question: str = "",
    company_name: str | None = None,
    tenant_id: str | None = None,
    source_material_ids: list[str] | None = None,
    context_sources: list[dict] | None = None,
) -> dict:
    """按用户的自然语言要求改这一篇（Owner 2026-09-22）。

    诚实约束：改稿**不新增企业事实** —— 注入的还是同一份企业事实块；没有依据的内容不许写。
    返回 {"title", "content", "source_title"}。
    """
    instruction = (instruction or "").strip()
    content = (content or "").strip()
    if not instruction:
        raise ValueError("请先写清楚要改什么")
    if not content:
        raise ValueError("没有可改的内容")

    if not tenant_id:
        from app.services.store import current_tenant

        tenant_id = current_tenant() or "tenant_corp_01"
    if context_sources is None:
        ctx = await build_context(
            question=(question or title or instruction).strip(),
            company_name=company_name,
            tenant_id=tenant_id,
            source_material_ids=source_material_ids,
        )
        facts = "\n".join(ctx["materials"][:30]) or "（本轮没有检索到相关资料；不能据此断言企业没有资料）"
        used_sources = [s for s in ctx.get("context_sources", [])
                        if s.get("kind") in ("enterprise_fact", "document_chunk", "entity", "uploaded_material", "faq_asset", "asset")]
        # Match the provenance projection to what improve actually consumes, including
        # original hand-written material/FAQ. Monitoring signals are not rewrite facts.
        for source in used_sources:
            if source.get("kind") in ("faq_asset", "asset"):
                for item in source.get("items") or []:
                    facts += f"\n- [用户素材，未经独立核验：{item.get('title')}] {item.get('content') or ''}"
    else:
        # API has checked these excerpts against the current cabinet/read contract.
        # Render the exact prior projection; never re-rank or silently add sources.
        used_sources = [s for s in context_sources if s.get("kind") in (
            "enterprise_fact", "document_chunk", "entity", "uploaded_material", "faq_asset", "asset")]
        lines = []
        for source in used_sources:
            for item in source.get("items") or []:
                value = item.get("content") or item.get("fact") or item.get("chunk") or item.get("name")
                if value:
                    lines.append(f"- [{source.get('label') or source.get('kind')}] {value}")
        facts = "\n".join(lines) or "（原稿没有记录可用依据，不得新增企业事实）"
        ctx = {"source_material_ids": source_material_ids or [], "knowledge_status": "unknown",
               "warnings": ["rewrite_uses_original_sources"]}
    prompt = (
        "可用依据（严格区分正式知识库与企业自行提供的素材，不得混称；禁止编造）：\n" + facts
        + "\n\n当前稿子\n标题：" + (title or "（无标题）")
        + "\n正文：\n" + content[:_IMPROVE_CONTENT_LIMIT]
        + "\n\n修改要求（用户原话）：\n" + instruction
        + "\n\n规则：\n"
        "- 只按修改要求改；不要顺手改写与要求无关的部分\n"
        "- 不得新增企业事实、数据、案例、客户名；没有依据的内容不要写\n"
        "- 保留清晰的小标题与结论式表述（这类句子最容易被 AI 引用）\n"
        '严格 JSON 输出：{"title": "...", "content": "..."}'
    )
    text = await chat(prompt, system=_IMPROVE_SYSTEM, max_tokens=4000)
    blob = (text or "").strip()
    if not blob.startswith("{"):
        import re as _re

        m = _re.search(r"\{[\s\S]*\}", blob)
        blob = m.group(0) if m else ""
    if not blob:
        raise ValueError("模型没有返回可用的 JSON")
    parsed = json.loads(blob)
    new_content = str(parsed.get("content") or "").strip()
    if not new_content:
        raise ValueError("模型返回的正文是空的")
    return {
        "title": str(parsed.get("title") or title or "").strip(),
        "content": new_content,
        "source_title": title or "",
        "source_material_ids": list(ctx.get("source_material_ids") or []),
        "context_sources": used_sources,
        "knowledge_status": ctx.get("knowledge_status", "unknown"),
        "warnings": list(ctx.get("warnings") or []),
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
    tenant_id: str | None = None,
    mode: str = "creative",  # Fact Gate 模式：strict（严谨）/ creative（创作，默认）/ draft（草稿）
    structure: str = "free",  # 认知编译器：free（自由长文，默认）/ geo（可抽取结构模板）
    materials_extra: list[dict] | None = None,  # H19：外部个人素材并入生成上下文
    source_material_ids: list[str] | None = None,
) -> dict:
    # Resolve and validate explicitly selected files before any early return from Fact Gate.
    if not tenant_id:
        from app.services.store import current_tenant

        tenant_id = current_tenant() or "tenant_corp_01"
    ctx = await build_context(question=question, company_name=company_name, tenant_id=tenant_id,
                              source_material_ids=source_material_ids)
    # 0) Fact Gate：提取用户声明 → 多路验证（正式知识库 / 当前柜原始素材 / 无依据）
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
            "source_material_ids": list(ctx.get("source_material_ids") or []),
            "context_sources": ctx.get("context_sources") or [],
            "knowledge_status": ctx.get("knowledge_status", "unknown"),
            "warnings": list(ctx.get("warnings") or []),
        }
    # 1) Content Context Builder：聚合 正式事实/文档切块/实体 + FAQ 资产 + 历史素材 + 问题池
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
            hint = f"未识别到企业名称「{company_name.strip()}」：企业知识库里没有这个名称的对象。请核对名称，或先做一次知识库初始化把本公司与产品点选确认下来。"
        else:
            hint = "未识别到企业名称：请先在「高级工具 → 知识库初始化」里点选确认本公司与产品（扫描结果里若有多个像公司的名字，系统不替你猜），或在生成时手动填写公司名称。"
        return {
            "ok": False,
            "error": hint,
            "unverified_facts": [],
        }

    # 认知编译器（structure=geo）：企业画像提前构建——材料与 fact_check 同源（审计 P1-4），只查一次知识库
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
    company_block += "\n可用资料（严格区分正式知识库与企业自行提供的素材，不得混称）：\n"
    if materials:
        company_block += "\n".join(materials)
    elif ctx.get("knowledge_status") == "unavailable":
        company_block += "（知识库本次读取不可用；不能据此断言企业没有资料。没有可用事实时只写不含企业事实的通用内容。）"
    else:
        company_block += "（本次检索没有找到相关企业事实；不能据此断言企业没有资料。没有可用事实时只写不含企业事实的通用内容。）"

    # 内容资产引用层（FAQ/历史素材 → 补充素材；问题池 → 文章结构参考）
    asset_lines = []
    if ctx["faq_assets"]:
        asset_lines.append("历史 FAQ 内容（只作问题结构参考，不能单独证明企业事实）：")
        for a in ctx["faq_assets"]:
            ex = _asset_excerpt(question, a, 300)
            where = f"（第 {int(ex['chunk_ordinal']) + 1} 段）" if ex["chunk_ordinal"] is not None else ""
            asset_lines.append(f"- Q：{a.get('title')}\n  A{where}：{ex['text']}")
    if ctx["other_assets"]:
        asset_lines.append("其他原始内容素材（可参考不可照抄，不能单独证明企业事实，来源：内容资产）：")
        for a in ctx["other_assets"]:
            # 注入问句最贴的那一段，而不是整篇开头固定 150 字（Owner 2026-09-21）。
            ex = _asset_excerpt(question, a, 400)
            where = f"（命中第 {int(ex['chunk_ordinal']) + 1} 段）" if ex["chunk_ordinal"] is not None else ""
            asset_lines.append(f"- {a.get('title')}{where}：{ex['text']}")
    if ctx["pool_questions"]:
        asset_lines.append("客户问题池（客户正在问这些，文章结构应尽量覆盖，来源：GEO 问题池）：")
        for q in ctx["pool_questions"]:
            asset_lines.append(f"- {q.get('question')}（优先级 {q.get('priority')}）")
    if asset_lines:
        company_block += "\n\n## 内容资产引用（补充素材，不得作为企业事实编造）\n" + "\n".join(asset_lines)

    # 2.5) 市场现状（审计 A6）：AI 现在怎么答 / 编造过什么 / 竞品被夸在哪 / 报告结论
    from services.content.signals import render_market_signals

    market_block = render_market_signals(ctx.get("signals") or {})
    if market_block:
        company_block += "\n\n" + market_block

    prompt_materials_used = (
        len(materials)
        + max(0, sum(len(s.get("items") or []) for s in ctx.get("uploaded_sources") or []) - 1)
        + len(ctx.get("faq_assets") or [])
        + len(ctx.get("other_assets") or [])
        + len(ctx.get("pool_questions") or [])
        + (1 if market_block else 0)
    )

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
            word_count = _target_word_count(length, p)  # 审计 A4：平台区间生效
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
                topicRule=topic_rule(question, auto_name),
                companyBlock=company_block,
            )
        else:
            word_count = _target_word_count(length, p)  # 审计 A4：平台区间生效
            prompt = _DEFAULT_GENERATE_PROMPT.format(
                platform=p["name"],
                platformFeatures=p["features"],
                style=style,
                wordCount=word_count,
                brandName=auto_name or "（企业名）",
                goalLine=goal_line,
                typeLine=type_line,
                question=question or "（未提供具体问题，按内容类型自行组织）",
                topicRule=topic_rule(question, auto_name),
                companyBlock=company_block,
            )
    else:
        # 通用（无平台）：保留原逻辑
        topic_rule_text = topic_rule(question, auto_name)
        prompt = f"""请基于以下信息生成一篇 GEO（生成式引擎优化）内容草稿。

## 内容目标
{goal_line}

## 内容类型与结构要求
{type_line}

## 用户问题 / 主题
{question or "（未提供具体问题，按内容目标与类型自行组织）"}

{topic_rule_text}

## 企业资料（用来支撑上面的题目，不是文章主角）
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

    # 生成（失败重试：瞬时限流/网络抖动；审计 B12——原实现同 prompt 原样立刻重发一次，
    # 对限流窗口没有意义。改为指数退避重试，最多 3 次尝试，最终仍失败则抛出最后一次错误。）
    import asyncio

    from adapters.llm import LLMError as _LLMError

    last_err: Exception | None = None
    text = ""
    for attempt in range(3):
        try:
            text = await chat(prompt, system=_SYSTEM, max_tokens=3000)
            last_err = None
            break
        except _LLMError as e:
            last_err = e
            if attempt < 2:
                await asyncio.sleep(2**attempt)  # 1s, 2s 退避
    if last_err is not None:
        raise last_err

    title = ""
    first_line = text.strip().split("\n")[0] if text.strip() else ""
    if first_line.startswith("#"):
        title = first_line.lstrip("#").strip()
    elif first_line.startswith("**") and first_line.endswith("**"):
        title = first_line.strip("*").strip()
    elif first_line.startswith("【标题】") or first_line.startswith("【SEO标题】"):
        title = re.sub(r"^【(?:SEO)?标题】\s*", "", first_line).strip()
        lines = text.strip().split("\n")
        if not title:
            title = next((line.strip() for line in lines[1:] if line.strip()), "")

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
        "materials_used": prompt_materials_used,
        "context_sources": ctx["context_sources"],
        "source_material_ids": list(ctx.get("source_material_ids") or []),
        "knowledge_status": ctx.get("knowledge_status", "unknown"),
        "warnings": list(ctx.get("warnings") or []),
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
        "market_signals": ctx.get("signals") or {},  # 审计 A6：本篇据以写作的市场现状（只读实测）
        "keywords": [],
        "geo_score": None,
        "status": "draft",
    }
