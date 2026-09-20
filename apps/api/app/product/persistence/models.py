"""Initial normalized GEO Product PostgreSQL model.

This metadata is intentionally separate from ``app.models.geo_models``. The
latter is the legacy SQLite compatibility store and must not become the target
schema by accidental reuse.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func


SCHEMA = "geo_product"
metadata = MetaData(schema=SCHEMA)


def _owner_columns() -> list[Column]:
    return [
        Column("deployment_id", String(128), nullable=False),
        Column("enterprise_id", String(128), nullable=False),
    ]


idempotency_records = Table(
    "idempotency_records", metadata,
    Column("id", String(128), primary_key=True),
    *_owner_columns(),
    Column("operation", String(128), nullable=False),
    Column("idempotency_key", String(256), nullable=False),
    Column("request_hash", String(80), nullable=False),
    Column("result_ref", String(256)),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("deployment_id", "enterprise_id", "operation", "idempotency_key", name="uq_geo_idempotency_scope"),
    UniqueConstraint("deployment_id", "enterprise_id", "id", name="uq_geo_idempotency_owner_id"),
)

# A ProductTask is GEO-owned durable execution intent.  It is deliberately
# distinct from monitor_tasks: the latter is a user-configured schedule while
# this table records one authorised product operation.
product_tasks = Table(
    "product_tasks", metadata,
    Column("id", String(128), primary_key=True),
    *_owner_columns(),
    Column("operation", String(128), nullable=False),
    Column("initiating_actor", String(256), nullable=False),
    Column("trace_ref", String(512), nullable=False),
    Column("idempotency_key", String(256), nullable=False),
    Column("request_hash", String(80), nullable=False),
    Column("status", String(32), nullable=False),
    Column("result_ref", String(256)),
    Column("failure_code", String(128)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "operation", "idempotency_key"],
        [
            f"{SCHEMA}.idempotency_records.deployment_id",
            f"{SCHEMA}.idempotency_records.enterprise_id",
            f"{SCHEMA}.idempotency_records.operation",
            f"{SCHEMA}.idempotency_records.idempotency_key",
        ],
        name="fk_geo_product_task_idempotency_owner",
    ),
    UniqueConstraint("deployment_id", "enterprise_id", "id", name="uq_geo_product_task_owner_id"),
)

monitor_objects = Table(
    "monitor_objects", metadata,
    Column("id", String(128), primary_key=True),
    *_owner_columns(),
    Column("subject_namespace", String(64), nullable=False),
    Column("subject_type", String(64), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("display_name", String(512), nullable=False),
    Column("monitor_type", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("probe_config", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True)),
    Column("archived_at", DateTime(timezone=True)),
    UniqueConstraint("deployment_id", "enterprise_id", "id", name="uq_geo_monitor_object_owner_id"),
)

monitor_tasks = Table(
    "monitor_tasks", metadata,
    Column("id", String(128), primary_key=True),
    *_owner_columns(),
    Column("name", String(512), nullable=False),
    Column("schedule", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("engine_policy", JSONB, nullable=False, server_default="{}"),
    Column("next_run_at", DateTime(timezone=True)),
    Column("last_run_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("deployment_id", "enterprise_id", "id", name="uq_geo_monitor_task_owner_id"),
)

monitor_task_objects = Table(
    "monitor_task_objects", metadata,
    *_owner_columns(),
    Column("task_id", String(128), nullable=False),
    Column("monitor_object_id", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "task_id"],
        [f"{SCHEMA}.monitor_tasks.deployment_id", f"{SCHEMA}.monitor_tasks.enterprise_id", f"{SCHEMA}.monitor_tasks.id"],
        name="fk_geo_task_object_task_owner",
    ),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "monitor_object_id"],
        [f"{SCHEMA}.monitor_objects.deployment_id", f"{SCHEMA}.monitor_objects.enterprise_id", f"{SCHEMA}.monitor_objects.id"],
        name="fk_geo_task_object_monitor_owner",
    ),
    UniqueConstraint("deployment_id", "enterprise_id", "task_id", "monitor_object_id", name="uq_geo_task_object"),
)

monitor_runs = Table(
    "monitor_runs", metadata,
    Column("id", String(128), primary_key=True),
    *_owner_columns(),
    Column("task_id", String(128)),
    Column("monitor_object_id", String(128)),
    Column("status", String(32), nullable=False),
    Column("trigger_type", String(32), nullable=False),
    Column("initiating_actor", String(256), nullable=False),
    Column("trace_ref", String(512), nullable=False),
    Column("idempotency_key", String(256), nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "task_id"],
        [f"{SCHEMA}.monitor_tasks.deployment_id", f"{SCHEMA}.monitor_tasks.enterprise_id", f"{SCHEMA}.monitor_tasks.id"],
        name="fk_geo_run_task_owner",
    ),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "monitor_object_id"],
        [f"{SCHEMA}.monitor_objects.deployment_id", f"{SCHEMA}.monitor_objects.enterprise_id", f"{SCHEMA}.monitor_objects.id"],
        name="fk_geo_run_monitor_owner",
    ),
    UniqueConstraint("deployment_id", "enterprise_id", "id", name="uq_geo_monitor_run_owner_id"),
    UniqueConstraint("deployment_id", "enterprise_id", "idempotency_key", name="uq_geo_monitor_run_idempotency"),
)

provider_attempts = Table(
    "provider_attempts", metadata,
    Column("id", String(128), primary_key=True),
    *_owner_columns(),
    Column("run_id", String(128), nullable=False),
    Column("attempt_no", Integer, nullable=False),
    Column("provider_binding_id", String(128), nullable=False),
    Column("adapter_version", String(128), nullable=False),
    Column("request_hash", String(80), nullable=False),
    Column("provider_request_ref", String(512)),
    Column("status", String(32), nullable=False),
    Column("degradation_code", String(128)),
    Column("error_code", String(128)),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "run_id"],
        [f"{SCHEMA}.monitor_runs.deployment_id", f"{SCHEMA}.monitor_runs.enterprise_id", f"{SCHEMA}.monitor_runs.id"],
        name="fk_geo_provider_attempt_run_owner",
    ),
    UniqueConstraint("deployment_id", "enterprise_id", "run_id", "attempt_no", name="uq_geo_provider_attempt_run_number"),
)

observations = Table(
    "observations", metadata,
    Column("id", String(128), primary_key=True),
    *_owner_columns(),
    Column("run_id", String(128)),
    Column("subject_namespace", String(64), nullable=False),
    Column("subject_type", String(64), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("foundation_object_ref", JSONB),
    Column("provider_subject_id", String(512)),
    Column("source_type", String(64), nullable=False),
    Column("platform", String(128)),
    Column("source_url", Text),
    Column("source_key", String(512), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("raw_text", Text, nullable=False),
    Column("content_hash", String(80), nullable=False),
    Column("provider_payload", JSONB),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "run_id"],
        [f"{SCHEMA}.monitor_runs.deployment_id", f"{SCHEMA}.monitor_runs.enterprise_id", f"{SCHEMA}.monitor_runs.id"],
        name="fk_geo_observation_run_owner",
    ),
    UniqueConstraint("deployment_id", "enterprise_id", "id", name="uq_geo_observation_owner_id"),
    UniqueConstraint("deployment_id", "enterprise_id", "source_type", "source_key", name="uq_geo_observation_source"),
)

observation_extractions = Table(
    "observation_extractions", metadata,
    Column("id", String(128), primary_key=True),
    *_owner_columns(),
    Column("observation_id", String(128), nullable=False),
    Column("version", Integer, nullable=False),
    Column("model_ref", String(256)),
    Column("status", String(32), nullable=False),
    Column("analysis", JSONB),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "observation_id"],
        [f"{SCHEMA}.observations.deployment_id", f"{SCHEMA}.observations.enterprise_id", f"{SCHEMA}.observations.id"],
        name="fk_geo_extraction_observation_owner",
    ),
    UniqueConstraint("deployment_id", "enterprise_id", "observation_id", "version", name="uq_geo_extraction_version"),
    UniqueConstraint("deployment_id", "enterprise_id", "id", name="uq_geo_extraction_owner_id"),
)

brand_mentions = Table(
    "brand_mentions", metadata,
    Column("id", String(128), primary_key=True),
    *_owner_columns(),
    Column("observation_id", String(128), nullable=False),
    Column("extraction_id", String(128), nullable=False),
    Column("brand_name", String(256), nullable=False),
    Column("mention_type", String(64), nullable=False),
    Column("factor", String(256), nullable=False),
    Column("evidence_quote", Text, nullable=False),
    Column("confidence", String(32)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "observation_id"],
        [f"{SCHEMA}.observations.deployment_id", f"{SCHEMA}.observations.enterprise_id", f"{SCHEMA}.observations.id"],
        name="fk_geo_mention_observation_owner",
    ),
    ForeignKeyConstraint(
        ["deployment_id", "enterprise_id", "extraction_id"],
        [f"{SCHEMA}.observation_extractions.deployment_id", f"{SCHEMA}.observation_extractions.enterprise_id", f"{SCHEMA}.observation_extractions.id"],
        name="fk_geo_mention_extraction_owner",
    ),
    UniqueConstraint("deployment_id", "enterprise_id", "id", name="uq_geo_mention_owner_id"),
    CheckConstraint("confidence IS NULL OR confidence IN ('low', 'medium', 'high')", name="ck_geo_mention_confidence"),
)
