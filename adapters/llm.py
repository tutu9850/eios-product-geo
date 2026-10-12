"""LLM 适配 —— 走**本部署自己的 Model Capability**，不再自带模型连接。

2026-09-20 改（Owner 拍板「连接一下」）。旧实现是 GEO 自己的一条模型连接：先打 Builder
（``http://localhost:3001/api/geo/model``），拿不到就回退 ``apps/api/.env`` 的
``LLM_API_KEY``/``LLM_BASE_URL``/``LLM_MODEL``。那在新栈里是**第二份模型真相**：
部署已经把「用哪个模型、走哪个 provider、凭据在哪」定好了（profile + ``pbind_`` 绑定账本），
产品再自带一份 .env 就等于绕开部署。

Owner 2026-09-21 再进一步：「Model Capability 是 EIOS 的统一模型入口，**不属于 GEO，
也不属于 Advisor**。企业部署配置模型，所有产品通过这一处调用。」

所以 GEO 不再在自己的进程里组合能力，而是按 HTTP 调 **EIOS 的统一入口**
（``adapters/model_entry.py`` → Model Capability 服务）：

- 以 ``consumer="geo.content_generation"`` 申请 ``model.text_generation``；
- ``model_id`` 用**部署的默认模型**（读 ``eios.model_catalog/v1``），GEO 不选 provider、
  不持凭据、不知道 base_url；
- 模型连接是部署事实：由部署的 catalog profile 与 ``pbind_`` 账本决定，改它要动部署配置。

失败一律如实报，不回落成裸 HTTP 调用：
- 组合不出能力 → ``LLMNotConfiguredError``（带真实原因）
- 能力拒绝 → ``LLMError(code)``，code 来自权威侧（如 ``PROVIDER_NOT_ACTIVE``）

契约没有 ``response_format`` 字段：要 JSON 时把「只输出 JSON」写进 system 指令，
**不伪造**一个权威侧不认识的参数。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import contextlib
import contextvars
import time
from dataclasses import dataclass, field
from typing import Any

from adapters import identity
from app.runtime.mode import require_outbound_network

logger = logging.getLogger("eios.geo.llm")

#: 契约 ``eios.model_invocation/v1`` 的 consumer 形状校验：小写点分。
CONSUMER = "geo.content_generation"
CAPABILITY = "model.text_generation"
INVOCATION_CONTRACT = "eios.model_invocation/v1"
#: 契约上限 16384；GEO 这一侧再压一道，防止某个调用点写错数量级。
MAX_OUTPUT_TOKENS = 16384

_JSON_ONLY = {"type": "json_object"}
_JSON_INSTRUCTION = "严格只输出 JSON（一个对象或数组），不要任何解释文字，不要代码块围栏。"

_capability: Any | None = None
_capability_error: str | None = None
_default_model_id: str = ""
_lock = threading.Lock()
_CONTENT_CALL_BUDGET_SECONDS = 35.0


@dataclass
class CallBudget:
    """Local waiting budget; stopping it does not terminate a running sync HTTP call."""
    deadline: float
    stopped: threading.Event = field(default_factory=threading.Event)

    def remaining(self) -> float:
        if self.stopped.is_set():
            raise LLMError("CONTENT_CANCELLED", "本次内容请求已停止等待")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise LLMError("CONTENT_DEADLINE_EXCEEDED", "本次内容请求已超过截止时间")
        return remaining


_budget: contextvars.ContextVar[CallBudget | None] = contextvars.ContextVar("geo_content_budget", default=None)


@contextlib.contextmanager
def call_budget(seconds: float):
    existing = _budget.get()
    budget = existing or CallBudget(time.monotonic() + seconds)
    token = _budget.set(budget)
    try:
        yield budget
    finally:
        if existing is None:
            budget.stopped.set()
        _budget.reset(token)


def remaining_budget(default: float = 120.0) -> float:
    budget = _budget.get()
    return min(default, budget.remaining()) if budget else default


async def bounded_content_call(call):
    """Use the existing 35s Product manage budget, including context and retries.

    ASGI task cancellation stops waiting and further attempts; a running thread
    can finish later, but its result cannot be returned as a successful draft.
    Product API client disconnect cancellation is not propagated into GEO.
    """
    with call_budget(_CONTENT_CALL_BUDGET_SECONDS) as budget:
        task = asyncio.create_task(call())
        try:
            done, _ = await asyncio.wait({task}, timeout=budget.remaining())
            budget.remaining()
            if task not in done:
                raise LLMError("CONTENT_DEADLINE_EXCEEDED", "本次内容请求已超过截止时间")
            return task.result()
        finally:
            budget.stopped.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class LLMNotConfiguredError(Exception):
    pass


class LLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _compose() -> Any:
    """接一次部署的统一模型入口。

    这里**不组合能力**，只建一个 HTTP 客户端：能力跑在基座自己的进程里（Owner
    2026-09-21），GEO 侧只有「入口在哪」这一个部署事实要读。失败也记住，
    不每次重试式地刷日志。
    """
    global _capability, _capability_error
    if _capability is not None or _capability_error is not None:
        return _capability
    with _lock:
        if _capability is not None or _capability_error is not None:
            return _capability
        try:
            from adapters.model_entry import ModelEntryClient

            entry = ModelEntryClient()
            if not entry.configured:
                raise RuntimeError(
                    "本部署没有配置 EIOS 的统一模型入口（EIOS_MODEL_CAPABILITY_URL）"
                )
            _capability = entry
        except Exception as exc:  # noqa: BLE001 — 接不上就是「这个部署没模型」，如实记下
            _capability_error = f"{type(exc).__name__}: {exc}"[:240]
            logger.warning("统一模型入口不可用：%s", _capability_error)
    return _capability


def _token(scopes: tuple[str, ...]) -> str:
    return identity.sign(
        audience=identity.MODEL_CAPABILITY_AUDIENCE,
        scopes=scopes,
        purpose=identity.PRODUCT_CONSUME_PURPOSE,
        code="MODEL_SIGNER_NOT_CONFIGURED",
    )


def _consume(scopes: tuple[str, ...], call) -> Any:
    capability = _compose()
    if capability is None:
        raise LLMNotConfiguredError(
            "这个部署还没有可用的 GEO 模型：EIOS 的统一模型入口接不上（"
            f"{_capability_error}）。它由部署的模型目录与 pbind_ 绑定账本决定，"
            "不是 GEO 能补的。"
        )
    return call(capability, _token(scopes))


def _default_model(capability: Any, token: str) -> str:
    """部署的默认模型。产品不选 provider —— 调用方没点名时，用部署已经定的那个。"""
    global _default_model_id
    if _default_model_id:
        return _default_model_id
    response = capability.catalog(auth_context=token)
    body = response.body if isinstance(response.body, dict) else {}
    if response.status != 200:
        raise LLMError(
            str(body.get("code") or "MODEL_CATALOG_UNAVAILABLE"),
            f"读不到本部署的模型目录（HTTP {response.status}）",
        )
    default = str(body.get("default_model_id") or "").strip()
    if not default:
        # 部署没指定默认模型 = 部署没说用哪个；在这里替它挑一个就是 GEO 在选 provider。
        raise LLMNotConfiguredError(
            "这个部署还没有指定默认模型（eios.model_catalog/v1 的 default_model_id 为空）"
        )
    _default_model_id = default
    return default


def _invoke_sync(messages: list[dict[str, str]], max_tokens: int) -> str:
    """同步调能力（在工作者线程里跑，别卡事件循环）。"""
    def call(capability: Any, catalog_token: str) -> str:
        model_id = _default_model(capability, catalog_token)
        response = capability.invoke(
            auth_context=_token(("model.invoke",)),
            request={
                "contract": INVOCATION_CONTRACT,
                "model_id": model_id,
                "consumer": CONSUMER,
                "modality": "text",
                "messages": messages,
                "max_output_tokens": max(1, min(int(max_tokens), MAX_OUTPUT_TOKENS)),
            },
        )
        return _read_text(response)

    return _consume(("model.catalog.read",), call)


def _read_text(response: Any) -> str:
    body = response.body if isinstance(response.body, dict) else {}
    if response.status != 200 or not body.get("ok"):
        error = body.get("error") or {}
        raise LLMError(
            str(error.get("code") or body.get("code") or f"MODEL_HTTP_{response.status}"),
            str(error.get("message") or body.get("message") or "模型能力拒绝了这次调用")[:300],
        )
    if body.get("capability") != CAPABILITY:
        raise LLMError("MODEL_BAD_RESPONSE", f"能力返回了别的能力：{body.get('capability')}")
    data = body.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        raise LLMError("MODEL_BAD_RESPONSE", "模型结果里没有 text 字段")
    if data.get("consumer") != CONSUMER:
        raise LLMError("MODEL_BAD_RESPONSE", f"结果里的 consumer 不是本服务的：{data.get('consumer')}")
    return data["text"]


async def chat(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 2000,
    response_format: dict | None = None,
) -> str:
    """调部署的 GEO 模型生成文本。

    ``response_format``：契约里没有这个字段，所以它只被翻译成一条 system 指令
    （「严格只输出 JSON」），不会被塞进请求体。
    """
    # 封存运行时（baseline）必须在**进门处**就拦下这条边，并报出自己依赖的是谁：
    # 让它走到组合/签名再失败，报出来的会是「签不出票」，而不是「这个部署不允许出网」。
    require_outbound_network("llm")
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    if response_format == _JSON_ONLY and _JSON_INSTRUCTION not in (system or ""):
        messages.append({"role": "system", "content": _JSON_INSTRUCTION})
    messages.append({"role": "user", "content": prompt})
    # 同步能力调用放线程里：一次真调用可能几十秒，占着事件循环会把整个 GEO 拖住。
    budget = _budget.get()
    try:
        text = await asyncio.wait_for(asyncio.to_thread(_invoke_sync, messages, max_tokens), remaining_budget())
        remaining_budget()
        return text
    except asyncio.TimeoutError as exc:
        if budget:
            budget.stopped.set()
        raise LLMError("CONTENT_DEADLINE_EXCEEDED", "模型结果超过截止时间，未接受为成功稿") from exc
    except asyncio.CancelledError:
        if budget:
            budget.stopped.set()
        raise
