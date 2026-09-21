"""内容生成（草稿，不自动发布）— GEO 内容系统 MVP"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import ok, err
from adapters.llm import LLMNotConfiguredError, LLMError


class GenerateRequest(BaseModel):
    goal: str = "提升AI推荐概率"
    content_type: str = "企业介绍"
    question: str = ""
    company_name: str | None = None  # 留空 = 自动从 企业知识库读取
    style: str = "专业权威"
    length: str = "1500"
    industry: str | None = None
    platform: str | None = None  # 平台 id（zhihu/seo_article/...），空 = 通用
    seo: dict | None = None  # SEO 配置
    # 账号分柜（Owner 2026-09-22）：留空 = 用当前请求的柜（登录账号自己的），
    # 不再默认成所有人都共用的 tenant_corp_01。
    tenant_id: str | None = None
    mode: str = "creative"  # Fact Gate：strict（严谨）/ creative（创作，默认）/ draft（草稿）
    structure: str = "free"  # 认知编译器：free（自由长文）/ geo（可抽取结构模板）
    materials_extra: list[dict] | None = None  # H19：外部（如 yayu BFF 个人空间）素材并入生成上下文


class ScoreIn(BaseModel):
    content: str
    # 审计 A3：前端「内容评分」只发 title/content/goal/question/platform，从不发企业名，
    # 旧代码 company_name 缺省空串 → build_company_profile("") 返回空画像 → 评分恒 0。
    # 改为留空即自动识别当前企业（与 /content/generate 同口径）。
    company_name: str | None = None
    question: str = ""
    title: str = ""  # 前端携带（评分不使用；显式声明避免契约歧义）
    goal: str = ""  # 前端携带（同上）
    platform: str | None = None  # 前端携带（同上）
    tenant_id: str | None = None  # 留空 = 当前请求的柜（账号分柜）


router = APIRouter(prefix="/api/v1/content")


def _cabinet(explicit: str | None) -> str:
    """这次请求该读哪个柜：显式给的一律照用，否则用当前请求的柜（账号分柜）。"""
    if explicit:
        return explicit
    from app.services.store import current_tenant

    return current_tenant() or "tenant_corp_01"


@router.post("/generate")
async def generate(req: GenerateRequest):
    """生成 GEO 内容草稿（自动读企业资料；不自动发布）"""
    from services.content import generate as generate_impl

    try:
        result = await generate_impl(
            goal=req.goal,
            content_type=req.content_type,
            question=req.question,
            company_name=req.company_name,
            style=req.style,
            length=req.length,
            industry=req.industry,
            platform=req.platform,
            seo=req.seo,
            tenant_id=_cabinet(req.tenant_id),
            mode=req.mode,
            structure=req.structure,
            materials_extra=req.materials_extra,
        )
    except LLMNotConfiguredError as exc:
        return err("llm_not_configured", str(exc))
    except LLMError as exc:
        return err(exc.code, exc.message)
    return ok(result)


@router.post("/score")
async def score_content(req: ScoreIn):
    """GEO 评分：实体覆盖/事实密度/问题覆盖/结构完整 + 引用潜力（启发式）。"""
    from services.content.geo_score import score_geo_content
    from services.content.templates import parse_sections
    from app.services.company_profile import build_company_profile

    company_name = (req.company_name or "").strip()
    if not company_name:
        # 审计 A3：没给企业名时不再拿空画像评分，自动识别当前企业（读 企业知识库实体）
        from services.content import _auto_company

        company_name, _materials = await _auto_company(_cabinet(req.tenant_id))
        company_name = (company_name or "").strip()
    profile = await build_company_profile(company_name, tenant_id=_cabinet(req.tenant_id)) if company_name else {}
    # 2026-09-21（Owner：内容生成消费「文档切块 + 实体」）：
    # - 实体覆盖用**实体名**（``value`` 是那段原文，带着表格里别人的数字，不能当事实值）；
    # - 事实密度的数据点来自**正式事实 + 文档切块**（数字在原始资料里，正式事实多是职责句）。
    mentions = [{"canonical_name": (m.get("canonical_name") or "")} for m in (profile.get("facts") or [])]
    data_sources = [
        {"canonical_name": (f.get("canonical_name") or "")} for f in (profile.get("knowledge_facts") or [])
    ] + [
        {
            "kind": "document_chunk",
            "canonical_name": c.get("document_title") or "",
            "document_title": c.get("document_title") or "",
            "value": c.get("text") or "",
        }
        for c in (profile.get("knowledge_chunks") or [])
    ]
    sections = parse_sections(req.content)
    result = score_geo_content(
        req.content,
        knowledge_facts=mentions,
        data_sources=data_sources,
        pool_questions=profile.get("questions", []) if profile else [],
        sections=sections,
        company_name=company_name,  # 审计 P1-9：实体核心词剥离企业名前缀（参数化）
    )
    result["company_name"] = company_name or ""
    result["profile_resolved"] = bool(company_name)
    return ok(result)


@router.get("/company")
async def company():
    """识别当前企业（知识库 + 用户确认的档案）。

    2026-09-21：把「从哪认出来的」如实一起返回（profile / monitor_item / knowledge_scan /
    unresolved）—— 旧实现只回一个名字，前端拿到的错名字（素材标题）无从解释。
    """
    from services.company_identity import resolve_self_company
    from services.content import _auto_company

    # 账号分柜（Owner 2026-09-22）：识别「本公司」用的是**当前账号这个柜**的资料，
    # 不再固定读那个所有人共用的默认柜。
    from app.services.store import current_tenant

    cabinet = current_tenant() or "tenant_corp_01"
    resolved = await resolve_self_company(cabinet)
    name, materials = await _auto_company(cabinet)
    return ok({
        "company_name": name,
        "materials_count": len(materials),
        "company_source": resolved.get("source"),
    })


class ParseRequest(BaseModel):
    text: str


@router.post("/parse")
async def parse(req: ParseRequest):
    """AI 自动配置：把自然语言需求解析成 GEO 配置（目标/类型/风格/长度/平台/问题）"""
    from services.content import parse_intent
    from adapters.llm import LLMNotConfiguredError, LLMError

    if not req.text.strip():
        return err("empty_text", "请先描述你的需求")
    try:
        parsed = await parse_intent(req.text.strip())
    except LLMNotConfiguredError as exc:
        return err("llm_not_configured", str(exc))
    except LLMError as exc:
        return err(exc.code, exc.message)
    except ValueError as exc:
        return err("parse_failed", str(exc))
    return ok(parsed)


class QualityIn(BaseModel):
    content: str
    question: str = ""
    company_name: str | None = None


@router.post("/quality")
async def quality(req: QualityIn):
    """GEO 质量检测：内容 → 5 项评分（0-100）+ 改进建议"""
    from services.content import quality as quality_impl
    from adapters.llm import LLMNotConfiguredError, LLMError

    if not req.content.strip():
        return err("empty_content", "请先生成内容再检测")
    try:
        result = await quality_impl(
            content=req.content,
            question=req.question,
            company_name=req.company_name,
        )
    except LLMNotConfiguredError as exc:
        return err("llm_not_configured", str(exc))
    except LLMError as exc:
        return err(exc.code, exc.message)
    except ValueError as exc:
        return err("quality_failed", str(exc))
    return ok(result)
