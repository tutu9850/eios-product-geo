import { useEffect, useMemo, useState } from 'react'
import { geoGet } from './geo-api'
import { GeoCardShell, GeoError, GeoFormattedAnswer, GeoLoading, monitorTypeText, sentimentText, shortDay, stripAnswerMarkdown } from './shared'

export interface MonitorAnswer {
  ts: string
  monitor_id: string
  batch_id?: string | null
  group_id?: string
  item_type: string
  query: string
  engine: string
  /** null = 该模型没有返回回答；false = 有回答但没有提到企业。 */
  mentioned: boolean | null
  /** `not_recognised` = 有回答但无法确认所说主体是不是目标企业。 */
  recognition?: 'recognised' | 'not_recognised' | 'not_mentioned' | string | null
  sentiment_status?: 'classified' | 'unknown' | 'not_applicable' | string | null
  rank_est: number | null
  sentiment: string
  snippet: string
  /** 模型回答全文（后端一直有返回；以前只渲染了 snippet，长回答看不到） */
  answer?: string
}

interface MonitorAnswerGroup {
  group_id: string
  monitor_id: string
  ts: string
  query: string
  item_type: string
  answers: Array<Omit<MonitorAnswer, 'monitor_id' | 'query' | 'ts' | 'item_type'>>
}
interface MonitorAnswerPage { groups?: MonitorAnswerGroup[]; answers?: MonitorAnswer[]; group_total?: number; page?: number; pages?: number }

interface SentimentOverview {
  total: number
  positive: number
  negative: number
  neutral: number
  pos_pct: number
  neg_pct: number
  neu_pct: number
}

/**
 * 2026-09-21：这两个字段的真实形状一直是**对象数组**（monitor.py `_aggregate_sentiment` 直接
 * 把聚合出来的 dict 丢出来），类型却写着 string[]。后果：负面样本直接当 React 子节点渲染 →
 * 整张监测报告卡崩掉（React error #31），高频词 join 出「[object Object]」。
 */
interface SentimentResult {
  scope?: { scope_required?: boolean; monitor_id?: string | null }
  unknown_count?: number
  overview: SentimentOverview | null
  trend: Array<{ date: string; positive: number; negative: number; neutral: number }>
  questions: string[]
  top_words: Array<{ word: string; count: number }>
  negative_samples: Array<{ question?: string; platform?: string; snippet?: string; ts?: string }>
}

type ReportTab = 'answers' | 'sentiment' | 'citations' | 'sources'

/**
 * 提及位置（2026-09-21 口径修正，Owner：「输出正常但不正确」）。
 *
 * `rank_est` 在后端的真实含义是**企业名第一次出现在回答的第几句话**（见 monitor.py 的
 * `_parse_answer`：「rank_est：企业名首次出现的句序号（按 [。！？\n] 切句），未提及 = None」）。
 * 它**不是** AI 给出的推荐排名，也不是「第几推荐」。原来这里按它分成
 * 「第一推荐／强推荐／普通推荐」，页面上就出现了「普通推荐 · 排名 6」这种看着正常、
 * 实际编出来的结论（模型根本没排过名）。现在只说这句话本身：提到了、在第几句提到。
 * 颜色仍按出现早晚分档，但只作为「提到得早/晚」的视觉提示。
 */
function positionOf(a: { mentioned: boolean | null; rank_est: number | null; recognition?: string | null }): { label: string; cls: string } {
  if (a.recognition === 'not_recognised') return { label: '无法确认企业主体', cls: 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-muted)]' }
  if (a.mentioned == null) return { label: '未获得回答', cls: 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-faint)]' }
  if (!a.mentioned) return { label: '未提及', cls: 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-faint)]' }
  const n = a.rank_est
  if (n == null) return { label: '提及（未记位置）', cls: 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-muted)]' }
  const cls = n <= 3 ? 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-foreground)]' : 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-muted)]'
  return { label: n === 1 ? '首句提及' : `第 ${n} 句提及`, cls }
}

function sampleSentiment(a: { sentiment: string; recognition?: string | null; sentiment_status?: string | null }): string {
  return a.recognition === 'not_recognised' || a.sentiment_status === 'unknown' ? '未判定' : sentimentText(a.sentiment)
}

/** 监测报告卡（拆自原监测卡后半）：AI 回答 + 情绪分析 + 引用 + 来源，维度 tab 切换 */
export function GeoMonitorReportCard() {
  const [tab, setTab] = useState<ReportTab>('answers')
  const [groups, setGroups] = useState<MonitorAnswerGroup[]>([])
  const [itemNames, setItemNames] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [groupTotal, setGroupTotal] = useState(0)
  const [selectedMonitorIds, setSelectedMonitorIds] = useState<string[]>([])
  const [itemTypes, setItemTypes] = useState<string[]>(['all'])
  const [answerType, setAnswerType] = useState('all')
  const [sentiment, setSentiment] = useState<SentimentResult | null>(null)
  const [citations, setCitations] = useState<Array<Record<string, unknown>>>([])
  const [sources, setSources] = useState<Array<Record<string, unknown>>>([])
  const [sourceNote, setSourceNote] = useState('')
  const [reasons, setReasons] = useState<{ reasons: Array<{ query: string; engine: string; snippet: string }>; missing_evidence: string[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState('')
  const [error, setError] = useState<string | null>(null)
  // 同一个问题的 6 家回答叠成一组：默认展开第一家，其余用平台按钮切换（Owner 2026-09-21）
  const [picked, setPicked] = useState<Record<string, string>>({})
  const [openFull, setOpenFull] = useState<Record<string, boolean>>({})

  const load = async (nextPage = 1, append = false) => {
    if (append) { setLoadingMore(true); setLoadMoreError('') }
    else { setLoading(true); setError(null) }
    try {
      const [a, m] = await Promise.all([
        geoGet<MonitorAnswerPage>(`/monitor/answers?page=${nextPage}&page_size=20${answerType !== 'all' ? `&item_type=${answerType}` : ''}${selectedMonitorIds.length ? `&monitor_ids=${encodeURIComponent(selectedMonitorIds.join(','))}` : ''}`),
        geoGet<{ items: Array<{ monitor_id: string; type: string; entity?: string }> }>('/monitor/items'),
      ])
      const nextGroups = a.groups ?? (() => {
        const grouped = new Map<string, MonitorAnswerGroup>()
        for (const answer of a.answers ?? []) {
          const key = answer.group_id || `${answer.monitor_id}|${answer.batch_id || answer.ts}|${answer.query}`
          const group = grouped.get(key) ?? { group_id: key, monitor_id: answer.monitor_id, ts: answer.ts, query: answer.query, item_type: answer.item_type, answers: [] }
          group.answers.push({ engine: answer.engine, mentioned: answer.mentioned, recognition: answer.recognition, sentiment_status: answer.sentiment_status, rank_est: answer.rank_est, sentiment: answer.sentiment, snippet: answer.snippet, answer: answer.answer })
          grouped.set(key, group)
        }
        return [...grouped.values()]
      })()
      setGroups((prev) => append ? [...prev, ...nextGroups] : nextGroups)
      const names: Record<string, string> = {}
      for (const item of m.items ?? []) names[item.monitor_id] = item.entity || item.monitor_id
      setItemNames(names)
      setPage(a.page ?? nextPage)
      setPages(a.pages ?? 1)
      setGroupTotal(a.group_total ?? nextGroups.length)
      const types = ['all', ...new Set((m.items ?? []).map((i) => i.type))]
      setItemTypes(types)
    } catch (e) {
      const message = e instanceof Error ? e.message : '监测报告加载失败'
      if (append) setLoadMoreError(message)
      else setError(message)
    } finally {
      if (append) setLoadingMore(false)
      else setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answerType, selectedMonitorIds])

  useEffect(() => {
    const onSelection = (event: Event) => {
      const detail = (event as CustomEvent<{ monitorIds: string[] }>).detail
      setSelectedMonitorIds(detail?.monitorIds ?? [])
    }
    window.addEventListener('geo-monitor-selection', onSelection)
    return () => window.removeEventListener('geo-monitor-selection', onSelection)
  }, [])

  // 维度数据按 tab 懒加载
  useEffect(() => {
    if (tab === 'answers' && !reasons) {
      geoGet<{ reasons: Array<{ query: string; engine: string; snippet: string }>; missing_evidence: string[] }>('/cognition/reasons')
        .then(setReasons)
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

  useEffect(() => {
    if (tab !== 'sentiment') return
    let cancelled = false
    setSentiment(null)
    const brandId = selectedMonitorIds.length === 1 ? selectedMonitorIds[0] : ''
    geoGet<SentimentResult>(`/monitor/sentiment${brandId ? `?monitor_id=${encodeURIComponent(brandId)}` : ''}`)
      .then((result) => { if (!cancelled) setSentiment(result) })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [tab, selectedMonitorIds])

  const visibleGroups = useMemo(() => groups.map((group) => [group, group.answers.map((answer) => ({ ...answer, monitor_id: group.monitor_id, query: group.query, ts: group.ts, item_type: group.item_type }))] as const), [groups])

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
              <div className="mb-2 text-[11px] font-semibold text-[var(--yayu-foreground)]">AI 为什么提到你 <span className="font-normal text-[var(--yayu-muted)]">· 真实回答样本</span></div>
              {reasons.reasons.length > 0 ? (
                <div className="space-y-1">
                  {reasons.reasons.slice(0, 3).map((r, i) => (
                    <div key={i} className="rounded-md bg-[var(--yayu-surface-raised)] px-2 py-1">
                      <div className="flex items-center justify-between gap-2 text-[10.5px]">
                        <span className="truncate font-medium text-[var(--yayu-foreground)]">{r.query}</span>
                        <span className="shrink-0 text-[var(--yayu-faint)]">{r.engine}</span>
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">{stripAnswerMarkdown(r.snippet)}</p>
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
                {/* 2026-09-21：这里是监测对象的类型枚举（brand/product/keyword/competitor），
                    原来直接把英文丢在筛选按钮上，用户看不懂。统一走 monitorTypeText。 */}
                {t === 'all' ? '全部' : monitorTypeText(t)}
              </button>
            ))}
          </div>
          {/* 2026-09-21：把「第 N 句提及」的口径写在页面上，别让用户把它读成 AI 给的推荐排名 */}
          {selectedMonitorIds.length ? <p className="mb-1 rounded bg-[var(--yayu-surface-raised)] px-2 py-1 text-[10px] text-[var(--yayu-muted)]">报告范围：所选监测对象（{selectedMonitorIds.length} 个）</p> : <p className="mb-1 text-[10px] text-[var(--yayu-faint)]">报告范围：全部监测对象</p>}
          <p className="mb-1 text-[10px] leading-relaxed text-[var(--yayu-faint)]">
            口径：「第 N 句提及」= 企业名第一次出现在回答的第几句话（位置，不是 AI 给的推荐排名）；按监测对象、批次和问题分组，点平台按钮切换。
          </p>
          {visibleGroups.length === 0 ? (
            <p className="text-[11px] text-[var(--yayu-faint)]">暂无监测回答，先运行一次监测。</p>
          ) : (
            <div className="space-y-2">
              {visibleGroups.map(([group, list]) => {
                const query = group.query
                const groupKey = group.group_id
                const hasResponse = (row: MonitorAnswer) => !!(row.answer || row.snippet) || row.mentioned != null
                const answered = list.filter(hasResponse)
                const activeEngine = picked[groupKey] ?? answered[0]?.engine ?? list[0]?.engine ?? ''
                const current = list.find((x) => x.engine === activeEngine) ?? list[0]
                const expanded = !!openFull[groupKey]
                const pos = current ? positionOf(current) : null
                const body = (current?.answer || current?.snippet || '').trim()
                return (
                  <div key={groupKey} className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-surface-raised)] px-2 py-1.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0"><span className="text-[12px] leading-snug text-[var(--yayu-foreground)]">{query}</span><div className="text-[9.5px] text-[var(--yayu-faint)]">{itemNames[group.monitor_id] ?? group.monitor_id} · {shortDay(group.ts)} · {monitorTypeText(group.item_type)}</div></div>
                      <span className="shrink-0 rounded bg-[var(--yayu-input)] px-1.5 py-0.5 text-[10px] text-[var(--yayu-faint)]">
                        {answered.length} / {list.length} 个平台有回答
                      </span>
                    </div>
                    {/* 平台切换：没回答、回答但未提及、已提及是三种不同状态。 */}
                    <div className="mt-1 flex flex-wrap gap-1">
                      {list.map((a) => {
                        const on = a.engine === activeEngine
                        const dot = a.recognition === 'not_recognised'
                          ? 'bg-[var(--yayu-muted)]'
                          : a.mentioned == null || !a.mentioned
                          ? 'bg-[var(--yayu-border)]'
                          : (a.rank_est ?? 99) <= 3
                            ? 'bg-[var(--yayu-foreground)]'
                            : 'bg-[var(--yayu-muted)]'
                        return (
                          <button
                            key={a.engine}
                            type="button"
                            title={a.recognition === 'not_recognised' ? '回答中无法确认所说主体是否为当前企业；情绪未判定' : a.mentioned == null ? '该模型未获得回答' : a.mentioned ? `已确认提及${a.rank_est !== null ? `（企业名在第 ${a.rank_est} 句首次出现）` : ''}` : '已回答，但未提及本企业'}
                            onClick={() => setPicked((prev) => ({ ...prev, [groupKey]: a.engine }))}
                            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] transition-colors ${
                              on
                                ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                                : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-muted)] hover:border-[var(--yayu-muted)]'
                            }`}
                          >
                            <span className={`mr-1 inline-block size-1.5 rounded-full ${dot}`} />
                            {a.engine}
                            {a.mentioned && a.rank_est !== null ? <span className="ml-1 opacity-70">{a.rank_est}</span> : null}
                          </button>
                        )
                      })}
                    </div>
                    {current ? (
                      <>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-[var(--yayu-faint)]">
                          {pos ? <span className={`rounded px-1.5 py-0.5 ${pos.cls}`}>{pos.label}</span> : null}
                          {current.rank_est !== null ? <span>企业名在第 {current.rank_est} 句首次出现</span> : null}
                          <span>{sampleSentiment(current)}</span>
                          {body ? <span className="ml-auto">{body.length} 字</span> : null}
                        </div>
                        {/* 全文放进一个框里滚动看，不把整页撑长（Owner：「用页面滑轮去调整」） */}
                        {expanded ? (
                          body ? (
                            <div className="mt-1 max-h-72 overflow-y-auto rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1.5 text-[11px] leading-relaxed text-[var(--yayu-muted)]">
                              <GeoFormattedAnswer text={body} />
                            </div>
                          ) : (
                            <p className="mt-1 text-[10.5px] text-[var(--yayu-faint)]">这家没有返回正文。</p>
                          )
                        ) : (
                          <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-[var(--yayu-muted)]">
                            {current.snippet ? stripAnswerMarkdown(current.snippet) : '（这家没有返回正文）'}
                          </div>
                        )}
                        {body ? (
                          <button
                            type="button"
                            onClick={() => setOpenFull((prev) => ({ ...prev, [groupKey]: !expanded }))}
                            className="mt-1 text-[10.5px] text-[var(--yayu-muted)] underline decoration-dotted"
                          >
                            {expanded ? '收起全文' : `展开全文（${body.length} 字）`}
                          </button>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                )
              })}
              <div className="flex items-center justify-between pt-1 text-[10.5px] text-[var(--yayu-faint)]"><span>已显示 {groups.length}/{groupTotal} 组完整观测</span>{page < pages ? <button className="underline" disabled={loadingMore} onClick={() => void load(page + 1, true)}>{loadingMore ? '正在加载…' : '加载更多'}</button> : null}</div>
              {loadMoreError ? <p className="text-[10.5px] text-[var(--yayu-muted)]">后续页面加载失败：{loadMoreError} <button className="underline" onClick={() => void load(page + 1, true)}>重试</button></p> : null}
            </div>
          )}
        </>
      ) : null}

      {tab === 'sentiment' ? (
        sentiment?.scope?.scope_required ? (
          <p className="text-[11px] text-[var(--yayu-faint)]">请在左侧只勾选一个企业品牌监测对象，再查看该主体的情绪分析。</p>
        ) : ov && ov.total > 0 ? (
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
            {/* 2026-09-21：口径如实写在页面上。原来的「负面 N%」会被读成「N% 的人在骂我们」，
                实际是词表统计——模型答「我无法判断，建议你查工商信息/警惕风险」也会算负面。 */}
            <p className="text-[10px] leading-relaxed text-[var(--yayu-faint)]">
              正、负、中为规则估算结果；无法确认企业主体或态度的回答单列为未判定，不计入正负中占比。
              {sentiment.unknown_count != null ? ` 未判定 ${sentiment.unknown_count} 条。` : ''}
            </p>
            {sentiment?.top_words && sentiment.top_words.length > 0 ? (
              <div className="text-[11px] text-[var(--yayu-muted)]">
                高频词：{sentiment.top_words.slice(0, 8).map((w) => (w?.word ? `${w.word}（${w.count ?? 0}）` : String(w))).join('、')}
              </div>
            ) : null}
            {sentiment?.negative_samples && sentiment.negative_samples.length > 0 ? (
              <div className="space-y-1">
                <div className="text-[11px] font-medium text-[var(--yayu-muted)]">负面样本</div>
                {sentiment.negative_samples.slice(0, 3).map((s, i) => (
                  <div key={i} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[11px] text-[var(--yayu-muted)]">
                    <div className="text-[10px] text-[var(--yayu-faint)]">
                      {[s?.question, s?.platform, s?.ts ? shortDay(s.ts) : ''].filter(Boolean).join(' · ')}
                    </div>
                    <div className="mt-0.5 leading-relaxed">{s?.snippet || '（这条没有正文）'}</div>
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
