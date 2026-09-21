# GEO 内容生成影响因子 + 蒸馏链路 · 逻辑漏洞审计（2026-09-21）

> 只读审计。**本轮没有改任何代码**（除本文件）。
> 结论分两类，逐条标注：**【实测】**= 本轮真跑过接口/脚本拿到输出；**【代码】**= 只读代码推断，未跑。
> 环境：GEO API `127.0.0.1:8091` → 产品门 `127.0.0.1:8090/api/product/geo/*`，知识库 `127.0.0.1:8040`，
> Model Capability `127.0.0.1:8094`，UI `:18093` → `packages/geo/dist`，Client `:4173/app/geo`。

---

## 一、内容生成的影响因子：现状清单

### 1.1 调用方给的（`POST /content/generate` 的入参）

| 因子 | 取值 | 前端是否真的传 |
|---|---|---|
| `goal` 内容目标 | 6 种 | ✅ 传 |
| `content_type` 内容类型 | 6 种 | ✅ 传 |
| `style` 风格 | 5 种 | ✅ 传 |
| `length` 长度 | 500 / 1500 / 3000 | ✅ 传 |
| `platform` 平台 | 8 新媒体 + 6 SEO | ✅ 传（通用=null） |
| `question` 主题 | 自由文本 | ✅ 传 |
| `industry` 行业 | 自由文本 | ❌ 前端无入口 |
| `company_name` 企业名 | 空 = 自动识别 | ❌ 前端不传（走后端自动识别） |
| `seo{}` SEO 参数 | keywords/密度/调性/受众 | ❌ 前端无入口（选 SEO 平台也传 null） |
| `mode` Fact Gate 模式 | strict / creative / draft | ❌ 前端不传 → 恒 `creative` |
| `structure` 认知编译器 | free / geo | ❌ 前端不传 → 恒 `free` |
| `materials_extra` 外部素材 | 数组 | ❌ 前端不传（yayu BFF 侧曾用） |

### 1.2 服务端自动聚合的（`services/content/__init__.py :: build_context`）

| 因子 | 取数来源 | 规则 |
|---|---|---|
| 企业事实 `materials` | EIOS 知识库检索 | top 8 |
| FAQ 内容资产 | GEO 库 `kb` 表 `source_type=faq` | 字符重叠排序 top 3 |
| 历史内容资产 | GEO 库 `kb` 表 `source_type∈{generated,text,url}` | 字符重叠排序 top 2 |
| 客户问题池 | GEO 库 `questions` 表 | 字符重叠排序 top 5 |

### 1.3 生成前后的闸门与结构层

| 环节 | 实现 | 前端可见性 |
|---|---|---|
| Fact Gate（用户声明核验） | `_fact_gate`：kernel / material / none 三档 | 结果 `unverified_facts` **前端从不读** |
| 认知编译器结构模板 | `structure="geo"` → `STRUCTURE_GEO_INSTRUCTION` | **不可达**（前端不传） |
| 结构解析 `sections` | `parse_sections` | **不可达** |
| 事实密度 `fact_check` | `score_fact_density`，需 Kernel 带数字锚点事实 | **不可达** |
| 生成后评分 | 独立的 `POST /content/score` | ✅ 调了，但入参残缺（见 B2） |
| 生成后质量检测 | 独立的 `POST /content/quality`（5 项 LLM 评分） | ✅ 调了 |

---

## 二、够不够？—— 主输入是断的（按严重度排序）

### A1【实测·最高危】企业事实恒为空：知识检索读错了键名

`adapters/eios.search_knowledge()` 返回的字典顶层键是 **`hits`**。
三处调用点全部读 `res.get("results") or res.get("objects") or res.get("items")` → 恒 `[]`：

- `services/content/__init__.py:331`（`_auto_company`）
- `services/content/__init__.py:450`（`build_context`）
- `apps/api/app/services/company_profile.py:90`（`build_company_profile`）

实测证据：

```
search_knowledge 顶层 keys: ['contract','hits','layers','matched','provenance','query','query_id','snapshot_recorded','warnings']
查询「企业AI获客入口改造」→ 12 条命中；查询「亚宇臻隆」→ 87 条命中（score 13.5~14.0）
res.get('results') -> None ; res.get('items') -> None
命中样例：- 经营月报 | 营业收入 | 1680000 | 年营收目标¥2,000万 | 本月完成率100.8%
```

后果（全部实测）：

| 接口 | 实测输出 |
|---|---|
| `GET /content/company` | `materials_count: 0` |
| `POST /content/generate` | `materials_used: 0`；`context_sources.kernel.items = 0` |
| 生成正文开头 | 「截至本文撰写时，**企业知识库中暂无「企业AI获客入口改造」这一主体的详细资料**……本文**不是**对该企业的事实性介绍，而是一篇**通用概念说明**」 |
| `GET /knowledge/profile` | `facts: []`、`key_facts: []`、`relations: []`，而 `kernel_ok: true`（知识库可达、就是没读） |
| `POST /content/score` | `entity_coverage 0.0`、`fact_density 0.0` |

也就是说：**企业知识库有货（87 条），内容生成一条都拿不到**，产出的永远是「通用概念说明」，还自带免责声明。
这条修好之前，Owner 说的「内容生产必须从知识库来」在链路上是不成立的。

### A2【实测】认知编译器（`structure="geo"`）+ Fact Gate 模式在 UI 上不可达

`POST /content/generate` 实测返回 `structure: "free"`、`sections: null`、`fact_check: null`、`geo_score: null`。
前端 `GeoContentGenForm.tsx` 只发 `goal/content_type/style/length/platform/question` 六个字段；
全仓 grep 前端，`structure` / `mode` / `fact_check` / `sections` / `unverified_facts` / `context_sources` / `materials_used` **一次都没用**。

后果：仓里那套「可抽取结构模板 + 事实密度校验 + 一键重写建议」的**认知编译器只在后端存在，产品里点不出来**；
Fact Gate 的 `strict`（无依据拒绝生成）和 `draft` 也点不出来，用户永远拿不到「哪句话没依据」的提示。

### A3【实测】`POST /content/score` 入参残缺，评分恒低

前端发的是 `{title, content, goal, question, platform}`；
后端 `ScoreIn` 只认 `content / company_name / question / tenant_id` → `company_name` 缺省为空串
→ `build_company_profile("")` 直接返回空画像 → `kernel_facts=[]`、`pool_questions=[]`。

实测：同一段带 5 段模板结构的正文，`entity_coverage 0.0 / fact_density 0.0 / question_coverage 0.0 / total 0.28`，
建议永远是「知识库暂无该企业的带数据事实」。**UI 上那个「可发布度评分」目前是坏的**（且 A1 修好后仍需先补 `company_name`）。

### A4【代码】平台字数配置是死代码

`word_count = length if length in ("500","1500","3000") else str(p["wordCount"][0])`。
而 `length` 由表单/`parse_intent` 归一后**永远是**这三个值之一 → `p["wordCount"]` 永不生效。
小红书配的是 600–1000 字，实际会按 1500 字下单。

### A5【代码】检索用的是字符重叠，仓里现成的混合检索没用

`build_context` 排序调 `_overlap_score`（注释自称「第一版，不引入 embedding」），只比对 `title`：
`sum(1 for ch in a if ch in b and not ch.isspace())` —— 共用常用字越多分越高，且不看正文。
而同仓 `services/embed/__init__.py` 已有 `hybrid_search`（n-gram + 向量，素材页 `/knowledge/materials/search` 在用）。
FAQ / 历史素材 / 问题池三路召回都走这个弱排序。

### A6【实测】该看而没看的因子（遗漏清单）

这些信号仓里**都有数据**，但生成时一个字都不读：

| 可用信号 | 在哪 | 生成时是否使用 |
|---|---|---|
| AI 现在怎么回答（6 引擎 snippet、mentioned、rank_est、sentiment） | `monitor_history`（实测有真实回答） | ❌ |
| AI 有没有引用过你的素材 | `monitor_history[].citations` | ❌ |
| 认知评估：grounded / partial / **hallucination** claims | `cognition_evaluations` | ❌ |
| 周期报告结论：竞品为什么赢、能力缺口、gap_matrix、actions | `geo_insight_reports` | ❌ |
| 竞品被夸的因子（factor-gaps left） | `services/intelligence/cognition.factor_gaps` | ❌（只落到计划 `reason`，不进生成 prompt） |
| 48 认知子项覆盖度 | `enterprise_profile` | ❌ |
| 素材发布点（`published_at` / `published_url`）与效应 | `kb` 表 | ❌ |

后果：生成是「闭着眼睛写」——不知道 AI 当前怎么答、不知道竞品被夸在哪、不知道自己被指认过什么幻觉。
而这些恰恰是最该决定「这篇该写什么」的输入。

---

## 三、蒸馏：怎么蒸的、怎么用的

### 3.1 两条蒸馏链（都在跑）

**链 1 · 内容蒸馏（`distill.py`，产品名「蒸馏中心」）**

```
监测问 AI（consumer=geo.monitor，部署决定要不要联网）
  → monitor_history（问题/6 引擎/提及/排名/情感/snippet/引用）
  → POST /distill/questions   种子词(空则从知识库抽实体) → LLM 生成客户问题池
      （intent/customer_stage/priority/related_entities；evidence_level 一律 "C"）
  → POST /distill/gaps        逐问 Kernel 检索 → 4 级判定 COVERED/PARTIAL/GAP/UNRELATED
      → 命中 48 认知子项 → 知识缺口（子项粒度）
  → POST /distill/content-plan 问题价值×AI缺口 → 48 子项压力 → Kernel 知识检查 → Top N 计划
  → POST /distill/loop/run     planned → 自动生成内容 → 存 kb（source_type=generated）→ produced
  → POST /distill/content-publish / content-recheck  人工发布打点 + 复测
另：POST /distill/opportunities（知识对象→机会）、POST /distill/plans（缺口→LLM 计划）
```

**链 2 · 分析引擎（`services/intelligence/`，产品名「EIOS 分析」）**

```
geo_evidence（监测回答统一原文）
  → extractor（LLM 抽 6.1 JSON）→ geo_extraction + brand_mention（因子/引用/信任信号）
  → aggregator（无 LLM：维度榜 + 三色 + 观察区）
  → reasoning（LLM 写周期报告，Kernel 对照定 gap_type）→ geo_insight_reports
  → cognition.compare / factor_gaps（竞品有·我方无 / 我方有·竞品无）
另：cognition_evaluate（LLM 批处理）→ cognition_evaluations → cognition/profile（健康度/四指标/错误认知）
```

### 3.2 蒸馏被谁消费

| 消费方 | 读什么 |
|---|---|
| UI 六个页签 | 上述 GET 接口 |
| `content.generate` | 只读 `questions` 表（问题池 top 5）——**gaps / plans / 报告 / 评估一概不读** |
| `loop.auto_production` | 读 `content_plans` 的 `planned` |
| `report_pdf` / `monitor/export` | 读问题池与批量监测摘要 |
| 顾问（`geo_consumer`） | 只读快照台账 |

也就是说：**蒸馏产出的大部分结论（缺口/机会/报告/幻觉）在「生成内容」这一步是被丢掉的**——链 1 只喂了问题池。

---

## 四、其他逻辑漏洞（蒸馏与生成周边）

### B1【实测】认知漏斗/认知地图的「企业覆盖」恒 0%，而且被当成结论

`distill_overview` / `cognition_map` / `report_pdf` 都用 `q.get("evidence_level") == "grounded"` 计数。
但全仓 grep：**没有任何地方把 question 的 `evidence_level` 写成 `grounded`**，`gen_questions` 只写 `"C"`。

实测 `GET /distill/overview`：
```
funnel: [{stage:"其他", question_count:2, coverage_pct: 0}]
ai_judgment.reason: "客户已进入「其他」阶段，但企业资料覆盖仅 0%——AI 回答该类问题时无法引用企业"
```
`GET /distill/cognition-map` 同样是 `coverage_pct: 0`。
这是**把「没写过的字段」渲染成 0% 并给出因果结论**，不是空态。
正确做法应是 null（诚实空态）——同一文件的注释自己也写了「无数据阶段标 null」。

### B2【实测】问题评分的「企业覆盖/机会分」恒 null

`list_questions` 用 `_cov_map = {"grounded":80,"partial":50,"none":20}` 反查 `evidence_level`，
而问题记录上是 `"C"` 或 `None` → `coverage: null`、`opportunity: null`（实测每条都是 null）。
`attention` 却兜底成 50（`q.get("priority") or 50`），于是出现「priority: None 但 attention: 50」的自相矛盾。

### B3【实测】`gen_opportunities`「来源 A（知识对象→可直接生产）」整条是死的

它用 `_CT_MAP = {"material":…, "project":…, "company":…}` 过滤 `object_type`；
但 EIOS 知识对象只有两种类型——实测 `Counter({'entity': 171, 'fact': 29})`。
→ 每个实体都在 `obj_t not in _CT_MAP` 处被跳过，来源 A **产出恒 0**。
（现存 64 条 `source_type=material` 的计划是旧 Kernel 时代的遗留数据，新跑不出来。）

### B4【代码】连带失效：`_self_company_names` 的兜底分支 + `_attach_factor_notes`

- `_self_company_names` 兜底读 `e.get("object_type") == "company"` → 永不成立（同 B3）。主路径（`monitor_items` 里配置的 brand）仍可用。
- `_attach_factor_notes` 要求 `source == "capability"` 且 `source_type == "material"`，而 B3 之后新数据产不出 `material`；
  实测 100 条计划里 `factor_notes` 有 **0** 条。它依赖的 `factor_gaps` 实测 `left/right/both = 0`（`/intelligence/compare` 的 `total_evidence = 0`，解析层在 dev 没出数）。
  → 「竞品被夸而你没被夸」这个卖点，在 dev 上是**完全静默**的。

### B5【代码】`enterprise_profile` 两处同源缺陷

- `_load_knowledge()` 用 `search_knowledge("")` 取事实；空查询走的是「对象目录」分支，
  `_map_hit` 在该分支给出 `value: ""`、`predicate: None` → `facts` 过滤条件 `if predicate or value` **恒不成立** → `facts` 恒 `[]`。
  子项详情与 Word 导出因此永远显示「已有资料：实体 N · **事实 0** · 关系 N」。
- 同文件 734 行读 `h.get("text") or h.get("content")`，但 `_map_hit` 给的是 `value`/`snippet` → 「相关文档块」恒空。

### B6【代码】`reasoning._kernel_summary` 的 fact 分支是死的

`_map_hit` **不产出 `kind` 字段**，而 `_kernel_summary` 按 `kind == "fact"` / `kind == "chunk"` 分流 →
全部落 `else`，只带上实体名，**丢掉 predicate/value**。周期报告里的「企业关键事实」实际只有一堆名字。

### B7【实测+代码】Kernel 命中阈值 0.5 与 EIOS 分数量纲不匹配

`reasoning._kernel_has` 与 `services/content._fact_gate` 都用 `best >= 0.5`；
但 EIOS 的 `score` 实测是 **13.5 / 14.0**（排序分，不是 0–1 余弦）。
→ 只要检索返回任何命中，这个条件就恒真。`_kernel_has` 的结果会系统性地偏向
`capability_hidden`（「有能力没讲出来→去写文章」），而不是 `capability_missing`（「真缺知识→去补资料」）。
`_fact_gate` 里该条件也成了摆设（真正起作用的是后面的 `related` 相关性判断）。

### B8【代码】复测「真实差值」其实不是差值；且无幂等

`content_recheck` 的 docstring 写「impact 规则映射（**真实差值**，非 LLM）」，但：

- `base_rate`、`total_mention_delta` 两个变量**赋值后从未被读取**（grep 全仓仅出现在赋值/初始化行）；
- `before_snapshot` 里只有 `questions` 与 `pressure`，**没有发布时的逐问提及率**，所以 `delta: null`；
- 最终 impact 用**发布后的绝对正向率**分档：`>=50 high / >=20 medium / else neutral` —— 与环境、竞品、时间无关。
- 每次调用都 `store.insert("content_impacts", …)` 追加一行，**重复复测会累积重复记录**（无幂等键）。

### B9【代码】`cognition_evaluate` 先清空再重算，中途失败即丢数据

开头 `for old in store.load("cognition_evaluations"): store.delete(...)` 先把历史评估全删；
之后按批调 LLM，任一批失败就 `return ok({"evaluated": len(results), "error": …})` 提前退出
——此时旧数据已删、新数据只有前面几批。用户看到的是「部分成功」，但历史已经没了。

### B10【代码】`store.save()` 是整表替换，且被读路径调用

`Store.save()` 语义 = 「删掉该租户全部行 → 重新插入」，并且把**所有行**的 `created_at` 刷成同一时刻。
问题：

- `GET /distill/plans` 会执 `_attach_factor_notes(all_plans)` + `_save_plans(all_plans)` —— **读接口在写库**。
- 所有 `load → 改 → save` 的写法（`gen_questions`/`detect_gaps`/`gen_plans`/`delete_question`/`delete_plan`/`publish`/`recheck`/`auto_production`/`list_plans`）
  在并发下会互相覆盖：**后写的把先写的整体顶掉**（含把已删除的行复活）。
- `load()` 按 `created_at` 升序，而 `save()` 让所有行时间相同 → 「最新 N 条」的排序实际上依赖 SQLite 的行序，不是设计保证。

### B11【代码】自动蒸馏链跑的是「旧」计划算法

`monitor._distill_after_run`（每月/每次批量监测后自动跑）顺序是：
`gen_questions → detect_gaps → gen_opportunities → gen_plans`。
其中 `gen_plans` 是「缺口 → LLM 直接编内容计划」的**旧算法**；
2026-08-19 拍板的新算法 `POST /distill/content-plan`（48 子项压力）**不在自动链里**，只有 UI 手动点才跑。
→ 同一套「内容计划」在同一张表里由两种口径产出，自动来的没有 `subitem`/`before_snapshot`，复测也就无从对比。

### B12【代码】其它小项

- `distill_overview.opportunities_count = len(plans)` 把 `archived`/`published` 也算进「机会数」。
- `POST /distill/faq` 的 grounded 分支只捕获 `LLMError`，`LLMNotConfiguredError` 会冒成 500。
- `delete_question` / `delete_plan` 只删本体，**不清理引用它的 gaps / plans**（计划里会留下指向已删问题的 `target_question`）。
- `_extract_fact_claims` 的截尾关键词表是硬编码中文（「，请」「请帮我们」…），英文/口语化输入提取不到声明。
- `generate()` 失败重试是**同一 prompt 原样重发一次**，无退避（对限流场景作用有限）。
- 前端 `GeoContentGenForm` 的平台列表只暴露 11/14 个平台（缺 网易/搜狐/微博/产品页/新闻稿/博客）。

---

## 五、与 Owner 既有决定的对照（未发现越界）

| 决定 | 现状 | 判定 |
|---|---|---|
| GEO 不许写知识库 | `adapters/eios.write_candidate` 直接抛 `AUTHORITY_WRITE_NOT_ALLOWED` | ✅ |
| 读到的都存进 GEO 自己的库 | `knowledge_snapshot.record`，按 payload_hash 去重累加 | ✅ |
| GEO 不持模型 Key / 不选 provider | `adapters/llm.py` + `model_entry.py` 只走 HTTP，`model_id` 取部署默认 | ✅ |
| temperature / thinking 不进 GEO | 全仓 grep 无 | ✅ |
| 内容生产不联网 | 联网白名单 `WEB_SEARCH_CONSUMERS = ("geo.monitor","geo.battle")`，`geo.content_generation` 不在内 | ✅ |
| 认知编译器「本地已有/待补知识」口径 | `content-plan` 只出「本地已有」，其余归缺口 | ✅（但被 A1 拖累：`_subitem_knowledge` 走 `_knowledge_check` 正确读 `hits`，所以这层没坏） |
| 待确认 | `geo.onboard` 不在联网白名单，但 onboard 用 `consumer=geo.onboard` | ⚠️ 需要 Owner 确认是否符合预期 |

---

## 六、复现方法

```bash
TOKEN=$(curl -s -D - -o /dev/null -X POST http://127.0.0.1:8090/api/product/auth/login \
  -H 'content-type: application/json' -d '{"username":"alice","password":"alice-dev"}' \
  | grep -i '^x-eios-session:' | awk '{print $2}' | tr -d '\r')

# A1
curl -s -H "X-EIOS-Session: $TOKEN" http://127.0.0.1:8090/api/product/geo/content/company
curl -s -X POST -H "X-EIOS-Session: $TOKEN" -H 'content-type: application/json' \
  http://127.0.0.1:8090/api/product/geo/content/generate \
  -d '{"goal":"提升AI推荐概率","content_type":"企业介绍","style":"专业权威","length":"1500","question":"企业AI获客入口改造是做什么的"}'
# → materials_used: 0，正文自述「知识库暂无……通用概念说明」

# B1
curl -s -H "X-EIOS-Session: $TOKEN" http://127.0.0.1:8090/api/product/geo/distill/overview
# → funnel[0].coverage_pct: 0 + ai_judgment 断言「覆盖仅 0%」

# B2
curl -s -H "X-EIOS-Session: $TOKEN" 'http://127.0.0.1:8090/api/product/geo/distill/questions?limit=3'
# → coverage: null / opportunity: null / attention: 50

# B3/B4
curl -s -H "X-EIOS-Session: $TOKEN" 'http://127.0.0.1:8090/api/product/geo/intelligence/factor-gaps?days=30'
# → left/right/both = 0
```

知识检索实际返回值（独立脚本，只读，落到 `/tmp/eios-test/geo-audit/probe.db`）：
见本审计第 A1 节的实测输出。

---

## 七、建议优先级（**未施工，等 Owner 拍板**）

1. **A1 键名修正**（3 处一行改动）——不修的话，内容生成、企业画像、内容评分、企业资料「事实数」全是空的。这是所有下游问题的根。
2. **B1/B2 evidence_level 口径**（要么真写 `grounded`，要么改成 null 诚实空态，不许把没写过的字段渲染成 0% 并给结论）。
3. **B3/B4 来源 A 与竞品标注**（按 EIOS 的 `entity`/`fact` + `object_scope` 重定映射，或明确下线这两个功能）。
4. **B9/B10 存储语义**（`cognition_evaluate` 先写后删；`save()` 别用在读路径；删除/发布改按行更新）。
5. **A2/A3 前端把已有能力接出来**（`structure`/`mode`/`unverified_facts`/`company_name`）。
6. **A6 把监测与评估信号喂进生成**（这一步会真正改变产出质量，但涉及「生成看什么」的产品口径，需要 Owner 定）。
7. **B7/B8/B11 口径与文案诚实性**（阈值量纲、复测差值、自动链算法一致性）。

> 全部为审计结论，**本轮一行代码都没改**。

---

## 八、修复落地（2026-09-21 第二轮 · Owner 拍板「全修」）

> 审计是只读的；以下为**同一工作树**的修复落地记录（未 commit 前为工作区改动）。
> 验证方式：`/tmp` 隔离库副本（`GEO_DB_PATH`）+ 真跑接口，**不碰 dev 库**。

| 编号 | 状态 | 修了什么 | 文件 |
|---|---|---|---|
| A1 | 已修 | 新增 `hits_of()` 统一读取助手，三个调用点（`_auto_company` / `build_context` / `build_company_profile`）改用它；旧键保留兜底 | `adapters/eios/__init__.py`、`services/content/__init__.py`、`apps/api/app/services/company_profile.py` |
| A2 | 已修 | 前端生成表单接出 `structure`（认知编译器）/ `mode`（Fact Gate 三档）/ `industry` / `seo{}`；结果区新增「未验证声明 / 事实密度 / 引用来源 / 结构化分节 / 严谨模式拒绝」展示 | `packages/geo/src/geo-advisor/GeoContentGenForm.tsx` |
| A3 | 已修 | `ScoreIn` 企业名留空即自动识别当前企业；`title/goal/platform` 显式声明；返回 `company_name`/`profile_resolved`；顺带修「可发布度」显示（0.85 被 `Math.round` 成 1 分） | `apps/api/app/api/v1/content.py`、`GeoContentGenForm.tsx` |
| A4 | 已修 | 新增 `_target_word_count()`：按平台字数区间把请求长度夹进 `[min,max]`（小红书 1500 → 1000） | `services/content/__init__.py` |
| A5 | 已修 | 新增 `services.embed.n_gram_scores()` 并让 `hybrid_search` 复用；`build_context` 的 FAQ/历史素材/问题池排序从「标题字符重叠」换成同源 n-gram（标题 2x + 正文 1x），空 query 稳定退化 | `services/embed/__init__.py`、`services/content/__init__.py` |
| A6 | 待拍板 | 监测回答 / 幻觉 / 报告结论 / 竞品因子喂进生成 prompt —— 涉及「生成看什么」的产品口径，未擅动 | — |
| B1 | 已修 | `detect_gaps` 把知识判定结果如实写回问题 `evidence_level`（grounded/partial/none）；`_funnel_rows()` 统一漏斗口径（按**已判定**问题算比例，未判定给 `null` + `judged_count`）；`overview`/`cognition-map`/PDF 全部改用 | `apps/api/app/api/v1/distill.py`、`apps/api/app/services/report_pdf.py` |
| B2 | 已修 | `attention` 不再兜底 50（没填即 `null`）；`opportunity` 要求 cov 与 att 同时存在才计算 | `apps/api/app/api/v1/distill.py` |
| B3 | 部分修 / 待拍板 | `_match_knowledge` 不再用旧 Kernel 类型词表硬排除（新增 `_KNOWN_OBJECT_TYPES`，未知类型改走 predicate/关键词并标 `match_basis`）。**来源 A 的完整重定映射或下线仍待 Owner 拍板** | `apps/api/app/api/v1/enterprise_profile.py` |
| B4 | 未动 | 依赖 B3 拍板；`_self_company_names` 兜底分支同因失效 | — |
| B5 | 已修 | `_load_knowledge()` 的 facts 改从 `get_entities()` 取 `object_type == "fact"`；文档块改读 `value/snippet` | `apps/api/app/api/v1/enterprise_profile.py` |
| B6 | 已修 | `_kernel_summary` 改按「有没有正文」分流，带上 predicate/value | `services/intelligence/reasoning.py` |
| B7 | 已修 | `_kernel_has` 去掉假阈值，改以权威侧 `matched`/`hits` 为准；`_fact_gate` 去掉 `best >= 0.5`，改为 `hit_name and related` | `services/intelligence/reasoning.py`、`services/content/__init__.py` |
| B8 | 已修 | 发布时落逐问基线（`before_snapshot["stats"]`），复测改用真差值 `delta_mention_rate`，无基线报 `level: "unknown"`；写 `content_impacts` 前删同 plan 旧行（幂等） | `apps/api/app/api/v1/distill.py` |
| B9 | 已修 | `cognition_evaluate` 改「全部批次算完再替换」；任一批失败 → 返回错误并**完整保留**上一轮评估（不落半份） | `apps/api/app/api/v1/distill.py` |
| B10 | 已修 | `GET /distill/plans` 不再写库（只对返回项即时标注）；`Store.save()` 按 id 保留既有行 `created_at`（列与 JSON 都不再被刷成同一时刻） | `apps/api/app/api/v1/distill.py`、`apps/api/app/services/store.py` |
| B11 | 已修 | 监测后自动链改为跑 2026-08-19 拍板的新算法 `gen_content_plan`（不再跑旧 `gen_plans`） | `apps/api/app/api/v1/monitor.py` |
| B12 | 已修 | 机会数只数在办（排除 archived/published/completed）；`/distill/faq` 补捕 `LLMNotConfiguredError`；`delete_question` 清 gaps 与计划悬空 `target_question`（不连坐删计划）；`delete_plan` 连带清 `content_impacts`；`_extract_fact_claims` 支持英文分句/动词/截尾；生成重试改指数退避（3 次）；前端平台补齐 14 个 | 多文件 |

验证摘要（隔离库，实跑）：`A1 materials_used 0→19`；`A3 total 0.28→0.85`；`A4 小红书 1500→1000`；
`B1 judged 0→2、未判定阶段 coverage=null`；`B9 3 条历史评估在 LLM 失败后 0 丢失`；
`B10 GET 前后 content_plans 行哈希全等`；产品门 `:8090/api/product/geo/*` 与 UI `:4173/app/geo` 端到端通过。
