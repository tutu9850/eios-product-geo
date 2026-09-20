from sqlalchemy.dialects import postgresql

from datetime import datetime, timezone

from app.product.persistence.repository import (
    build_brand_mention_insert,
    build_extraction_insert,
    build_monitor_run_insert,
    build_observation_insert,
    build_provider_attempt_insert,
)
from app.product.session import ProductSession
from app.product.task import ProductTask


def _session() -> ProductSession:
    return ProductSession(
        deployment_id="dep_test",
        enterprise_id="enterprise_test",
        principal_id="human:alice",
        actor_type="human",
        service_id="eios-geo",
        trace_ref="trace_request",
    )


def _task() -> ProductTask:
    return ProductTask(
        id="task_1",
        deployment_id="dep_test",
        enterprise_id="enterprise_test",
        operation="geo.monitor.run",
        initiating_actor="human:alice",
        trace_ref="trace_task",
        idempotency_key="idem_1",
    )


def test_monitor_run_statement_is_owner_and_idempotency_scoped():
    statement = build_monitor_run_insert(session=_session(), task=_task(), run_id="run_1", trigger_type="manual")
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "geo_product.monitor_runs" in sql
    assert "deployment_id" in sql and "enterprise_id" in sql
    assert "idempotency_key" in sql
    assert "tenant_id" not in sql


def test_monitor_run_rejects_cross_owner_task():
    foreign = ProductTask(
        id="task_foreign", deployment_id="dep_other", enterprise_id="enterprise_test",
        operation="geo.monitor.run", initiating_actor="human:bob", trace_ref="trace", idempotency_key="idem",
    )
    try:
        build_monitor_run_insert(session=_session(), task=foreign, run_id="run_1", trigger_type="manual")
    except ValueError as exc:
        assert "ownership" in str(exc)
    else:
        raise AssertionError("cross-owner ProductTask must be rejected")


def test_provider_attempt_rejects_invalid_attempt_number():
    try:
        build_provider_attempt_insert(
            session=_session(), run_id="run_1", attempt_id="attempt_1", attempt_no=0,
            provider_binding_id="binding_1", adapter_version="v1", request_hash="sha256:abc",
        )
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("attempt number must be positive")


def test_observation_chain_uses_geo_names_and_formal_owner_scope():
    observation = build_observation_insert(
        session=_session(), observation_id="obs_1", source_type="ai_answer", source_key="source_1",
        subject_namespace="geo_product", subject_type="company", subject_id="subject_1",
        observed_at=datetime.now(timezone.utc), raw_text="answer", content_hash="sha256:abc",
    )
    extraction = build_extraction_insert(
        session=_session(), extraction_id="extract_1", observation_id="obs_1", version=1, status="succeeded",
    )
    mention = build_brand_mention_insert(
        session=_session(), mention_id="mention_1", observation_id="obs_1", extraction_id="extract_1",
        brand_name="Acme", mention_type="recommended", factor="quality", evidence_quote="quoted", confidence="high",
    )
    sql = "\n".join(str(item.compile(dialect=postgresql.dialect())) for item in (observation, extraction, mention))
    assert "geo_product.observations" in sql
    assert "geo_product.observation_extractions" in sql
    assert "geo_product.brand_mentions" in sql
    assert "geo_evidence" not in sql and "tenant_id" not in sql
