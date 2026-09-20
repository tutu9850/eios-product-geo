# GEO P2 Monitor Vertical Slice Audit

## Scope and status

This checkpoint implements one GEO Product-owned monitor-run path.  It does
not migrate SQLite data, dual-write, remove the legacy v1 path, change EIOS
Foundation, or claim a production Provider/AuthContext configuration.

| Item | Value |
| --- | --- |
| Endpoint | `POST /api/v2/product/monitor-runs` |
| Operation | `geo.monitor.run` |
| Official runtime mode | `GEO_AUTH_MODE=auth_context` + `GEO_PRODUCT_STORAGE_MODE=postgres` |
| Product state | `geo_product` PostgreSQL schema |
| Legacy dependencies | none in this route |

## Real execution path

```text
Bearer token
  -> injected server-side AuthContext verifier
  -> VerifiedAuthContext
  -> ProductSession(deployment_id, enterprise_id, principal, trace_ref)
  -> Product operation policy: geo.monitor.run
  -> ProductMonitorRunService transaction
     -> idempotency_records
     -> product_tasks
     -> monitor_runs
     -> provider_attempts
     -> GEO-owned Provider Port
     -> observations
  -> Product response(task_id, run_id, observation_id, trace_ref)
```

The HTTP request cannot select `deployment_id` or `enterprise_id`; both come
only from the verified context.  `X-Tenant-Id`, including `tenant_corp_01`, is
irrelevant to the v2 path and cannot authenticate a request.

## Ownership and boundaries

- `ProductSession` is the only ownership input to repository builders.
- PostgreSQL composite scope and foreign keys reject cross-enterprise product
  task/idempotency relationships.
- `GeoObservation` is stored in `geo_product.observations`; it is not
  Foundation Evidence and no `geo_evidence` table is used.
- The Provider is a GEO product-local injected port.  The acceptance suite uses
  a deterministic test implementation; a production Provider Adapter remains
  a separately configured, replaceable GEO dependency.
- This slice does not require Foundation resources.  When a later product flow
  requires Knowledge/Data, it must call Foundation APIs and retain references,
  never query a Foundation database or revive the legacy Kernel as authority.

## Idempotency protocol

The scope is `(deployment_id, enterprise_id, operation, Idempotency-Key)`.

- First request reserves an `in_progress` record and executes once.
- Same key and same canonical request hash replays the completed run.
- Same key and a different hash is rejected with `409`.
- A concurrent `in_progress` duplicate is rejected with `409`.
- Provider failure records failed product state before the error is returned;
  it is not silently retried under the same key.

## Test evidence

Executed against a dedicated temporary PostgreSQL 16 container, not any
Foundation database:

```text
GEO_TEST_POSTGRES_URL=postgresql+psycopg://... \
PYTHONPATH=apps/api python -m pytest \
  apps/api/tests/test_product_session.py \
  apps/api/tests/test_product_repository.py \
  apps/api/tests/test_product_http_auth.py \
  apps/api/tests/test_product_postgres_schema.py \
  apps/api/tests/test_product_monitor_vertical_slice.py \
  tests/test_reset_source.py -q

18 passed
```

The black-box acceptance test verifies normal execution, idempotent replay,
idempotency conflict, missing AuthContext with legacy tenant header, durable
task/run/provider-attempt/observation writes, and the cross-owner task foreign
key.

## Rollback / forward-fix

Pre-switch, the v2 endpoint is inactive unless both strict modes and its
runtime dependencies are configured.  Post-switch, defects are repaired
forward: no downgrade is used to erase accepted GEO Product state.  Legacy v1
continues as a separate compatibility path and is not invoked by this slice.

## Remaining explicit work

1. Configure the production Foundation AuthContext verifier/trust material;
   the present seam intentionally fails closed when absent.
2. Implement a governed production GEO Provider Adapter behind the new port;
   do not reconnect this route to legacy Kernel/Store adapters.
3. Migrate monitor configuration and other GEO functions in separate slices;
   no claim of full feature parity is made by this checkpoint.
