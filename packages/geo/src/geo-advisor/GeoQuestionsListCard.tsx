import { useCallback, useEffect, useState } from 'react'
import { Sparkles, Trash2 } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoDelete, geoGet, geoPost, type GeoQuestion } from './geo-api'
import { GeoCardShell, GeoError, GeoLoading, askGeoConfirm } from './shared'

type Filter = 'all' | 'high' | 'unverified' | 'verified'

const FILTERS: Array<{ id: Filter; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'high', label: '高优先' },
  { id: 'unverified', label: '未验证' },
  { id: 'verified', label: '已验证' },
]

/** 决策链阶段分类（关键词规则，客户端过滤） */
const STAGES: Array<{ key: string; label: string; words: string[] }> = [
  { key: 'price', label: '价格', words: ['价格', '多少钱', '报价', '费用', '预算', '成本', '性价比', '划算'] },
  { key: 'compare', label: '比较', words: ['哪个好', '对比', '区别', '哪家强', '谁家好', '哪个品牌'] },
  { key: 'choose', label: '选择', words: ['怎么选', '选哪', '选什么', '推荐', '选择'] },
  { key: 'trust', label: '信任', words: ['口碑', '评价', '靠谱', '可信', '案例', '真实', '靠谱吗'] },
  { key: 'know', label: '认知', words: ['是什么', '有哪些', '怎么样', '了解', '介绍', '什么是', '干嘛的'] },
  { key: 'decide', label: '决策', words: ['值得', '要不要', '该不该', '买不买', '合适吗', '能买吗'] },
]

function stageOf(q: string): string {
  for (const s of STAGES) if (s.words.some((w) => q.includes(w))) return s.key
  return 'other'
}

/** 客户问题池卡：筛选 + 平台详情 + 删除（交互对齐 Builder GeoDistill） */
export function GeoQuestionsListCard() {
  const [filter, setFilter] = useState<Filter>('all')
  const [stageFilter, setStageFilter] = useState('all')
  const [coverage, setCoverage] = useState<Array<{ key: string; label: string; question_count: number; coverage: number | null }> | null>(null)
  const [items, setItems] = useState<GeoQuestion[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [platforms, setPlatforms] = useState<Record<string, Array<{ platform?: string; answer?: string; url?: string }>>>({})
  const [platformLoading, setPlatformLoading] = useState<string | null>(null)
  const [seeds, setSeeds] = useState('')
  const [generating, setGenerating] = useState(false)

  const load = useCallback(async (f: Filter = filter) => {
    setLoading(true)
    setError(null)
    try {
      const q = f === 'all' ? '' : f === 'high' ? '&priority=high' : `&validated=${f === 'verified'}`
      const [d, cov] = await Promise.all([
        geoGet<{ items: GeoQuestion[]; total: number }>(`/distill/questions?limit=50${q}`),
        geoGet<{ stages: Array<{ key: string; label: string; question_count: number; coverage: number | null }> }>('/cognition/coverage'),
      ])
      setItems(d.items)
      setCoverage(cov.stages ?? [])
    } catch (e) {
      setError(e instanceof Error ? e.message : '问题池加载失败')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    void load()
  }, [load])

  const changeFilter = (f: Filter) => {
    setFilter(f)
    void load(f)
  }

  const togglePlatforms = async (qid: string) => {
    if (platforms[qid]) {
      setPlatforms((prev) => {
        const next = { ...prev }
        delete next[qid]
        return next
      })
      return
    }
    setPlatformLoading(qid)
    try {
      const d = await geoGet<{ items: Array<{ platform?: string; answer?: string; url?: string }> }>(
        `/distill/questions/${qid}/platforms`,
      )
      setPlatforms((prev) => ({ ...prev, [qid]: d.items }))
    } catch (e) {
      setError(e instanceof Error ? e.message : '平台数据加载失败')
    } finally {
      setPlatformLoading(null)
    }
  }

  const removeQuestion = async (qid: string) => {
    if (!(await askGeoConfirm('删除后这个问题不会再进入内容计划，已生成的内容不受影响。'))) return
    setError(null)
    try {
      await geoDelete(`/distill/questions/${qid}`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  const generateQuestions = async () => {
    setGenerating(true); setError(null)
    try { await geoPost('/distill/questions', { seed_keywords: seeds.split(/[，,\n]/).map((x) => x.trim()).filter(Boolean), count: 10 }); setSeeds(''); await load() }
    catch (e) { setError(e instanceof Error ? e.message : '问题生成失败') } finally { setGenerating(false) }
  }

  if (loading) return <GeoLoading text="客户问题池加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />
  const sorted = [...(items ?? [])]
    .filter((q) => stageFilter === 'all' || stageOf(q.question) === stageFilter)
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))

  return (
    <GeoCardShell title="客户问题池" className="geo-growth-workbench">
      <div className="question-generator"><div><b>生成真实客户问法</b><span>输入种子词；留空时系统尝试从企业资料自动提取。</span></div><input value={seeds} onChange={(e)=>setSeeds(e.target.value)} placeholder="例如：GEO 服务，知识库搭建，AI 数字员工"/><Button size="sm" disabled={generating} onClick={()=>void generateQuestions()}><Sparkles className="size-3.5"/>{generating?'生成中…':'生成 10 个问题'}</Button></div>
      {/* 场景覆盖矩阵（决策链各阶段覆盖） */}
      {coverage && coverage.length > 0 ? (
        <div className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-1.5">
          <div className="mb-1 text-[11px] font-medium text-[var(--yayu-muted)]">场景覆盖矩阵（决策链各阶段）</div>
          <div className="space-y-1">
            {coverage.map((s) => (
              <div key={s.key} className="flex items-center gap-2">
                <span className="w-10 shrink-0 text-[10.5px] text-[var(--yayu-muted)]">{s.label}</span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--yayu-surface-raised)]">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${s.coverage ?? 0}%`,
                      background: (s.coverage ?? 0) >= 70 ? 'var(--good)' : (s.coverage ?? 0) >= 40 ? 'var(--warn)' : 'var(--bad)',
                    }}
                  />
                </div>
                <span className="w-14 shrink-0 text-right text-[10px] text-[var(--yayu-faint)]">
                  {s.coverage === null ? '未监测' : `${s.coverage}%`} · {s.question_count}问
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* 筛选按钮组（重新筛选 = 切换条件重拉） */}
      {sorted.length === 0 ? <div className="market-empty">还没有客户问题，可以从种子词开始生成。</div> : null}
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => changeFilter(f.id)}
            className={`rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors ${
              filter === f.id
                ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-muted)] hover:border-[var(--yayu-muted)]'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* 决策链阶段筛选（客户端分类：认知→比较→选择→决策→信任→价格） */}
      <div className="flex flex-wrap items-center gap-1.5 pt-1">
        <span className="text-[10.5px] text-[var(--yayu-faint)]">决策阶段：</span>
        {[{ key: 'all', label: '全部' }, ...STAGES.map((s) => ({ key: s.key, label: s.label }))].map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => setStageFilter(s.key)}
            className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
              stageFilter === s.key
                ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-muted)] hover:border-[var(--yayu-muted)]'
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="space-y-1.5">
        {sorted.map((q) => (
          <div key={q.id} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[12px] leading-snug text-[var(--yayu-foreground)]">{q.question}</div>
                <div className="mt-0.5 text-[11px] text-[var(--yayu-muted)]">
                  阶段：{q.customer_stage} · 意图：{q.intent}
                  {q.evidence_level ? ` · 证据：${q.evidence_level}` : ''}
                  {q.validated ? ' · ✅已验证' : ' · 未验证'}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <span className="rounded bg-[var(--yayu-surface-raised)] px-1.5 py-0.5 text-[10px] text-[var(--yayu-muted)]">
                  优先级 {q.priority}
                </span>
                <Button variant="ghost" size="sm" onClick={() => void togglePlatforms(q.id)} disabled={platformLoading === q.id}>
                  {platformLoading === q.id ? '…' : '平台'}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void removeQuestion(q.id)} aria-label="删除该问题">
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </div>
            {platforms[q.id] ? (
              <div className="mt-2 space-y-1 rounded-lg bg-[var(--yayu-surface-raised)] p-2">
                {platforms[q.id].length === 0 ? (
                  <p className="text-[11px] text-[var(--yayu-faint)]">该问题尚未在监测平台命中（可先跑监测）。</p>
                ) : (
                  platforms[q.id].map((p, index) => (
                    <div key={index} className="flex items-center justify-between gap-2 text-[11px]">
                      <span className="font-medium text-[var(--yayu-foreground)]">{p.platform ?? '平台'}</span>
                      {p.answer ? <span className="truncate text-[var(--yayu-muted)]">{p.answer}</span> : null}
                      {p.url ? (
                        <a href={p.url} target="_blank" rel="noreferrer" className="shrink-0 text-[var(--yayu-foreground)] underline">
                          查看
                        </a>
                      ) : null}
                    </div>
                  ))
                )}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </GeoCardShell>
  )
}
