import { useEffect, useState } from 'react'
import { geoGet } from './geo-api'
import { GeoCardShell, GeoError, GeoLoading } from './shared'

export interface MonitorAnswer {
  ts: string
  monitor_id: string
  item_type: string
  query: string
  engine: string
  mentioned: boolean
  rank_est: number | null
  sentiment: string
  snippet: string
}

interface SentimentOverview {
  total: number
  positive: number
  negative: number
  neutral: number
  pos_pct: number
  neg_pct: number
  neu_pct: number
}

interface SentimentResult {
  overview: SentimentOverview | null
  trend: Array<{ date: string; positive: number; negative: number; neutral: number }>
  questions: string[]
  top_words: string[]
  negative_samples: string[]
}

type ReportTab = 'answers' | 'sentiment' | 'citations' | 'sources'

/** 推荐位置分级（按排名估计）：1=第一推荐 2-3=强推荐 4-6=普通 其余=顺带提及；未提及=未提及 */
function positionOf(a: { mentioned: boolean; rank_est: number | null }): { label: string; cls: string } {
  if (!a.mentioned) return { label: '未提及', cls: 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-faint)]' }
  if (a.rank_est === 1) return { label: '第一推荐', cls: 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-foreground)]' }
  if ((a.rank_est ?? 99) <= 3) return { label: '强推荐', cls: 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-foreground)]' }
  if ((a.rank_est ?? 99) <= 6) return { label: '普通推荐', cls: 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-muted)]' }
  return { label: '顺带提及', cls: 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-faint)]' }
}

/** 监测报告卡（拆自原监测卡后半）：AI 回答 + 情绪分析 + 引用 + 来源，维度 tab 切换 */
export function GeoMonitorReportCard() {
  const [tab, setTab] = useState<ReportTab>('answers')
  const [answers, setAnswers] = useState<MonitorAnswer[]>([])
  const [itemTypes, setItemTypes] = useState<string[]>(['all'])
  const [answerType, setAnswerType] = useState('all')
  const [sentiment, setSentiment] = useState<SentimentResult | null>(null)
  const [citations, setCitations] = useState<Array<Record<string, unknown>>>([])
  const [sources, setSources] = useState<Array<Record<string, unknown>>>([])
  const [sourceNote, setSourceNote] = useState('')
  const [reasons, setReasons] = useState<{ reasons: Array<{ query: string; engine: string; snippet: string }>; missing_evidence: string[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [a, m] = await Promise.all([
        geoGet<{ answers: MonitorAnswer[] }>(`/monitor/answers?limit=20${answerType !== 'all' ? `&item_type=${answerType}` : ''}`),
        geoGet<{ items: Array<{ monitor_id: string; type: string }> }>('/monitor/items'),
      ])
      setAnswers(a.answers ?? [])
      const types = ['all', ...new Set((m.items ?? []).map((i) => i.type))]
      setItemTypes(types)
    } catch (e) {
      setError(e instanceof Error ? e.message : '监测报告加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answerType])

  // 维度数据按 tab 懒加载
  useEffect(() => {
    if (tab === 'answers' && !reasons) {
      geoGet<{ reasons: Array<{ query: string; engine: string; snippet: string }>; missing_evidence: string[] }>('/cognition/reasons')
        .then(setReasons)
        .catch(() => undefined)
    }
    if (tab === 'sentiment' && !sentiment) {
      geoGet<SentimentResult>('/monitor/sentiment')
        .then(setSentiment)
        .catch(() => undefined)
    }
    if (tab === 'citations' && citations.length === 0) {
      geoGet<{ items: Array<Record<string, unknown>> }>('/monitor/citations')
        .then((d) => setCitations(d.items ?? []))
        .catch(() => undefined)
    }
    if (tab === 'sources' && sources.length === 0) {
      geoGet<{ items: Array<Record<string, unknown>>; note?: string }>('/cognition/sources')
        .then((d) => {
          setSources(d.items ?? [])
          setSourceNote(d.note ?? '')
        })
        .catch(() => undefined)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  if (loading) return <GeoLoading text="监测报告加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  const tabs: Array<{ key: ReportTab; label: string }> = [
    { key: 'answers', label: 'AI 回答' },
    { key: 'sentiment', label: '情绪分析' },
    { key: 'citations', label: '引用' },
    { key: 'sources', label: '来源' },
  ]

  const ov = sentiment?.overview

  return (
    <GeoCardShell title="📈 监测报告" className="sm:flex-1">
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
              tab === t.key
                ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-muted)] hover:border-[var(--yayu-muted)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'answers' ? (
        <>
          {/* 推荐理由/证据链（AI 为什么提到我们） */}
          {reasons && (reasons.reasons.length > 0 || reasons.missing_evidence.length > 0) ? (
            <div className="mb-1.5 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-1.5">
              <div className="mb-1 text-[11px] font-medium text-[var(--yayu-muted)]">🧠 AI 为什么提到你（真实回答样本）</div>
              {reasons.reasons.length > 0 ? (
                <div className="space-y-1">
                  {reasons.reasons.slice(0, 3).map((r, i) => (
                    <div key={i} className="rounded-md bg-[var(--yayu-surface-raised)] px-2 py-1">
                      <div className="flex items-center justify-between gap-2 text-[10.5px]">
                        <span className="truncate font-medium text-[var(--yayu-foreground)]">{r.query}</span>
                        <span className="shrink-0 text-[var(--yayu-faint)]">{r.engine}</span>
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">{r.snippet}</p>
                    </div>
                  ))}
                </div>
              ) : null}
              {reasons.missing_evidence.length > 0 ? (
                <p className="pt-1 text-[10.5px] text-[var(--yayu-faint)]">
                  缺失证据：{reasons.missing_evidence.join('、')}——资料里有但 AI 回答没引用
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            {itemTypes.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setAnswerType(t)}
                className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
                  answerType === t
                    ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                    : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-muted)] hover:border-[var(--yayu-muted)]'
                }`}
              >
                {t === 'all' ? '全部' : t}
              </button>
            ))}
          </div>
          {answers.length === 0 ? (
            <p className="text-[11px] text-[var(--yayu-faint)]">暂无监测回答，先运行一次监测。</p>
          ) : (
            <div className="space-y-1.5">
              {answers.slice(0, 10).map((a, index) => {
                const pos = positionOf(a)
                return (
                <div key={index} className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-surface-raised)] px-2 py-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[12px] text-[var(--yayu-foreground)]">{a.query}</span>
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${pos.cls}`}>{pos.label}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px] text-[var(--yayu-faint)]">
                    <span>{a.engine}</span>
                    {a.rank_est !== null ? <span>· 排名 {a.rank_est}</span> : null}
                    <span>· {a.sentiment}</span>
                  </div>
                  {a.snippet ? (
                    <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-[var(--yayu-muted)]">{a.snippet}</div>
                  ) : null}
                </div>
                )
              })}
            </div>
          )}
        </>
      ) : null}

      {tab === 'sentiment' ? (
        ov && ov.total > 0 ? (
          <div className="space-y-2">
            <div className="flex h-2 w-full overflow-hidden rounded-full bg-[var(--yayu-surface-raised)]">
              <div className="bg-[var(--yayu-foreground)]" style={{ width: `${ov.pos_pct}%` }} />
              <div className="bg-[var(--yayu-border)]" style={{ width: `${ov.neu_pct}%` }} />
              <div className="bg-[var(--yayu-surface-raised)]" style={{ width: `${ov.neg_pct}%` }} />
            </div>
            <div className="flex justify-between text-[10px] text-[var(--yayu-muted)]">
              <span>正面 {ov.positive}（{ov.pos_pct}%）</span>
              <span>中性 {ov.neutral}（{ov.neu_pct}%）</span>
              <span>负面 {ov.negative}（{ov.neg_pct}%）</span>
            </div>
            {sentiment?.top_words && sentiment.top_words.length > 0 ? (
              <div className="text-[11px] text-[var(--yayu-muted)]">
                高频词：{sentiment.top_words.slice(0, 8).join('、')}
              </div>
            ) : null}
            {sentiment?.negative_samples && sentiment.negative_samples.length > 0 ? (
              <div className="space-y-1">
                <div className="text-[11px] font-medium text-[var(--yayu-muted)]">负面样本</div>
                {sentiment.negative_samples.slice(0, 3).map((s, i) => (
                  <div key={i} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[11px] text-[var(--yayu-muted)]">
                    {s}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <p className="text-[11px] text-[var(--yayu-faint)]">暂无情绪数据，先运行监测。</p>
        )
      ) : null}

      {tab === 'citations' ? (
        citations.length === 0 ? (
          <p className="text-[11px] text-[var(--yayu-faint)]">暂无引用记录。</p>
        ) : (
          <div className="space-y-1.5">
            {citations.map((c, index) => (
              <div key={index} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[11px] text-[var(--yayu-muted)]">
                {String(c.title ?? c.url ?? c.query ?? '')}
              </div>
            ))}
          </div>
        )
      ) : null}

      {tab === 'sources' ? (
        sources.length === 0 ? (
          <p className="text-[11px] text-[var(--yayu-faint)]">{sourceNote || '暂无来源数据，先运行监测（监测回答含来源链接后自动统计）。'}</p>
        ) : (
          <div className="space-y-1.5">
            {/* 来源贡献饼图（CSS conic-gradient，灰阶色块，无依赖） */}
            <div className="flex items-center gap-4">
              <div
                className="size-24 shrink-0 rounded-full"
                style={{
                  background: `conic-gradient(${sources
                    .map((s, i) => {
                      const share = Number(s.share ?? 0)
                      const from = sources.slice(0, i).reduce((acc, x) => acc + Number(x.share ?? 0), 0)
                      const colors = ['#111827', '#6b7280', '#9ca3af', '#d1d5db', '#374151', '#4b5563', '#e5e7eb', '#1f2937']
                      return `${colors[i % colors.length]} ${from}% ${from + share}%`
                    })
                    .join(', ')})`,
                }}
              />
              <div className="min-w-0 flex-1 space-y-1">
                {sources.map((s, i) => {
                  const colors = ['#111827', '#6b7280', '#9ca3af', '#d1d5db', '#374151', '#4b5563', '#e5e7eb', '#1f2937']
                  return (
                    <div key={i} className="flex items-center gap-2 text-[11px]">
                      <span className="size-2 shrink-0 rounded-full" style={{ background: colors[i % colors.length] }} />
                      <span className="w-16 shrink-0 text-[var(--yayu-foreground)]">{String(s.label ?? '')}</span>
                      <span className="text-[var(--yayu-faint)]">{String(s.count ?? '')} 处</span>
                      <span className="ml-auto text-[var(--yayu-muted)]">{String(s.share ?? '')}%</span>
                    </div>
                  )
                })}
              </div>
            </div>
            {sourceNote ? <p className="text-[9.5px] text-[var(--yayu-faint)]">{sourceNote}</p> : null}
          </div>
        )
      ) : null}
    </GeoCardShell>
  )
}
