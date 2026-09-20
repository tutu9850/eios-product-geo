"""GEO 统计汇总（数据中心）：聚合各模块数据成总览"""
from fastapi import APIRouter

from app.core.envelope import ok
from app.api.v1.knowledge import _load as _load_materials
from app.api.v1.links import _load as _load_links
from app.api.v1.monitor import _load_history

router = APIRouter(prefix="/api/v1/stats")


@router.get("/overview")
async def overview():
    # 知识库素材
    materials = _load_materials()
    text_blocks = sum(int(m.get("blocks") or 0) for m in materials)
    kb_bytes = sum(len(str(m.get("content") or "")) for m in materials)

    # 链接收录
    links = _load_links()
    linked = sum(1 for l in links if l.get("index_status") == "indexed")
    failed = sum(1 for l in links if l.get("index_status") == "failed")
    pending = sum(1 for l in links if l.get("index_status") in (None, "pending"))
    unknown = sum(1 for l in links if l.get("index_status") == "unknown")

    # 监测历史（2026-08-15 修复：旧实现读顶层 score/results——已迁移到 summary/questions 结构，看板恒 0）
    history = _load_history()
    monitor_count = len(history)
    mentioned = 0
    score_sum = 0
    for h in history:
        sm = h.get("summary") or {}
        if h.get("batch"):
            # 批量监测：只取 summary.mentioned_questions（去重后的被提及问题数）。
            # 修复（审计 H1）：不再叠加 questions[].mentioned_count 之和——该值与
            # mentioned_questions 语义重复（单引擎下恒等），旧实现双倍计数（13 → 26）。
            mentioned += sm.get("mentioned_questions") or 0
            score_sum += sm.get("coverage_pct") or 0
        else:
            # 单次 check：summary.mentioned / summary.score
            mentioned += sm.get("mentioned") or 0
            score_sum += sm.get("score") or 0
    avg_score = round(score_sum / monitor_count, 1) if monitor_count else 0

    # 引擎配置
    from adapters.engines import list_engines, engine_api_key

    engines = list_engines()
    configured = 0
    for e in engines:
        if await engine_api_key(e["id"]):
            configured += 1

    # 企业知识库（Kernel）状态（H21：purge 后为空 → 前端据此提示"知识库为空，内容生成/缺口判定受限"）
    try:
        from adapters.eios import get_entities

        kernel_entities = len(await get_entities())
        kernel_empty = kernel_entities == 0
        kernel_error = None
    except Exception as exc:  # noqa: BLE001
        kernel_entities = None
        kernel_empty = None
        kernel_error = str(exc)[:120]

    return ok(
        {
            "knowledge": {"materials": len(materials), "text_blocks": text_blocks, "bytes": kb_bytes},
            "links": {"total": len(links), "indexed": linked, "failed": failed, "pending": pending, "unknown": unknown},
            "monitor": {"runs": monitor_count, "mentioned": mentioned, "avg_score": avg_score},
            "engines": {"total": len(engines), "configured": configured},
            "kernel": {"entities": kernel_entities, "empty": kernel_empty, "error": kernel_error},
        }
    )
