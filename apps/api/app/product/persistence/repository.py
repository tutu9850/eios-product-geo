"""Scoped statement builders for GEO Product PostgreSQL persistence.

Route modules do not construct cross-enterprise SQL. A later Unit of Work owns
transactions; these builders make owner/trace/idempotency inputs explicit.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Insert, insert

from app.product.session import ProductSession
from app.product.task import ProductTask
from app.product.persistence.models import (
    brand_mentions,
    monitor_runs,
    observation_extractions,
    observations,
    product_tasks,
    provider_attempts,
)


def build_monitor_run_insert(
    *,
    session: ProductSession,
    task: ProductTask,
    run_id: str,
    trigger_type: str,
    status: str = "requested",
    requested_at: datetime | None = None,
) -> Insert:
    """Build a scope-bound run insert without legacy tenant fields."""
    if task.ownership_key() != (session.deployment_id, session.enterprise_id):
        raise ValueError("ProductTask ownership does not match ProductSession")
    values = {
        "id": run_id,
        "deployment_id": session.deployment_id,
        "enterprise_id": session.enterprise_id,
        # ``monitor_tasks`` is the user-owned schedule configuration.  A
        # ProductTask is one authorised execution intent and is correlated by
        # trace/idempotency until the schedule model is separately migrated.
        "task_id": None,
        "status": status,
        "trigger_type": trigger_type,
        "initiating_actor": task.initiating_actor,
        "trace_ref": task.trace_ref,
        "idempotency_key": task.idempotency_key,
    }
    if requested_at is not None:
        values["requested_at"] = requested_at
    return insert(monitor_runs).values(**values)


def build_product_task_insert(
    *,
    task: ProductTask,
    request_hash: str,
    status: str = "in_progress",
) -> Insert:
    """Persist the authorised GEO ProductTask, never a caller owner scope."""
    return insert(product_tasks).values(
        id=task.id,
        deployment_id=task.deployment_id,
        enterprise_id=task.enterprise_id,
        operation=task.operation,
        initiating_actor=task.initiating_actor,
        trace_ref=task.trace_ref,
        idempotency_key=task.idempotency_key,
        request_hash=request_hash,
        status=status,
    )


def build_provider_attempt_insert(
    *,
    session: ProductSession,
    run_id: str,
    attempt_id: str,
    attempt_no: int,
    provider_binding_id: str,
    adapter_version: str,
    request_hash: str,
    status: str = "requested",
) -> Insert:
    """Build a provider attempt tied to an already-scoped product run."""
    if attempt_no < 1:
        raise ValueError("attempt_no must be positive")
    return insert(provider_attempts).values(
        id=attempt_id,
        deployment_id=session.deployment_id,
        enterprise_id=session.enterprise_id,
        run_id=run_id,
        attempt_no=attempt_no,
        provider_binding_id=provider_binding_id,
        adapter_version=adapter_version,
        request_hash=request_hash,
        status=status,
    )


def build_observation_insert(
    *,
    session: ProductSession,
    observation_id: str,
    source_type: str,
    source_key: str,
    subject_namespace: str,
    subject_type: str,
    subject_id: str,
    observed_at: datetime,
    raw_text: str,
    content_hash: str,
    status: str = "recorded",
    run_id: str | None = None,
    platform: str | None = None,
    source_url: str | None = None,
    foundation_object_ref: dict | None = None,
    provider_subject_id: str | None = None,
    provider_payload: dict | None = None,
) -> Insert:
    """Build a GEO observation insert; it never accepts a Foundation Evidence ID."""
    if not source_key or not raw_text or not content_hash:
        raise ValueError("source_key, raw_text, and content_hash are required")
    return insert(observations).values(
        id=observation_id,
        deployment_id=session.deployment_id,
        enterprise_id=session.enterprise_id,
        run_id=run_id,
        subject_namespace=subject_namespace,
        subject_type=subject_type,
        subject_id=subject_id,
        foundation_object_ref=foundation_object_ref,
        provider_subject_id=provider_subject_id,
        source_type=source_type,
        platform=platform,
        source_url=source_url,
        source_key=source_key,
        observed_at=observed_at,
        raw_text=raw_text,
        content_hash=content_hash,
        provider_payload=provider_payload,
        status=status,
    )


def build_extraction_insert(
    *,
    session: ProductSession,
    extraction_id: str,
    observation_id: str,
    version: int,
    status: str,
    model_ref: str | None = None,
    analysis: dict | None = None,
    error: str | None = None,
) -> Insert:
    if version < 1:
        raise ValueError("extraction version must be positive")
    return insert(observation_extractions).values(
        id=extraction_id,
        deployment_id=session.deployment_id,
        enterprise_id=session.enterprise_id,
        observation_id=observation_id,
        version=version,
        model_ref=model_ref,
        status=status,
        analysis=analysis,
        error=error,
    )


def build_brand_mention_insert(
    *,
    session: ProductSession,
    mention_id: str,
    observation_id: str,
    extraction_id: str,
    brand_name: str,
    mention_type: str,
    factor: str,
    evidence_quote: str,
    confidence: str | None = None,
) -> Insert:
    if confidence not in {None, "low", "medium", "high"}:
        raise ValueError("invalid mention confidence")
    return insert(brand_mentions).values(
        id=mention_id,
        deployment_id=session.deployment_id,
        enterprise_id=session.enterprise_id,
        observation_id=observation_id,
        extraction_id=extraction_id,
        brand_name=brand_name,
        mention_type=mention_type,
        factor=factor,
        evidence_quote=evidence_quote,
        confidence=confidence,
    )
