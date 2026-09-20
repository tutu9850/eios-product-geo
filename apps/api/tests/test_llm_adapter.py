"""GEO's model edge: one deployment model, named honestly, never a second truth.

2026-09-20 Owner 拍板「连接一下」：GEO 不再自带一条模型连接（Builder :3001 + 自己的
``.env``），改走**本部署自己的 Model Capability** —— 用哪个模型、走哪个 provider、凭据
在哪，都是部署事实（profile + ``pbind_`` 账本），产品不选 provider、不持凭据。

这个文件钉住四件事：
1. 出站票的部署声明缺一项就签不出来（``SigningUnavailable``，503），不降级成无票调用；
2. TTL 不超过契约上限；
3. 组合不出能力时如实报 ``LLMNotConfiguredError``（带原因），不回落成裸 HTTP；
4. 请求体就是契约 ``eios.model_invocation/v1``，``model_id`` 取部署的默认模型，
   ``response_format`` 只被翻译成 system 指令，不伪造契约里没有的字段。
"""
from __future__ import annotations

import asyncio
import pathlib

import pytest

import adapters.identity as identity
import adapters.llm as llm


class _Response:
    def __init__(self, status: int, body: dict) -> None:
        self.status = status
        self.body = body


class _FakeCapability:
    def __init__(self, *, default_model_id: str = "deepseek") -> None:
        self.default_model_id = default_model_id
        self.requests: list[dict] = []

    def catalog(self, *, auth_context: str) -> _Response:
        return _Response(200, {"default_model_id": self.default_model_id, "items": []})

    def invoke(self, *, request: dict, auth_context: str) -> _Response:
        self.requests.append(request)
        return _Response(200, {
            "ok": True,
            "capability": "model.text_generation",
            "data": {
                "text": '{"ok": true}',
                "consumer": request["consumer"],
                "model_id": request["model_id"],
            },
        })


@pytest.fixture()
def llm_state():
    """Save and restore the module's process-wide composition cache."""
    saved = (llm._capability, llm._capability_error, llm._default_model_id)
    yield
    llm._capability, llm._capability_error, llm._default_model_id = saved


@pytest.fixture()
def signing(monkeypatch):
    """A ticket, without depending on a key file for the contract tests."""
    monkeypatch.setattr(identity, "sign", lambda **kwargs: "ticket")
    monkeypatch.setattr(llm.identity, "sign", lambda **kwargs: "ticket")


def test_missing_deployment_claims_produce_no_ticket(monkeypatch):
    """A gap in the deployment is reported as a gap -- never as an unsigned call.

    An unsigned call would come back 401 from the authority and be shown as "the other
    service is broken", which is exactly how a configuration gap gets hidden.
    """
    monkeypatch.delenv("EIOS_AUTH_KID", raising=False)
    monkeypatch.delenv("EIOS_AUTH_PRIVATE_KEY_PATH", raising=False)
    with pytest.raises(identity.SigningUnavailable) as caught:
        identity.sign(audience="eios-model-capability", scopes=("model.invoke",),
                      purpose=identity.PRODUCT_CONSUME_PURPOSE, code="MODEL_SIGNER_NOT_CONFIGURED")
    assert caught.value.code == "MODEL_SIGNER_NOT_CONFIGURED"
    assert caught.value.status == 503
    assert "key_id" in caught.value.message and "private_key_path" in caught.value.message


def test_ticket_ttl_never_exceeds_the_contract_limit(monkeypatch):
    seen = {}

    def capture(ticket, *, private_key, key_id):
        seen.update(ticket)
        return "ticket"

    monkeypatch.setenv("EIOS_AUTH_KID", "dev-2026-08")
    monkeypatch.setenv("EIOS_AUTH_PRIVATE_KEY_PATH", "/dev/never-read.pem")
    monkeypatch.setenv("EIOS_AUTH_ISSUER", "eios-dev-issuer")
    monkeypatch.setattr("eios_auth.sign_auth_context", capture)
    identity.sign(audience="eios-model-capability", scopes=("model.invoke",),
                  purpose=identity.PRODUCT_CONSUME_PURPOSE, ttl=9999, code="X")
    assert seen["exp"] - seen["iat"] == identity.MAX_TTL_SECONDS
    assert seen["service_id"] == "eios-geo"
    assert seen["audience"] == "eios-model-capability"


def test_a_deployment_without_the_unified_entry_answers_with_the_reason(monkeypatch, llm_state):
    """没有统一入口 = 这个部署没说模型在哪。报那句话，不假装 GEO 自己有一条连接。"""
    import adapters.model_entry as model_entry

    monkeypatch.setattr(model_entry, "base_url", lambda: "")
    llm._capability, llm._capability_error, llm._default_model_id = None, None, ""
    with pytest.raises(llm.LLMNotConfiguredError) as caught:
        asyncio.run(llm.chat("你好"))
    assert "EIOS_MODEL_CAPABILITY_URL" in str(caught.value)


def test_the_request_is_the_contract_and_uses_the_deployments_default_model(llm_state, signing):
    fake = _FakeCapability(default_model_id="deepseek")
    llm._capability, llm._capability_error, llm._default_model_id = fake, None, ""

    text = asyncio.run(llm.chat("只输出 JSON", system="你是 GEO。", response_format={"type": "json_object"}, max_tokens=99999))

    assert text == '{"ok": true}'
    request = fake.requests[0]
    assert request["contract"] == llm.INVOCATION_CONTRACT
    assert request["consumer"] == llm.CONSUMER
    assert request["modality"] == "text"
    # The deployment decides which model answers; GEO does not name a provider.
    assert request["model_id"] == "deepseek"
    # The contract's cap is respected, and nothing outside the contract is invented.
    assert request["max_output_tokens"] == llm.MAX_OUTPUT_TOKENS
    assert "response_format" not in request
    assert [m["role"] for m in request["messages"]] == ["system", "system", "user"]
    assert "JSON" in request["messages"][1]["content"]


def test_a_refused_invocation_reports_the_authoritys_own_code(llm_state, signing):
    class Refusing(_FakeCapability):
        def invoke(self, *, request, auth_context):
            return _Response(503, {"ok": False, "error": {"code": "PROVIDER_NOT_ACTIVE", "message": "模型提供方未启用"}})

    llm._capability, llm._capability_error, llm._default_model_id = Refusing(), None, ""
    with pytest.raises(llm.LLMError) as caught:
        asyncio.run(llm.chat("你好"))
    assert caught.value.code == "PROVIDER_NOT_ACTIVE"


def test_a_catalog_without_a_default_model_is_a_deployment_gap(llm_state, signing):
    fake = _FakeCapability(default_model_id="")
    llm._capability, llm._capability_error, llm._default_model_id = fake, None, ""
    with pytest.raises(llm.LLMNotConfiguredError):
        asyncio.run(llm.chat("你好"))
    assert fake.requests == []


def test_the_adapter_holds_no_second_model_truth():
    """No provider credential, no base URL, no vendor HTTP client in this adapter.

    The whole point of the 2026-09-20 change: "which model, whose key" is a deployment
    fact. A ``.env`` or a URL here would be the second answer to that question.
    """
    import ast

    tree = ast.parse(pathlib.Path(llm.__file__).read_text(encoding="utf-8"))
    # Docstrings are allowed to *name* the old settings -- explaining what was removed is
    # the point of them. Code is not.
    docstrings = {
        doc
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and (doc := ast.get_docstring(node, clean=False))
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in docstrings
    ]
    for forbidden in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "localhost:3001"):
        assert not any(forbidden in literal for literal in literals), forbidden
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not imported & {"httpx", "aiohttp", "requests", "openai", "anthropic"}, imported


def test_no_module_holds_geo_its_own_model_key_or_base_url():
    """Owner 2026-09-21：「GEO 不保留 Builder / .env / 自己的模型 Key」。

    ``adapters/llm.py`` 自己干净还不够 —— 只要**仓库里任何地方**还读 ``LLM_API_KEY`` /
    ``LLM_BASE_URL`` / ``LLM_MODEL`` / ``BUILDER_GEO_MODEL_URL``，GEO 就还留着同一件事的
    第二份答案（换个 import 就能复活）。所以守卫扫整个 app/ 与 adapters/ 的**代码**。
    注释与 docstring 允许点名它们（说明「删了什么」正是它们的用途）。
    """
    import ast
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[3]  # eios-product-geo
    roots = [repo / "apps" / "api" / "app", repo / "adapters"]
    forbidden = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "BUILDER_GEO_MODEL_URL")
    offenders: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {
                doc
                for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and (doc := ast.get_docstring(node, clean=False))
            }
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                if node.value in docstrings:
                    continue
                for name in forbidden:
                    if name in node.value:
                        offenders.append(f"{path.relative_to(repo)}:{node.lineno} {name}")
    assert not offenders, offenders
