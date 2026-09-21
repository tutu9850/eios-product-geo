"""GEO 服务配置 —— 从**部署环境**读取，不读 GEO 自己的 .env。

Owner 2026-09-21：「GEO 不保留 Builder / .env / 自己的模型 Key。」
原来这里有 ``load_dotenv(apps/api/.env)``：那是「GEO 本地还有一份配置真相」的入口，
而它最容易装的东西恰好是模型 key（``DEEPSEEK_API_KEY`` 之流）。已删除 —— 删掉之后
本进程只能看到部署给它的环境，与「所有产品通过 EIOS 的统一模型入口调用模型」一致。
"""
import os
from pathlib import Path

# 引擎（有哪些、端点在哪、凭据是什么、温度多少、要不要关思考、能不能联网）**不在这里**：
# Owner 2026-09-21「GEO 不保留 Builder / .env / 自己的模型 Key」「GEO 不再写死 6 个」。
# 那些是**部署**的事实：模型目录 + pbind_ 绑定账本 + 适配器，产品只按 HTTP 调统一模型入口
# （见 adapters/engines/ 与 adapters/llm.py）。原来这里的 ENGINES 常量、engine_api_key()、
# engine_status() 与 BUILDER_GEO_ENGINES_URL 已删除 —— 它们是同一件事的第三份答案。

KERNEL_API_URL = os.environ.get("KERNEL_API_URL", "http://localhost:8000")
# Kernel 企业知识租户（≠ GEO 部门柜）。入驻读实体走这里，避免把部门名当成 Kernel tenant 抽空。
KERNEL_TENANT_ID = os.environ.get("KERNEL_TENANT_ID", "tenant_corp_01")

# 内容生成模型（`adapters/llm.py`）**不在这里配置**：Owner 2026-09-21
#「GEO 不保留 Builder / .env / 自己的模型 Key」「Model Capability 必须成为所有产品统一
# 调用模型的唯一正规入口」。原来那三行（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）与
# BUILDER_GEO_MODEL_URL 已删除 —— 它们既是死代码，也是同一件事的第二份答案。

# 数据库（2026-08-07：JSON 文件库 → SQLite）
_GEO_ROOT = Path(__file__).resolve().parents[3]  # eios-geo/
GEO_DB_PATH = os.environ.get("GEO_DB_PATH", str(_GEO_ROOT / "geo.db"))
GEO_MEDIA_DIR = os.environ.get("GEO_MEDIA_DIR", str(_GEO_ROOT / "storage" / "media"))
