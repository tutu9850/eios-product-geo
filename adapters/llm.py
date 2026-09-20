"""LLM 适配（OpenAI 兼容）— 内容生成用

配置来源（优先级）：
1. Builder 设置里的 GEO 专用模型（db.json geoModel，经 /api/geo/model 拉取）
2. 回退 apps/api/.env 的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
规则：所有外部调用走 adapters/，统一超时/错误码（架构方案 §8）。
"""
import httpx

from app.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, BUILDER_GEO_MODEL_URL
from app.runtime.mode import require_outbound_network

_TIMEOUT = 60.0


class LLMNotConfiguredError(Exception):
    pass


class LLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def _resolve_llm_config() -> tuple[str, str, str]:
    """优先从 Builder 设置拉 GEO 模型配置，失败回退 .env"""
    require_outbound_network("builder_model_config")
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            r = await client.get(BUILDER_GEO_MODEL_URL)
            j = r.json()
        d = (j or {}).get("data") if (j or {}).get("ok") else None
        if d and d.get("base_url") and d.get("api_key") and d.get("model"):
            return d["base_url"], d["api_key"], d["model"]
    except Exception:  # noqa: BLE001
        pass
    return LLM_BASE_URL, LLM_API_KEY, LLM_MODEL


async def chat(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 2000,
    response_format: dict | None = None,
) -> str:
    """调 LLM 生成文本（OpenAI 兼容 chat/completions）

    response_format：如 {"type": "json_object"} —— 强制结构化输出
    （deepseek-v4-flash 为推理模型，长 prompt 偶发 content 为空；json 模式可规避）
    """
    require_outbound_network("llm")
    base_url, api_key, model = await _resolve_llm_config()
    if not api_key:
        raise LLMNotConfiguredError("GEO 模型未配置：请到 设置 → 企业级自定义模型 → GEO 专用模型 填写")
    url = base_url.rstrip("/") + "/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if response_format:
        payload["response_format"] = response_format
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
            resp = await client.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
    except Exception as exc:  # noqa: BLE001
        raise LLMError("llm_network_error", str(exc)[:150])
    if resp.status_code != 200:
        raise LLMError(f"llm_http_{resp.status_code}", resp.text[:200])
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001
        raise LLMError("llm_bad_response", str(data)[:200])
