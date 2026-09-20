"""国内 6 引擎适配（OpenAI 兼容）

P0：注册表 + 连通性探测 ping。
Key 来源（优先级）：Builder 配置中心（db.json geoEngineKeys，经 /api/geo/engines-config 拉取）→ .env 回退。
规则：所有外部调用走 adapters/，统一超时/重试/错误码（架构方案 §8）。
"""
import asyncio
import json
import time

import httpx

from app.core.config import ENGINES, engine_api_key as _env_key, BUILDER_GEO_ENGINES_URL
from app.runtime.mode import require_outbound_network

_TIMEOUT = 60.0  # 2026-08-21：15s→60s（qwen/kimi 联网搜索实际 20-60s，15s 必超时）
# Builder key 缓存策略（防 N+1 雪崩，审计 P0-3）：
# - 成功：缓存 30s（配置中心改 key 最长 30s 生效）
# - 失败：负缓存 5s（Builder 挂时最多 1 次/5s 探测，不再按引擎次数重复打）
_builder_keys_cache: dict[str, dict] | None = None
_builder_keys_ok_at: float = 0.0
_builder_keys_fail_at: float = 0.0
_builder_fetch_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _builder_fetch_lock
    if _builder_fetch_lock is None:
        _builder_fetch_lock = asyncio.Lock()
    return _builder_fetch_lock


async def _builder_engine_keys() -> dict[str, dict]:
    """从 Builder 配置中心拉 6 引擎三元组配置（带缓存 + 失败负缓存 + 并发锁）

    配置中心格式（V2）：{engine_id: {base_url?, api_key?, model?}}——每引擎可单独覆盖
    base_url / model（默认写死 ENGINES 常量，连不上时在设置里改）；api_key 为空时回退 .env。
    兼容旧格式：{engine_id: "sk-..."}（纯 key）→ 包成 {api_key: v}。
    修复点（审计 P0-3）：原实现只在成功时写缓存，失败每次都重打 Builder，
    stats/overview、meta/engines 对 6 引擎循环 await engine_api_key →
    Builder 慢/挂时 6×timeout ≈ 16-30s。现在失败 5s 内直接返回空/旧缓存，
    并发首调由 Lock 串行化（防 6 引擎同时 miss 惊群）。
    """
    global _builder_keys_cache, _builder_keys_ok_at, _builder_keys_fail_at
    if _builder_keys_cache is None:
        require_outbound_network("builder_engine_config")
    now = time.monotonic()
    if _builder_keys_cache is not None and now - _builder_keys_ok_at < 30.0:
        return _builder_keys_cache
    if now - _builder_keys_fail_at < 5.0:
        return _builder_keys_cache or {}
    async with _lock():
        # 双检：等锁期间可能已被别的协程刷新
        now = time.monotonic()
        if _builder_keys_cache is not None and now - _builder_keys_ok_at < 30.0:
            return _builder_keys_cache
        if now - _builder_keys_fail_at < 5.0:
            return _builder_keys_cache or {}
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                r = await client.get(BUILDER_GEO_ENGINES_URL)
                j = r.json()
            d = (j or {}).get("data") if (j or {}).get("ok") else None
            if isinstance(d, dict):
                norm: dict[str, dict] = {}
                for k, v in d.items():
                    if isinstance(v, dict):
                        norm[k] = {kk: str(vv).strip() for kk, vv in v.items() if vv}
                    elif v:
                        norm[k] = {"api_key": str(v)}  # 旧格式：纯 key
                _builder_keys_cache = norm
                _builder_keys_ok_at = time.monotonic()
                _builder_keys_fail_at = 0.0
                return _builder_keys_cache
            _builder_keys_fail_at = time.monotonic()  # 返回但格式不对也记失败
        except Exception:  # noqa: BLE001
            _builder_keys_fail_at = time.monotonic()
        return _builder_keys_cache or {}


def list_engines() -> list[dict]:
    return [{"id": e["id"], "name": e["name"], "base_url": e["base_url"], "model": e["model"]} for e in ENGINES]


def _engine(engine_id: str) -> dict | None:
    return next((e for e in ENGINES if e["id"] == engine_id), None)


def resolve_temperature(engine_id: str, model: str) -> float:
    """按实际模型收温度。Kimi K 系列（k2.5 / k3）只允许 1.0，写 0.6 会 400（2026-08-21 实测修正）。"""
    eng = _engine(engine_id) or {}
    default = float(eng.get("temperature", 0.2))
    m = (model or "").lower()
    if engine_id == "kimi" and (m.startswith("kimi-k") or "k2.5" in m):
        return 1.0
    return default


def resolve_web_cfg(engine_id: str, model: str, web: bool) -> dict | None:
    """是否走联网、走哪套参数。豆包 Seed 官方联网在 /responses，chat/completions 带 web_search 会 400 后被当成没联网。"""
    if not web:
        return None
    eng = _engine(engine_id) or {}
    web_cfg = eng.get("web")
    if engine_id == "doubao" and "seed" in (model or "").lower():
        return {"mode": "responses", "tools": [{"type": "web_search", "max_keyword": 3}]}
    return web_cfg


def extract_responses_text(data: dict) -> str:
    """方舟 Responses API 正文。"""
    if not isinstance(data, dict):
        raise RuntimeError("empty_content")
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    texts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in ("message", None):
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("output_text", "text"):
                t = (part.get("text") or "").strip()
                if t:
                    texts.append(t)
    if not texts:
        raise RuntimeError("empty_content")
    return "\n".join(texts)


async def engine_api_key(engine_id: str) -> str | None:
    """引擎 key：Builder 配置中心优先，.env 回退"""
    builder = await _builder_engine_keys()
    if engine_id in builder:
        return (builder[engine_id].get("api_key") or "").strip() or None
    return _env_key(engine_id)


async def engine_config(engine_id: str) -> dict:
    """引擎最终配置（合并优先级）：Builder 三元组覆盖 → ENGINES 默认 → .env key 回退。

    返回 {id, name, base_url, api_key, model, configured}——每项可单独被 Builder 覆盖，
    解决「默认 base_url/model 连不上但无法在设置里改」的问题。
    """
    engine = _engine(engine_id) or {}
    builder = await _builder_engine_keys()
    ov = builder.get(engine_id) or {}
    # base_url 白名单回退：Builder 配置的 base_url 必须与平台默认端点**完全一致**才采信，
    # 否则一律用默认。（前端保存引擎配置是整包覆盖，用户手滑/页面残留会把 base_url 存成
    # 错端点——如 kimi 丢 /v1、豆包多 /responses、文心丢 /v2、填成 operator.las 等，导致 404；
    # 只比主机名不够（/v2/models vs /v2 同主机），此处精确匹配，宁可用默认不可用错端点）
    from urllib.parse import urlparse

    _cfg_url = (ov.get("base_url") or "").strip().rstrip("/")
    _default_url = (engine.get("base_url") or "").strip().rstrip("/")
    _cfg_host = urlparse(_cfg_url).netloc.lower() if _cfg_url else ""
    _def_host = urlparse(_default_url).netloc.lower() if _default_url else ""
    base_url = _cfg_url if (_cfg_url and _cfg_host == _def_host and _cfg_url == _default_url) else _default_url
    model = (ov.get("model") or engine.get("model") or "").strip()
    key = (ov.get("api_key") or "").strip()
    if not key:
        key = _env_key(engine_id) or ""
    return {
        "id": engine_id,
        "name": engine.get("name") or engine_id,
        "base_url": base_url,
        "api_key": key,
        "model": model,
        "configured": bool(key),
    }


async def engine_status() -> list[dict]:
    out = []
    for e in ENGINES:
        cfg = await engine_config(e["id"])
        out.append({"id": e["id"], "name": e["name"], "base_url": cfg["base_url"],
                    "model": cfg["model"], "configured": cfg["configured"]})
    return out


async def ping(engine_id: str) -> dict:
    """连通性实测：发一个最小 chat 请求（max_tokens=1），用最终配置（可被 Builder 覆盖）"""
    require_outbound_network("engine_ping")
    cfg = await engine_config(engine_id)
    if not cfg["configured"]:
        return {"id": engine_id, "configured": False, "reachable": None, "error": "no_api_key"}
    # 豆包独立搜索 API（feedcoopapi）：ping = 发真实搜索请求
    if "feedcoopapi.com" in str(cfg["base_url"]):
        try:
            r = await _ask_doubao_search(cfg, "连通性测试")
            return {"id": engine_id, "configured": True, "reachable": True, "error": None}
        except Exception as exc:
            return {"id": engine_id, "configured": True, "reachable": False, "error": str(exc)[:150]}
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": resolve_temperature(engine_id, cfg["model"]),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
            resp = await client.post(url, headers={"Authorization": f"Bearer {cfg['api_key']}"}, json=payload)
        if resp.status_code == 200:
            return {"id": engine_id, "configured": True, "reachable": True, "error": None}
        return {"id": engine_id, "configured": True, "reachable": False, "error": f"http_{resp.status_code}: {resp.text[:120]}"}
    except Exception as exc:  # noqa: BLE001
        return {"id": engine_id, "configured": True, "reachable": False, "error": str(exc)[:150]}


async def ping_all() -> list[dict]:
    return [await ping(e["id"]) for e in ENGINES]


async def ask(engine_id: str, question: str, max_tokens: int = 800, web: bool = True) -> str:
    """向指定引擎提问，返回回答文本（曝光监测用），用最终配置（可被 Builder 覆盖）

    web=True 时按平台配置开启联网搜索；平台不支持（deepseek）或参数被拒 → 自动降级纯知识模式。
    """
    meta = await ask_with_meta(engine_id, question, max_tokens=max_tokens, web=web)
    return meta["content"]


async def _ask_doubao_search(cfg: dict, question: str) -> dict:
    """豆包独立搜索 API（open.feedcoopapi.com/search_api/web_search）：
    搜问题 → 结果摘要拼成"回答"（含标题/来源/摘要），供监测提及判定。
    搜到 0 条时返回如实说明（不编造）。"""
    require_outbound_network("engine_search")
    url = str(cfg["base_url"]).rstrip("/") + "/search_api/web_search"
    # base_url 可能已是完整 URL（含 /search_api/web_search），容错
    if url.endswith("/search_api/web_search/search_api/web_search"):
        url = url.replace("/search_api/web_search/search_api/web_search", "/search_api/web_search")
    body = {
        "Query": question,
        "SearchType": "web_summary",
        "Count": 3,
        "Filter": {"NeedContent": False, "NeedUrl": True},
        "NeedSummary": True,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=body)
    except Exception as exc:
        raise RuntimeError(f"doubao_search_network: {str(exc)[:120]}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"http_{resp.status_code}: {resp.text[:150]}")
    # SSE 流式：逐行 data:{json}，取第一个 Result
    results = []
    summary = ""
    for line in resp.text.splitlines():
        s = line.strip()
        if not s or s == "data: [DONE]" or s == "[DONE]":
            continue
        if s.startswith("data:"):
            s = s[5:].strip()
        try:
            d = json.loads(s)
        except Exception:
            continue
        r = d.get("Result") or {}
        if r.get("Summary") and not summary:
            summary = str(r["Summary"]).strip()
        for w in r.get("WebResults") or []:
            results.append({
                "title": w.get("Title", ""),
                "site": w.get("SiteName", ""),
                "snippet": w.get("Snippet", ""),
                "url": w.get("Url", ""),
            })
    if not results:
        return {
            "content": f"[豆包搜索] 未检索到「{question}」的相关公开内容（0 条结果，真实数据）。",
            "web_realtime": True,
        }
    parts = [f"【豆包联网搜索】问题：{question}", f"共 {len(results)} 条结果："]
    for i, r in enumerate(results[:3], 1):
        parts.append(f"{i}. {r['title']}（{r['site']}）")
        if r["snippet"]:
            parts.append(f"   {r['snippet'][:150]}")
        if r["url"]:
            parts.append(f"   来源：{r['url'][:100]}")
    if summary:
        parts.append(f"概要：{summary[:200]}")
    return {"content": "\n".join(parts), "web_realtime": True}


async def ask_with_meta(engine_id: str, question: str, max_tokens: int = 800, web: bool = True) -> dict:
    """同 ask()，但返回 {"content", "web_realtime"}；web_realtime 如实标注本次是否以联网检索模式发出"""
    require_outbound_network("engine_ask")
    cfg = await engine_config(engine_id)
    if not cfg["configured"]:
        raise ValueError(f"no_api_key: {engine_id}")
    # 豆包独立搜索 API 分支（2026-08-21）：base_url 为 feedcoopapi 时走搜索服务，
    # 结果摘要拼成"回答"供监测提及判定（真联网曝光数据，比模型自答更接近真实 AI 搜索）。
    if "feedcoopapi.com" in str(cfg["base_url"]):
        return await _ask_doubao_search(cfg, question)
    chat_url = cfg["base_url"].rstrip("/") + "/chat/completions"
    responses_url = cfg["base_url"].rstrip("/") + "/responses"
    eng = next((e for e in ENGINES if e["id"] == engine_id), None)
    web_cfg = resolve_web_cfg(engine_id, cfg["model"], web)
    temperature = resolve_temperature(engine_id, cfg["model"])

    def build_payload(with_web: bool) -> dict:
        payload = {
            "model": cfg["model"],
            "messages": [{"role": "user", "content": question}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # thinking 禁用仅推理模型需要（deepseek-v4-flash 等防 reasoning_content 顶空 content）；
        # 非推理平台注入未知参数会被 400 拒绝 → 按平台开关
        if (eng or {}).get("thinking", False):
            payload["thinking"] = {"type": "disabled"}
        if with_web and web_cfg:
            if web_cfg.get("mode") == "tools":
                payload["tools"] = web_cfg.get("tools", [])
            elif web_cfg.get("mode") == "params":
                payload.update(web_cfg.get("params", {}))
        return payload

    def build_responses_payload() -> dict:
        return {
            "model": cfg["model"],
            "stream": False,
            "tools": (web_cfg or {}).get("tools") or [{"type": "web_search", "max_keyword": 3}],
            "input": [{"role": "user", "content": [{"type": "input_text", "text": question}]}],
        }

    def extract(data: dict) -> str:
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        if not content:
            # 兜底：推理模型 content 空时取 reasoning_content；仍空则按失败处理（不落空回答）
            content = (msg.get("reasoning_content") or "").strip()
        if not content:
            raise RuntimeError("empty_content")
        return content

    def _extract_msg(msg: dict) -> str:
        content = (msg.get("content") or "").strip()
        if not content:
            content = (msg.get("reasoning_content") or "").strip()
        if not content:
            raise RuntimeError("empty_content")
        return content

    async def post(url: str, payload: dict, parser) -> str:
        timeout = 30.0 if "responses" in url else _TIMEOUT
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.post(url, headers={"Authorization": f"Bearer {cfg['api_key']}"}, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"http_{resp.status_code}: {resp.text[:150]}")
        try:
            return parser(resp.json())
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"bad_response: {str(exc)[:150]}") from exc

    web_realtime = False
    if web_cfg:
        try:
            if web_cfg.get("mode") == "responses":
                content = await post(responses_url, build_responses_payload(), extract_responses_text)
            else:
                payload1 = build_payload(with_web=True)
                # Kimi $web_search 手册流程（2026-08-21 按官方文档修正）：
                # 初始化提问 → 循环处理 tool_calls：role=tool 消息必须带 tool_call_id+name，
                # content = 原样返回 arguments 的 json 字符串（search_impl 直接回传），
                # 直到 finish_reason != "tool_calls" 才取最终 content。
                async def _post_raw(url: str, payload: dict) -> dict:
                    async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
                        resp = await client.post(url, headers={"Authorization": f"Bearer {cfg['api_key']}"}, json=payload)
                    if resp.status_code != 200:
                        raise RuntimeError(f"http_{resp.status_code}: {resp.text[:150]}")
                    return resp.json()

                kimi_msg = {"role": "user", "content": question}
                messages = [kimi_msg]
                for _round in range(3):  # 有界循环防死转
                    payload_round = {
                        "model": cfg["model"],
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        # 每次请求都必须完整带 tools 声明（手册强调）
                        "tools": web_cfg.get("tools", []),
                    }
                    if (eng or {}).get("thinking", False):
                        payload_round["thinking"] = {"type": "disabled"}
                    data_round = await _post_raw(chat_url, payload_round)
                    choice = data_round["choices"][0]
                    finish = choice.get("finish_reason")
                    msg_r = choice["message"]
                    tool_calls = msg_r.get("tool_calls") or []
                    if finish != "tool_calls" or not tool_calls:
                        content = _extract_msg(msg_r)
                        break
                    messages.append(msg_r)  # assistant 消息进上下文
                    for tc in tool_calls:
                        try:
                            args = json.loads(tc["function"]["arguments"])
                        except Exception:
                            args = {}
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "name": tc["function"]["name"],
                            "content": json.dumps(args, ensure_ascii=False),  # 原样回传 arguments
                        })
                else:
                    raise RuntimeError("tool_calls 循环未收敛")
            web_realtime = True
            return {"content": content, "web_realtime": True}
        except RuntimeError as exc:
            # 400/422/404/429 多为参数不被该平台接受或限流 → 降级纯知识模式重试（其余错误直接抛）
            if not str(exc).startswith(("http_400", "http_422", "http_404", "http_429")):
                raise
    content = await post(chat_url, build_payload(with_web=False), extract)
    return {"content": content, "web_realtime": web_realtime}
