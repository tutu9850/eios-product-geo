"""Intelligence 分析引擎 — 进程内 asyncio 队列

评审定稿：不引 Celery/Redis；与现网 monitor 后台任务一致。
⚠️ 重启丢内存态 → 启动时调用 recover_pending() 按 evidence 状态重扫入队（幂等）。
同步上下文（监测钩子）无事件循环时：入队进 deferred 缓冲，由 recover/flush 在 loop 内消化，禁止静默丢弃。
"""
import asyncio
import json
import logging

logger = logging.getLogger("eios.intelligence.queue")

_queue: asyncio.Queue | None = None
_worker_task: asyncio.Task | None = None
# 无 running loop 时暂存，startup / recover_pending 时 flush
# A queued item carries the tenant captured at enqueue time.  The worker runs
# in a long-lived task whose ContextVar would otherwise stay on whichever
# tenant happened to start the API process.
_deferred: list[tuple[str, str] | tuple[str, str, bool]] = []
# FastAPI startup 绑定的主循环：监测钩子常在无 running loop 的线程里写库，靠 call_soon_threadsafe 入队
_main_loop: asyncio.AbstractEventLoop | None = None

# 攒够 20 条新 succeeded → 自动触发报告（内存态，重启丢失由每日定时兜底）
# Keep the report threshold isolated per tenant.  A single process may serve
# several account cabinets and a success in one cabinet must not trigger a
# report for another one.
_succeeded_since_report: dict[str, int] = {}
_report_running: set[str] = set()
AUTO_REPORT_THRESHOLD = 20
_WORKER_CONCURRENCY = 5


def bind_main_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """启动时绑定主事件循环（供跨线程 enqueue）。"""
    global _main_loop
    _main_loop = loop or asyncio.get_running_loop()


def ensure_worker() -> asyncio.Queue:
    """确保消费者在跑（须在事件循环内调用）。"""
    global _queue, _worker_task
    if _queue is None:
        _queue = asyncio.Queue()
        _worker_task = asyncio.create_task(_fan_out_supervisor())
        logger.info("intelligence queue worker started (concurrency=%d)", _WORKER_CONCURRENCY)
    return _queue


def _tenant_now() -> str:
    """Read the request/thread tenant without importing it at module load."""
    from app.services.store import current_tenant

    return current_tenant()


def _tenant_value(tenant_id: str | None = None) -> str:
    """Return a concrete tenant for a queued job.

    ``enqueue(evidence_id)`` remains the public compatibility form; when no
    explicit tenant is supplied it captures the current ContextVar *now*,
    rather than when the worker eventually happens to run.
    """
    value = str(tenant_id or _tenant_now() or "tenant_corp_01").strip()
    return value or "tenant_corp_01"


def _put_on_loop(tenant_id: str, evidence_id: str, auto_report: bool = True) -> None:
    job = (tenant_id, evidence_id) if auto_report else (tenant_id, evidence_id, False)
    ensure_worker().put_nowait(job)


def enqueue(
    evidence_id: str,
    tenant_id: str | None = None,
    *,
    auto_report: bool = True,
) -> None:
    """入队解析任务（不阻塞调用方）。无事件循环时优先投递主循环，否则 deferred。"""
    global _deferred
    if not evidence_id:
        return
    tenant = _tenant_value(tenant_id)
    job = (tenant, str(evidence_id)) if auto_report else (tenant, str(evidence_id), False)
    try:
        asyncio.get_running_loop()
        _put_on_loop(*job)
        return
    except RuntimeError:
        pass

    loop = _main_loop
    if loop is not None and loop.is_running():
        try:
            loop.call_soon_threadsafe(_put_on_loop, *job)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("call_soon_threadsafe failed, defer: %s (%s)", evidence_id, exc)

    if job not in _deferred:
        _deferred.append(job)
    logger.info("enqueue deferred (no event loop): %s tenant=%s", evidence_id, tenant)


def flush_deferred(tenant_id: str | None = None) -> int:
    """把 deferred 刷进真实队列（须在事件循环内）。返回刷入条数。"""
    global _deferred
    if not _deferred:
        return 0
    selected_tenant = _tenant_value(tenant_id) if tenant_id is not None else None
    selected: list[tuple[str, str] | tuple[str, str, bool]] = []
    remaining: list[tuple[str, str] | tuple[str, str, bool]] = []
    for raw_job in _deferred:
        job = raw_job
        if selected_tenant is None or job[0] == selected_tenant:
            selected.append(job)
        else:
            remaining.append(job)
    _deferred = remaining
    if not selected:
        return 0
    q = ensure_worker()
    n = 0
    for job in selected:
        try:
            q.put_nowait(job)
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("flush_deferred put failed: %s", job, exc_info=True)
            if job not in _deferred:
                _deferred.append(job)
    if n:
        logger.info("intelligence flush_deferred enqueued %d", n)
    return n


async def _worker() -> None:
    """消费队列：调 extractor 解析；失败不影响队列。攒 20 条 succeeded 自动出报告。"""
    from services.intelligence import extractor

    while True:
        raw_job = await _queue.get()
        # Two-item jobs are the compatibility path; controlled samples carry
        # an explicit False flag as their third item.
        if isinstance(raw_job, tuple) and len(raw_job) in (2, 3):
            if len(raw_job) == 3:
                tenant_id, evidence_id, auto_report = raw_job
            else:  # pragma: no cover - compatibility guard for old jobs
                tenant_id, evidence_id = raw_job
                auto_report = True
        else:  # pragma: no cover - compatibility guard for old in-memory jobs
            tenant_id, evidence_id, auto_report = _tenant_value(), str(raw_job), True
        previous_tenant = _tenant_now()
        try:
            from app.services.store import set_tenant

            set_tenant(str(tenant_id))
            result = await extractor.analyze_evidence(evidence_id)
            if result.get("status") == "succeeded":
                if auto_report:
                    count = _succeeded_since_report.get(str(tenant_id), 0) + 1
                    _succeeded_since_report[str(tenant_id)] = count
                    if count >= AUTO_REPORT_THRESHOLD and str(tenant_id) not in _report_running:
                        _report_running.add(str(tenant_id))
                        _succeeded_since_report[str(tenant_id)] = 0
                        asyncio.create_task(_auto_report(str(tenant_id)))
        except asyncio.CancelledError:  # noqa: PERF203
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("analyze failed (unexpected): %s: %s", evidence_id, exc)
        finally:
            try:
                from app.services.store import set_tenant

                set_tenant(previous_tenant)
            except Exception:  # noqa: BLE001
                logger.warning("failed to restore tenant context after %s", evidence_id, exc_info=True)
            _queue.task_done()


async def _fan_out_supervisor() -> None:
    """常驻 supervisor：保持 N 个 worker 协程存活（任一异常退出自动补位）。"""
    global _worker_task
    while True:
        workers = [asyncio.create_task(_worker()) for _ in range(_WORKER_CONCURRENCY)]
        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:  # noqa: PERF203
            raise
        except Exception:  # noqa: BLE001
            logger.exception("worker crashed, respawning")
        await asyncio.sleep(0.5)


async def _auto_report(tenant_id: str) -> None:
    """攒够 20 条后自动生成周期报告（失败不影响队列）。"""
    previous_tenant = _tenant_now()
    try:
        from app.services.store import set_tenant

        set_tenant(tenant_id)
        from services.intelligence.reasoning import generate_report

        # Pass the tenant explicitly as well as setting the ContextVar.  The
        # report's aggregators honour this argument, while its knowledge
        # adapters still read the ContextVar in their downstream calls.
        report = await generate_report(tenant=tenant_id)
        logger.info(
            "auto report generated（攒 20 条触发）：%d 维度，%d 行动",
            len(report.get("gap_matrix") or []),
            len(report.get("actions") or []),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto report failed: %s", exc)
    finally:
        try:
            from app.services.store import set_tenant

            set_tenant(previous_tenant)
        except Exception:  # noqa: BLE001
            logger.warning("failed to restore tenant context after auto report", exc_info=True)
        _report_running.discard(tenant_id)


async def recover_pending(
    tenant_id: str | None = None,
    monitor_id: str | None = None,
    limit: int | None = None,
    auto_report: bool = True,
) -> int:
    """启动/手动恢复：flush deferred + 把无 succeeded extraction 的 evidence 重新入队。返回入队数。"""
    from services.intelligence import repo

    # Queue recovery is an account operation.  Omitting tenant_id means the
    # current request cabinet, which is also the legacy default cabinet at
    # process startup; there is no implicit cross-tenant scan.
    selected_tenant = _tenant_value(tenant_id)
    # Deferred jobs are an independent stream, potentially for other monitors.
    # A bounded sample must not release them or count them against its budget.
    n = flush_deferred(selected_tenant) if limit is None else 0
    selected_monitor = str(monitor_id or "").strip()
    # The repository applies the scope at its data-access boundary; the small
    # defensive filter below keeps this queue boundary honest if a caller
    # supplies a custom repo or returns a broader pending list.
    pending = repo.list_evidence_pending(selected_tenant, selected_monitor or None)
    remaining = None if limit is None else max(0, int(limit) - n)
    for ev in pending:
        if remaining is not None and remaining <= 0:
            break
        if selected_monitor:
            context = ev.get("context_json") or {}
            if isinstance(context, str):
                try:
                    context = json.loads(context)
                except json.JSONDecodeError:
                    context = {}
            if not isinstance(context, dict) or str(context.get("monitor_id") or "") != selected_monitor:
                continue
        if auto_report:
            enqueue(ev["id"], tenant_id=ev.get("tenant_id") or selected_tenant)
        else:
            enqueue(
                ev["id"],
                tenant_id=ev.get("tenant_id") or selected_tenant,
                auto_report=False,
            )
        n += 1
        if remaining is not None:
            remaining -= 1
    if n:
        logger.info("intelligence recover_pending enqueued %d", n)
    return n


async def snapshot(
    tenant_id: str | None = None,
    monitor_id: str | None = None,
) -> dict:
    """解析队列实时快照（succeeded/failed/running/total/queue_size）——run-status 进度用。"""
    from sqlalchemy import func, or_

    from app.models.geo_models import GeoEvidence, GeoExtraction, SessionLocal, init_db

    init_db()
    selected_tenant = _tenant_value(tenant_id)
    selected_monitor = str(monitor_id or "").strip()
    with SessionLocal() as db:
        query = db.query(GeoExtraction.status, func.count(GeoExtraction.id))
        # Progress is account-scoped by default.  Passing tenant_id is useful
        # for scheduler/tests that explicitly run another cabinet, but an
        # omitted value must never fall back to a process-global count.
        query = query.filter(GeoExtraction.tenant_id == selected_tenant)
        monitor_evidence_ids: set[str] | None = None
        if selected_monitor:
            monitor_evidence_ids = set()
            evidence_rows = (
                db.query(GeoEvidence.id, GeoEvidence.context_json)
                .filter(GeoEvidence.tenant_id == selected_tenant)
                .all()
            )
            for evidence_id, context_json in evidence_rows:
                try:
                    context = json.loads(context_json or "{}")
                except (TypeError, json.JSONDecodeError):
                    context = {}
                if isinstance(context, dict) and str(context.get("monitor_id") or "") == selected_monitor:
                    monitor_evidence_ids.add(evidence_id)
            if monitor_evidence_ids:
                query = query.filter(
                    or_(
                        GeoExtraction.monitor_id == selected_monitor,
                        GeoExtraction.evidence_id.in_(monitor_evidence_ids),
                    )
                )
            else:
                query = query.filter(GeoExtraction.monitor_id == selected_monitor)
        rows = query.group_by(GeoExtraction.status).all()
    stats: dict = {"succeeded": 0, "failed": 0, "running": 0, "total": 0}
    for st, c in rows:
        stats[st if st in stats else "running"] = c
    stats["total"] = stats["succeeded"] + stats["failed"] + stats["running"]
    monitor_evidence_ids = monitor_evidence_ids if selected_monitor else None

    def _job_matches(job: tuple[str, str]) -> bool:
        if job[0] != selected_tenant:
            return False
        if monitor_evidence_ids is not None and job[1] not in monitor_evidence_ids:
            return False
        return True

    if _queue is not None:
        queued_jobs = list(getattr(_queue, "_queue", ()))
        stats["queue_size"] = sum(
            1
            for job in queued_jobs
            if isinstance(job, tuple) and len(job) == 2 and _job_matches(job)
        )
    else:
        stats["queue_size"] = _queue.qsize() if _queue is not None else 0
    stats["deferred"] = sum(1 for job in _deferred if _job_matches(job))
    return stats


async def wait_drained(timeout: float = 900.0) -> dict:
    """等待解析队列排空（自动配置/定时监测串行化用）。

    语义：队列空 + 无 running 解析 = 全部 AI 回复解析完成。
    之后蒸馏出的内容机会/缺口才基于完整解析数据。
    轮询 2s；超时返回 drained=False（调用方决定是否继续，不抛错）。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        s = await snapshot()
        if s["queue_size"] == 0 and s["running"] == 0 and s.get("deferred", 0) == 0:
            return {"drained": True, **s}
        if loop.time() > deadline:
            logger.warning("wait_drained timeout: %s", s)
            return {"drained": False, **s}
        await asyncio.sleep(2.0)
