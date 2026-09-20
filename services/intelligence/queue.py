"""Intelligence 分析引擎 — 进程内 asyncio 队列

评审定稿：不引 Celery/Redis；与现网 monitor 后台任务一致。
⚠️ 重启丢内存态 → 启动时调用 recover_pending() 按 evidence 状态重扫入队（幂等）。
同步上下文（监测钩子）无事件循环时：入队进 deferred 缓冲，由 recover/flush 在 loop 内消化，禁止静默丢弃。
"""
import asyncio
import logging

logger = logging.getLogger("eios.intelligence.queue")

_queue: asyncio.Queue | None = None
_worker_task: asyncio.Task | None = None
# 无 running loop 时暂存，startup / recover_pending 时 flush
_deferred: list[str] = []
# FastAPI startup 绑定的主循环：监测钩子常在无 running loop 的线程里写库，靠 call_soon_threadsafe 入队
_main_loop: asyncio.AbstractEventLoop | None = None

# 攒够 20 条新 succeeded → 自动触发报告（内存态，重启丢失由每日定时兜底）
_succeeded_since_report = 0
_report_running = False
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


def _put_on_loop(evidence_id: str) -> None:
    ensure_worker().put_nowait(evidence_id)


def enqueue(evidence_id: str) -> None:
    """入队解析任务（不阻塞调用方）。无事件循环时优先投递主循环，否则 deferred。"""
    global _deferred
    if not evidence_id:
        return
    try:
        asyncio.get_running_loop()
        _put_on_loop(evidence_id)
        return
    except RuntimeError:
        pass

    loop = _main_loop
    if loop is not None and loop.is_running():
        try:
            loop.call_soon_threadsafe(_put_on_loop, evidence_id)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("call_soon_threadsafe failed, defer: %s (%s)", evidence_id, exc)

    if evidence_id not in _deferred:
        _deferred.append(evidence_id)
    logger.info("enqueue deferred (no event loop): %s", evidence_id)


def flush_deferred() -> int:
    """把 deferred 刷进真实队列（须在事件循环内）。返回刷入条数。"""
    global _deferred
    if not _deferred:
        return 0
    ids = list(_deferred)
    _deferred = []
    q = ensure_worker()
    n = 0
    for eid in ids:
        try:
            q.put_nowait(eid)
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("flush_deferred put failed: %s (%s)", eid, exc)
            if eid not in _deferred:
                _deferred.append(eid)
    if n:
        logger.info("intelligence flush_deferred enqueued %d", n)
    return n


async def _worker() -> None:
    """消费队列：调 extractor 解析；失败不影响队列。攒 20 条 succeeded 自动出报告。"""
    global _succeeded_since_report, _report_running
    from services.intelligence import extractor

    while True:
        evidence_id = await _queue.get()
        try:
            result = await extractor.analyze_evidence(evidence_id)
            if result.get("status") == "succeeded":
                _succeeded_since_report += 1
                if _succeeded_since_report >= AUTO_REPORT_THRESHOLD and not _report_running:
                    _report_running = True
                    _succeeded_since_report = 0
                    asyncio.create_task(_auto_report())
        except asyncio.CancelledError:  # noqa: PERF203
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("analyze failed (unexpected): %s: %s", evidence_id, exc)
        finally:
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


async def _auto_report() -> None:
    """攒够 20 条后自动生成周期报告（失败不影响队列）。"""
    global _report_running
    try:
        from services.intelligence.reasoning import generate_report

        report = await generate_report()
        logger.info(
            "auto report generated（攒 20 条触发）：%d 维度，%d 行动",
            len(report.get("gap_matrix") or []),
            len(report.get("actions") or []),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto report failed: %s", exc)
    finally:
        _report_running = False


async def recover_pending() -> int:
    """启动/手动恢复：flush deferred + 把无 succeeded extraction 的 evidence 重新入队。返回入队数。"""
    from services.intelligence import repo

    n = flush_deferred()
    pending = repo.list_evidence_pending()
    for ev in pending:
        enqueue(ev["id"])
        n += 1
    if n:
        logger.info("intelligence recover_pending enqueued %d", n)
    return n


async def snapshot() -> dict:
    """解析队列实时快照（succeeded/failed/running/total/queue_size）——run-status 进度用。"""
    from sqlalchemy import func

    from app.models.geo_models import GeoExtraction, SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        rows = (
            db.query(GeoExtraction.status, func.count(GeoExtraction.id))
            .group_by(GeoExtraction.status)
            .all()
        )
    stats: dict = {"succeeded": 0, "failed": 0, "running": 0, "total": 0}
    for st, c in rows:
        stats[st if st in stats else "running"] = c
    stats["total"] = stats["succeeded"] + stats["failed"] + stats["running"]
    stats["queue_size"] = _queue.qsize() if _queue is not None else 0
    stats["deferred"] = len(_deferred)
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
