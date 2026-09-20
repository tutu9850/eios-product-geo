"""Create GEO product core PostgreSQL schema.

This is expand-only. It creates no data migration, dual write, or service switch.
"""
from __future__ import annotations

from alembic import op

from app.product.persistence.models import (
    SCHEMA,
    brand_mentions,
    idempotency_records,
    metadata,
    monitor_objects,
    monitor_runs,
    monitor_task_objects,
    monitor_tasks,
    observation_extractions,
    observations,
    provider_attempts,
)


revision = "20260903_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    bind = op.get_bind()
    # Keep this historic migration immutable: later tables belong to later
    # revisions, rather than appearing merely because current metadata changed.
    metadata.create_all(
        bind=bind,
        tables=[
            idempotency_records,
            monitor_objects,
            monitor_tasks,
            monitor_task_objects,
            monitor_runs,
            provider_attempts,
            observations,
            observation_extractions,
            brand_mentions,
        ],
        checkfirst=True,
    )


def downgrade() -> None:
    # Only valid before any accepted product write. Post-switch failures are
    # repaired forward; they must not silently drop product state.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
