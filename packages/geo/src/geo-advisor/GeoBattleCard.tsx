import { useState } from 'react'
import { Button } from '@yayu/ui'
import { Scale } from 'lucide-react'
import { geoPost, type GeoBattleResult } from './geo-api'
import { GeoCardShell, GeoError } from './shared'
import { ALL_SUBJECTS, MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'

/**
 * 模型对比 —— 同一个问题同时问部署里每一个模型，可做多轮对比，最后生成一份总结。
 *
 * 为什么界面上要写「几个模型 = 这个部署登记了几个」：引擎是谁、有几个是企业部署的
 * 事（Owner 2026-09-21「GEO 不再写死 6 个」／GEO 不持凭据）。一个都没登记时后端回
 * `no_engines_configured`，这里如实把它说出来，不显示一个假的对比结果。
 *
 * 多轮对比会消耗企业的模型额度，所以轮数在这里是显式的（1 = 一次回答，2–3 = 深入对比），
 * 默认 2 轮，不替用户加码。
 */
export function GeoBattleCard() {
  const [question, setQuestion] = useState('')
  const [rounds, setRounds] = useState(2)
  const [judge, setJudge] = useState(true)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<GeoBattleResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { value: subjectValue, subject } = useMonitorSubject()

  const run = async () => {
    const q = question.trim()
    if (!q || running) return
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const d = await geoPost<GeoBattleResult>('/battle', {
        question: q,
        rounds,
        judge,
        monitor_id: subjectValue && subjectValue !== ALL_SUBJECTS ? subjectValue : subjectValue || null,
      })
      setResult(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : '模型对比失败')
    } finally {
      setRunning(false)
    }
  }

  return (
    <GeoCardShell title="模型对比实验台" className="geo-battle-workbench">
      <p className="text-[11px] leading-snug text-[var(--yayu-muted)]">
        同一个问题会发给当前部署登记的每一个模型；可以进行多轮对比，最后生成一份差异总结。
        这是一次性实验，不会改变监测任务，也不会写入监测统计。
      </p>

      <MonitorSubjectPicker note="只标记本次即时实验的观察主体；回答不会自动变成监测结论或企业事实。" />
      <p className="text-[11px] leading-snug text-[var(--yayu-faint)]">
        {subject
          ? `本次实验主体：${subject.name}。模型原话仍需回到监测证据核对。`
          : '当前按账号汇总运行；如果问题涉及某个企业，请先选择对应监测主体。'}
      </p>

      <textarea
        aria-label="对比问题"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        rows={2}
        placeholder="要拿去问各个模型的问题"
        className="w-full resize-y rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1.5 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
      />

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-[var(--yayu-muted)]">
        <label className="flex items-center gap-1.5">
          对比轮数
          <select
            value={rounds}
            onChange={(e) => setRounds(Number(e.target.value))}
            className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-1.5 py-0.5 text-[11px] text-[var(--yayu-foreground)] outline-none"
          >
            <option value={1}>1（一次回答）</option>
            <option value={2}>2（两轮对比）</option>
            <option value={3}>3（深入对比）</option>
          </select>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" checked={judge} onChange={(e) => setJudge(e.target.checked)} className="size-3.5" />
          生成对比总结
        </label>
        <Button variant="primary" size="sm" disabled={running || !question.trim()} onClick={() => void run()}>
          <Scale className="size-3.5" /> {running ? '对比进行中…' : '开始对比'}
        </Button>
      </div>

      {error ? <GeoError message={error} onRetry={() => void run()} /> : null}

      {running ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">
          正在按顺序询问每个模型，多轮对比会慢一些；这一页别关。
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
          <div className="mb-1 text-[10.5px] text-[var(--yayu-faint)]">
            范围：{result.scope?.name || (result.scope?.mode === 'all' ? '全部主体' : '未指定主体')} · 一次性即时实验
          </div>
          <div className="text-[11px] font-semibold text-[var(--yayu-foreground)]">对比总结</div>
          <div className="mt-0.5 whitespace-pre-wrap text-[11.5px] leading-relaxed text-[var(--yayu-muted)]">
            {result.judge
              ? result.judge
              : result.judge_skipped
                ? '这个部署没有配置总结模型，本次只展示各模型原始回答。'
                : '未生成对比总结。'}
          </div>
        </div>
      ) : null}
    </GeoCardShell>
  )
}
