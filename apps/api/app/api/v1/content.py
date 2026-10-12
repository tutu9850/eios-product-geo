"""内容生成（草稿，不自动发布）— GEO 内容系统 MVP"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import ok, err
from adapters.llm import LLMNotConfiguredError, LLMError, bounded_content_call
from adapters.eios import EIOSKnowledgeError, validate_formal_content_sources


class _SourceUnavailable(ValueError):
    pass


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
    source_material_ids: list[str] | None = None


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
    """Resolve the cabinet exclusively from verified request context.

    ``explicit`` remains in the model for wire compatibility, but is ignored
    so a caller cannot select another tenant by crafting a body field.
    """
    from app.services.store import current_tenant

    return current_tenant() or "tenant_corp_01"


@router.post("/generate")
async def generate(req: GenerateRequest):
    """生成 GEO 内容草稿（自动读企业资料；不自动发布）"""
    from services.content import generate_formal as generate_impl

    try:
        result = await bounded_content_call(lambda: generate_impl(
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
            source_material_ids=req.source_material_ids,
        ))
    except EIOSKnowledgeError as exc:
        return err(exc.code, exc.message)
    except LLMNotConfiguredError as exc:
        return err("llm_not_configured", str(exc))
    except LLMError as exc:
        return err(exc.code, exc.message)
    except ValueError as exc:
        return err("source_unavailable", str(exc))
    from services.content.claim_check import check_claims
    result["claim_check"] = check_claims(result.get("content", ""), result.get("context_sources", []))
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


class ImproveIn(BaseModel):
    """按用户的自然语言要求改这一篇（Owner 2026-09-22）。"""

    title: str = ""
    content: str
    instruction: str
    question: str = ""
    company_name: str | None = None
    tenant_id: str | None = None
    source_material_ids: list[str] | None = None
    context_sources: list[dict] | None = None


class SaveIn(BaseModel):
    """把生成/改好的内容存进 GEO 自己的内容资产（source_type=generated，会切块）。"""

    title: str = ""
    content: str
    question: str = ""
    source_material_ids: list[str] | None = None
    context_sources: list[dict] | None = None


class QualityIn(BaseModel):
    content: str
    question: str = ""
    company_name: str | None = None


@router.post("/improve")
async def improve(req: ImproveIn):
    """按提示词改这一篇（不新增企业事实）。"""
    from services.content import improve as improve_impl

    if not req.content.strip():
        return err("empty_content", "没有可改的内容")
    if not req.instruction.strip():
        return err("empty_instruction", "请先写清楚要改什么")
    try:
        async def run_improve():
            sources = None
            if req.context_sources is None:
                from services.content import build_formal_context
                context = await build_formal_context(question=req.question or req.title, company_name=req.company_name)
                sources = context["context_sources"]
            else:
                try:
                    sources, _ = await _validate_saved_sources(SaveIn(
                        title=req.title, content=req.content, question=req.question,
                        source_material_ids=req.source_material_ids, context_sources=req.context_sources,
                    ))
                except ValueError as exc:
                    raise _SourceUnavailable(str(exc)) from exc
            return await improve_impl(
                title=req.title,
                content=req.content,
                instruction=req.instruction,
                context_sources=sources,
                question=req.question,
                company_name=req.company_name,
                tenant_id=_cabinet(req.tenant_id),
                source_material_ids=req.source_material_ids,
            )

        result = await bounded_content_call(run_improve)
    except EIOSKnowledgeError as exc:
        return err(exc.code, exc.message)
    except LLMNotConfiguredError as exc:
        return err("llm_not_configured", str(exc))
    except LLMError as exc:
        return err(exc.code, exc.message)
    except _SourceUnavailable as exc:
        return err("source_unavailable", str(exc))
    except ValueError as exc:
        return err("improve_failed", str(exc))
    from services.content.claim_check import check_claims
    result["claim_check"] = check_claims(result.get("content", ""), result.get("context_sources", []))
    return ok(result)


@router.post("/save")
async def save(req: SaveIn):
    """存进当前账号柜的「内容资产 · 生成内容」。

    走的是内容资产同一条写入路径（``knowledge.add_material`` + 切块），
    所以存完在「内容资产」里能看到、也能被后续生成检索到。
    """
    from app.api.v1.knowledge import MaterialIn, add_material

    content = (req.content or "").strip()
    if not content:
        return err("empty_content", "没有可保存的内容")
    title = (req.title or "").strip() or (req.question or "").strip()[:40] or "未命名生成内容"
    try:
        sources, ids = await _validate_saved_sources(req)
    except EIOSKnowledgeError as exc:
        return err(exc.code, exc.message)
    except ValueError as exc:
        return err("source_unavailable", str(exc))
    from services.content.claim_check import check_claims
    body = await add_material(MaterialIn(
        title=title, content=content, source_type="generated",
        context_sources=sources, source_material_ids=ids,
        claim_check=check_claims(content, sources or []),
    ))
    if not body or not body.get("ok"):
        return body or err("save_failed", "保存失败，请重试")
    item = ((body or {}).get("data") or {}).get("item") or {}
    if not item.get("id"):
        return err("save_failed", "保存未返回草稿，请重试")
    return ok({"item": item, "source": "generated"})


async def _validate_saved_sources(req: SaveIn) -> tuple[list[dict] | None, list[str] | None]:
    """Re-read the current cabinet before accepting a client-side source projection.

    This preserves draft excerpts, not canonical Evidence or a certification. Old
    callers without provenance remain usable, with sources explicitly unrecorded.
    """
    if req.context_sources is None:
        if req.source_material_ids:
            raise ValueError("本篇出处未完整传回，请重新生成或改稿后保存")
        return None, None
    import json
    if len(req.context_sources) > 32 or len(json.dumps(req.context_sources, ensure_ascii=False)) > 60000:
        raise ValueError("本篇出处过大，请重新生成")
    if any(g.get("kind") == "canonical_fact" for g in req.context_sources):
        if any(g.get("kind") != "canonical_fact" for g in req.context_sources) or req.source_material_ids:
            raise EIOSKnowledgeError("FORMAL_SOURCE_REQUIRED", "正式稿不能混入未经治理的材料来源", 409)
        return await validate_formal_content_sources(req.context_sources), []
    import hashlib
    import json
    from app.services.store import get_store
    from services.content import build_context

    assets = {m.get("id"): m for m in get_store().load("kb")}
    ids = list(dict.fromkeys(req.source_material_ids or []))
    if len(ids) > 20 or any(i not in assets or assets[i].get("source_type") == "generated" for i in ids):
        raise ValueError("所选资料已不可用，请重新选材")
    # Local excerpts are validated against stored chunks, independently of ranking.
    for group in req.context_sources:
        if group.get("kind") != "uploaded_material":
            continue
        group["label"] = "用户上传资料（相关原文选段，未经独立核验）"
        for item in group.get("items") or []:
            if not isinstance(item, dict):
                raise ValueError("资料出处格式不完整")
            asset = assets.get(item.get("id"))
            if not asset or item.get("id") not in ids or asset.get("source_type") != "file" or item.get("source_type") != "file":
                raise ValueError("资料已不可用，请重新选材")
            chunks = asset.get("text_chunks") or []
            text = item.get("content")
            valid = any(c.get("text") == text and c.get("ordinal") == item.get("chunk_ordinal")
                        and c.get("id") == item.get("chunk_id") for c in chunks)
            if not chunks:
                valid = text == asset.get("content") and item.get("chunk_id") is None
            if not valid or item.get("title") != asset.get("title") or item.get("source_digest") != hashlib.sha256(str(text).encode()).hexdigest():
                raise ValueError("资料内容已变化或出处不匹配，请重新生成")
    others = [g for g in req.context_sources if g.get("kind") != "uploaded_material" and g.get("items")]
    if others:
        fresh = await build_context(question=req.question, tenant_id=_cabinet(None), source_material_ids=ids)
        for group in others:
            matches = [g for g in fresh.get("context_sources", []) if g.get("kind") == group.get("kind")]
            if not matches or any(item not in [i for g in matches for i in g.get("items", [])] for item in group.get("items", [])):
                raise ValueError("企业资料出处已不可用或变化，请重新取材")
    return req.context_sources, ids


@router.post("/quality")
async def quality(req: QualityIn):
    """GEO 质量检测：内容 → 5 项评分（0-100）+ 改进建议"""
    from services.content import quality as quality_impl
    from adapters.llm import LLMNotConfiguredError, LLMError

    if not req.content.strip():
        return err("empty_content", "请先生成内容再检测")
    try:
        result = await bounded_content_call(lambda: quality_impl(
            content=req.content,
            question=req.question,
            company_name=req.company_name,
        ))
    except LLMNotConfiguredError as exc:
        return err("llm_not_configured", str(exc))
    except LLMError as exc:
        return err(exc.code, exc.message)
    except ValueError as exc:
        return err("quality_failed", str(exc))
    return ok(result)
