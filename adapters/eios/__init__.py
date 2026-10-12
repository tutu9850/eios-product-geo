"""EIOS Foundation 知识库只读适配层 — GEO 读企业知识的唯一入口。

**读闸门（Owner 2026-09-22，代拍 · 待 Owner 复核）**：``除了手动的知识库同步以外，
不让 GEO 去知识库里找东西``。所以本模块默认**不放行实时读**：``_request`` 会抛
``KnowledgeReadBlocked``；各个读函数在闸门关着时改读 **GEO 自己柜里的快照**
（``app.services.knowledge_snapshot``，就是手动同步带回来的那份），没有同步过就如实返回空，
不回头去打 :8040。唯一放行实时读的入口是 ``knowledge_read_grant("kb_sync")`` ——
目前只有 ``/api/v1/kb-init/scan|apply``（页面上那个「知识库同步」按钮）持有它。


Owner 2026-09-20 拍板（本文件是它的落地）：
- **只读**。scope 常量表里只有读：``knowledge.search`` / ``knowledge.objects.read`` /
  ``knowledge.documents.read``。申请写 scope 的代码在这里不存在，也不接受调用方传入 scope。
- **不写**。知识库不接受 GEO 写入；换知识源前那个适配器的 ``write_candidate`` 已删除，调用它会明确
  失败（``AuthorityWriteNotAllowed``），不让「外部情报写回知识库」静默丢数据。
- **每一次读都留下快照**（``app/services/knowledge_snapshot.py``）：命中带回
  object_id / document_id / chunk_id / evidence_ids / 契约名 / 读的时刻。正本永远在知识库，
  GEO 库里那份只是快照，接口上如实标 ``authoritative=false``。
- **出站身份**：本部署密钥签 5 分钟票（``service_id=eios-geo``、``audience=eios-knowledge``、
  ``purpose=product.knowledge_consume``）。签发实现在 ``adapters/identity.py``（GEO 的出站
  身份只有那一处），和 eios-product-api / eios-product-advisor 是同一条路；scope 是本模块
  写死的只读表，调用方传不进来。

旧实现的记忆（为什么换）：换知识源前的适配器打的是 ``KERNEL_API_URL``（默认 localhost:8000），
那台在 EIOS 里根本不存在 —— dev 栈里 ``:8000`` 无人监听，所以「企业资料检测 / 缺口判定 /
内容生成」一直在拨空号。现在换成 EIOS 的知识库（``EIOS_KNOWLEDGE_URL``，dev 是 :8040）。
"""
from __future__ import annotations

import contextlib
import contextvars
from datetime import datetime, timezone
from typing import Any, Iterator

import httpx

from adapters import identity
from app.runtime.mode import require_outbound_network

#: audience → 允许申请的 scope。**只读**，且写死在这里，不接受调用方覆盖。
KNOWLEDGE_AUDIENCE = identity.KNOWLEDGE_AUDIENCE
KNOWLEDGE_READ_SCOPES: tuple[str, ...] = (
    "knowledge.search",
    "knowledge.objects.read",
    "knowledge.documents.read",
)
KNOWLEDGE_PURPOSE = identity.PRODUCT_CONSUME_PURPOSE
SEARCH_CONTRACT = "eios.knowledge_search/v2"
SEARCH_RESULT_CONTRACT = "eios.knowledge_search_result/v2"

DEFAULT_LIMIT = 8
MAX_LIMIT = 20
DEFAULT_TIMEOUT = 20.0
#: 出站票的 TTL。权威侧接受的最长 TTL 是 300s，取满即可（每次读现签，不缓存票）。
TOKEN_TTL_SECONDS = 300


class EIOSKnowledgeError(RuntimeError):
    """知识库调用失败（带权威错误码，供上层转成诚实的 envelope）。"""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.category = self._category(code, status)
        self.authority_refused = self.category == "refused"

    @staticmethod
    def _category(code: str, status: int) -> str:
        """Stable user-facing class while preserving the authority's original code."""
        normalized = str(code or "").upper()
        if normalized == "KNOWLEDGE_INVALID_RESPONSE":
            return "invalid_response"
        if status in (401, 403, 404, 409, 410) or any(
            marker in normalized
            for marker in ("DENIED", "FORBIDDEN", "UNAUTHORIZED", "SCOPE", "PERMISSION", "NOT_VISIBLE")
        ):
            return "refused"
        if normalized in {"KNOWLEDGE_UNAVAILABLE", "DEPENDENCY_NOT_ACTIVE"} or status >= 500:
            return "unavailable"
        return "unreadable"


#: 兼容别名：这个异常在换知识源前另有名字，调用点统一按知识库的名字捕获即可。
KnowledgeError = EIOSKnowledgeError


class AuthorityWriteNotAllowed(EIOSKnowledgeError):
    """GEO 不允许写知识库（Owner 2026-09-20）。"""

    def __init__(self, operation: str):
        super().__init__(
            "AUTHORITY_WRITE_NOT_ALLOWED",
            f"GEO 不允许写 EIOS 知识库（{operation}）；外部情报只能留在 GEO 自己的库里",
            403,
        )


# ── 读闸门（Owner 2026-09-22）───────────────────────────────────────────
#: 上下文里的放行凭据（谁开的门，写在里面，出错时报得出来）。
_GRANT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "geo_knowledge_read_grant", default=None
)


class KnowledgeReadBlocked(EIOSKnowledgeError):
    """闸门关着还想实时读知识库。

    Owner 2026-09-22：``除了手动的知识库同步以外，不让 GEO 去知识库里找东西``。
    这不是知识库拒绝，是 GEO 自己不发起这次读 —— 所以正文里写清楚「该读自己的柜」。
    """

    def __init__(self, operation: str):
        super().__init__(
            "KNOWLEDGE_READ_NOT_GRANTED",
            f"GEO 不允许在运行时实时读企业知识库（{operation}）；"
            "只有「知识库同步」这一步可以读，运行时请读 GEO 自己柜里的快照",
            403,
        )


def runtime_reads_enabled() -> bool:
    """部署级开关：``GEO_KNOWLEDGE_READ=on`` 才允许任何运行时实时读（排障用，默认关）。"""
    return _env("GEO_KNOWLEDGE_READ", "manual").strip().lower() == "on"


def reads_granted() -> bool:
    """这次调用有没有资格实时读知识库。"""
    return _GRANT.get() is not None or runtime_reads_enabled()


def current_grant() -> str | None:
    """当前这次读是谁开的门（没开门 = None）。"""
    return _GRANT.get()


@contextlib.contextmanager
def knowledge_read_grant(purpose: str) -> Iterator[str]:
    """开一次「手动知识库同步」的门。

    只给 ``/kb-init`` 用：用户明确点了同步按钮，才会把知识库里的东西读回来存进 GEO 自己的柜。
    出了这个 with 块，读闸门立刻关回去（不是进程级开关，别的地方拿不到这个门）。
    """
    token = _GRANT.set(str(purpose or "manual"))
    try:
        yield str(purpose or "manual")
    finally:
        _GRANT.reset(token)

def _env(name: str, default: str = "") -> str:
    return identity.env(name, default)


def knowledge_url() -> str:
    return _env("EIOS_KNOWLEDGE_URL", "http://127.0.0.1:8040").rstrip("/")


def service_id() -> str:
    """本服务在票上的名字。与 ``adapters.identity`` 同一处取值。"""
    return identity.service_id()


def _deployment_claims() -> dict[str, str]:
    """保留旧名字（测试与调用点按它读），实现只有 ``adapters.identity`` 一份。"""
    return identity.deployment_claims()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sign_token() -> str:
    """签一张只读票（实现见 ``adapters.identity``：GEO 的出站身份只有一处）。"""
    try:
        return identity.sign(
            audience=KNOWLEDGE_AUDIENCE,
            scopes=KNOWLEDGE_READ_SCOPES,
            purpose=KNOWLEDGE_PURPOSE,
            code="KNOWLEDGE_SIGNER_NOT_CONFIGURED",
            ttl=TOKEN_TTL_SECONDS,
        )
    except identity.SigningUnavailable as exc:
        raise EIOSKnowledgeError(exc.code, exc.message, exc.status) from exc


async def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_outbound_network("eios_knowledge")
    if not reads_granted():
        raise KnowledgeReadBlocked(f"{method} {path}")
    token = _sign_token()
    url = f"{knowledge_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, trust_env=False, follow_redirects=False) as client:
            response = await client.request(
                method,
                url,
                headers={"EIOS-Auth-Context": token, "Accept": "application/json"},
                json=json_body,
                params=params,
            )
    except httpx.HTTPError as exc:
        raise EIOSKnowledgeError("KNOWLEDGE_UNAVAILABLE", f"知识库不可达：{exc.__class__.__name__}", 502) from exc

    try:
        body = response.json()
    except ValueError as exc:
        if response.status_code in (401, 403, 404, 409, 410):
            raise EIOSKnowledgeError(
                "KNOWLEDGE_HTTP_ERROR",
                f"知识库拒绝请求（HTTP {response.status_code}，响应正文无法读取）",
                response.status_code,
            ) from exc
        raise EIOSKnowledgeError(
            "KNOWLEDGE_INVALID_RESPONSE", f"知识库返回非 JSON（HTTP {response.status_code}）", 502
        ) from exc

    if not isinstance(body, dict):
        if response.status_code in (401, 403, 404, 409, 410):
            raise EIOSKnowledgeError(
                "KNOWLEDGE_HTTP_ERROR",
                f"知识库拒绝请求（HTTP {response.status_code}，响应结构异常）",
                response.status_code,
            )
        raise EIOSKnowledgeError("KNOWLEDGE_INVALID_RESPONSE", "知识库返回结构异常", 502)
    if response.status_code >= 400 and body.get("ok"):
        code = "KNOWLEDGE_FORBIDDEN" if response.status_code in (401, 403) else "KNOWLEDGE_HTTP_ERROR"
        raise EIOSKnowledgeError(code, f"知识库请求失败（HTTP {response.status_code}）", response.status_code)
    if not body.get("ok"):
        error = body.get("error") or {}
        code = str(error.get("code") or "KNOWLEDGE_ERROR")
        response_status = response.status_code if response.status_code >= 400 else 502
        # Some authority routes encode denial in the envelope while returning HTTP 200.
        # Preserve the authority code and make the denial impossible to mistake for outage.
        if EIOSKnowledgeError._category(code, response_status) == "refused" and response_status == 502:
            response_status = 403
        raise EIOSKnowledgeError(
            code,
            str(error.get("message") or "知识库拒绝该请求")[:300],
            response_status,
        )
    data = body.get("data")
    if not isinstance(data, dict):
        raise EIOSKnowledgeError("KNOWLEDGE_INVALID_RESPONSE", "知识库成功响应缺少 data 对象", 502)
    return data


def _record(kind: str, payload: dict[str, Any]) -> bool:
    """把这次读到的内容落进 GEO 自己的库（快照）。失败不影响读，但要如实标注。

    返回 False = 这次读没有留下快照，调用方的 ``snapshot_recorded`` 就会是 false，
    不假装记上了。
    """
    try:
        from app.services.knowledge_snapshot import record

        record(kind=kind, payload=payload, source_url=knowledge_url())
        return True
    except Exception as exc:  # noqa: BLE001 — 快照失败不能让读失败
        import logging

        logging.getLogger("eios.geo.eios_adapter").warning("知识快照未落库（%s）: %s", kind, exc)
        return False


def _provenance(**extra: Any) -> dict[str, Any]:
    return {
        "source": "eios-knowledge",
        "source_url": knowledge_url(),
        "authority": KNOWLEDGE_AUDIENCE,
        "contract": SEARCH_RESULT_CONTRACT,
        "read_at": _now_iso(),
        "authoritative": False,
        "note": "这是 GEO 从 EIOS 知识库读到的快照；正本在知识库，可能已经更新",
        **extra,
    }


def _map_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """知识库 hit → GEO 内部沿用字段。

    ``value`` 放知识库给的原文片段（snippet）。这不是换知识源前那种 fact value：
    判定链（缺口/覆盖）读的是「有没有实质文本证据」，而片段就是权威给出的那段证据，
    所以这里如实当文本用，不伪造 predicate。
    """
    obj = hit.get("knowledge_object") or {}
    return {
        "score": hit.get("score"),
        "canonical_name": obj.get("canonical_name") or hit.get("document_title") or "",
        "name": obj.get("canonical_name") or hit.get("document_title") or "",
        "predicate": None,
        "value": hit.get("snippet") or "",
        "snippet": hit.get("snippet") or "",
        "layer": hit.get("authority"),
        "source_layer": hit.get("source_layer"),
        "object_id": obj.get("id"),
        "object_type": obj.get("type"),
        "document_id": hit.get("document_id"),
        "document_title": hit.get("document_title"),
        "chunk_id": hit.get("chunk_id"),
        "evidence_ids": list(hit.get("evidence_ids") or []),
        "freshness": hit.get("freshness"),
        "rank_reasons": list(hit.get("rank_reasons") or []),
    }


def hits_of(result: Any) -> list[dict[str, Any]]:
    """从 ``search_knowledge`` 的返回里取命中列表。

    2026-09-21 审计 A1：返回的顶层键是 ``hits``。三个调用点此前读
    ``results`` / ``objects`` / ``items``，全部恒空 —— 内容生成的「企业事实」
    因此永远是 0 条，正文里写着「知识库暂无该企业资料」。这里只留一个入口，
    不再让调用点各自猜键名（旧键仅作兼容兜底）。
    """
    if not isinstance(result, dict):
        return []
    for key in ("hits", "results", "objects", "items"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    return []


# ── 闸门关着时的读法：读 GEO 自己柜里的快照 ───────────────────────────────
# 这些函数**不打网络**：数据是「知识库同步」那一步读回来放进 GEO 库里的
# （``app.services.knowledge_snapshot``，kind = objects / documents / chunks / relations）。
# 没同步过 → 如实返回空，由调用方如实说「还没同步」，而不是回头去打 :8040。

_LOCAL_NOTE = "来自 GEO 自己柜里的知识库快照（手动同步带回来的那份）；正本仍在企业知识库"


def _local_provenance(**extra: Any) -> dict[str, Any]:
    return {
        "source": "geo_snapshot",
        "source_url": "",
        "authority": KNOWLEDGE_AUDIENCE,
        "contract": SEARCH_RESULT_CONTRACT,
        "read_at": _now_iso(),
        "authoritative": False,
        "note": _LOCAL_NOTE,
        **extra,
    }


def _n_gram_rank(text: str, rows: list[dict[str, Any]]) -> dict[str, float]:
    """用既有的 n-gram 口径给候选打分（不新建第二套打分公式，也不调模型/向量）。"""
    if not text or not rows:
        return {}
    try:
        from services.embed import n_gram_scores

        docs = [
            {"id": str(r.get("id") or ""), "title": str(r.get("title") or ""), "content": str(r.get("content") or "")}
            for r in rows
        ]
        return dict(n_gram_scores(text, docs, title_key="title", content_key="content"))
    except Exception as exc:  # noqa: BLE001 — 打分不可用就一条不给，不猜相关性
        import logging

        logging.getLogger("eios.geo.eios_adapter").warning("本地快照打分不可用: %s", exc)
        return {}


def _local_hit(source: dict[str, Any], *, score: float) -> dict[str, Any]:
    """本地快照条目 → 与 ``_map_hit`` 同形状的命中（调用方不用分两套字段）。"""
    return {
        "score": score,
        "canonical_name": source.get("canonical_name") or source.get("document_title") or "",
        "name": source.get("canonical_name") or source.get("document_title") or "",
        "predicate": None,
        "value": source.get("text") or source.get("snippet") or "",
        "snippet": source.get("text") or source.get("snippet") or "",
        "layer": source.get("layer") or "material",
        "source_layer": "geo_snapshot",
        "object_id": source.get("object_id"),
        "object_type": source.get("object_type"),
        "document_id": source.get("document_id"),
        "document_title": source.get("document_title"),
        "chunk_id": source.get("chunk_id"),
        "evidence_ids": list(source.get("evidence_ids") or []),
        "freshness": None,
        "rank_reasons": ["geo_snapshot"],
    }


def local_search(query: str, *, top_k: int = DEFAULT_LIMIT, include_candidates: bool = True) -> dict[str, Any]:
    """在 GEO 自己的快照里检索（切块 + 实体）。

    口径与实时检索一致：没有命中就返回空 —— **不许拿「最新资料」凑数**（Owner 2026-09-22）。
    """
    from app.services import knowledge_snapshot

    text = (query or "").strip()
    limit = max(1, min(int(top_k or DEFAULT_LIMIT), MAX_LIMIT))
    hits: list[dict[str, Any]] = []
    if text:
        chunks = knowledge_snapshot.all_chunks()
        scores = _n_gram_rank(
            text,
            [
                {
                    "id": str(c.get("chunk_id") or ""),
                    "title": str(c.get("document_title") or ""),
                    "content": str(c.get("text") or ""),
                }
                for c in chunks
            ],
        )
        for chunk in sorted(chunks, key=lambda c: -scores.get(str(c.get("chunk_id")), 0.0)):
            score = scores.get(str(chunk.get("chunk_id")), 0.0)
            if score <= 0:
                continue
            hits.append(_local_hit(chunk, score=score))
            if len(hits) >= limit:
                break
        if include_candidates:
            objects = knowledge_snapshot.objects()
            obj_scores = _n_gram_rank(
                text,
                [
                    {"id": str(o.get("object_id") or ""), "title": str(o.get("canonical_name") or ""), "content": ""}
                    for o in objects
                ],
            )
            for obj in objects:
                score = obj_scores.get(str(obj.get("object_id")), 0.0)
                if score <= 0:
                    continue
                hit = _local_hit(
                    {"canonical_name": obj.get("canonical_name"), "object_id": obj.get("object_id"),
                     "object_type": obj.get("object_type"), "evidence_ids": obj.get("evidence_ids")},
                    score=score,
                )
                if not any(h.get("object_id") == hit["object_id"] for h in hits):
                    hits.append(hit)
    payload = {
        "contract": SEARCH_RESULT_CONTRACT,
        "query": text[:512],
        "query_id": None,
        "matched": bool(hits),
        "hits": hits,
        "warnings": ["read_from_geo_snapshot", _LOCAL_NOTE],
        "layers": ["governed"] + (["material"] if include_candidates else []),
    }
    result = dict(payload)
    chunk_state = knowledge_snapshot.read_status("chunks")
    object_state = knowledge_snapshot.read_status("objects")
    has_snapshot = any(s["status"] != "not_synced" for s in (chunk_state, object_state))
    result["status"] = (
        "partial" if any(s["status"] == "partial" for s in (chunk_state, object_state))
        else "ready" if hits else ("empty" if has_snapshot else "not_synced")
    )
    result["provenance"] = _local_provenance(kind="search", query=text[:512])
    result["snapshot_recorded"] = False
    return result


def local_entities(*, limit: int = 200) -> list[dict[str, Any]]:
    """GEO 柜里的企业知识对象（快照），字段与 ``get_entities`` 一致。"""
    from app.services import knowledge_snapshot

    out = []
    for item in knowledge_snapshot.objects(limit=limit):
        out.append(
            {
                "canonical_name": item.get("canonical_name") or "",
                "name": item.get("canonical_name") or "",
                "object_type": item.get("object_type"),
                "status": item.get("status"),
                "evidence_ids": list(item.get("evidence_ids") or []),
                "object_id": item.get("object_id"),
                "object_scope": item.get("object_scope"),
                "semantic_object_id": item.get("semantic_object_id"),
                "authority_level": item.get("authority_level"),
                "source": "geo_snapshot",
            }
        )
    return out


async def search_knowledge(
    query: str,
    tenant_id: str | None = None,
    top_k: int = DEFAULT_LIMIT,
    include_candidates: bool = True,
) -> dict[str, Any]:
    """检索企业知识。

    ``include_candidates=True`` → 连未成为正式知识的**材料**（material 层）一起读，
    并在每条 ``layer`` 上标明；``False`` → 只读正式知识（governed 层）。
    ``tenant_id`` 参数保留只为兼容旧调用点：租户在 EIOS 里由票上的
    deployment/enterprise 决定，调用方无权指定。
    """
    if not reads_granted():
        # 闸门关着：读 GEO 自己柜里同步回来的那份，没有就如实空着（不打 :8040）。
        return local_search(query, top_k=top_k, include_candidates=include_candidates)
    text = (query or "").strip()
    if not text:
        # 空查询在换知识源前的老适配器里等于「列全部」。EIOS 的检索契约要求 query 非空，
        # 所以这里改走对象目录，并如实标成 list（不是 search 命中）。
        listed = await list_knowledge_objects(limit=MAX_LIMIT * 2)
        hits = [
            {
                "score": None,
                "canonical_name": item.get("canonical_name") or "",
                "name": item.get("canonical_name") or "",
                "predicate": None,
                "value": "",
                "snippet": "",
                "layer": "governed",
                "source_layer": "knowledge_object_list",
                "object_id": item.get("object_id"),
                "object_type": item.get("object_type"),
                "document_id": None,
                "document_title": None,
                "chunk_id": None,
                "evidence_ids": list(item.get("evidence_ids") or []),
                "freshness": None,
                "rank_reasons": ["object_catalog"],
            }
            for item in listed
        ]
        return {
            "contract": SEARCH_RESULT_CONTRACT,
            "query": "",
            "query_id": None,
            "matched": bool(hits),
            "hits": hits,
            "warnings": ["empty_query_reads_object_catalog"],
            "provenance": _provenance(kind="object_catalog"),
        }

    layers = ["governed"] + (["material"] if include_candidates else [])
    data = await _request(
        "POST",
        "/api/v1/knowledge/search",
        json_body={
            "contract": SEARCH_CONTRACT,
            "query": text[:512],
            "limit": max(1, min(int(top_k or DEFAULT_LIMIT), MAX_LIMIT)),
            "layers": layers,
            "version_scope": "current",
        },
    )
    hits = [_map_hit(hit) for hit in (data.get("hits") or [])]
    payload = {
        "contract": data.get("contract") or SEARCH_RESULT_CONTRACT,
        "query": text[:512],
        "query_id": data.get("query_id"),
        "matched": bool(data.get("matched")),
        "hits": hits,
        "warnings": list(data.get("warnings") or []),
        "layers": layers,
    }
    result = dict(payload)
    result["provenance"] = _provenance(
        kind="search", query=text[:512], query_id=data.get("query_id"), layers=layers
    )
    result["snapshot_recorded"] = _record("search", payload)
    _record_read_chunks(hits)
    return result


async def list_knowledge_objects(limit: int = 100, name: str | None = None) -> list[dict[str, Any]]:
    """企业知识对象目录（只读正式对象）。空查询/枚举场景用这个，不用假检索。"""
    if not reads_granted():
        from app.services import knowledge_snapshot

        return [
            {
                "object_id": item.get("object_id"),
                "canonical_name": item.get("canonical_name") or "",
                "object_type": item.get("object_type"),
                "status": item.get("status"),
                "object_scope": item.get("object_scope"),
                "semantic_object_id": item.get("semantic_object_id"),
                "authority_level": item.get("authority_level"),
                "evidence_ids": list(item.get("evidence_ids") or []),
            }
            for item in knowledge_snapshot.objects(limit=limit)
            if not name or name in str(item.get("canonical_name") or "")
        ]
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    remaining = max(1, int(limit))
    while remaining > 0:
        params: dict[str, Any] = {"limit": min(100, remaining), "status": "active"}
        if name:
            params["name"] = name
        if cursor:
            params["cursor"] = cursor
        data = await _request("GET", "/api/v1/knowledge/objects", params=params)
        page = data.get("items", [])
        if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
            raise EIOSKnowledgeError(
                "KNOWLEDGE_INVALID_RESPONSE", "知识库对象响应中的 items 格式无效", 502
            )
        next_cursor = data.get("next_cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise EIOSKnowledgeError(
                "KNOWLEDGE_INVALID_RESPONSE", "知识库对象响应中的 next_cursor 格式无效", 502
            )
        for item in page:
            items.append(
                {
                    "object_id": item.get("id"),
                    "canonical_name": item.get("canonical_name") or "",
                    "object_type": item.get("type"),
                    "status": item.get("status"),
                    "object_scope": item.get("object_scope"),
                    # 权威语义关联 + 权威等级：归类只许依据这两个权威字段，
                    # 不许 GEO 自己按关键词给事实分类（Owner 2026-09-21）。
                    "semantic_object_id": item.get("semantic_object_id"),
                    "authority_level": item.get("authority_level"),
                    "evidence_ids": list(item.get("evidence_ids") or []),
                }
            )
        cursor = next_cursor
        remaining -= len(page)
        if not cursor or not page:
            break
    return items


async def get_entities(
    company_id: str | None = None,
    include_candidates: bool = True,
    tenant_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """企业知识对象（老调用点沿用这个名字）。

    与换知识源前的老适配器的差别必须说清：EIOS 的知识对象只有 ``entity`` / ``fact`` 两种 type，
    没有 企业知识库那套 ``company`` / ``product`` / ``service`` 分类 —— 分类在 Semantic。
    所以 ``object_type`` 就是 EIOS 给的那两种，调用方不要再假设能拿到 company/product。
    ``company_id`` / ``tenant_id`` 保留只为兼容：租户由票决定。
    """
    if not reads_granted():
        return local_entities(limit=limit)
    require_outbound_network("eios_knowledge")
    items = await list_knowledge_objects(limit=limit)
    _record(
        "objects",
        {
            "contract": "eios.knowledge_object_list",
            "count": len(items),
            "items": items,
        },
    )
    out = []
    for item in items:
        out.append(
            {
                "canonical_name": item["canonical_name"],
                "name": item["canonical_name"],
                "object_type": item["object_type"],
                "status": item["status"],
                "evidence_ids": item["evidence_ids"],
                "object_id": item["object_id"],
                "object_scope": item.get("object_scope"),
                "semantic_object_id": item.get("semantic_object_id"),
                "authority_level": item.get("authority_level"),
                "source": "eios-knowledge",
            }
        )
    return out


async def list_enterprise_facts(limit: int = 400) -> list[dict[str, Any]]:
    """企业正式事实（``type=fact`` 的 active 知识对象）。

    Owner 2026-09-21 拍板：Knowledge 里的 active fact 就是正式企业事实，GEO 应当消费；
    GEO 只读、只展示、只给生成用，**不创建也不改写**事实。

    为什么走「对象目录」而不是检索：事实的 ``canonical_name`` 是一句三元组
    （如「吴鑫宇 负责人 自媒体运营」），里面通常不含公司名，用公司名检索**永远搜不到**
    （实测 77 条 fact 里 0 条含企业名）。目录才是企业自己那批对象的全集。

    ``limit`` 默认 400：实测本部署企业可见对象 371 条（entity 342 + fact 29），
    目录会自己按页取完并提前结束。
    """
    if not reads_granted():
        from app.services import knowledge_snapshot

        return knowledge_snapshot.objects(kind_filter="fact", limit=limit)
    items = await list_knowledge_objects(limit=limit)
    facts = [it for it in items if it.get("object_type") == "fact"]
    _record(
        "objects",
        {
            "contract": "eios.knowledge_object_list",
            "kind_filter": "fact",
            "count": len(facts),
            "items": facts,
        },
    )
    return facts


def _record_read_chunks(hits: list[dict[str, Any]]) -> bool:
    """把这次检索读到的**文档切块**单独落一条台账（kind=chunks）。

    Owner 2026-09-21：「读到的所有信息存进自己的数据库里存着」+「同步知识库的时候
    就能看得到一并带过来存起来」。切块正文是内容生成最要紧的材料，单独成条之后
    ``chunks_for_document()`` 才按文档取得回来（未发布文档的门关了也不至于丢材料）。
    """
    from app.services.knowledge_snapshot import chunk_snapshot_payload, record

    items = [
        {
            "document_id": hit.get("document_id"),
            "document_title": hit.get("document_title") or "",
            "chunk_id": hit.get("chunk_id"),
            "layer": hit.get("layer") or hit.get("authority"),
            "text": hit.get("snippet") or hit.get("value") or "",
        }
        for hit in hits
    ]
    payload = chunk_snapshot_payload(items)
    if not payload["items"]:
        return False
    try:
        info = record(kind="chunks", payload=payload, source_url=knowledge_url())
        return bool(info.get("snapshot_id"))
    except Exception as exc:  # noqa: BLE001 — 快照失败不能让读失败
        import logging

        logging.getLogger("eios.geo.eios_adapter").warning("切块快照未落库: %s", exc)
        return False


#: 读一份文档的切块时最多翻几页（每页最多 ``MAX_LIMIT`` 条）。到顶就如实标 ``truncated``，
#: 而不是把前几页当成全部 —— 「带过来存起来」不能把不完整说成完整。
_MAX_CHUNK_PAGES = 5


async def list_document_chunks(document_id: str, *, limit: int = 20) -> dict[str, Any]:
    """读某份文档的切块原文。

    权威的门（``GET /api/v1/knowledge/documents/{id}/chunks``）对**未发布**文档额外要求
    治理 scope；GEO 只有读 scope，所以未发布文档在那里是 404（fail-closed，权威侧有意为之，
    不是 GEO 能改的）。拒权代表本次没有读取资格，不能再用旧快照绕过当前拒绝。
    只有服务不可达等非拒绝失败才可显示明确标记为历史的快照：

    - ``source="knowledge"``：权威给的（正本，``authoritative`` 仍为 false —— GEO 不冒充权威）；
    - ``source="geo_snapshot"``：GEO 读过的快照（带 ``note`` 说明正本在知识库）；
    - 权威成功但返回空列表 → 合法空，不用旧快照补数据；
    - 拒权 → 原样抛出拒绝错误，绝不读取旧快照；
    - 服务不可达等失败 → 可显示带历史标记的快照；
    - 两边都没有 → 原样抛错误，不伪造空内容。

    ``limit`` 是**每页**条数；权威给了 ``next_cursor`` 就继续翻（最多 ``_MAX_CHUNK_PAGES`` 页）。
    翻到上限还有下一页时 ``truncated=true``，如实说明「这些不是全部」，不静默少带。
    """
    doc = (document_id or "").strip()
    if not doc:
        raise EIOSKnowledgeError("INVALID_PARAMETER", "document_id 不能为空", 400)
    page_limit = max(1, min(int(limit), MAX_LIMIT))
    path = f"/api/v1/knowledge/documents/{doc}/chunks"
    authority_error: Exception | None = None
    try:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _page in range(_MAX_CHUNK_PAGES):
            params: dict[str, Any] = {"limit": page_limit}
            if cursor:
                params["cursor"] = cursor
            data = await _request("GET", path, params=params)
            page_items = data.get("items")
            if not isinstance(page_items, list) or any(not isinstance(item, dict) for item in page_items):
                raise EIOSKnowledgeError(
                    "KNOWLEDGE_INVALID_RESPONSE", "知识库切块响应中的 items 格式无效", 502
                )
            items.extend(
                {
                    "document_id": doc,
                    "chunk_id": str(item.get("id") or ""),
                    "ordinal": item.get("ordinal"),
                    "text": str(item.get("content") or ""),
                    "document_title": "",
                    "source": "knowledge",
                    "authoritative": False,
                    "note": "来自企业知识库的正式读接口；GEO 只读，不冒充权威",
                }
                for item in page_items
            )
            cursor = data.get("next_cursor")
            if cursor is not None and not isinstance(cursor, str):
                raise EIOSKnowledgeError(
                    "KNOWLEDGE_INVALID_RESPONSE", "知识库切块响应中的 next_cursor 格式无效", 502
                )
            if not cursor:
                break
        truncated = bool(cursor)
        # A successful empty response is meaningful. Never turn it into stale cache data.
        if not items:
            return {
                "document_id": doc,
                "source": "knowledge",
                "items": [],
                "truncated": False,
                "warnings": [],
                "provenance": _provenance(kind="document_chunks"),
            }
        if items:
            _record_read_chunks([{**i, "snippet": i["text"]} for i in items])
            warnings = (
                [
                    "authority_chunks_truncated",
                    f"这份文档还有没读完的切块（翻到第 {_MAX_CHUNK_PAGES} 页上限），"
                    "这里只是其中一部分",
                ]
                if truncated
                else []
            )
            return {
                "document_id": doc,
                "source": "knowledge",
                "items": items,
                "truncated": truncated,
                "warnings": warnings,
                "provenance": _provenance(kind="document_chunks"),
            }
    except EIOSKnowledgeError as exc:
        # A current Authority refusal cannot be turned into a fresh cache grant.
        # Manual mode declines to issue a live request; it is not an Authority
        # denial. Preserve its existing historical-view behavior, clearly marked.
        if exc.authority_refused and not isinstance(exc, KnowledgeReadBlocked):
            raise
        authority_error = exc
    except Exception as exc:
        authority_error = exc

    from app.services.knowledge_snapshot import chunks_for_document

    stored = chunks_for_document(doc)
    if stored:
        return {
            "document_id": doc,
            "source": "geo_snapshot",
            "status": "historical_snapshot",
            "error": {"code": str(getattr(authority_error, "code", "KNOWLEDGE_UNAVAILABLE")),
                      "category": str(getattr(authority_error, "category", "unavailable")),
                      "message": str(authority_error)[:300]},
            "items": stored,
            "truncated": False,
            "warnings": [
                "authority_document_chunks_denied",
                f"权威文档读接口不可用（{type(authority_error).__name__ if authority_error else 'unknown'}），"
                "以下切块来自 GEO 自己读过的快照",
            ],
            "provenance": _provenance(kind="document_chunks", source="geo_snapshot"),
        }
    if authority_error is not None:
        raise authority_error
    return {
        "document_id": doc,
        "source": "knowledge",
        "items": [],
        "truncated": False,
        "warnings": [],
        "provenance": _provenance(kind="document_chunks"),
    }


async def list_documents(limit: int = 50) -> list[dict[str, Any]]:
    """企业文档列表（只读）。用于回答「企业有没有上传过资料」。

    闸门关着 → 读 GEO 柜里同步回来的文档名单（没有同步过就是空的，不打 :8040）。
    """
    if not reads_granted():
        from app.services import knowledge_snapshot

        return knowledge_snapshot.documents(limit=limit)
    require_outbound_network("eios_knowledge")
    data = await _request(
        "GET", "/api/v1/knowledge/documents", params={"limit": max(1, min(int(limit), 100))}
    )
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or any(not isinstance(item, dict) for item in raw_items):
        raise EIOSKnowledgeError(
            "KNOWLEDGE_INVALID_RESPONSE", "知识库文档响应中的 items 格式无效", 502
        )
    items = []
    for item in raw_items:
        items.append(
            {
                "document_id": item.get("id") or item.get("document_id"),
                "title": item.get("title") or "",
                "status": item.get("status"),
                "version": item.get("version"),
            }
        )
    _record("documents", {"contract": "eios.knowledge_documents", "count": len(items), "items": items})
    return items


async def search_relations(
    query: str, tenant_id: str | None = None, include_historical: bool = False
) -> list[dict[str, Any]]:
    """按实体名查关系：先在对象目录里按名找到对象，再读该对象的实例关系。

    返回空列表 = 该名字没有对象或没有关系；抛错 = 知识库不可用/无权限。
    两者必须区分，所以这里不吞异常。
    """
    text = (query or "").strip()
    if not text:
        return []
    if not reads_granted():
        from app.services import knowledge_snapshot

        return [
            r
            for r in knowledge_snapshot.relations()
            if text in str(r.get("source_name") or "") or text in str(r.get("target_name") or "")
        ]
    objects = await list_knowledge_objects(limit=5, name=text[:80])
    if not objects:
        return []
    relations: list[dict[str, Any]] = []
    for obj in objects[:3]:
        object_id = obj.get("object_id")
        if not object_id:
            continue
        data = await _request(
            "GET", f"/api/v1/knowledge/objects/{object_id}/instance-relations", params={"limit": 50}
        )
        for item in data.get("items") or []:
            relations.append(
                {
                    "source_id": item.get("source_object_id") or item.get("source_id") or object_id,
                    "relation_type": item.get("predicate") or item.get("relation_type"),
                    "target_id": item.get("target_object_id") or item.get("target_id"),
                    "target_name": item.get("target_name"),
                    "source_name": item.get("source_name") or obj.get("canonical_name"),
                    "evidence_ids": list(item.get("evidence_ids") or []),
                    "raw": item,
                }
            )
    _record(
        "relations",
        {"contract": "eios.knowledge_object_relations", "query": text[:80], "items": relations},
    )
    return relations


async def write_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """已删除的写路径。GEO 不允许写知识库（Owner 2026-09-20）。"""
    raise AuthorityWriteNotAllowed("knowledge.write")


__all__ = [
    "hits_of",
    "KnowledgeReadBlocked",
    "current_grant",
    "knowledge_read_grant",
    "local_entities",
    "local_search",
    "reads_granted",
    "runtime_reads_enabled",
    "AuthorityWriteNotAllowed",
    "EIOSKnowledgeError",
    "KnowledgeError",
    "KNOWLEDGE_AUDIENCE",
    "KNOWLEDGE_READ_SCOPES",
    "get_entities",
    "knowledge_url",
    "list_documents",
    "list_enterprise_facts",
    "list_document_chunks",
    "list_knowledge_objects",
    "search_knowledge",
    "search_relations",
    "write_candidate",
]
