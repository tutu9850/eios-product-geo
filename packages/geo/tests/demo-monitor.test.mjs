import assert from 'node:assert/strict'
import test from 'node:test'
import { buildDemoMonitor, DEMO_OBSERVATIONS, DEMO_MONITOR, DEMO_EMPTY_MONITOR, DEMO_FAILED_MONITOR, DEMO_MATERIALS, DEMO_SECONDARY_OBSERVATIONS } from '../src/geo-advisor/demo-monitor-samples.ts'

test('raw observations account for all slots without inventing successful answers', () => {
  const s = DEMO_MONITOR.summary
  assert.deepEqual(s, { slots: 36, answered: 33, failed: 3, recognised: 28, not_mentioned: 2, unknown: 3, rounds: 3, groups: 9, mention_pct: 85, recommendation_pct: 39 })
  assert.equal(new Set(DEMO_OBSERVATIONS.map(r => r.id)).size, 36)
  assert.equal(DEMO_MONITOR.groups.flatMap(g => g.answers).length, 36)
  for (const r of DEMO_OBSERVATIONS) {
    if (!r.answer) assert.equal(r.mentioned, null)
    if (r.recognition === 'not_recognised') {
      assert.equal(r.rank_est, null)
      assert.equal(r.sentiment_status, 'unknown')
    }
    for (const id of r.citation_ids) assert.ok(DEMO_MATERIALS.some(m => m.id === id && m.published_at))
  }
})

test('cross-page totals and details reconcile with raw observations', () => {
  const m = DEMO_MONITOR
  assert.equal(m.sources.reduce((n, s) => n + s.total, 0), m.summary.answered)
  assert.equal(m.sources.reduce((n, s) => n + s.mentioned, 0), m.summary.recognised)
  assert.equal(m.sentiment.overview.total, m.summary.recognised)
  assert.equal(m.sentiment.overview.positive + m.sentiment.overview.neutral + m.sentiment.overview.negative, m.sentiment.overview.total)
  assert.equal(m.sentiment.trend.reduce((n, s) => n + s.total, 0), m.sentiment.overview.total)
  assert.equal(m.sentiment.negative_samples.length, m.analytics['public-opinion'].detail_total)
  assert.equal(m.overview.citations_count, m.citations.reduce((n, c) => n + c.count, 0))
  const f = m.analytics['fact-check']
  assert.equal(f.truth.total_checked, f.truth.hit_kb + f.truth.unsupported_count + f.truth.abnormal_count + f.truth.no_claim_count)
  assert.equal(f.truth.abnormal_count, f.details.length)
  // Unsupported assertions never inflate the count of suspected conflicts.
  assert.equal(f.truth.unsupported_count, 5)
  assert.equal(f.truth.abnormal_count, 1)
})

test('empty and all-failed inputs cannot produce brand or citation performance', () => {
  for (const m of [DEMO_EMPTY_MONITOR, DEMO_FAILED_MONITOR]) {
    assert.equal(m.summary.answered, 0)
    assert.equal(m.summary.recognised, 0)
    assert.equal(m.overview.recommend.value, null)
    assert.equal(m.overview.rank.value, null)
    assert.equal(m.overview.cite_rate, null)
    assert.equal(m.analytics['fact-check'].truth.available, false)
    assert.equal(m.analytics.competitor.pairs.length, 0)
    assert.equal(m.analytics.industry.empty, true)
    assert.ok(Object.values(m.overview.platforms).every(points => points.length === 0))
  }
})

test('removing a round changes both details and cumulative totals', () => {
  const m = buildDemoMonitor(DEMO_OBSERVATIONS.filter(r => r.round === 2))
  assert.equal(m.summary.slots, 12)
  assert.equal(m.summary.answered, 11)
  assert.equal(m.groups.length, 3)
  assert.equal(m.summary.rounds, 1)
  assert.equal(m.stats.runs, 1)
  assert.equal(m.overview.recommend.delta, null)
  assert.ok(m.sources.every(s => s.total <= 3))
})

test('a second subject cannot change the selected brand metrics or details', () => {
  const mixed = [...DEMO_OBSERVATIONS, ...DEMO_SECONDARY_OBSERVATIONS]
  assert.deepEqual(buildDemoMonitor(mixed), DEMO_MONITOR)
  const secondary = buildDemoMonitor(mixed, 'demo-secondary')
  assert.equal(secondary.summary.slots, 12)
  assert.equal(secondary.summary.answered, 11)
  assert.ok(secondary.groups.every(g => g.monitor_id === 'demo-secondary'))
  assert.equal(secondary.analytics['fact-check'].company_name, '月白示例家居')
  assert.equal(buildDemoMonitor(mixed, 'missing-subject').summary.slots, 0)
})
