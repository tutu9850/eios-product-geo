"""The intelligence route must bind a concrete MonitorItem before aggregating."""

from app.api.v1 import intelligence


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def load(self, table):
        assert table == "monitor_items"
        return self.rows


def test_resolve_monitor_company_uses_selected_active_brand(monkeypatch):
    monkeypatch.setattr(
        "app.services.store.get_store",
        lambda: _Store(
            [
                {
                    "monitor_id": "mon_brand_1",
                    "type": "brand",
                    "status": "active",
                    "entity": "展示名",
                    "config_json": {"company": "真实企业"},
                }
            ]
        ),
    )

    assert intelligence._resolve_monitor_company(None, "mon_brand_1") == ("真实企业", None)


def test_resolve_monitor_company_fails_closed_for_unknown_or_paused_subject(monkeypatch):
    monkeypatch.setattr(
        "app.services.store.get_store",
        lambda: _Store(
            [
                {"monitor_id": "mon_paused", "status": "paused", "config_json": {"company": "暂停企业"}},
            ]
        ),
    )

    assert intelligence._resolve_monitor_company(None, "missing") == (None, "选中的监测主体不存在或不属于当前账号")
    assert intelligence._resolve_monitor_company(None, "mon_paused") == (None, "选中的监测主体当前未启用")


def test_sov_route_passes_resolved_company_to_aggregator(monkeypatch):
    monkeypatch.setattr(
        "app.services.store.get_store",
        lambda: _Store(
            [
                {"monitor_id": "mon_brand_1", "status": "active", "config_json": {"company": "真实企业"}},
            ]
        ),
    )
    seen = {}
    monkeypatch.setattr(
        intelligence.aggregator,
        "share_of_voice",
        lambda **kwargs: seen.update(kwargs) or {"company": kwargs["company"]},
    )

    response = intelligence.sov(monitor_id="mon_brand_1")

    assert response["ok"] is True
    assert seen["company"] == "真实企业"

