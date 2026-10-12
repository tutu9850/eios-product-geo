"""GEO → EIOS 统一模型入口（Model Capability 服务）的 HTTP 客户端。

Owner 2026-09-21：「Model Capability 是 EIOS 的统一模型入口，**不属于 GEO，也不属于
Advisor**。企业部署配置模型，所有产品通过这一处调用。」

所以在 GEO 这一侧只剩一件事：拿自己的票，按 HTTP 调那个入口。这个模块**不**组合能力、
不读绑定账本、不认识 provider、不碰凭据 —— 那些是部署的事，也是**服务进程**的事。
之前 GEO 在自己的进程里 `from integrations.model_capability import from_environment`，
那是「同一份实现、多份实例」：每份都要自己拿到账本、适配器插件和部署公钥，
换个模式还会和自己的 PDP 撞车（一次实测：`EIOS_PDP_MODE=deployment_reads` 下
GEO 自己那次的模型目录读被判 403 `FORBIDDEN_SCOPE`）。

它与能力内部既有 `TransportResponse` 同形（`.status` / `.body`），于是
``adapters/llm.py`` 的调用点一行都不用改 —— 换掉的只是「能力从哪来」。

失败一律如实报，不回落成裸 HTTP：
* 没配 ``EIOS_MODEL_CAPABILITY_URL`` → 明确说这个部署没有模型入口；
* 服务说 401/403/503 → 原样把它的状态码与 code 交给上层（GEO 不重写权威的错误码）。
"""
from __future__ import annotations

from typing import Any, NamedTuple

import httpx

from adapters import identity
from app.runtime.mode import require_outbound_network

CATALOG_PATH = "/model/catalog"
INVOKE_PATH = "/model/invoke"
#: 一次真调用可能几十秒（联网搜索的引擎 20-60s），所以超时给足；不重试、不降级。
TIMEOUT_SECONDS = 120.0
#: 冷启动/重启期间服务还没起来时，上层看到的是一句「暂时不可达」，不是一个假的空答案。
_UNAVAILABLE = "MODEL_CAPABILITY_UNAVAILABLE"


class EntryResponse(NamedTuple):
    """与能力内部 ``TransportResponse`` 同形。"""

    status: int
    body: dict[str, Any]


def base_url() -> str:
    return identity.env("EIOS_MODEL_CAPABILITY_URL", "").rstrip("/")


class ModelEntryClient:
    """只做传输与契约校验。没有缓存，没有重排，没有本地回落。"""

    def __init__(self, url: str = "", *, transport: httpx.BaseTransport | None = None) -> None:
        self._url = (url or base_url()).rstrip("/")
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._url)

    def _call(
        self,
        path: str,
        *,
        scopes: tuple[str, ...],
        method: str = "POST",
        payload: dict[str, Any] | None = None,
    ) -> EntryResponse:
        require_outbound_network("model_capability_entry")
        from adapters.llm import remaining_budget
        remaining_budget(TIMEOUT_SECONDS)
        if not self.configured:
            # 部署没给统一入口 = 部署没说模型在哪。这里补一个默认地址就是 GEO 替部署决定。
            return EntryResponse(
                503,
                {
                    "code": "MODEL_CAPABILITY_NOT_CONFIGURED",
                    "message": "本部署没有配置 EIOS 的统一模型入口（EIOS_MODEL_CAPABILITY_URL）",
                },
            )
        ticket = identity.sign(
            audience=identity.MODEL_CAPABILITY_AUDIENCE,
            scopes=scopes,
            purpose=identity.PRODUCT_CONSUME_PURPOSE,
            code="MODEL_SIGNER_NOT_CONFIGURED",
        )
        try:
            with httpx.Client(
                timeout=remaining_budget(TIMEOUT_SECONDS),
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                remaining_budget(TIMEOUT_SECONDS)
                response = client.request(
                    method,
                    f"{self._url}{path}",
                    headers={"EIOS-Auth-Context": ticket, "Accept": "application/json"},
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError, TimeoutError, ConnectionError) as exc:
            return EntryResponse(
                503, {"code": _UNAVAILABLE, "message": f"统一模型入口暂时不可达：{exc}"[:300]}
            )
        remaining_budget(TIMEOUT_SECONDS)
        try:
            body = response.json()
        except ValueError:
            return EntryResponse(
                response.status_code,
                {
                    "code": "MODEL_INVALID_RESPONSE",
                    "message": f"统一模型入口返回了无法解析的响应（HTTP {response.status_code}）",
                },
            )
        return EntryResponse(response.status_code, body if isinstance(body, dict) else {})

    def catalog(self, *, auth_context: str) -> EntryResponse:
        """部署的模型目录。读它只为一件事实：这个部署默认调用哪个模型。"""
        return self._call(CATALOG_PATH, scopes=("model.catalog.read",), method="GET")

    def invoke(self, *, request: dict[str, Any], auth_context: str) -> EntryResponse:
        return self._call(INVOKE_PATH, scopes=("model.invoke",), payload=request)


__all__ = ["CATALOG_PATH", "INVOKE_PATH", "EntryResponse", "ModelEntryClient", "base_url"]
