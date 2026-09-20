"""LLM 对战（自由辩论 + AI 裁判）

蓝本：GEO优化系统 llm-battle 的自由辩论模式（多轮 + 裁判）。
模式：rounds=1 单轮对比；rounds>1 多轮辩论（每轮把前几轮回答喂给各引擎辩论）；
judge 开启时用 GEO 专用模型裁判点评。
（两两对决/锦标赛/协作模式第一版不搬——偏娱乐，价值密度低。）
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import ok, err

router = APIRouter(prefix="/api/v1/battle")


class BattleIn(BaseModel):
    question: str
    rounds: int = 2  # 1 = 单轮对比，2-3 = 多轮辩论
    judge: bool = True


@router.post("")
async def battle(payload: BattleIn):
    from adapters.engines import list_engines, engine_api_key, ask
    from adapters.llm import chat, LLMNotConfiguredError, LLMError

    if not payload.question.strip():
        return err("empty_question", "请先输入问题")
    rounds = max(1, min(payload.rounds, 3))

    configured = [e for e in list_engines() if await engine_api_key(e["id"])]
    if not configured:
        return err("no_engines_configured", "还没有配置任何引擎 Key：请到 配置中心 填写")

    rounds_data = []
    prev_summary = ""
    for rnd in range(1, rounds + 1):
        round_results = []
        for e in configured:
            if rnd == 1:
                q = payload.question
            else:
                q = (
                    f"{payload.question}\n\n"
                    f"【前几轮各 AI 的回答摘要（辩论背景）】\n{prev_summary}\n\n"
                    f"这是第 {rnd} 轮辩论。请基于你的专业判断继续作答：可以补充、反驳或深化前面的观点。"
                    "保持简洁（400 字内）。"
                )
            try:
                answer = await ask(e["id"], q, max_tokens=900)
            except Exception as ex:  # noqa: BLE001
                answer = f"（调用失败：{ex}）"
            round_results.append({"engine_id": e["id"], "engine_name": e["name"], "answer": answer})
        rounds_data.append({"round": rnd, "results": round_results})
        prev_summary = "\n".join(
            f"{r['engine_name']}：{r['answer'][:280]}" for r in round_results
        )

    judge = None
    if payload.judge:
        last = rounds_data[-1]["results"]
        judge_prompt = (
            "你是 AI 对战裁判。下面是一道问题及多个 AI 的回答，请点评：\n"
            "1) 谁的回答更准确、更全面、更符合用户需求（说明理由）\n"
            "2) 回答之间有哪些分歧点、哪个更可信\n"
            "3) 给用户的最终结论（简短、可直接采用）\n\n"
            f"问题：{payload.question}\n\n回答：\n"
            + "\n".join(f"【{r['engine_name']}】\n{r['answer']}" for r in last)
        )
        try:
            judge = await chat(judge_prompt, max_tokens=900)
        except (LLMNotConfiguredError, LLMError):
            judge = None  # 裁判模型未配置时跳过点评

    return ok(
        {
            "question": payload.question,
            "rounds": rounds_data,
            "judge": judge,
            "judge_skipped": payload.judge and judge is None,
        }
    )
