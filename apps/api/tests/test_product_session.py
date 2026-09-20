from app.product.session import (
    ProductSession,
    bind_product_session,
    current_product_session,
    product_session_from_verified_auth_context,
)
from app.product.task import ProductTask


def test_product_session_requires_trusted_in_process_binding():
    assert current_product_session() is None
    session = ProductSession(
        deployment_id="dep_test",
        enterprise_id="ent_test",
        principal_id="user_test",
        actor_type="human",
        service_id="eios-geo",
        trace_ref="trace_test",
    )
    with bind_product_session(session):
        assert current_product_session() == session
    assert current_product_session() is None


def test_product_task_has_explicit_ownership_and_idempotency_context():
    task = ProductTask(
        id="task_test",
        deployment_id="dep_test",
        enterprise_id="ent_test",
        operation="geo.monitor.run",
        initiating_actor="user_test",
        trace_ref="trace_test",
        idempotency_key="idem_test",
    )
    assert task.ownership_key() == ("dep_test", "ent_test")
    assert task.idempotency_key == "idem_test"


def test_product_session_can_only_be_derived_from_verified_context_shape():
    class Context:
        deployment_id = "dep_test"
        enterprise_id = "enterprise_test"
        subject = "human:alice"
        service_id = "eios-geo"

    session = product_session_from_verified_auth_context(Context(), trace_ref="trace_test")
    assert session.deployment_id == "dep_test"
    assert session.enterprise_id == "enterprise_test"
    assert session.principal_id == "human:alice"
    assert session.actor_type == "human"


def test_product_session_rejects_untyped_legacy_principal():
    class Context:
        deployment_id = "dep_test"
        enterprise_id = "enterprise_test"
        subject = "tenant_corp_01"
        service_id = "eios-geo"

    import pytest

    with pytest.raises(ValueError, match="subject"):
        product_session_from_verified_auth_context(Context())
