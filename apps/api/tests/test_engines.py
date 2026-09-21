"""GEO 的引擎面：清单来自部署的模型目录，提问走部署的统一模型入口。

Owner 2026-09-21 两句话钉住了这个文件：

* 「Model Capability 是 EIOS 的统一模型入口，不属于 GEO……企业部署配置模型，所有产品通过
  这一处调用。」
* 「GEO 不再写死 6 个。」

所以这里验的是「GEO 还剩什么」：读目录、发调用、如实翻译结果与拒绝。**不验**端点、模型名、
温度、联网参数、豆包形状 —— 那些不归 GEO，验在基座与 eios-integrations 自己的测试里。
"""
from __future__ import annotations

import asyncio

import pytest

import adapters.engines as engines
import adapters.model_entry as model_entry


class _Response:
    def __init__(self, status: int, body: dict):
        self.status, self.body = status, body


class _Entry:
    """一个假的入口客户端：记录收到什么，回放一个固定的答复。"""

    def __init__(self, *, catalog: dict | None = None, invoke: dict | None = None):
        self.configured = True
        self.calls: list[tuple[str, dict]] = []
        self._catalog = catalog or {"ok": True, "items": []}
        self._invoke = invoke or {"ok": True, "capability": "model.text_generation", "data": {}}

    def catalog(self, *, auth_context: str):  # noqa: ARG002 - 形状与真客户端一致
        self.calls.append(("catalog", {}))
        return _Response(200, self._catalog)

    def invoke(self, *, request: dict, auth_context: str):  # noqa: ARG002
        self.calls.append(("invoke", request))
        body = dict(self._invoke)
        if isinstance(body.get("data"), dict):
            # 只在假答复没写死这两项时回填：显式写了就要原样回放（测「结果说自己是别人」）。
            filled = {"model_id": request["model_id"], "consumer": request["consumer"]}
            filled.update({k: v for k, v in body["data"].items() if k in ("model_id", "consumer")})
            body["data"] = {**body["data"], **filled}
        return _Response(200, body)


def _catalog(*items: dict) -> dict:
    return {"ok": True, "contract": "eios.model_catalog/v1", "items": list(items), "default_model_id": None}


def _item(model_id: str, *, enabled: bool = True, modalities: tuple[str, ...] = ("text",)) -> dict:
    return {"model_id": model_id, "display_name": model_id.upper(), "enabled": enabled,
            "modalities": list(modalities), "capability_tags": ["text_generation"]}


@pytest.fixture()
def entry(monkeypatch):
    """把入口换成假的，并重置进程内缓存（真实现只组合一次）。"""
    def install(fake: _Entry) -> _Entry:
        monkeypatch.setattr(engines, "_client", fake)
        monkeypatch.setattr(engines, "_client_error", None)
        return fake

    monkeypatch.setattr(engines.identity, "sign", lambda **kwargs: f"ticket:{kwargs['scopes']}")
    return install


# ── 清单：部署说了算 ──────────────────────────────────────────────────────


def test_engines_come_from_the_deployment_catalog_not_a_hard_coded_six(entry):
    """有几个引擎是**部署目录**决定的：登记三个就是三个。"""
    entry(_Entry(catalog=_catalog(_item("alpha"), _item("beta"), _item("gamma"))))
    listed = asyncio.run(engines.list_engines())
    assert [e["id"] for e in listed] == ["alpha", "beta", "gamma"]
    assert listed[0]["name"] == "ALPHA"


def test_the_listing_carries_no_endpoint_model_or_credential(entry):
    """GEO 不该知道 base_url / model —— 那是部署的连接，产品知道得越少越好。"""
    entry(_Entry(catalog=_catalog({**_item("alpha"), "base_url": "https://secret.example/v1", "model": "x"})))
    listed = asyncio.run(engines.list_engines())
    assert set(listed[0]) == {"id", "name"}


def test_disabled_and_non_text_entries_are_not_monitored(entry):
    """监测问的是文本问题：停用的、不能接文本的都不进清单。"""
    entry(_Entry(catalog=_catalog(
        _item("alpha"),
        _item("off", enabled=False),
        _item("image_only", modalities=("image",)),
    )))
    assert [e["id"] for e in asyncio.run(engines.list_engines())] == ["alpha"]


# ── 调用：形状与如实翻译 ─────────────────────────────────────────────────


def test_an_invocation_is_the_monitoring_consumer_on_the_deployment_binding(entry):
    """调用只带三件事：契约、部署里的 model_id、consumer=geo.monitor。"""
    fake = entry(_Entry(catalog=_catalog(_item("alpha")),
                        invoke={"ok": True, "capability": "model.text_generation", "data": {"text": "你好"}}))
    meta = asyncio.run(engines.ask_with_meta("alpha", "问题", max_tokens=64))
    assert meta["content"] == "你好"
    request = dict(fake.calls[-1][1])
    assert request["contract"] == "eios.model_invocation/v1"
    assert request["model_id"] == "alpha"
    assert request["consumer"] == "geo.monitor"
    # GEO 不选模型参数：温度/思考/联网都是部署绑定与适配器的事，请求体里一个都不该有。
    assert set(request) == {"contract", "model_id", "consumer", "modality", "messages", "max_output_tokens"}


def test_web_search_is_reported_from_the_authority_not_guessed(entry):
    """「这条是搜来的」由权威侧如实回报；它没说，就按没联网记，不替它猜。"""
    entry(_Entry(catalog=_catalog(_item("alpha")),
                 invoke={"ok": True, "capability": "model.text_generation", "data": {"text": "a", "web_search": True}}))
    assert asyncio.run(engines.ask_with_meta("alpha", "q"))["web_realtime"] is True

    entry(_Entry(catalog=_catalog(_item("alpha")),
                 invoke={"ok": True, "capability": "model.text_generation", "data": {"text": "a"}}))
    assert asyncio.run(engines.ask_with_meta("alpha", "q"))["web_realtime"] is False


@pytest.mark.parametrize("code", ["MODEL_SECRET_UNAVAILABLE", "MODEL_BINDING_MISSING", "PROVIDER_NOT_ACTIVE"])
def test_a_model_the_deployment_did_not_provision_reads_as_unconfigured(entry, code):
    """部署没给这个模型凭据 = 「未配置」，不是故障。

    这条是监测落行的依据：``ValueError`` 分支把这一行标成 ``configured: False`` 并带上原因，
    而不是把它算成一次失败回答（那会让覆盖率的分母变得不诚实）。
    """
    entry(_Entry(catalog=_catalog(_item("alpha")),
                 invoke={"ok": False, "error": {"code": code, "message": "no"}}))
    with pytest.raises(engines.EngineNotConfigured):
        asyncio.run(engines.ask_with_meta("alpha", "q"))
    assert issubclass(engines.EngineNotConfigured, ValueError)


def test_another_refusal_keeps_the_authority_code(entry):
    """别的拒绝（策略/限流/坏答复）原样带码上来，GEO 不重写成一个自己的码。"""
    entry(_Entry(catalog=_catalog(_item("alpha")),
                 invoke={"ok": False, "error": {"code": "MODEL_POLICY_DENIED", "message": "denied"}}))
    with pytest.raises(engines.EngineCallFailed) as caught:
        asyncio.run(engines.ask_with_meta("alpha", "q"))
    assert caught.value.code == "MODEL_POLICY_DENIED"


def test_a_result_from_another_consumer_is_refused(entry):
    """结果里的 consumer 不是本服务的 → 拒绝，不当成自己的答案。"""
    fake = entry(_Entry(catalog=_catalog(_item("alpha"))))
    fake._invoke = {"ok": True, "capability": "model.text_generation",
                    "data": {"text": "a", "consumer": "advisor.chat"}}
    with pytest.raises(engines.EngineCallFailed) as caught:
        asyncio.run(engines.ask_with_meta("alpha", "q"))
    assert caught.value.code == "MODEL_BAD_RESPONSE"


def test_a_result_from_another_capability_is_refused(entry):
    entry(_Entry(catalog=_catalog(_item("alpha")),
                 invoke={"ok": True, "capability": "knowledge.lexical_retrieval", "data": {"text": "a"}}))
    with pytest.raises(engines.EngineCallFailed) as caught:
        asyncio.run(engines.ask_with_meta("alpha", "q"))
    assert caught.value.code == "MODEL_BAD_RESPONSE"


# ── 接不上：如实说，不回落 ───────────────────────────────────────────────


def test_a_deployment_without_an_entry_says_so_instead_of_falling_back(monkeypatch):
    """没有 EIOS_MODEL_CAPABILITY_URL = 这个部署没有模型入口：报那句话，不回落裸 HTTP。"""
    monkeypatch.setattr(model_entry, "base_url", lambda: "")
    monkeypatch.setattr(engines, "_client", None)
    monkeypatch.setattr(engines, "_client_error", None)
    monkeypatch.setattr(engines.identity, "sign", lambda **kwargs: "ticket")
    with pytest.raises(engines.EngineEntryUnavailable) as caught:
        asyncio.run(engines.list_engines())
    assert "EIOS_MODEL_CAPABILITY_URL" in caught.value.message


def test_engine_status_reports_the_catalog_and_no_credential_claim(entry):
    """「配置」页只能说产品知道的那件事：哪些模型登记在这个部署里。"""
    entry(_Entry(catalog=_catalog(_item("alpha"), _item("beta", enabled=False))))
    rows = asyncio.run(engines.engine_status())
    assert [(r["id"], r["enabled"]) for r in rows] == [("alpha", True), ("beta", False)]
    assert all("configured" not in row for row in rows)
    assert all(row["source"] == "deployment_catalog" for row in rows)


def test_ping_reports_what_the_authority_answered(entry):
    entry(_Entry(catalog=_catalog(_item("alpha")),
                 invoke={"ok": True, "capability": "model.text_generation", "data": {"text": "ok"}}))
    assert asyncio.run(engines.ping("alpha"))["reachable"] is True

    entry(_Entry(catalog=_catalog(_item("alpha")),
                 invoke={"ok": False, "error": {"code": "MODEL_SECRET_UNAVAILABLE", "message": "no key"}}))
    unreachable = asyncio.run(engines.ping("alpha"))
    assert unreachable["reachable"] is None and unreachable["configured"] is False


# ── 批量监测：没有引擎可问时如实收场 ─────────────────────────────────────


def _one_probe() -> list[dict]:
    return [{"monitor_id": "m1", "type": "question", "config_json": {"query": "q"}}]


def test_a_batch_with_no_engines_says_so_instead_of_running_empty_probes(monkeypatch):
    """部署一个模型都没登记时，批量监测如实收场（沿用既有 skipped 形状）。

    跑一遍空探针只会得到「0 个答案」，用户看不出原因 —— 那是把部署状态藏起来。
    """
    from app.api.v1 import monitor as monitor_module

    async def no_engines() -> list[dict]:
        return []

    monkeypatch.setattr(engines, "list_engines", no_engines)
    data = asyncio.run(monitor_module.run_batch_items(_one_probe()))
    assert data["results"] == []
    assert "还没有登记任何模型" in data["skipped"]


def test_a_batch_reports_an_unreachable_entry_with_its_own_code(monkeypatch):
    """入口接不上：批量监测把**那个码**说出来，而不是一句「服务内部错误」。"""
    from app.api.v1 import monitor as monitor_module

    async def boom() -> list[dict]:
        raise engines.EngineEntryUnavailable("这个部署的统一模型入口接不上")

    monkeypatch.setattr(engines, "list_engines", boom)
    data = asyncio.run(monitor_module.run_batch_items(_one_probe()))
    assert data["results"] == []
    assert "MODEL_CAPABILITY_UNAVAILABLE" in data["skipped"]


# ── 各面报自己的家门：辩论不该记成「监测」 ───────────────────────────────


def test_each_face_reports_its_own_consumer_name(entry):
    """consumer 决定部署要不要给这次调用联网；名字要如实，别人查账本时看得懂。"""
    fake = entry(_Entry(catalog=_catalog(_item("alpha")),
                        invoke={"ok": True, "capability": "model.text_generation", "data": {"text": "ok"}}))

    asyncio.run(engines.ask("alpha", "q", consumer=engines.BATTLE_CONSUMER))
    assert fake.calls[-1][1]["consumer"] == "geo.battle"

    asyncio.run(engines.ask("alpha", "q", consumer=engines.ONBOARD_CONSUMER))
    assert fake.calls[-1][1]["consumer"] == "geo.onboard"

    # 不写就是监测面（ping / 监测循环都是它）
    asyncio.run(engines.ask("alpha", "q"))
    assert fake.calls[-1][1]["consumer"] == "geo.monitor"


def test_a_result_echoing_another_consumer_is_still_refused_for_that_face(entry):
    """每个面都拿自己的名字去核结果，不能因为 default 是 geo.monitor 就放行别人。"""
    fake = entry(_Entry(catalog=_catalog(_item("alpha"))))
    fake._invoke = {"ok": True, "capability": "model.text_generation",
                    "data": {"text": "a", "consumer": "geo.monitor"}}
    with pytest.raises(engines.EngineCallFailed):
        asyncio.run(engines.ask("alpha", "q", consumer=engines.BATTLE_CONSUMER))


def test_onboarding_asks_every_registered_model_about_the_local_market(entry):
    """入驻的竞品发现：按**所在地**分问，问**每个登记且能答**的模型（Owner 2026-09-21 重做）。

    原来的实现只问一个写死的豆包、只问一句话，而且城市只能从公司名里抠 ——
    「笔革家居」抠不出城市，实测退化成全国（返回三维家/酷家乐一类的平台，不是成都本地公司）。
    现在：问题按 行业 / 产品 / 服务 分组，每个模型都问，consumer 仍是 geo.onboard；
    哪个模型没配凭据就如实跳过，并把「几个答了」带回去。
    """
    from app.api.v1 import onboard

    seen_prompts: list[tuple[str, str]] = []

    class _PerModelEntry(_Entry):
        """按 model_id 回不同答案：alpha 与 gamma 都提「成都锦华」，beta 是没配凭据。"""

        def invoke(self, *, request, auth_context):  # noqa: ARG002
            self.calls.append(("invoke", request))
            model_id = request["model_id"]
            seen_prompts.append((model_id, request["messages"][-1]["content"]))
            if model_id == "beta":
                return _Response(200, {"ok": False, "error": {"code": "MODEL_SECRET_UNAVAILABLE",
                                                             "message": "no key"}})
            names = {"alpha": ["成都锦华设计", "我们自家"], "gamma": ["成都锦华设计", "蜀韵家装"]}[model_id]
            # 权威侧会把 model_id / consumer 原样回执，签名的调用方据此确认「这是给我的答复」
            body = {"ok": True, "capability": "model.text_generation",
                    "data": {"text": "[%s]" % ",".join(
                        '{"name": "%s", "company": "%s公司"}' % (n, n) for n in names),
                        "model_id": model_id, "consumer": request["consumer"]}}
            return _Response(200, body)

    entry(_PerModelEntry(catalog=_catalog(_item("alpha"), _item("beta"), _item("gamma"))))
    out = asyncio.run(onboard._step_discover(
        ["全案定制"], own_names=["笔革家居", "我们自家"], company="笔革家居",
        industry="家装设计", city="成都", services=["全案设计"],
    ))

    # ① 每个模型都被问了，且用的是入驻自己的 consumer
    assert {m for m, _ in seen_prompts} == {"alpha", "beta", "gamma"}
    assert all(prompt for _, prompt in seen_prompts)

    # ② 问题按「所在地 + 行业/产品/服务」分组提出来（不再只问一句）
    assert any("家装设计" in q for q in out["questions"])
    assert any("全案定制" in q for q in out["questions"])
    assert any("全案设计" in q for q in out["questions"])
    for _, prompt in seen_prompts:
        assert "成都" in prompt

    # ③ 没配凭据的模型跳过，但如实报出「几个答了」
    assert out["engines_total"] == 3
    assert out["engines_answered"] == 2
    assert out["not_answered"] == ["beta"]

    # ④ 两个模型都提到的排在最前；自家名字被剔掉
    names = [c["name"] for c in out["competitors"]]
    assert names[0] == "成都锦华设计"
    assert out["competitors"][0]["mentioned_by"] == ["alpha", "gamma"]
    assert "我们自家" not in names and "笔革家居" not in names


def test_onboarding_falls_back_to_the_company_name_for_the_city(entry):
    """用户没填所在地时退回从公司名抠（旧行为），并如实说明城市是从哪来的。"""
    from app.api.v1 import onboard

    class _One(_Entry):
        def invoke(self, *, request, auth_context):  # noqa: ARG002
            self.calls.append(("invoke", request))
            return _Response(200, {"ok": True, "capability": "model.text_generation",
                                   "data": {"text": '[{"name": "蓉城设计", "company": "蓉城"}]',
                                            "model_id": request["model_id"],
                                            "consumer": request["consumer"]}})

    entry(_One(catalog=_catalog(_item("alpha"))))
    out = asyncio.run(onboard._step_discover(
        [], own_names=[], company="成都亚宇臻隆科技", industry="家装设计", city="",
    ))
    assert out["city"] == "成都"
    assert out["city_source"] == "company_name"
    assert any("成都" in q for q in out["questions"])


def test_onboarding_says_so_when_there_is_no_model_to_ask(entry):
    """部署一个模型都没登记 → 空候选 + 明确提示，不编造竞品。"""
    from app.api.v1 import onboard

    entry(_Entry(catalog=_catalog()))
    out = asyncio.run(onboard._step_discover(
        ["全案定制"], own_names=["笔革家居"], company="笔革家居", industry="家装设计", city="成都",
    ))
    assert out["competitors"] == []
    assert out["empty"] is True
    assert out["engines_total"] == 0
    assert out["hint"]


# ── 竞品发现：模型回答被截断也不能把整步弄挂 ──────────────────────────────


def test_a_truncated_model_answer_still_yields_candidates():
    """max_tokens 截断是常态（实测第 45 行断在第 31 列）。

    解析必须尽力而为：完整的名字照收，取不到的当没有；绝不允许一次截断
    让整步 discover 失败（改造前 `json.loads` 没兜底，实测就是这么挂的）。
    """
    from app.api.v1 import onboard

    truncated = ('[{"name": "成都锦华设计", "company": "锦华设计有限公司"},\n'
                 '{"name": "蜀韵家装", "company": "蜀韵装饰"}, \n'
                 '{"name": "未写完的公司", "comp')
    got = onboard._candidates_from(truncated, own_names=[])
    assert [c["name"] for c in got] == ["成都锦华设计", "蜀韵家装"]
    assert got[0]["company"] == "锦华设计有限公司"


def test_a_model_answer_that_is_not_json_at_all_falls_back_to_lines():
    """连 JSON 影子都没有（模型改成编号列表）→ 逐行取名字，不抛异常。"""
    from app.api.v1 import onboard

    got = onboard._candidates_from("1. 成都锦华设计\n2. 蜀韵家装\n以上是我的回答", own_names=[])
    assert "成都锦华设计" in [c["name"] for c in got]


def test_the_json_helper_never_raises_on_garbage():
    from app.api.v1 import onboard

    for junk in ("", "[", "{{", "【不是 JSON】", "[\"未闭合"):
        assert onboard._extract_json_array(junk) == []
