"""内测：从企业知识库初始化「本公司资料」（Owner 2026-09-21 拍板）。

Owner 原话：「先搜知识库，筛选里面的公司和产品和相关文档，就是自动配置，让用户点击
选择，单独一个按钮，内测用，后面就第一次 增量刷新，快照」。

**这是全 GEO 唯一允许实时读企业知识库的地方**（Owner 2026-09-22：「除了手动的知识库同步
以外，不让 GEO 去知识库里找东西」）。别的面运行时只读 GEO 自己柜里的快照；这里因为是人
明确点了「同步」按钮，才用 ``adapters.eios.knowledge_read_grant("kb_sync")`` 开一次门。

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


class KnowledgeUnreadable(RuntimeError):
    """放行块里读知识库核对文档失败（调用方转成 ``knowledge_unreadable``）。"""


async def _capture_enterprise_knowledge(company_names: list[str]) -> dict:
    """把这次同步读到的**企业知识对象 / 正式事实 / 本公司关系**一并落进 GEO 自己的柜。

    为什么必须在同步这一步做：运行时（企业画像 / 蒸馏 / 监测 / 内容生成）已经不许实时读
    知识库了，它们读的是「GEO 自己柜里的快照」。同步时不多带一份回去，那边就只能是空的
    —— 那就不是「读自己的柜」，是「没数据」。

    读失败不抛：如实把 ``error`` 报出来，让页面知道这次同步少带了什么。
    """
    captured: dict = {"objects": 0, "facts": 0, "relations": 0, "error": None}
    try:
        from adapters.eios import get_entities

        captured["objects"] = len(await get_entities() or [])
    except Exception as exc:  # noqa: BLE001
        captured["error"] = f"读企业知识对象失败：{str(exc)[:160]}"
    try:
        from adapters.eios import list_enterprise_facts

        captured["facts"] = len(await list_enterprise_facts() or [])
    except Exception as exc:  # noqa: BLE001
        captured["error"] = f"读正式事实失败：{str(exc)[:160]}"
    try:
        from adapters.eios import search_relations

        total = 0
        for name in [c for c in company_names if c][:3]:
            total += len(await search_relations(name) or [])
        captured["relations"] = total
    except Exception as exc:  # noqa: BLE001 — 关系只是补充，读不到不影响这次同步
        logger.warning("kb-init scan: relations failed: %s", exc)
    return captured


async def _knowledge_content_probe() -> dict:
    """知识库里到底有没有东西（**必须在放行块内调用**）。

    Owner 2026-09-22：``公司产品可以不选，相关文档也可以不选``，而「20 个知识库对象 +
    0 个文档」仍然要把 GEO 工作空间初始化出来。所以空选择能不能落库，判据不是「人勾了
    几项」，而是**知识库里到底有没有货**：

    - 有对象（哪怕一个文档都没有）→ 有货，照常初始化；
    - 什么都没有 → 这才是「真的没东西」，仍然拒 ``empty_selection``，不做一个空壳初始化；
    - 读不到（票签不出来 / 连不上）→ 如实报 ``error``，调用方按 ``knowledge_unreadable``
      处理 —— 读不到 ≠ 是空的。
    """
    out: dict = {"objects": 0, "documents": 0, "has_content": False, "error": None}
    try:
        from adapters.eios import get_entities

        out["objects"] = len(await get_entities() or [])
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"读企业知识对象失败：{str(exc)[:160]}"
    try:
        from adapters.eios import list_documents

        out["documents"] = len(await list_documents(limit=1) or [])
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"读知识库文档列表失败：{str(exc)[:160]}"
    out["has_content"] = bool(out["objects"] or out["documents"])
    return out


async def _pull_documents(wanted_ids: list[str], list_documents, list_document_chunks):
    """在放行块里核对文档标题并拉回切块（只被 ``/apply`` 调用，调用方负责开门）。

    返回 ``(documents, unknown, chunks_pulled)``：
    - ``documents``：核对上的文档（id/标题/版本）；
    - ``unknown``：知识库里核不到的 id（如实列出来，不静默丢）；
    - ``chunks_pulled``：每份文档这次带回了几个切块（翻页到上限时标 ``truncated``）。
    """
    documents: list[dict] = []
    unknown: list[str] = []
    chunks_pulled: list[dict] = []
    if not wanted_ids:
        return documents, unknown, chunks_pulled
    try:
        known = {str(d.get("document_id") or ""): d for d in (await list_documents(limit=100) or [])}
    except Exception as exc:  # noqa: BLE001 — 核不了标题就不能假装存了
        raise KnowledgeUnreadable(f"读知识库核对文档失败：{str(exc)[:200]}") from exc
    # 知识库未发布的文档不在 documents 列表里，但 GEO 读到过它的切块 —— 也认。
    for c in knowledge_snapshot.documents_with_chunks():
        known.setdefault(
            c["document_id"],
            {"document_id": c["document_id"], "title": c["title"], "version": None,
             "source": "geo_snapshot"},
        )
    for doc_id in wanted_ids:
        item = known.get(doc_id)
        if item is None:
            unknown.append(doc_id)
            continue
        # 同步时把切块正文一并带过来存下（权威门开着读权威；门关着用 GEO 已存的快照）。
        pulled = 0
        truncated = False
        try:
            got = await list_document_chunks(doc_id)
            found = got.get("items") or []
            pulled = len(found)
            truncated = bool(got.get("truncated"))
            # **存下来**（Owner 2026-09-22：「同步知识库的时候就能看得到一并带过来存起来啊」）。
            # 以前这里只数了数就丢了 —— 台账 kind=chunks 从来没人写过，于是内容生成的
            # 「知识库文档切块（原文）」恒为 0。正本仍在知识库，这里存的是 GEO 读到的快照。
            if found:
                knowledge_snapshot.record(
                    kind="chunks",
                    payload=knowledge_snapshot.chunk_snapshot_payload(
                        [
                            {
                                **c,
                                # 台账按 document_id 取回某份文档的切块 —— 不管上游有没有给，
                                # 这里都用本次循环的 doc_id 钉死，别存成孤儿行。
                                "document_id": c.get("document_id") or doc_id,
                                "document_title": str(c.get("document_title") or item.get("title") or ""),
                            }
                            for c in found
                        ]
                    ),
                    source_url="",
                )
        except Exception as exc:  # noqa: BLE001 — 拉不到切块不影响「选中文档」这件事，但要如实报
            logger.warning("kb-init apply: chunks for %s failed: %s", doc_id, exc)
        entry = {"document_id": doc_id, "chunks": pulled}
        if truncated:
            # 翻页到上限还有下一页：如实说「这只是其中一部分」，不把少带说成带全了。
            entry["truncated"] = True
        chunks_pulled.append(entry)
        documents.append(
            {
                "document_id": doc_id,
                "title": str(item.get("title") or ""),
                "version": item.get("version"),
            }
        )
    return documents, unknown, chunks_pulled



@router.post("/scan")
async def kb_init_scan():
    """扫一遍知识库，给出可点选的候选（公司 / 产品 / 相关文档）。

    公司/产品沿用入驻 ``detect`` 那一条已经验过的路（EIOS 的知识对象只有 entity/fact
    两种 type，公司/产品分类在 Semantic 不在 Knowledge，所以那边是「名称规则挑候选池 →
    模型只在候选池里挑」）。这里不重写第二套分类逻辑：调它，再补上文档那一桶。

    「读不到知识库」和「知识库是空的」必须分得开：前者原样报错并保留 ``error``，
    后者才是 ``empty=true`` + 提示上传。
    """
    from adapters.eios import knowledge_read_grant, list_documents
    from app.api.v1 import onboard

    profile = _current_profile()
    have_companies = set(profile["companies"])
    have_products = set(profile["products"])
    have_documents = {d["document_id"] for d in profile["documents"]}

    # 开门：只有这里能实时读知识库；出了这个 with，别的面一律读 GEO 自己的柜。
    with knowledge_read_grant("kb_sync"):
        detect = await onboard._step_detect_from_knowledge()
        if detect.get("error"):
            return err("knowledge_unreadable", str(detect["error"])[:300])

        documents: list[dict] = []
        doc_error: str | None = None
        try:
            documents = await list_documents(limit=100) or []
        except Exception as exc:  # noqa: BLE001 — 文档读不到只少一桶，不假装三桶齐全
            doc_error = str(exc)[:200]
            logger.warning("kb-init scan: list_documents failed: %s", exc)
        # 同步一步到位：对象 / 正式事实 / 本公司关系一并落进 GEO 自己的柜
        # （运行时不再实时读知识库，靠的就是这份）。
        captured = await _capture_enterprise_knowledge(
            [str(x) for x in (detect.get("company") or [])]
        )

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
    # GEO 读到过切块的文档（含知识库里**未发布**、文档列表看不到的那些）。
    # Owner 2026-09-21：切块既然读得到并已存进 GEO 台账，同步时就该一并出现在候选里。
    read_docs = knowledge_snapshot.documents_with_chunks()
    seen_ids = {str(d.get("document_id") or "") for d in documents}
    document_items = [
        {
            "document_id": str(d.get("document_id") or ""),
            "title": str(d.get("title") or ""),
            "version": d.get("version"),
            "in_profile": str(d.get("document_id") or "") in have_documents,
            "listed": True,          # 知识库文档列表里有它（已发布）
            "chunks_stored": next(
                (int(c["chunks"]) for c in read_docs if c["document_id"] == str(d.get("document_id") or "")), 0
            ),
        }
        for d in documents
        if d.get("document_id")
    ] + [
        {
            "document_id": c["document_id"],
            "title": c["title"] or c["document_id"],
            "version": None,
            "in_profile": c["document_id"] in have_documents,
            "listed": False,        # 只在 GEO 快照里有（知识库未发布，读文档会被拒）
            "chunks_stored": int(c["chunks"]),
        }
        for c in read_docs
        if c["document_id"] and c["document_id"] not in seen_ids
    ]
    document_items = document_items[:MAX_CANDIDATES]

    empty = not companies and not products and not document_items
    # 「没有可勾选的候选」不等于「知识库里什么都没有」（Owner 2026-09-22：20 个对象 +
    # 0 个文档也要能把工作空间建起来）。所以空态提示要把对象数如实说出来，
    # 并且明确告诉人：不勾选也能初始化。
    objects_in_knowledge = int((captured or {}).get("objects") or 0)
    if empty and objects_in_knowledge > 0:
        empty_hint = (
            f"知识库里有 {objects_in_knowledge} 个知识对象，但没筛出可勾选的公司 / 产品 / 文档候选。"
            "不勾选也能点上面的按钮初始化工作空间 —— 这些对象和正式事实会一并带回 GEO 自己的柜。"
        )
    elif empty:
        # Foundation 会按当前登录主体、企业和文档 visibility_scope 过滤结果。
        # 这里不能把「当前账号看不到」说成「Foundation 没有资料」，更不能为了让
        # 卡片有数据而跨账号读取 personal 文档。把权限范围写进空态，用户才能知道
        # 应该切换账号、共享/发布文档，还是去排查服务连接。
        empty_hint = (
            "当前登录账号没有可导入的 Foundation 企业资料（只显示你有权限看到的文档）。"
            "请确认登录账号，或在 Foundation 将资料发布/共享后重新查找。"
        )
    else:
        empty_hint = ""
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
            "documents_from_snapshot": [
                {"document_id": c["document_id"], "title": c["title"], "chunks": c["chunks"]}
                for c in read_docs
                if c["document_id"] not in seen_ids
            ],
            "snapshot_note": (
                "有些文档在知识库里还没发布，读它的文档门会被拒（fail-closed）；"
                "它们的切块文本 GEO 已经读到并存进自己的台账，所以这里也能点选。"
                if any(c["document_id"] not in seen_ids for c in read_docs)
                else ""
            ),
            "captured": captured,
            "classification_source": detect.get("classification_source"),
            "industry": detect.get("industry"),
            "empty": empty,
            "objects_in_knowledge": objects_in_knowledge,
            "visibility_note": (
                "候选只来自当前登录账号在 Foundation 有权限读取的企业和文档；"
                "其他账号的私有资料、未共享或未发布的文档不会出现在这里。"
            ),
            "error": doc_error,
            "hint": empty_hint or detect.get("hint"),
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
    - **公司 / 产品 / 文档都可以不选**（Owner 2026-09-22）：空选择时先探一下知识库
      到底有没有货 —— 有（哪怕只有对象、0 个文档）就照样初始化工作空间并把企业对象 /
      事实带回 GEO 自己的柜；真什么都没有才拒 ``empty_selection``。
    """
    from adapters.eios import knowledge_read_grant, list_document_chunks, list_documents

    companies = _clean_names(payload.companies)
    products = _clean_names(payload.products)
    wanted_ids = _clean_names(payload.documents, limit=MAX_CANDIDATES)
    # Owner 2026-09-22：公司 / 产品 / 相关文档**都可以不选**。不勾选不再等于「拒绝」——
    # 只要知识库里确实有东西（例如 20 个知识对象 + 0 个文档），这一次同步照样把 GEO
    # 工作空间初始化出来（顺带把企业对象 / 正式事实 / 关系带回 GEO 自己的柜）。
    selection_empty = not companies and not products and not wanted_ids

    prev = _current_profile()

    # 同一次「手动同步」的放行块：核对文档标题 + 拉切块 + （空选择时）探知识库有没有货。
    captured: dict | None = None
    try:
        with knowledge_read_grant("kb_sync"):
            if selection_empty:
                probe = await _knowledge_content_probe()
                if probe["error"]:
                    return err("knowledge_unreadable", str(probe["error"])[:300])
                if not probe["has_content"]:
                    return err(
                        "empty_selection",
                        "一项都没选，知识库里也没有可用的对象 / 文档：先去知识库放资料，"
                        "或者扫描后勾选已有的项。",
                    )
                captured = await _capture_enterprise_knowledge([])
            documents, unknown, chunks_pulled = await _pull_documents(
                wanted_ids, list_documents, list_document_chunks
            )
    except KnowledgeUnreadable as exc:
        return err("knowledge_unreadable", str(exc)[:300])

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
    # 同步完成后让企业资料体检丢弃“未同步”缓存，下一次读取只看新快照。
    try:
        from app.api.v1.enterprise_profile import _clear_cache

        _clear_cache()
    except Exception as exc:  # noqa: BLE001 — 同步成功不能被展示缓存失败拖成失败
        logger.warning("clear enterprise profile cache after kb sync failed: %s", exc)

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
            # 同步时带回来的切块数（权威门开着=权威给的；门关着=GEO 已存快照）
            "chunks_pulled": chunks_pulled,
            "chunks_total": sum(c["chunks"] for c in chunks_pulled),
            "chunks_truncated": [c["document_id"] for c in chunks_pulled if c.get("truncated")],
            # recorded=false = 这份选择和上次一模一样（台账去重命中了）——「增量刷新」
            # 里什么都没变就该是这个结果，不是错误。
            "recorded": bool(outcome.get("recorded")),
            "revision": outcome.get("snapshot_id"),
            "read_count": outcome.get("read_count"),
            # 空选择 = 只是「把工作空间初始化出来」：公司 / 产品 / 文档清单还是空的，
            # 但企业对象 / 事实 / 关系已经带回 GEO 自己的柜（本次带回多少如实报 captured）。
            "selection_empty": selection_empty,
            "captured": captured,
            "note": (
                "这次没勾选任何项：工作空间已初始化，企业对象 / 正式事实已带回 GEO 自己的柜，"
                "公司 / 产品 / 文档清单还是空的，随时可以回去勾选。"
                if selection_empty
                else "落在 GEO 自己的快照台账里；正本仍在企业知识库，GEO 只读不写"
            ),
        }
    )


__all__ = ["router", "PROFILE_KIND", "CONTRACT"]
