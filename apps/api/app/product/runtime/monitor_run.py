"""Product-owned monitor execution with Provider IO outside DB transactions."""
from __future__ import annotations

import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.product.persistence.models import idempotency_records, monitor_runs, observations, product_tasks, provider_attempts
from app.product.persistence.repository import build_monitor_run_insert, build_observation_insert, build_product_task_insert, build_provider_attempt_insert
from app.product.session import ProductSession
from app.product.task import ProductTask

OPERATION = "geo.monitor.run"


class ProductOperationError(Exception): status_code, code = 500, "PRODUCT_OPERATION_FAILED"
class ProductPolicyDenied(ProductOperationError): status_code, code = 403, "PRODUCT_OPERATION_DENIED"
class ProductRuntimeUnavailable(ProductOperationError): status_code, code = 503, "PRODUCT_RUNTIME_UNAVAILABLE"
class IdempotencyConflict(ProductOperationError): status_code, code = 409, "IDEMPOTENCY_KEY_REUSED"
class IdempotencyInProgress(ProductOperationError): status_code, code = 409, "IDEMPOTENCY_IN_PROGRESS"
class ProviderTimedOut(ProductOperationError): status_code, code = 504, "PROVIDER_TIMED_OUT"


class ProductPolicy(Protocol):
    def __call__(self, session: ProductSession, operation: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    raw_text: str
    source_key: str
    provider_request_ref: str | None = None
    provider_subject_id: str | None = None
    provider_payload: dict | None = None


class GeoMonitorProvider(Protocol):
    binding_id: str
    adapter_version: str
    def observe(self, *, query: str, subject_id: str) -> ProviderObservation: ...


@dataclass(frozen=True, slots=True)
class MonitorRunCommand:
    subject_namespace: str; subject_type: str; subject_id: str; query: str; idempotency_key: str; source_type: str = "ai_answer"
    def request_hash(self) -> str:
        value = json.dumps({"subject_namespace": self.subject_namespace, "subject_type": self.subject_type, "subject_id": self.subject_id, "query": self.query, "source_type": self.source_type}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class MonitorRunResult:
    task_id: str; run_id: str; observation_id: str; trace_ref: str; replayed: bool = False


@dataclass(frozen=True, slots=True)
class _Execution:
    task: ProductTask; run_id: str; attempt_id: str; observation_id: str; request_hash: str


class ProductMonitorRunService:
    def __init__(self, *, engine: Engine, policy: ProductPolicy, provider: GeoMonitorProvider, provider_timeout_seconds: float = 30.0):
        self._engine, self._policy, self._provider, self._timeout = engine, policy, provider, provider_timeout_seconds

    def execute(self, *, session: ProductSession, command: MonitorRunCommand) -> MonitorRunResult:
        if not self._policy(session, OPERATION): raise ProductPolicyDenied("product policy denied geo.monitor.run")
        if not command.idempotency_key.strip(): raise ProductOperationError("Idempotency-Key is required")
        reserved = self._reserve(session, command)
        if isinstance(reserved, MonitorRunResult): return reserved
        self._mark_running(session, reserved)
        try:
            provider_result = self._call_provider(command)
        except ProviderTimedOut:
            self._finish_failure(session, reserved, "timed_out", "PROVIDER_TIMED_OUT")
            raise
        except Exception as exc:
            self._finish_failure(session, reserved, "failed", "PROVIDER_FAILED")
            raise ProductOperationError("GEO Provider execution failed") from exc
        return self._finish_success(session, command, reserved, provider_result)

    def recover_stale(self, *, older_than: timedelta) -> int:
        """Explicit operator recovery: fail stale leases; never replay Provider blindly."""
        cutoff, now = datetime.now(timezone.utc) - older_than, datetime.now(timezone.utc)
        with self._engine.begin() as c:
            rows = c.execute(select(provider_attempts).where(provider_attempts.c.status.in_(["requested", "running"]), provider_attempts.c.started_at < cutoff).with_for_update()).mappings().all()
            for row in rows:
                filters = _owned(provider_attempts, row["deployment_id"], row["enterprise_id"])
                c.execute(update(provider_attempts).where(*filters, provider_attempts.c.id == row["id"]).values(status="failed", error_code="RECOVERY_REQUIRED", finished_at=now))
                run = c.execute(select(monitor_runs).where(*_owned(monitor_runs, row["deployment_id"], row["enterprise_id"]), monitor_runs.c.id == row["run_id"])).mappings().one()
                c.execute(update(monitor_runs).where(*_owned(monitor_runs, row["deployment_id"], row["enterprise_id"]), monitor_runs.c.id == row["run_id"]).values(status="failed", finished_at=now))
                c.execute(update(product_tasks).where(*_owned(product_tasks, row["deployment_id"], row["enterprise_id"]), product_tasks.c.idempotency_key == run["idempotency_key"]).values(status="failed", failure_code="RECOVERY_REQUIRED", finished_at=now))
                c.execute(update(idempotency_records).where(*_owned(idempotency_records, row["deployment_id"], row["enterprise_id"]), idempotency_records.c.operation == OPERATION, idempotency_records.c.idempotency_key == run["idempotency_key"]).values(status="failed"))
            return len(rows)

    def _reserve(self, session, command):
        digest = command.request_hash()
        with self._engine.begin() as c:
            created = c.execute(pg_insert(idempotency_records).values(id=_id("idem"), deployment_id=session.deployment_id, enterprise_id=session.enterprise_id, operation=OPERATION, idempotency_key=command.idempotency_key, request_hash=digest, status="in_progress").on_conflict_do_nothing(index_elements=["deployment_id", "enterprise_id", "operation", "idempotency_key"]).returning(idempotency_records.c.id)).scalar_one_or_none()
            if created is None: return self._existing(c, session, command.idempotency_key, digest)
            task = ProductTask(_id("ptask"), session.deployment_id, session.enterprise_id, OPERATION, session.principal_id, session.trace_ref, command.idempotency_key)
            execution = _Execution(task, _id("run"), _id("attempt"), _id("obs"), digest)
            c.execute(build_product_task_insert(task=task, request_hash=digest))
            c.execute(build_monitor_run_insert(session=session, task=task, run_id=execution.run_id, trigger_type="manual"))
            c.execute(build_provider_attempt_insert(session=session, run_id=execution.run_id, attempt_id=execution.attempt_id, attempt_no=1, provider_binding_id=self._provider.binding_id, adapter_version=self._provider.adapter_version, request_hash=digest))
            return execution

    def _existing(self, c, session, key, digest):
        record = c.execute(select(idempotency_records).where(*_idem(session, key)).with_for_update()).mappings().one()
        if record["request_hash"] != digest: raise IdempotencyConflict("Idempotency-Key was already used for a different request")
        if record["status"] == "in_progress": raise IdempotencyInProgress("identical request is already running")
        if record["status"] != "succeeded" or not record["result_ref"]: raise ProductOperationError("previous request with this Idempotency-Key failed")
        run = c.execute(select(monitor_runs).where(*_owned(monitor_runs, session.deployment_id, session.enterprise_id), monitor_runs.c.id == record["result_ref"])).mappings().one()
        obs = c.execute(select(observations.c.id).where(*_owned(observations, session.deployment_id, session.enterprise_id), observations.c.run_id == run["id"])).scalar_one()
        task = c.execute(select(product_tasks.c.id).where(*_owned(product_tasks, session.deployment_id, session.enterprise_id), product_tasks.c.operation == OPERATION, product_tasks.c.idempotency_key == key)).scalar_one()
        return MonitorRunResult(task, run["id"], obs, run["trace_ref"], True)

    def _mark_running(self, session, x):
        now = datetime.now(timezone.utc)
        with self._engine.begin() as c:
            c.execute(update(provider_attempts).where(*_owned(provider_attempts, session.deployment_id, session.enterprise_id), provider_attempts.c.id == x.attempt_id).values(status="running", started_at=now))
            c.execute(update(monitor_runs).where(*_owned(monitor_runs, session.deployment_id, session.enterprise_id), monitor_runs.c.id == x.run_id).values(status="in_progress", started_at=now))
            c.execute(update(product_tasks).where(*_owned(product_tasks, session.deployment_id, session.enterprise_id), product_tasks.c.id == x.task.id).values(status="in_progress", started_at=now))

    def _call_provider(self, command):
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="geo-provider")
        future = pool.submit(self._provider.observe, query=command.query, subject_id=command.subject_id)
        try: return future.result(timeout=self._timeout)
        except FutureTimeout as exc:
            future.cancel(); raise ProviderTimedOut("GEO Provider exceeded its execution deadline") from exc
        finally: pool.shutdown(wait=False, cancel_futures=True)

    def _finish_success(self, session, command, x, result):
        now = datetime.now(timezone.utc); content_hash = "sha256:" + hashlib.sha256(result.raw_text.encode()).hexdigest()
        with self._engine.begin() as c:
            c.execute(build_observation_insert(session=session, observation_id=x.observation_id, run_id=x.run_id, source_type=command.source_type, source_key=result.source_key, subject_namespace=command.subject_namespace, subject_type=command.subject_type, subject_id=command.subject_id, observed_at=now, raw_text=result.raw_text, content_hash=content_hash, provider_subject_id=result.provider_subject_id, provider_payload=result.provider_payload))
            self._final_updates(c, session, x, "succeeded", None, now, result.provider_request_ref)
        return MonitorRunResult(x.task.id, x.run_id, x.observation_id, x.task.trace_ref)

    def _finish_failure(self, session, x, attempt_status, code):
        with self._engine.begin() as c: self._final_updates(c, session, x, attempt_status, code, datetime.now(timezone.utc), None)

    def _final_updates(self, c, session, x, attempt_status, code, now, request_ref):
        c.execute(update(provider_attempts).where(*_owned(provider_attempts, session.deployment_id, session.enterprise_id), provider_attempts.c.id == x.attempt_id).values(status=attempt_status, error_code=code, provider_request_ref=request_ref, finished_at=now))
        c.execute(update(monitor_runs).where(*_owned(monitor_runs, session.deployment_id, session.enterprise_id), monitor_runs.c.id == x.run_id).values(status="succeeded" if attempt_status == "succeeded" else "failed", finished_at=now))
        c.execute(update(product_tasks).where(*_owned(product_tasks, session.deployment_id, session.enterprise_id), product_tasks.c.id == x.task.id).values(status="succeeded" if attempt_status == "succeeded" else "failed", result_ref=x.run_id if attempt_status == "succeeded" else None, failure_code=code, finished_at=now))
        c.execute(update(idempotency_records).where(*_idem(session, x.task.idempotency_key)).values(status="succeeded" if attempt_status == "succeeded" else "failed", result_ref=x.run_id if attempt_status == "succeeded" else None))


def _owned(table, deployment_id, enterprise_id): return (table.c.deployment_id == deployment_id, table.c.enterprise_id == enterprise_id)
def _idem(session, key): return (*_owned(idempotency_records, session.deployment_id, session.enterprise_id), idempotency_records.c.operation == OPERATION, idempotency_records.c.idempotency_key == key)
def _id(prefix): return f"{prefix}_{uuid.uuid4().hex}"
