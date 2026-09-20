"""Durable-task contract for the target GEO product runtime.

Persistence is intentionally deferred to the PostgreSQL slice.  Defining the
data contract now prevents the legacy scheduler's tenant enumeration from
becoming the new task ownership model.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductTask:
    id: str
    deployment_id: str
    enterprise_id: str
    operation: str
    initiating_actor: str
    trace_ref: str
    idempotency_key: str

    def ownership_key(self) -> tuple[str, str]:
        return (self.deployment_id, self.enterprise_id)
