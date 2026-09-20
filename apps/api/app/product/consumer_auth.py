"""消费方（顾问）读 GEO 的入站身份门 —— 验签 EIOS AuthContext，fail-closed。

契约（Owner 2026-09-20 拍板落地）：
- GEO 留一个**只读**的交接面给别的产品查 GEO 自己的库；
- 来的票必须是本部署信任的钥签的 ``eios.auth_context/v1``；
- ``audience`` 必须是 GEO（默认 ``eios-geo``）；
- 票上必须有本面要求的 scope（默认 ``geo.knowledge.read``），否则 403。

下面这些一律 fail-closed，不允许降级：
- 没有票 → 401；票无效/过期/不是签给 GEO 的 → 401；
- 票上没有要求的 scope → 403；
- 本服务没有配信任钥 → 503（不是放行，也不是假装通过）。

验签与 scope 之后还有**第四道**：本部署的**正式 PDP**（Owner 2026-09-21「正式 PDP 声明
``geo.knowledge.read``」）。票上的 audience + scope 只说「这张票是谁签给谁的、带没带这个权力」，
它**不是**「本部署允许这个读者读 GEO 的库」这句话 —— 那句话只能由部署的策略声明回答，所以这里
把同一次读取交给 ``app.state.consumer_pdp`` 判一次（payload 形状与 Foundation 各读门逐字段对齐）：

- 本进程没有 PDP → 503 ``DEPENDENCY_NOT_ACTIVE``（不是放行）；
- PDP 拒绝 → 403 ``GEO_CONSUMER_PDP_DENIED``，并**照实转述** PDP 自己的理由；
- PDP 返回资源级约束 → 503（这个面按部署级读取判定，裁剪不了资源，于是拒绝而不是忽略）；
- 允许 → 把那次决策的 ``decision_id`` / ``policy_version`` 留在 principal 里，由响应如实报出。

严格与否由部署声明决定：``EIOS_PDP_MODE=deployment_reads`` 时是**强制**（``enforced``），
dev 的 ``development_allow`` 是一个允许一切的替身，响应里会如实报成 ``development_allow``，
**不许**被读成「资源约束已被强制」。

这与 ``app.product.http_auth`` 是同一套信任模型（都只认服务端验过的 AuthContext），
但**不是**同一道门：那道门是宿主（product-api）打 GEO 产品面的身份，只有
``GEO_AUTH_MODE=auth_context`` 才启用。这一道是产品之间读数据的身份，自己的开关，
不改变 GEO 产品面现在的身份模式。
"""
from __future__ import annotations

import inspect
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Protocol

from fastapi import Request

AUTH_CONTEXT_HEADER = "EIOS-Auth-Context"
DEFAULT_AUDIENCE = "eios-geo"
DEFAULT_SCOPE = "geo.knowledge.read"
#: 交给 PDP 的「动作」。动词必须落在 Foundation 的 ``BUSINESS_READ_ACTIONS`` 里
#: （``BusinessReadPolicyDecisionPoint`` 只看最后一段），所以 ``….read`` 才是合法的读取动作。
DEFAULT_PDP_ACTION = "geo.knowledge.read"
#: 交给 PDP 的「资源类型」。**不能**取 ``capability_*`` 三个保留类型，否则
#: ``deployment_reads`` 会把它当能力读门去判，业务 scope 永远判不出来。
DEFAULT_PDP_RESOURCE = "geo_consumer_store"


@dataclass(frozen=True, slots=True)
class ConsumerAuthError(Exception):
    code: str
    message: str
    status_code: int


@dataclass(frozen=True, slots=True)
class ConsumerPrincipal:
    """一个已被验证的、来读 GEO 的消费方身份。"""

    deployment_id: str
    enterprise_id: str
    subject: str
    service_id: str
    scopes: tuple[str, ...] = field(default=())
    #: 票上声明的用途。策略门会把它一起交给 PDP（与 Foundation 各读门同一份 payload 形状），
    #: 本服务不解释它 —— 解释「这个 purpose 允不允许读」是策略的事。
    purpose: str = ""
    #: 这次读取的**策略事实**：PDP 自己给的 ``decision_id`` / ``policy_version`` / ``reason``。
    #: 允许时也在 —— 一个「已授权」的说法必须能对回某一次真实决策，不能由本服务另编一个。
    policy_decision: dict[str, Any] = field(default_factory=dict)
    #: 本进程 PDP 的强制模式（``enforced`` / ``development_allow`` / ``unavailable``）。
    #: 它不是决策的一部分，是「这台机器上的 PDP 到底算不算数」这个独立事实，所以分开报。
    policy_enforcement: str = ""


class _Verifier(Protocol):
    def __call__(self, token: str, *, audience: str) -> Any: ...


def consumer_audience() -> str:
    return os.environ.get("EIOS_GEO_CONSUMER_AUDIENCE", DEFAULT_AUDIENCE).strip() or DEFAULT_AUDIENCE


def consumer_scope() -> str:
    return os.environ.get("EIOS_GEO_CONSUMER_SCOPE", DEFAULT_SCOPE).strip() or DEFAULT_SCOPE


def consumer_pdp_action() -> str:
    """交给 PDP 的动作。默认就是那条被声明的读取动作 ``geo.knowledge.read``。"""
    return (
        os.environ.get("EIOS_GEO_CONSUMER_PDP_ACTION", DEFAULT_PDP_ACTION).strip()
        or DEFAULT_PDP_ACTION
    )


def consumer_pdp_resource() -> str:
    """交给 PDP 的资源类型：GEO 自己这个只读交接面。"""
    return (
        os.environ.get("EIOS_GEO_CONSUMER_PDP_RESOURCE", DEFAULT_PDP_RESOURCE).strip()
        or DEFAULT_PDP_RESOURCE
    )


def consumer_pdp_resource_id() -> str:
    """资源的 id：GEO 自己这个服务。读的是本部署 GEO 的库，不是某一条记录。"""
    return os.environ.get("EIOS_GEO_SERVICE_ID", "eios-geo").strip() or "eios-geo"


def _trust_keys() -> dict[str, str]:
    """信任钥表：``kid=path`` 逗号分隔；单钥部署可以直接给 ``EIOS_AUTH_PUBLIC_KEY_PATH``。"""
    explicit = os.environ.get("EIOS_GEO_CONSUMER_TRUST_KEYS", "").strip()
    keys: dict[str, str] = {}
    if explicit:
        for item in explicit.split(","):
            kid, _, path = item.partition("=")
            if kid.strip() and path.strip():
                keys[kid.strip()] = path.strip()
        return keys
    single = os.environ.get("EIOS_AUTH_PUBLIC_KEY_PATH", "").strip()
    kid = os.environ.get("EIOS_AUTH_KID", "").strip()
    if single and kid:
        keys[kid] = single
    return keys


def _default_verifier(token: str, *, audience: str) -> Any:
    """用基座 ``eios_auth`` 的验签器验一张票；缺配置/缺库都抛 ConsumerAuthError。"""
    keys = _trust_keys()
    if not keys:
        raise ConsumerAuthError(
            "GEO_CONSUMER_AUTH_NOT_CONFIGURED",
            "GEO 未配置消费方信任钥（EIOS_GEO_CONSUMER_TRUST_KEYS 或 EIOS_AUTH_PUBLIC_KEY_PATH）",
            503,
        )
    issuer = os.environ.get("EIOS_AUTH_ISSUER", "").strip()
    if not issuer:
        raise ConsumerAuthError("GEO_CONSUMER_AUTH_NOT_CONFIGURED", "GEO 未配置 EIOS_AUTH_ISSUER", 503)
    missing = [kid for kid, path in keys.items() if not Path(path).is_file()]
    if missing:
        raise ConsumerAuthError(
            "GEO_CONSUMER_AUTH_NOT_CONFIGURED", f"信任钥文件不存在：{', '.join(sorted(missing))}", 503
        )
    try:
        from eios_auth import AuthContextError, TrustStore, verify_auth_context
    except ImportError as exc:  # 基座库不在（PYTHONPATH / cryptography 缺失）
        raise ConsumerAuthError(
            "GEO_CONSUMER_AUTH_NOT_CONFIGURED", f"eios_auth 不可用：{exc}", 503
        ) from exc
    store = TrustStore.from_pem_files(keys)
    try:
        return verify_auth_context(
            token, trust_store=store, expected_issuer=issuer, expected_audience=audience
        )
    except AuthContextError as exc:
        raise ConsumerAuthError(exc.code or "AUTH_CONTEXT_INVALID", exc.message, exc.http_status or 401) from exc


def _carried_token(request: Request) -> str:
    token = request.headers.get(AUTH_CONTEXT_HEADER, "").strip()
    if token:
        return token
    authorization = request.headers.get("Authorization", "")
    scheme, _, bearer = authorization.partition(" ")
    return bearer.strip() if scheme.lower() == "bearer" else ""


async def require_consumer(request: Request) -> ConsumerPrincipal:
    """FastAPI 依赖：只有验过签、且有本面 scope 的消费方才能读 GEO。"""
    audience = consumer_audience()
    token = _carried_token(request)
    if not token:
        raise ConsumerAuthError("AUTH_CONTEXT_REQUIRED", "需要 EIOS AuthContext（EIOS-Auth-Context 头）", 401)
    verifier: Callable[..., Any] | None = getattr(request.app.state, "consumer_token_verifier", None)
    verify = verifier or _default_verifier
    try:
        context = verify(token, audience=audience)
        if inspect.isawaitable(context):
            context = await context
    except ConsumerAuthError:
        raise
    except (ConnectionError, TimeoutError, OSError) as exc:
        raise ConsumerAuthError("AUTH_CONTEXT_UNAVAILABLE", "验签依赖暂时不可用", 503) from exc
    except (ValueError, PermissionError) as exc:
        raise ConsumerAuthError("AUTH_CONTEXT_INVALID", f"AuthContext 无效：{exc}", 401) from exc

    def _claim(name: str) -> str:
        value = getattr(context, name, None)
        return str(value or "").strip()

    scopes = tuple(str(s) for s in (getattr(context, "scopes", ()) or ()))
    required = consumer_scope()
    if required not in scopes:
        raise ConsumerAuthError(
            "GEO_CONSUMER_SCOPE_REQUIRED", f"这个消费方面需要 scope {required}", 403
        )
    principal = ConsumerPrincipal(
        deployment_id=_claim("deployment_id"),
        enterprise_id=_claim("enterprise_id"),
        subject=_claim("subject"),
        service_id=_claim("service_id"),
        scopes=scopes,
        purpose=_claim("purpose"),
    )
    if not (principal.deployment_id and principal.enterprise_id and principal.service_id):
        raise ConsumerAuthError("AUTH_CONTEXT_INVALID", "AuthContext 缺少部署/企业/服务声明", 401)
    decision, enforcement = _decide(request, principal)
    return replace(
        principal,
        policy_decision={
            "decision_id": decision.decision_id,
            "policy_version": decision.policy_version,
            "allow": bool(decision.allow),
            "reason": getattr(decision, "reason", None) or "",
        },
        policy_enforcement=enforcement,
    )


def _decide(request: Request, principal: ConsumerPrincipal) -> tuple[Any, str]:
    """把这次读取交给本部署的 PDP；判不了就拒绝，绝不放行。"""
    pdp = getattr(request.app.state, "consumer_pdp", None)
    if pdp is None:
        # 一个没有 PDP 的进程证明不了「谁可以读我的库」。放行会把「没人判过」说成「允许」。
        raise ConsumerAuthError(
            "DEPENDENCY_NOT_ACTIVE",
            "本进程没有配置 Policy Decision Point，消费面无法判定这次读取",
            503,
        )
    try:
        from eios_policy import PolicyUnavailable
    except ImportError as exc:  # 基座策略包不在（PYTHONPATH 缺失）
        raise ConsumerAuthError(
            "DEPENDENCY_NOT_ACTIVE", f"eios_policy 不可用：{exc}", 503
        ) from exc
    try:
        decision = pdp.decide(
            {
                "subject": principal.subject,
                "service_id": principal.service_id,
                "purpose": principal.purpose,
                "scopes": list(principal.scopes),
                "deployment_id": principal.deployment_id,
                "enterprise_id": principal.enterprise_id,
                "action": consumer_pdp_action(),
                "resource": {"type": consumer_pdp_resource(), "id": consumer_pdp_resource_id()},
            }
        )
    except PolicyUnavailable as exc:
        raise ConsumerAuthError("DEPENDENCY_NOT_ACTIVE", "Policy Decision Point 不可用", 503) from exc
    constraints = getattr(decision, "constraints", None)
    if not isinstance(constraints, dict):
        raise ConsumerAuthError(
            "DEPENDENCY_NOT_ACTIVE", "Policy Decision Point 返回了畸形的约束", 503
        )
    if constraints:
        # 与 Foundation 各读门同一条判断：这个面是按部署级读取判定的，裁剪不了资源。
        # 忽略一个 resource_ids 白名单会让一次不受限的读取看起来像被裁过。
        raise ConsumerAuthError(
            "DEPENDENCY_NOT_ACTIVE",
            "Policy Decision Point 返回了资源级约束，而本面按部署级读取判定，不能忽略",
            503,
        )
    if not decision.allow:
        # PDP 自己的理由照实转述：一句笼统的 denied 会把「策略里没有你这个读者」和
        # 「这个动作根本不是读取」说成同一句话，现场就没法定位。
        reason = f"：{decision.reason}" if getattr(decision, "reason", None) else ""
        raise ConsumerAuthError("GEO_CONSUMER_PDP_DENIED", f"Policy Decision Point 拒绝了这次读取{reason}", 403)
    enforcement = getattr(request.app.state, "consumer_policy_enforcement", "")
    if not enforcement:
        try:
            from eios_policy import policy_enforcement_mode

            enforcement = policy_enforcement_mode(pdp)
        except ImportError:  # pragma: no cover - 与上面同一次 import 失败
            enforcement = ""
    return decision, enforcement


__all__ = [
    "ConsumerAuthError",
    "ConsumerPrincipal",
    "consumer_audience",
    "consumer_pdp_action",
    "consumer_pdp_resource",
    "consumer_pdp_resource_id",
    "consumer_scope",
    "require_consumer",
]
