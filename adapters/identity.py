"""GEO 出站身份的唯一点：本部署的钥 + 部署声明 → EIOS AuthContext 票。

GEO 有两个出站方向，票都从这里签，不各签各的：

* 读企业知识库 → ``audience=eios-knowledge``（见 ``adapters/eios``）
* 调部署的 Model Capability → ``audience=eios-model-capability``（见 ``adapters/llm.py``）

两条都只签「本服务是 ``eios-geo``」这一件事。**scope 由调用方给出的写死常量决定，
不接受 HTTP 请求里的值** —— 那是调用方给自己加权限的入口。

缺任何一项部署声明（部署/企业/subject/issuer/kid/私钥）→ 明确抛错，绝不降级成无票调用：
无票调用在权威侧只会拿到 401，然后被上层显示成「对方服务坏了」，把配置缺失伪装成故障。
"""
from __future__ import annotations

import os
import time
from typing import Sequence

from app.runtime.mode import require_outbound_network

AUTH_CONTEXT_CONTRACT = "eios.auth_context/v1"
KNOWLEDGE_AUDIENCE = "eios-knowledge"
MODEL_CAPABILITY_AUDIENCE = "eios-model-capability"
#: EIOS 只接受 300s 以内的 AuthContext TTL。
MAX_TTL_SECONDS = 300
#: 模型调用的 purpose。契约 ``eios.auth_context/v1`` 的 purpose 是枚举，没有 geo 专用值；
#: ``product.knowledge_consume`` 是「产品消费企业能力」那一类，顾问调模型用的也是它。
PRODUCT_CONSUME_PURPOSE = "product.knowledge_consume"


class SigningUnavailable(RuntimeError):
    """签不出票（部署声明缺失 / 钥不可读 / 基座库不在）。"""

    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def service_id() -> str:
    return env("EIOS_GEO_SERVICE_ID", "eios-geo")


def subject() -> str:
    return env("EIOS_GEO_SUBJECT", "system:eios-geo")


def deployment_claims() -> dict[str, str]:
    """本部署的签名声明。缺哪一项，票就签不出来 —— 不猜默认值。"""
    return {
        "deployment_id": env("EIOS_DEPLOYMENT_ID", "dep_beichen_dev"),
        "enterprise_id": env("EIOS_ENTERPRISE_ID", "enterprise_beichen"),
        "subject": subject(),
        "issuer": env("EIOS_AUTH_ISSUER", ""),
        "key_id": env("EIOS_AUTH_KID", ""),
        "private_key_path": env("EIOS_AUTH_PRIVATE_KEY_PATH", ""),
    }


def sign(
    *,
    audience: str,
    scopes: Sequence[str],
    purpose: str,
    code: str,
    ttl: int = MAX_TTL_SECONDS,
) -> str:
    """签一张票。``code`` 是调用方希望上层看到的错误码（各自的名字各自负责）。"""
    claims = deployment_claims()
    missing = [k for k, v in claims.items() if not v]
    if missing:
        raise SigningUnavailable(
            code, f"出站票的签发声明缺失：{', '.join(sorted(missing))}", 503
        )
    require_outbound_network(f"auth_sign:{audience}")
    try:
        from eios_auth import sign_auth_context
    except ImportError as exc:  # 基座库不在（PYTHONPATH 没指到 foundation / 缺 cryptography）
        raise SigningUnavailable(code, f"eios_auth 不可用：{exc}", 503) from exc

    now = int(time.time())
    ticket = {
        "contract": AUTH_CONTEXT_CONTRACT,
        "deployment_id": claims["deployment_id"],
        "enterprise_id": claims["enterprise_id"],
        "subject": claims["subject"],
        "service_id": service_id(),
        "purpose": purpose,
        "scopes": list(scopes),
        "issuer": claims["issuer"],
        "audience": audience,
        "iat": now,
        "exp": now + max(1, min(int(ttl), MAX_TTL_SECONDS)),
        "kid": claims["key_id"],
        "jti": f"jti_{time.time_ns()}",
    }
    try:
        return sign_auth_context(
            ticket, private_key=claims["private_key_path"], key_id=claims["key_id"]
        )
    except (OSError, ValueError) as exc:  # 钥文件读不到 / 不是一把能用的钥
        raise SigningUnavailable(code, f"出站密钥不可用：{exc}", 503) from exc


__all__ = [
    "AUTH_CONTEXT_CONTRACT",
    "KNOWLEDGE_AUDIENCE",
    "MAX_TTL_SECONDS",
    "MODEL_CAPABILITY_AUDIENCE",
    "PRODUCT_CONSUME_PURPOSE",
    "SigningUnavailable",
    "deployment_claims",
    "env",
    "service_id",
    "sign",
    "subject",
]
