"""Kernel 接入适配层 — GEO 读写知识的唯一入口

契约（架构方案 V2 §5）：
- 只调既有 Kernel API，不新增端点
- 读：GET /knowledge/entities、POST /knowledge/search
- 写：POST /knowledge/write（永远 status=candidate，不碰正式 DNA）
- 禁止：直接读 Kernel 数据库
"""
import httpx

from app.core.config import KERNEL_API_URL, KERNEL_TENANT_ID
from app.runtime.mode import require_outbound_network

_TIMEOUT = 15.0
DEFAULT_TENANT = KERNEL_TENANT_ID


class KernelError(Exception):
    """Kernel 调用失败（统一错误码，供上层转 envelope）"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def _request(method: str, path: str, **kwargs) -> dict:
    require_outbound_network("legacy_kernel")
    url = f"{KERNEL_API_URL.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
        resp = await client.request(method, url, **kwargs)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        raise KernelError("kernel_bad_response", f"Kernel 返回非 JSON: {resp.status_code} {resp.text[:120]}")
    if not body.get("ok"):
        raise KernelError("kernel_error", str(body.get("error") or "未知错误")[:200])
    return body.get("data", {})


async def get_entities(
    company_id: str | None = None,
    include_candidates: bool = True,
    tenant_id: str | None = None,
) -> list[dict]:
    """读企业资料（知识对象 entities）

    2026-08-19 用户拍板：GEO 消息来源不要求发布——部门库浅抽深抽的 candidate 也算，
    默认包含候选实体（Kernel 侧仅 active 不够，浅抽深抽产物未发布也要能读到）。

    tenant_id 走 Kernel 企业租户（KERNEL_TENANT_ID），不是 GEO 部门柜——部门隔离只作用在 3002 表。
    """
    params: dict = {"tenant_id": tenant_id or KERNEL_TENANT_ID}
    if company_id:
        params["company_id"] = company_id
    if include_candidates:
        params["include_candidates"] = "true"
    data = await _request("GET", "/api/v1/knowledge/entities", params=params)
    return data.get("entities", [])


async def search_knowledge(
    query: str, tenant_id: str = DEFAULT_TENANT, top_k: int = 10, include_candidates: bool = True
) -> dict:
    """Kernel 检索。

    2026-08-19 用户拍板：GEO 消息来源不要求发布——部门库浅抽深抽的 candidate 也算，
    默认包含候选（08-14 审计的「只读 active」契约按新业务规则放宽；治理/审计类显式传 False）。
    """
    return await _request(
        "POST",
        "/api/v1/knowledge/search",
        json={
            "query": query,
            "tenant_id": tenant_id,
            "top_k": top_k,
            "include_candidates": include_candidates,
        },
    )


async def search_relations(
    query: str, tenant_id: str = DEFAULT_TENANT, include_historical: bool = False
) -> list[dict]:
    """按实体名查 Kernel 关系（人话列表：'陈砚舟 负责 华信精工'）"""
    data = await _request(
        "POST",
        "/api/v1/knowledge/relations/search",
        json={
            "query": query,
            "tenant_id": tenant_id,
            "include_historical": include_historical,
        },
    )
    return data.get("relations") or data.get("items") or []


async def write_candidate(
    *,
    canonical_name: str,
    type_: str = "fact",
    predicate: str | None = None,
    value: str | None = None,
    evidence_ids: list[str] | None = None,
    authority_level: str = "system_record",
    tenant_id: str = DEFAULT_TENANT,
    company_id: str | None = None,
) -> dict:
    """写外部情报 → Kernel（永远 candidate，不碰正式 DNA）

    注意：Kernel write 只接受 type='entity'|'fact'（不支持 event）。
    外部事件用 fact + predicate 表达（如 predicate="launch_product"）。
    """
    payload = {
        "canonical_name": canonical_name,
        "type": type_,
        "predicate": predicate,
        "value": value,
        "evidence_ids": evidence_ids or [],
        "authority_level": authority_level,
        "tenant_id": tenant_id,
    }
    if company_id:
        payload["company_id"] = company_id
    return await _request("POST", "/api/v1/knowledge/write", json=payload)
