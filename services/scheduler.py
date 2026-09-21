"""GEO 定时任务（APScheduler）：每日自动跑问题池批量监测

- 每天 09:00 读取问题池 → 批量监测 → 存历史（统计页趋势自动积累）
- 问题池为空或未配置引擎时跳过（不报错）
- 可通过 GEO_SCHEDULE_HOUR / GEO_SCHEDULE_MINUTE 环境变量调整时间
"""
import hashlib
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("geo.scheduler")

_scheduler: AsyncIOScheduler | None = None


async def _for_each_tenant(job, label: str) -> None:
    """每个 GEO 柜跑一遍（无柜时仍跑默认柜，兼容空库）。"""
    from app.services.store import list_tenant_ids, set_tenant

    tenants = list_tenant_ids() or ["tenant_corp_01"]
    for tid in tenants:
        set_tenant(tid)
        try:
            await job()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[scheduler] %s 租户 %s 失败：%s", label, tid, str(exc)[:150])


async def _daily_monitor_job() -> None:
    await _for_each_tenant(_daily_monitor_one, "监测")


async def _daily_monitor_one() -> None:
    """每日批量监测任务（0.3：遍历 active 任务按 schedule 跑，回退全部 active items）"""
    from app.api.v1.monitor import _load_pool, run_batch_items, _load_items, _load_tasks, _run_task_items
    from adapters.engines import EngineFaceError, list_engines
    from app.services.store import current_tenant

    # 引擎清单来自部署登记的模型（Owner 2026-09-21）。一个都没有（或入口接不上）时
    # 如实说明原因再跳过，不假装跑过一轮。
    try:
        configured = await list_engines()
    except EngineFaceError as exc:
        logger.info("[scheduler] 统一模型入口接不上，跳过每日监测：%s", str(exc)[:150])
        return
    if not configured:
        logger.info("[scheduler] 这个部署还没有登记任何模型，跳过每日监测")
        return

    logger.info("[scheduler] 监测租户 %s", current_tenant())
    tasks = [t for t in _load_tasks() if t.get("status") == "active"]
    if tasks:
        # weekly 任务只在周一跑
        from datetime import datetime

        weekday = datetime.now().weekday()  # 0=周一
        ran = 0
        failed = 0
        for t in tasks:
            if t.get("schedule") == "weekly" and weekday != 0:
                continue
            logger.info("[scheduler] 任务「%s」开始", t.get("name"))
            # 2026-08-15 修复：per-task 隔离——单个任务异常不吞掉当天其余任务
            try:
                await _run_task_items(t)
                ran += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.exception("[scheduler] 任务「%s」失败：%s", t.get("name"), exc)
        logger.info("[scheduler] 每日监测完成：%d 个任务成功，%d 个失败", ran, failed)
        return

    active_items = [i for i in _load_items() if i.get("status") == "active"]
    if active_items:
        logger.info("[scheduler] 每日监测开始（无任务，跑全部 active 对象）：%d 个", len(active_items))
        await run_batch_items(active_items)
        logger.info("[scheduler] 每日监测完成")
        return

    pool = _load_pool()
    questions = pool.get("questions") or []
    if not questions:
        logger.info("[scheduler] 问题池为空且无监测对象/任务，跳过每日监测")
        return
    logger.info("[scheduler] 每日监测开始（问题池回退）：%d 个问题", len(questions))
    # P1-1（Cursor 验收）：池回退也转临时 item → 统一 run_batch_items，不留旧执行路径
    temp_items = [
        {
            "monitor_id": f"tmp_{hashlib.md5(q.encode()).hexdigest()[:8]}",
            "type": "question",
            "config_json": {"query": q},
            "temporary": True,
            "entity": pool.get("company_name"),
        }
        for q in questions
    ]
    await run_batch_items(temp_items, pool.get("company_name"))
    logger.info("[scheduler] 每日监测完成")


async def _daily_intel_job() -> None:
    await _for_each_tenant(_daily_intel_one, "Intelligence")


async def _daily_intel_one() -> None:
    """每日 Intelligence 周期报告（监测跑完后出报告；无数据/无 LLM 时静默跳过）。"""
    try:
        from app.services.store import current_tenant
        from services.intelligence.reasoning import generate_report

        report = await generate_report(tenant=current_tenant())
        logger.info("[scheduler] Intelligence 报告生成：%d 维度，%d 行动", len(report.get("gap_matrix") or []), len(report.get("actions") or []))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[scheduler] Intelligence 报告失败（不影响监测）: %s", str(exc)[:150])


async def _daily_distill_job() -> None:
    await _for_each_tenant(_daily_distill_one, "蒸馏")


async def _daily_distill_one() -> None:
    """每日蒸馏闭环（监测跑完后自动，幂等）：知识缺口 → 内容计划 → 内容机会。

    - detect_gaps：新问题 → Kernel 对照 → 缺口落库（existing_q 去重）
    - gen_plans：LLM 内容计划（target_question 去重）
    - gen_opportunities：规则内容机会补漏（target_question 去重）
    全链路幂等：重复跑不产生重复缺口/计划；任何一步失败不影响其他步骤和监测。
    """
    try:
        from app.api.v1 import distill as D

        # 等解析排空再蒸馏（每日监测刚跑完时解析队列可能还在后台）
        try:
            from services.intelligence import queue as Q

            await Q.wait_drained(timeout=1200)
        except Exception:  # noqa: BLE001
            pass
        g = await D.detect_gaps(limit=30)
        gaps_added = (g.get("data") or g).get("added", 0) if g.get("ok") else 0
        p = await D.gen_plans(limit=15)
        plans_added = (p.get("data") or p).get("added", 0) if p.get("ok") else 0
        o = await D.gen_opportunities(limit=15)
        opps_added = (o.get("data") or o).get("added", 0) if o.get("ok") else 0
        logger.info(
            "[scheduler] 蒸馏闭环完成：新增缺口 %d、计划 %d、机会 %d",
            gaps_added, plans_added, opps_added,
        )
        # 2026-08-15：自动生产闭环——planned 计划自动生成内容存资产（发布仍人工）；
        # 验证在下次监测后（verify_production 幂等，可每日跑）
        try:
            from services.loop import auto_production, verify_production

            prod = await auto_production(limit=3)
            ver = verify_production()
            logger.info(
                "[scheduler] 生产闭环：生产 %d、跳过 %d、错误 %d；验证通过 %d、待验证 %d",
                len(prod.get("produced") or []), len(prod.get("skipped") or []),
                len(prod.get("errors") or []), len(ver.get("verified") or []),
                len(ver.get("pending") or []),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[scheduler] 生产闭环失败（不影响监测）: %s", str(exc)[:150])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[scheduler] 蒸馏闭环失败（不影响监测）: %s", str(exc)[:150])


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    try:
        hour = int(os.environ.get("GEO_SCHEDULE_HOUR", "9"))
        minute = int(os.environ.get("GEO_SCHEDULE_MINUTE", "0"))
    except ValueError:
        hour, minute = 9, 0
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _daily_monitor_job,
        CronTrigger(hour=hour, minute=minute),
        id="daily_monitor",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Intelligence 每日报告（监测 09:00 跑完后 09:30 出报告；攒 20 条触发在 queue worker）
    def _plus_minutes(base_hour: int, base_minute: int, add: int) -> tuple[int, int]:
        """2026-08-15 修复：分钟进位到小时（原实现 minute+X ≥60 时只归 0 不 hour+1，
        导致 intel 可能早于 monitor 跑、取旧数据）。"""
        total = base_hour * 60 + base_minute + add
        return (total // 60) % 24, total % 60

    _intel_h, _intel_m = _plus_minutes(hour, minute, 30)
    _scheduler.add_job(
        _daily_intel_job,
        CronTrigger(hour=_intel_h, minute=_intel_m),
        id="daily_intel_report",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # 蒸馏闭环每日自动（监测 09:00 跑完后 09:10：缺口 → 计划 → 机会；幂等可重复跑）
    _dist_h, _dist_m = _plus_minutes(hour, minute, 10)
    _scheduler.add_job(
        _daily_distill_job,
        CronTrigger(hour=_dist_h, minute=_dist_m),
        id="daily_distill_loop",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    print(f"[scheduler] 已启动：每日 {hour:02d}:{minute:02d} 自动批量监测 + Intelligence 报告")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
