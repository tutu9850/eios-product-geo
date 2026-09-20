"""GEO 服务配置 —— 从**部署环境**读取，不读 GEO 自己的 .env。

Owner 2026-09-21：「GEO 不保留 Builder / .env / 自己的模型 Key。」
原来这里有 ``load_dotenv(apps/api/.env)``：那是「GEO 本地还有一份配置真相」的入口，
而它最容易装的东西恰好是模型 key（``DEEPSEEK_API_KEY`` 之流）。已删除 —— 删掉之后
本进程只能看到部署给它的环境，与「所有产品通过 EIOS 的统一模型入口调用模型」一致。
"""
import os
from pathlib import Path

# 国内 6 引擎（OpenAI 兼容；model 为各引擎默认对话模型，P0 实测用）
# web: 联网搜索参数（None = 该平台 API 不支持联网，如实标注不冒充）
#   mode "tools"  → 注入 payload["tools"]（function calling / 平台工具）
#   mode "params" → 合并进 payload 顶层（平台专用参数）
# 国内 6 引擎（OpenAI 兼容；model 为各引擎默认对话模型，P0 实测用）
# web: 联网搜索参数（None = 该平台 API 不支持联网，如实标注不冒充）
#   mode "tools"  → 注入 payload["tools"]（function calling / 平台工具）
#   mode "params" → 合并进 payload 顶层（平台专用参数）
# temperature: 各平台/模型允许的采样温度（写死 0.2 会被 kimi-k2.5 等拒绝——审计修复 2026-08-19）
# thinking: 是否注入 "thinking":{"type":"disabled"}（仅推理模型需要禁用思考防 content 被顶空；
#           非推理平台/未知平台不注入，避免 400）
ENGINES = [
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "env_key": "DEEPSEEK_API_KEY", "web": None, "temperature": 0.2, "thinking": True},
    {"id": "kimi", "name": "Kimi", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k", "env_key": "KIMI_API_KEY", "web": {"mode": "tools", "tools": [{"type": "builtin_function", "function": {"name": "$web_search"}}]}, "temperature": 0.6, "thinking": False},
    {"id": "doubao", "name": "豆包", "base_url": "https://open.feedcoopapi.com", "model": "doubao-websearch", "env_key": "DOUBAO_API_KEY", "web": {"mode": "tools", "tools": [{"type": "web_search"}]}, "temperature": 0.3, "thinking": False},
    {"id": "wenxin", "name": "文心一言", "base_url": "https://qianfan.baidubce.com/v2", "model": "ernie-4.0-8k", "env_key": "WENXIN_API_KEY", "web": {"mode": "params", "params": {"web_search": {"enable": True}}}, "temperature": 0.2, "thinking": False},
    {"id": "qwen", "name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "env_key": "QWEN_API_KEY", "web": {"mode": "params", "params": {"enable_search": True, "search_options": {"enable_source": True}}}, "temperature": 0.2, "thinking": False},
    {"id": "zhipu", "name": "智谱", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash", "env_key": "ZHIPU_API_KEY", "web": {"mode": "tools", "tools": [{"type": "web_search", "web_search": {"enable": True, "search_result": True}}]}, "temperature": 0.2, "thinking": False},
]


def engine_status() -> list[dict]:
    out = []
    for e in ENGINES:
        key = os.environ.get(e["env_key"], "")
        out.append({"id": e["id"], "name": e["name"], "base_url": e["base_url"], "model": e["model"], "configured": bool(key)})
    return out


def engine_api_key(engine_id: str) -> str | None:
    for e in ENGINES:
        if e["id"] == engine_id:
            return os.environ.get(e["env_key"], "") or None
    return None


KERNEL_API_URL = os.environ.get("KERNEL_API_URL", "http://localhost:8000")
# Kernel 企业知识租户（≠ GEO 部门柜）。入驻读实体走这里，避免把部门名当成 Kernel tenant 抽空。
KERNEL_TENANT_ID = os.environ.get("KERNEL_TENANT_ID", "tenant_corp_01")

# 内容生成模型（`adapters/llm.py`）**不在这里配置**：Owner 2026-09-21
#「GEO 不保留 Builder / .env / 自己的模型 Key」「Model Capability 必须成为所有产品统一
# 调用模型的唯一正规入口」。原来那三行（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）与
# BUILDER_GEO_MODEL_URL 已删除 —— 它们既是死代码，也是同一件事的第二份答案。

# GEO 引擎 Key 来源：优先从 Builder 配置中心（db.json geoEngineKeys）拉取，拿不到才回退 .env
BUILDER_GEO_ENGINES_URL = os.environ.get("BUILDER_GEO_ENGINES_URL", "http://localhost:3001/api/geo/engines-config")

# 数据库（2026-08-07：JSON 文件库 → SQLite）
_GEO_ROOT = Path(__file__).resolve().parents[3]  # eios-geo/
GEO_DB_PATH = os.environ.get("GEO_DB_PATH", str(_GEO_ROOT / "geo.db"))
GEO_MEDIA_DIR = os.environ.get("GEO_MEDIA_DIR", str(_GEO_ROOT / "storage" / "media"))
