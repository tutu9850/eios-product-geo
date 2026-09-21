"""GEO 的引擎面：只认部署的统一模型入口。

Owner 2026-09-21 两条拍板合起来就是这个文件的样子：

* 「Model Capability 是 EIOS 的统一模型入口，**不属于 GEO**，也不属于 Advisor。企业部署
  配置模型，所有产品通过这一处调用。」
* 「GEO 不再写死 6 个。」 —— 有哪些引擎由**部署目录**说了算，企业配了几个就监测几个。

所以这里不再有 base_url / model / api_key / 温度表 / 联网参数表 / 豆包搜索分支：那些全是
部署的事实（绑定里的 ``base_url`` ``model`` ``secret_ref`` ``temperature``
``disable_thinking``，加上适配器里的联网参数与豆包搜索形状）。GEO 只剩两句问法：

* 「这个部署有哪些模型」→ ``GET /model/catalog``
* 「问其中一个」→ ``POST /model/invoke``，consumer 写死 ``geo.monitor``

联网与否也由部署决定：监测这一面被登记为「可以联网」，于是结果里的 ``web_search`` 是
权威侧如实回报的事实 —— 监测报告要问 AI 再总结，内容生产不许联网，这条规矩不落在 GEO。

失败一律如实报，不回落成裸 HTTP，也不替部署猜一个模型：

* 入口没配 / 接不上 → ``EngineEntryUnavailable``
* 部署没给这个模型凭据 → ``EngineNotConfigured``（``ValueError`` 子类，监测按「未配置」落行）
* 权威侧其它拒绝 → ``EngineCallFailed``，code 原样带上来
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Sequence

from adapters import identity

#: 监测/问答这一面的 consumer 名。部署侧按这个名字决定要不要注入联网参数。
MONITOR_CONSUMER = "geo.monitor"
INVOCATION_CONTRACT = "eios.model_invocation/v1"
CAPABILITY = "model.text_generation"
#: 契约上限 16384；这一侧再压一道，防止某个调用点写错数量级。
MAX_OUTPUT_TOKENS = 16384

#: 权威侧这些话的意思是「这个部署还没有这个模型」，不是「调用失败」——监测据此落
#: 「未配置」那一行，而不是把它渲染成一次故障。
_NOT_CONFIGURED_CODES = frozenset({
    "MODEL_SECRET_UNAVAILABLE",
    "MODEL_BINDING_MISSING",
    "MODEL_CAPABILITY_NOT_CONFIGURED",
    "MODEL_CATALOG_UNAVAILABLE",
    "PROVIDER_NOT_ACTIVE",
})

_client: Any | None = None
_client_error: str | None = None
_client_lock = threading.Lock()


class EngineFaceError(RuntimeError):
    """引擎面这一侧说得清的一类失败：带 code / message / status。

    调用方（HTTP 端点）按它回一句可读的话，而不是让全局处理器把原因吞成 500
    「服务内部错误」—— 那样用户看到的是「GEO 坏了」，而真相可能是「你们的模型入口没起」。
    """

    code = "MODEL_CAPABILITY_UNAVAILABLE"

    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class EngineEntryUnavailable(EngineFaceError):
    """部署的统一模型入口接不上（没配这个部署，或服务不在）。"""

    def __init__(self, message: str, status: int = 503):
        super().__init__("MODEL_CAPABILITY_UNAVAILABLE", message, status)


class EngineNotConfigured(ValueError):
    """这个部署没有这个模型（或没给凭据）。不是故障，是部署事实。"""


class EngineCallFailed(EngineFaceError):
    """权威侧拒绝了这次调用：code 是它给的，原样带上去，不重写、不猜。"""


def _compose() -> Any:
    """接一次部署的统一模型入口。

    这里**不组合能力**，只建一个 HTTP 客户端：能力跑在基座自己的进程里（Owner
    2026-09-21），GEO 侧只有「入口在哪」这一个部署事实要读。失败也记住，不每次刷日志。
    """
    global _client, _client_error
    if _client is not None or _client_error is not None:
        return _client
    with _client_lock:
        if _client is not None or _client_error is not None:
            return _client
        try:
            from adapters.model_entry import ModelEntryClient

            entry = ModelEntryClient()
            if not entry.configured:
                raise RuntimeError(
                    "本部署没有配置 EIOS 的统一模型入口（EIOS_MODEL_CAPABILITY_URL）"
                )
            _client = entry
        except Exception as exc:  # noqa: BLE001 — 接不上就是「这个部署没模型」，如实记下
            _client_error = f"{type(exc).__name__}: {exc}"[:240]
    return _client


def _entry() -> Any:
    entry = _compose()
    if entry is None:
        raise EngineEntryUnavailable(
            "这个部署的统一模型入口接不上（"
            f"{_client_error}）。它由部署的模型目录与 pbind_ 绑定账本决定，不是 GEO 能补的。"
        )
    return entry


def _ticket(scopes: Sequence[str]) -> str:
    return identity.sign(
        audience=identity.MODEL_CAPABILITY_AUDIENCE,
        scopes=scopes,
        purpose=identity.PRODUCT_CONSUME_PURPOSE,
        code="MODEL_SIGNER_NOT_CONFIGURED",
    )


def _error_of(response: Any) -> tuple[int, str, str]:
    """``(status, code, message)`` —— 权威侧的答复原样读出来，不改写。"""
    body = response.body if isinstance(response.body, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = str(error.get("code") or body.get("code") or f"MODEL_HTTP_{response.status}")
    message = str(error.get("message") or body.get("message") or "统一模型入口拒绝了这次调用")[:300]
    return int(response.status), code, message


def _raise_for(response: Any) -> None:
    status, code, message = _error_of(response)
    if code in _NOT_CONFIGURED_CODES:
        raise EngineNotConfigured(f"{code}: {message}")
    raise EngineCallFailed(code, message, status)


async def _catalog_items() -> list[dict]:
    entry = _entry()
    response = await asyncio.to_thread(entry.catalog, auth_context=_ticket(("model.catalog.read",)))
    if response.status != 200:
        _raise_for(response)
    body = response.body if isinstance(response.body, dict) else {}
    items = body.get("items")
    if not isinstance(items, list):
        raise EngineCallFailed("MODEL_BAD_RESPONSE", "模型目录里没有 items")
    return [item for item in items if isinstance(item, dict)]


async def list_engines() -> list[dict]:
    """这个部署登记的监测引擎。**有几个是部署说了算**，GEO 不再写死。

    只取能接文本的（监测问的是文本问题），并且不暴露 base_url / model —— 那两件事
    是部署的，GEO 知道得越少越好。
    """
    return [
        {"id": str(item.get("model_id") or ""), "name": str(item.get("display_name") or item.get("model_id") or "")}
        for item in await _catalog_items()
        if item.get("enabled") is True and "text" in (item.get("modalities") or [])
    ]


async def engine_status() -> list[dict]:
    """给「引擎配置」页看的事实：哪些引擎登记在这个部署里。

    **不再报 ``configured``** —— 凭据由企业部署持有，产品无法预先知道；报一个「已配置」
    而实际调不通就是替部署吹牛。能不能调通，看 ``ping`` 实测或监测那一行的真实结果。
    """
    return [
        {
            "id": str(item.get("model_id") or ""),
            "name": str(item.get("display_name") or item.get("model_id") or ""),
            "enabled": item.get("enabled") is True,
            "capability_tags": list(item.get("capability_tags") or []),
            "source": "deployment_catalog",
        }
        for item in await _catalog_items()
    ]


async def _invoke(engine_id: str, question: str, max_tokens: int) -> dict:
    entry = _entry()
    request = {
        "contract": INVOCATION_CONTRACT,
        "model_id": engine_id,
        "consumer": MONITOR_CONSUMER,
        "modality": "text",
        "messages": [{"role": "user", "content": question}],
        "max_output_tokens": max(1, min(int(max_tokens), MAX_OUTPUT_TOKENS)),
    }
    response = await asyncio.to_thread(
        entry.invoke, request=request, auth_context=_ticket(("model.invoke",))
    )
    if response.status != 200:
        _raise_for(response)
    body = response.body if isinstance(response.body, dict) else {}
    if not body.get("ok"):
        _raise_for(response)
    if body.get("capability") != CAPABILITY:
        raise EngineCallFailed("MODEL_BAD_RESPONSE", f"能力返回了别的能力：{body.get('capability')}")
    data = body.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        raise EngineCallFailed("MODEL_BAD_RESPONSE", "模型结果里没有 text 字段")
    if data.get("consumer") != MONITOR_CONSUMER:
        raise EngineCallFailed("MODEL_BAD_RESPONSE", f"结果里的 consumer 不是本服务的：{data.get('consumer')}")
    # ``web_search`` 是权威侧如实回报的事实；老适配器不报 = 不知道，按「没联网」记。
    return {"content": data["text"], "web_realtime": bool(data.get("web_search"))}


async def ask_with_meta(engine_id: str, question: str, max_tokens: int = 800) -> dict:
    """问一个引擎，返回 ``{"content", "web_realtime"}``。"""
    return await _invoke(engine_id, question, max_tokens)


async def ask(engine_id: str, question: str, max_tokens: int = 800) -> str:
    """同 ``ask_with_meta``，只取正文。"""
    return (await _invoke(engine_id, question, max_tokens))["content"]


async def ping(engine_id: str) -> dict:
    """连通性实测：真发一次最小调用（``max_output_tokens=1``），如实报能不能通。"""
    try:
        await _invoke(engine_id, "ping", 1)
    except EngineNotConfigured as exc:
        return {"id": engine_id, "reachable": None, "configured": False, "error": str(exc)[:150]}
    except EngineCallFailed as exc:
        return {"id": engine_id, "reachable": False, "configured": None, "error": f"{exc.code}: {exc.message}"[:150]}
    except EngineEntryUnavailable as exc:
        return {"id": engine_id, "reachable": None, "configured": None, "error": str(exc)[:150]}
    return {"id": engine_id, "reachable": True, "configured": True, "error": None}


__all__ = [
    "EngineCallFailed",
    "EngineFaceError",
    "EngineEntryUnavailable",
    "EngineNotConfigured",
    "ask",
    "ask_with_meta",
    "engine_status",
    "list_engines",
    "ping",
]
