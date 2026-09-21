import { useState } from 'react'
import { Button } from '@yayu/ui'
import { Swords } from 'lucide-react'
import { geoPost, type GeoBattleResult } from './geo-api'
import { GeoCardShell, GeoError } from './shared'

/**
 * AI 对战 —— 同一个问题同时问部署里每一个模型，可多轮辩论，最后由裁判模型点评。
 *
 * 为什么界面上要写「几个模型 = 这个部署登记了几个」：引擎是谁、有几个是企业部署的
 * 事（Owner 2026-09-21「GEO 不再写死 6 个」／GEO 不持凭据）。一个都没登记时后端回
 * `no_engines_configured`，这里如实把它说出来，不显示一个假的对战结果。
 *
 * 辩论烧的是企业的模型额度，所以轮数在这里是显式的（1 = 单轮对比，2–3 = 多轮辩论），
 * 默认 2 轮，不替用户加码。
 */
export function GeoBattleCard() {
  const [question, setQuestion] = useState('')
  const [rounds, setRounds] = useState(2)
  const [judge, setJudge] = useState(true)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<GeoBattleResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    const q = question.trim()
    if (!q || running) return
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const d = await geoPost<GeoBattleResult>('/battle', { question: q, rounds, judge })
      setResult(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : '对战失败')
    } finally {
      setRunning(false)
    }
  }

  return (
    <GeoCardShell title="⚔️ AI 对战">
      <p className="text-[11px] leading-snug text-[var(--yayu-muted)]">
        同一个问题问这个部署登记的每一个模型；多轮时后一轮带着前几轮的摘要继续辩，最后可选裁判点评。
      </p>

      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        rows={2}
        placeholder="要拿去问各个模型的问题"
        className="w-full resize-y rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1.5 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
      />

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-[var(--yayu-muted)]">
        <label className="flex items-center gap-1.5">
          轮数
          <select
            value={rounds}
            onChange={(e) => setRounds(Number(e.target.value))}
            className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-1.5 py-0.5 text-[11px] text-[var(--yayu-foreground)] outline-none"
          >
            <option value={1}>1（单轮对比）</option>
            <option value={2}>2（多轮辩论）</option>
            <option value={3}>3（多轮辩论）</option>
          </select>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" checked={judge} onChange={(e) => setJudge(e.target.checked)} className="size-3.5" />
          裁判点评
        </label>
        <Button variant="primary" size="sm" disabled={running || !question.trim()} onClick={() => void run()}>
          <Swords className="size-3.5" /> {running ? '对战进行中…' : '开战'}
        </Button>
      </div>

      {error ? <GeoError message={error} onRetry={() => void run()} /> : null}

      {running ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">
          正在按顺序问每个模型，多轮 + 裁判会慢一些；这一页别关。
        </p>
      ) : null}

      {result
        ? result.rounds.map((round) => (
            <div key={round.round} className="space-y-1">
              <div className="text-[11px] font-semibold text-[var(--yayu-foreground)]">
                第 {round.round} 轮 · {round.results.length} 个模型作答
              </div>
              {round.results.map((r) => (
                <div
                  key={`${round.round}-${r.engine_id}`}
                  className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1"
                >
                  <div className="text-[11px] text-[var(--yayu-muted)]">{r.engine_name}</div>
                  <div className="mt-0.5 max-h-40 overflow-y-auto whitespace-pre-wrap text-[11.5px] leading-relaxed text-[var(--yayu-foreground)]">
                    {r.answer}
                  </div>
                </div>
              ))}
            </div>
          ))
        : null}

      {result ? (
        <div className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-surface-raised)] px-2 py-1.5">
          <div className="text-[11px] font-semibold text-[var(--yayu-foreground)]">裁判点评</div>
          <div className="mt-0.5 whitespace-pre-wrap text-[11.5px] leading-relaxed text-[var(--yayu-muted)]">
            {result.judge
              ? result.judge
              : result.judge_skipped
                ? '这个部署没有配裁判模型，本次没有点评（不是「点评了没意见」）。'
                : '没有请裁判。'}
          </div>
        </div>
      ) : null}
    </GeoCardShell>
  )
}
