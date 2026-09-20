"""Intelligence 分析引擎 — Extractor（条级解析）

输入：geo_evidence（raw_text + context）
流程：LLM（adapters/llm.chat，GEO 专用模型）→ 6.1 JSON → 校验 quote → 写
      geo_extraction（升 version）+ 展开 brand_mention。
失败重试 ≤2 → status=failed。
"""
import json
import logging
from datetime import datetime, timezone

from services.intelligence import repo
from services.intelligence.prompts import EXTRACTOR_PROMPT, EXTRACTOR_SYSTEM, PROMPT_VERSION

logger = logging.getLogger("eios.intelligence.extractor")

MAX_RETRIES = 2


def _parse_json(text: str) -> dict | None:
    """容错解析：剥 ```json 代码块 / 前后杂质。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        # 去掉首尾代码块标记
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # 尝试从第一个 { 到最后一个 }
        s, e = t.find("{"), t.rfind("}")
        if 0 <= s < e:
            try:
                return json.loads(t[s : e + 1])
            except json.JSONDecodeError:
                return None
        return None


def _expand_mentions(evidence: dict, analysis: dict) -> list[dict]:
    """从 analysis_json 展开 brand_mention 行（缺 quote 的由 repo 丢弃）。"""
    mentions: list[dict] = []
    ev_id = evidence["id"]

    for b in analysis.get("brands") or []:
        name = (b.get("name") or "").strip()
        if not name:
            continue
        for r in b.get("reasons") or []:
            mentions.append(
                {
                    "evidence_id": ev_id,
                    "brand_name": name,
                    "mention_type": "reason",
                    "factor": r.get("factor"),
                    "evidence_quote": r.get("evidence_quote"),
                    "confidence": r.get("confidence"),
                }
            )
        for t in b.get("trust_signals") or []:
            mentions.append(
                {
                    "evidence_id": ev_id,
                    "brand_name": name,
                    "mention_type": "trust",
                    "factor": t.get("signal"),
                    "evidence_quote": t.get("evidence_quote"),
                    "confidence": t.get("confidence"),
                }
            )

    sb = analysis.get("self_brand") or {}
    if sb.get("mentioned") and not sb.get("recommended"):
        mentions.append(
            {
                "evidence_id": ev_id,
                "brand_name": sb.get("name") or evidence.get("subject_company") or "unknown",
                "mention_type": "missing",
                "factor": "__missing__",  # 评审钉死：missing 无维度词时固定占位
                "evidence_quote": sb.get("evidence_quote"),
                "confidence": None,
            }
        )
    return mentions


async def analyze_evidence(evidence_id: str) -> dict:
    """解析单条 evidence（幂等：已有 succeeded 最新版则跳过）。"""
    evidence = repo.get_evidence(evidence_id)
    if not evidence:
        return {"evidence_id": evidence_id, "status": "not_found"}

    # 幂等：最新 succeeded 直接返回
    latest = repo.latest_extraction(evidence_id)
    if latest and latest.get("status") == "succeeded":
        return {"evidence_id": evidence_id, "status": "already_succeeded", "version": latest.get("version")}

    from adapters.llm import LLMNotConfiguredError, chat  # 延迟 import：避免循环

    ctx = evidence.get("context_json") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except json.JSONDecodeError:
            ctx = {}
    source_type = evidence.get("source_type") or "ai_answer"
    capture_mode = ctx.get("capture_mode") or ("search_result" if source_type == "research_harvest" else "ai_answer")
    question = ctx.get("question") or ""
    if source_type == "research_harvest":
        question = (
            f"{question or '外网补搜'}｜注意：原文是搜索引擎摘要（capture_mode={capture_mode}），"
            "不是网页正文或消费者评论；只抽取摘要里出现的原句"
        )
    engine = ctx.get("engine") or evidence.get("platform") or ""
    competitors = ", ".join(ctx.get("competitors") or []) or "无"
    raw_text = (evidence.get("raw_text") or "").strip()

    last_error = ""
    version = repo.next_version(evidence_id)
    model_name = ""

    # running 占位（可查进度；后续 succeeded/failed 更新同一行，不占新 version）
    run_row = repo.insert_extraction(
        {
            "evidence_id": evidence_id,
            "source_type": evidence.get("source_type", "ai_answer"),
            "subject_company": evidence.get("subject_company", ""),
            "status": "running",
            "version": version,
            "question": question,
            "engine": engine,
            "monitor_id": ctx.get("monitor_id"),
        }
    )
    run_id = run_row.get("id")

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            # 长文本是 deepseek-v4-flash 空输出的诱因：重试时逐级截短（800→500 字）
            raw = raw_text
            if attempt > 1:
                raw = raw_text[:800]
            if attempt > 2:
                raw = raw_text[:500]
            prompt = EXTRACTOR_PROMPT.format(
                question=question or "（无问题记录）",
                engine=engine or "unknown",
                subject_company=evidence.get("subject_company") or "",
                competitors=competitors,
                raw_text=raw,
                evidence_id=evidence_id,
            )
            text = await chat(
                prompt,
                system=EXTRACTOR_SYSTEM,
                max_tokens=8000,  # 4000 会截断长输出（多 brand JSON）→ 解析失败
                response_format={"type": "json_object"},  # 推理模型长 prompt 偶发空 content，json 模式 + 截断双保险
            )
            analysis = _parse_json(text)
            if not analysis:
                raise ValueError(f"LLM 输出不是合法 JSON: {text[:300]!r}")
            analysis["evidence_id"] = evidence_id
            analysis["source_type"] = source_type
            analysis["capture_mode"] = capture_mode

            # P2（08-11）：行业/推荐类问题（"有哪些推荐/哪个好/怎么选"）AI 回答常不点名品牌——
            # 无提及不判失败，存为「认知证据」（analysis 保留全文 + mentions_empty 标注，前端可溯源展示）。
            # 品牌探针（"亚宇臻隆科技是什么？"）正常情况必点名 → mentions 有，不受影响；
            # 异常情况（LLM 诚实判断无提及）也保留原文而非整条作废。
            mentions = _expand_mentions(evidence, analysis)
            n_mentions = repo.insert_mentions(mentions)
            if not mentions:
                analysis["mentions_empty"] = True

            model_name = f"geo-llm-v{PROMPT_VERSION}"
            rec = repo.update_extraction(
                run_id,
                status="succeeded",
                model=model_name,
                analysis_json=analysis,
            )
            logger.info("extracted %s v%s mentions=%d", evidence_id, version, n_mentions)
            return {"evidence_id": evidence_id, "status": "succeeded", "version": version, "mentions": n_mentions}
        except LLMNotConfiguredError as exc:
            last_error = str(exc)
            break  # 配置缺失，重试无意义
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.warning("analyze attempt %d/%d failed: %s: %s", attempt, MAX_RETRIES + 1, evidence_id, last_error)
            if attempt <= MAX_RETRIES:
                import asyncio

                await asyncio.sleep(1.5 * attempt)

    # 全失败 → 更新同一行为 failed（保留 running 行的版本记录错误）
    repo.update_extraction(
        run_id,
        status="failed",
        model=model_name,
        error=last_error,
    )
    logger.error("extract failed %s: %s", evidence_id, last_error)
    return {"evidence_id": evidence_id, "status": "failed", "error": last_error}
