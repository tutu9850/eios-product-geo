"""GEO 自动闭环（2026-08-15 新增）：监测报告分析 → 内容计划 → 内容生产 → 资产落库 → 重测验证

设计（诚实红线）：
- 自动生产：planned 计划 → content.generate（过 Fact Gate）→ 存 geo_kb 内容资产（source_type=generated）
- 不自动对外发布：存资产=「生产完成」，发布保持人工（红线：AI 不自动上线）
- 幂等：每条计划只生产一次（planned→produced 状态机防重复）；无目标问题/无公司名的计划跳过
- 验证：produced 计划关联素材，最新监测中该问题被提及或素材被引用 → verified
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.chunking import chunk_material

logger = logging.getLogger("eios.geo.loop")


def _tenant(explicit: str | None = None) -> str:
    from app.services.store import current_tenant

    return explicit or current_tenant()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_plans() -> List[Dict[str, Any]]:
    from app.services.store import get_store

    return get_store().load("content_plans")


def _save_plans(items: List[Dict[str, Any]]) -> None:
    from app.services.store import get_store

    get_store().save("content_plans", items)


def _load_materials() -> List[Dict[str, Any]]:
    from app.services.store import get_store

    return get_store().load("kb")


def _save_materials(items: List[Dict[str, Any]]) -> None:
    from app.services.store import get_store

    get_store().save("kb", items)


async def auto_production(limit: int = 5, tenant_id: str | None = None) -> Dict[str, Any]:
    """自动生产：planned 高优先级计划 → 生成内容 → 存内容资产 → 计划标 produced。

    返回 {produced: [...], skipped: [...], errors: [...]}。幂等：仅处理 planned。
    """
    from services.content import generate as generate_impl
    from app.services.store import set_tenant

    tenant_id = _tenant(tenant_id)
    set_tenant(tenant_id)

    plans = _load_plans()
    candidates = [
        p for p in plans
        if p.get("status") == "planned"
        and (p.get("target_question") or p.get("topic"))
    ]
    candidates.sort(key=lambda p: -(p.get("priority") or 0))
    candidates = candidates[:limit]

    produced: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    now = _now()

    for p in candidates:
        pid = p.get("id") or f"p_{uuid.uuid4().hex[:10]}"
        question = (p.get("target_question") or "").strip() or (p.get("topic") or "").strip()
        if not question:
            skipped.append({"plan_id": pid, "reason": "无目标问题/主题"})
            continue
        try:
            result = await generate_impl(
                goal="提升AI推荐概率",
                content_type=p.get("recommended_content_type") or "FAQ+案例文章",
                question=question,
                style="专业权威",
                length="1200",
                mode="creative",  # creative：未核验事实标「据企业宣传」（Fact Gate 兜底）
                tenant_id=tenant_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("loop 生产失败 %s: %s", pid, exc)
            errors.append({"plan_id": pid, "error": str(exc)[:120]})
            continue
        if not result or not result.get("ok") or not result.get("content"):
            reason = (result or {}).get("error") or "生成无内容"
            skipped.append({"plan_id": pid, "reason": str(reason)[:120]})
            continue

        # 存内容资产（source_type=generated，关联计划与覆盖问题）
        materials = _load_materials()
        mid = f"m_{uuid.uuid4().hex[:12]}"
        item = {
            "id": mid,
            "title": result.get("title") or question[:40],
            "content": result.get("content", ""),
            "source_type": "generated",
            "plan_id": pid,
            "gap_id": p.get("gap_id"),
            "coverage_questions": [question],
            "status": "stored",
            "chunks": 0,
            "vectors": 0,
            "created_at": now,
        }
        chunk_material(item)  # 自动生产出来的素材同样切块（只切块，不向量化）
        materials.insert(0, item)
        _save_materials(materials)

        # 计划 → produced（记录素材 id，供验证）
        for pl in plans:
            if (pl.get("id") or "").strip() == str(pid).strip() or pl.get("id") == pid:
                pl["status"] = "produced"
                pl["material_id"] = mid
                pl["produced_at"] = now
                break
        _save_plans(plans)

        produced.append({
            "plan_id": pid,
            "material_id": mid,
            "title": result.get("title"),
            "question": question,
            "unverified": len(result.get("unverified_facts") or []),
        })
        logger.info("[loop] 已生产 %s → %s（%s）", pid, mid, question[:30])

    return {
        "produced": produced,
        "skipped": skipped,
        "errors": errors,
        "total": len(produced),
        "note": "内容已存资产库（source_type=generated），发布保持人工；重测验证在下次监测后执行",
    }


def verify_production(tenant_id: str | None = None) -> Dict[str, Any]:
    """验证闭环：produced 计划关联素材 → 最新监测该问题是否被提及/素材被引用 → verified。

    诚实：只读 monitor_history 最新 batch；无新监测数据 → 保持 produced 不判定。
    """
    from app.services.store import get_store, set_tenant

    set_tenant(_tenant(tenant_id))
    plans = _load_plans()
    produced_plans = [p for p in plans if p.get("status") == "produced" and p.get("material_id")]
    if not produced_plans:
        return {"verified": [], "pending": [], "note": "无待验证计划"}

    history = get_store().load("monitor_history")
    batches = [h for h in history if h.get("batch")]
    latest = batches[-1] if batches else None

    verified: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    if not latest:
        return {
            "verified": [], "pending": [{"plan_id": p["id"], "material_id": p["material_id"]} for p in produced_plans],
            "note": "尚无批量监测数据，保持待验证（下次监测后自动核对）",
        }

    # 最新 batch：被提及的问题集合 + 被引用的素材 id 集合
    mentioned_questions = set()
    cited_material_ids = set()
    for q in latest.get("questions") or []:
        if q.get("mentioned_count", 0) > 0:
            mentioned_questions.add(q.get("question") or "")
    for c in latest.get("citations") or []:
        if c.get("material_id"):
            cited_material_ids.add(c["material_id"])

    now = _now()
    for p in produced_plans:
        q = (p.get("target_question") or "").strip()
        mid = p.get("material_id")
        hit = bool(q and q in mentioned_questions) or bool(mid and mid in cited_material_ids)
        if hit:
            p["status"] = "verified"
            p["verified_at"] = now
            verified.append({"plan_id": p["id"], "material_id": mid, "question": q, "evidence": "最新监测提及/引用"})
        else:
            pending.append({"plan_id": p["id"], "material_id": mid, "question": q, "reason": "最新监测未提及/未引用"})
    _save_plans(plans)

    return {
        "verified": verified,
        "pending": pending,
        "latest_batch": latest.get("created_at"),
        "note": "produced→verified：内容有效（监测提及/引用）；未命中保持 produced，提示调整内容后重测",
    }


async def run_loop(limit: int = 5, tenant_id: str | None = None) -> Dict[str, Any]:
    """完整闭环一次：自动生产 + 验证。"""
    tid = _tenant(tenant_id)
    prod = await auto_production(limit=limit, tenant_id=tid)
    ver = verify_production(tenant_id=tid)
    return {"production": prod, "verification": ver}
