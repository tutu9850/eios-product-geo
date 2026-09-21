"""内测：从企业知识库初始化「本公司资料」（Owner 2026-09-21 拍板）。

Owner 原话：「先搜知识库，筛选里面的公司和产品和相关文档，就是自动配置，让用户点击
选择，单独一个按钮，内测用，后面就第一次 增量刷新，快照」。

所以这个面只有三件事：

1. **扫**知识库（只读 —— GEO 永不写知识库，Owner 2026-09-20）→ 三桶候选：
   公司 / 产品 / 相关文档；
2. 让**用户点选**（前端一个独立按钮，明确标注「内测」）；
3. 把选中的落进 **GEO 自己的库** —— 用的还是那张既有的快照台账
   （``geo_knowledge_snapshots``，``kind=kb_initialization``）。

为什么不建第二张表：Owner 2026-09-20 已经拍过「读到的所有信息存进自己的数据库里存着」，
台账就是为这件事建的。这里不新建 Store、不双写、不新增 Authority。

「第一次全量 / 之后增量刷新」是**同一份选择不堆行**实现的：payload 只装稳定内容
（名字、文档 id 与标题、版本），不含时间戳，于是重复提交同一份选择时 payload_hash
不变 → 台账只累加 read_count 并推进 last_read_at；选择变大了就多一行新修订。
界面据此区分「本次新增了什么 / 一直是哪些」。

租户诚实说明：与其余 v1 面一样，仍按 legacy 租户柜（``tenant_id``）存，尚未按 EIOS
部署/企业身份分区 —— 这一点由快照台账的 ``tenant_id`` 如实带出，这里不另做一套。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import err, ok
from app.services import knowledge_snapshot

logger = logging.getLogger("eios.geo.kb_init")

router = APIRouter(prefix="/api/v1/kb-init")

#: 快照台账里这次初始化用的 kind。台账的 UniqueConstraint 是 (tenant, kind, hash)。
PROFILE_KIND = "kb_initialization"
CONTRACT = "product.geo_kb_init/v1"
#: 候选上限：内测阶段给人点选的名单，超过这个数就没法点了。
MAX_CANDIDATES = 60


class KbInitApplyIn(BaseModel):
    """用户点选的结果。文档只收 id —— 标题由 GEO 自己去知识库核对，不信客户端传的。"""

    companies: list[str] = []
    products: list[str] = []
    documents: list[str] = []


def _clean_names(values: list[str], limit: int = MAX_CANDIDATES) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        name = str(raw or "").strip()
        if not name or len(name) > 80 or name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _current_profile() -> dict:
    """GEO 库里现在这份「本公司资料」= 最近一次初始化的那份选择。

    没有 = 还没初始化过（``initialized=False``），而不是「知识库是空的」。
    """
    recent = knowledge_snapshot.list_recent(kind=PROFILE_KIND, limit=1)
    if not recent:
        return {
            "initialized": False,
            "revision": None,
            "last_applied_at": None,
            "read_count": 0,
            "companies": [],
            "products": [],
            "documents": [],
        }
    row = recent[0]
    payload = row.get("payload") or {}
    return {
        "initialized": True,
        "revision": row.get("snapshot_id"),
        "last_applied_at": row.get("last_read_at"),
        "read_count": int(row.get("read_count") or 1),
        "companies": [str(x) for x in (payload.get("companies") or [])],
        "products": [str(x) for x in (payload.get("products") or [])],
        "documents": [
            {
                "document_id": str(d.get("document_id") or ""),
                "title": str(d.get("title") or ""),
                "version": d.get("version"),
            }
            for d in (payload.get("documents") or [])
            if isinstance(d, dict)
        ],
    }


@router.post("/scan")
async def kb_init_scan():
    """扫一遍知识库，给出可点选的候选（公司 / 产品 / 相关文档）。

    公司/产品沿用入驻 ``detect`` 那一条已经验过的路（EIOS 的知识对象只有 entity/fact
    两种 type，公司/产品分类在 Semantic 不在 Knowledge，所以那边是「名称规则挑候选池 →
    模型只在候选池里挑」）。这里不重写第二套分类逻辑：调它，再补上文档那一桶。

    「读不到知识库」和「知识库是空的」必须分得开：前者原样报错并保留 ``error``，
    后者才是 ``empty=true`` + 提示上传。
    """
    from adapters.eios import list_documents
    from app.api.v1 import onboard

    profile = _current_profile()
    have_companies = set(profile["companies"])
    have_products = set(profile["products"])
    have_documents = {d["document_id"] for d in profile["documents"]}

    detect = await onboard._step_detect()
    if detect.get("error"):
        return err("knowledge_unreadable", str(detect["error"])[:300])

    documents: list[dict] = []
    doc_error: str | None = None
    try:
        documents = await list_documents(limit=100) or []
    except Exception as exc:  # noqa: BLE001 — 文档读不到只少一桶，不假装三桶齐全
        doc_error = str(exc)[:200]
        logger.warning("kb-init scan: list_documents failed: %s", exc)

    companies = [
        {"name": n, "in_profile": n in have_companies}
        for n in _clean_names(detect.get("company") or [])[:30]
    ]
    # 服务类也归在「产品」这一桶里点选：Owner 说的是「公司和产品」，而 detect 把
    # 产品/服务分开只是它内部的归类；对内测的人来说「我有哪些东西」是一件事。
    products = [
        {"name": n, "in_profile": n in have_products}
        for n in _clean_names([*(detect.get("products") or []), *(detect.get("services") or [])])
    ]
    document_items = [
        {
            "document_id": str(d.get("document_id") or ""),
            "title": str(d.get("title") or ""),
            "version": d.get("version"),
            "in_profile": str(d.get("document_id") or "") in have_documents,
        }
        for d in documents
        if d.get("document_id")
    ][:MAX_CANDIDATES]

    empty = not companies and not products and not document_items
    return ok(
        {
            "contract": CONTRACT,
            "initialized": profile["initialized"],
            "revision": profile["revision"],
            "last_applied_at": profile["last_applied_at"],
            "existing": {
                "companies": profile["companies"],
                "products": profile["products"],
                "documents": profile["documents"],
            },
            "candidates": {
                "companies": companies,
                "products": products,
                "documents": document_items,
            },
            "classification_source": detect.get("classification_source"),
            "industry": detect.get("industry"),
            "empty": empty,
            "error": doc_error,
            "hint": detect.get("hint"),
        }
    )


@router.post("/apply")
async def kb_init_apply(payload: KbInitApplyIn):
    """把用户点选的那份资料落进 GEO 自己的库（快照台账）。

    - 第一次 = 全量新建；
    - 之后 = **增量刷新**：选中的并进已有的那份，重复提交同一份选择不堆行（台账按
      payload_hash 去重），返回里如实说这次「新增了什么 / 一直是哪些」。
    - 文档标题由 GEO 自己去知识库核对：客户端只报 id。核不到的 id 不静默丢掉，
      原样列进 ``unknown_documents``。
    """
    from adapters.eios import list_documents

    companies = _clean_names(payload.companies)
    products = _clean_names(payload.products)
    wanted_ids = _clean_names(payload.documents, limit=MAX_CANDIDATES)
    if not companies and not products and not wanted_ids:
        return err("empty_selection", "一项都没选：至少勾选一个公司 / 产品 / 文档再提交")

    prev = _current_profile()

    documents: list[dict] = []
    unknown: list[str] = []
    if wanted_ids:
        try:
            known = {str(d.get("document_id") or ""): d for d in (await list_documents(limit=100) or [])}
        except Exception as exc:  # noqa: BLE001 — 核不了标题就不能假装存了
            return err("knowledge_unreadable", f"读知识库核对文档失败：{str(exc)[:200]}")
        for doc_id in wanted_ids:
            item = known.get(doc_id)
            if item is None:
                unknown.append(doc_id)
                continue
            documents.append(
                {
                    "document_id": doc_id,
                    "title": str(item.get("title") or ""),
                    "version": item.get("version"),
                }
            )

    merged_companies = sorted({*prev["companies"], *companies})
    merged_products = sorted({*prev["products"], *products})
    merged_documents = sorted(
        {d["document_id"]: d for d in [*prev["documents"], *documents]}.values(),
        key=lambda d: d["document_id"],
    )

    # payload 只装稳定内容：不含时间戳，否则每次提交哈希都变，去重与「增量」都没了。
    stored = {
        "contract": CONTRACT,
        "companies": merged_companies,
        "products": merged_products,
        "documents": merged_documents,
    }
    outcome = knowledge_snapshot.record(kind=PROFILE_KIND, payload=stored, source_url="")

    added_companies = [n for n in companies if n not in set(prev["companies"])]
    added_products = [n for n in products if n not in set(prev["products"])]
    had_docs = {d["document_id"] for d in prev["documents"]}
    added_documents = [d for d in documents if d["document_id"] not in had_docs]

    return ok(
        {
            "contract": CONTRACT,
            "first_time": not prev["initialized"],
            "added": {
                "companies": added_companies,
                "products": added_products,
                "documents": added_documents,
            },
            "kept": {
                "companies": len(merged_companies) - len(added_companies),
                "products": len(merged_products) - len(added_products),
                "documents": len(merged_documents) - len(added_documents),
            },
            "total": {
                "companies": len(merged_companies),
                "products": len(merged_products),
                "documents": len(merged_documents),
            },
            "unknown_documents": unknown,
            # recorded=false = 这份选择和上次一模一样（台账去重命中了）——「增量刷新」
            # 里什么都没变就该是这个结果，不是错误。
            "recorded": bool(outcome.get("recorded")),
            "revision": outcome.get("snapshot_id"),
            "read_count": outcome.get("read_count"),
            "note": "落在 GEO 自己的快照台账里；正本仍在企业知识库，GEO 只读不写",
        }
    )


__all__ = ["router", "PROFILE_KIND", "CONTRACT"]
