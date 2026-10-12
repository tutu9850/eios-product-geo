# GEO Product Constitution / Object Model V1（Draft）

状态：**Draft，证据约束版**（2026-09-26）  
基线：`eios-product-geo` `codex/geo-ui-layout` @ `4cb07251e10601d2294b826ee5bdcb6d5f22aa83`

本文冻结 GEO Product 的对象语义、关系和计数口径。它是产品边界草案，不是迁移批准，也不把缺失的后端对象假定为已实现。`MUST`/`MUST NOT` 是本草案的规范用语；任何改变它们的实现都需要单独的 Owner 决策和施工卡。

## 1. 证据范围与当前实现分界

本草案只依据当前仓库可见的代码、测试和文档：

- Product-owned PostgreSQL 模型：`apps/api/app/product/persistence/models.py`；运行路径：`apps/api/app/product/runtime/monitor_run.py`；入口：`apps/api/app/api/v2/product_monitor.py`。
- legacy SQLite 模型：`apps/api/app/models/geo_models.py`；legacy 监测入口和历史形状：`apps/api/app/api/v1/monitor.py`。
- 分母与主体选择的回归约束：`apps/api/tests/test_geo_answer_denominator_audit.py`、`apps/api/tests/test_geo_subject_scope_and_top_words.py`。
- Product-owned 纵切片说明：`docs/audits/geo-product-p2-monitor-vertical-slice-2026-09-03.md`；产品健康审计：`docs/audits/geo-product-health-check-2026-09-26.md`。

仓库同时存在两条运行时：

1. **legacy 面**：`monitor_items`/`monitor_tasks` 写入 SQLite，`/api/v1/monitor/check` 和 `/batch` 把结果追加进 `monitor_history`，回答以 `questions[].engine_detail[]`（或单问的 `engine_detail[]`）出现；`GeoEvidence` 是另一张 legacy 表。
2. **Product-owned 面**：`geo_product.monitor_objects`、`monitor_tasks`、`monitor_runs`、`provider_attempts`、`observations` 等表形成一条受 ProductSession 约束的纵切片。`observations` 是 GEO 产品自己的观察记录，代码明确拒绝把它当 Foundation Evidence。

两条面在本草案中**不自动互相转换、不互相计数、不合并为一套事实**。健康审计已经把这视为双运行时/双真相风险；在迁移卡明确之前，任何跨面统计都必须说明来源面。

## 2. 对象词典（严格定义）

### 2.1 Subject（被观察主体）

**定义。** Subject 是 GEO 要回答“模型是否提到、如何描述、是否引用”的对象。它是被观察者的业务身份，不是一次配置、一次请求、一个模型或一条回答。

**现有落点。** Product-owned 面没有独立 `subjects` 表；`monitor_objects` 用四列表达它：`subject_namespace`、`subject_type`、`subject_id`、`display_name`。`monitor_runs`/`observations` 也复制了这组 subject 字段。legacy 面用 `monitor_id` 标识长期监测对象，品牌名称主要来自 `config_json.company` 或 `entity`。这些是当前仓库的事实，不能推导出一个尚不存在的 Subject Authority。

**规则。**

- Subject 身份必须由稳定的 namespace/type/id 组合（Product-owned）或已登记的 `monitor_id`（legacy）承载；显示名称、别名和模型原话不是身份。
- 同名字符串不得自动合并两个 Subject；多个品牌对象存在时，缺少选择必须保持“需要选择”，不能猜第一个。`all` 只能表示明确的全选范围。
- Subject 的状态不能由一次回答推断。归档/暂停是 Monitor 的生命周期事实；它们不删除历史回答或证据。
- `ProductSession.subject`（AuthContext 中的 `human:*`/`agent:*`/`system:*` principal）是调用者身份，永远不是业务 Subject。

### 2.2 Monitor（长期监测对象，Monitor Object）

**定义。** Monitor 是“反复观察一个 Subject 的配置和生命周期对象”。它提供监测类型、探针配置和状态，并可被多次运行。

**现有落点。** Product-owned 表为 `monitor_objects`：`id`、Subject 四列、`monitor_type`、`status`、`probe_config` 和时间列。legacy 表 `GeoMonitorItems` 提供 `monitor_id`、`type`、`status`，完整配置留在 `data_json`/`config_json`；API 允许 `brand`、`product`、`competitor`、`keyword`、`review`、`question` 类型。

**规则。**

- Monitor MUST reference exactly one Subject identity in its own scope；一个 Subject 可以有多个不同用途的 Monitor，但这些 Monitor 不因此变成一个 Monitor。
- `active`、`paused`、`archived` 是当前 legacy 生命周期值；Product-owned 状态由表中 `status` 承载。归档 Monitor 不得新运行，历史仍可读。
- Monitor 是配置，不是任务执行、回答、证据或报告；修改 `probe_config` 不得改写既有 Run/Answer/Evidence。
- 任务与 Monitor 的多对多关系只能通过现有 `monitor_task_objects`（或 legacy `item_ids`）表达；不能把 `task_id` 塞进 Subject 身份。

### 2.3 Monitoring Run（一次计划/手动监测运行）

**定义。** Monitoring Run 是一次按 Monitor/Task 作用域执行探针并记录执行状态的事件。它回答“这一次运行何时被请求、由谁触发、成功还是失败、产生了哪些观察”。

**现有落点。** Product-owned 表 `monitor_runs` 有 `id`、可选 `task_id`/`monitor_object_id`、`status`、`trigger_type`、发起者、trace、幂等键和请求/开始/结束时间。它由 `ProductMonitorRunService` 与 `product_tasks`、`provider_attempts`、`observations` 一起写入。当前 builder 可能把 `task_id` 留空，所以不得声称每个 Run 都已经来自持久化调度 Task。legacy 批量历史中 `h_*` 记录和其中的 `questions[]` 是兼容面的 run-like 记录，不是 Product-owned `monitor_runs`。

**规则。**

- 一个 Run 是一个执行生命周期；Provider 重试属于 `provider_attempts`，不是多个 Run。
- Run 成功只说明执行链完成并写入 Observation；它不说明 Subject 被提及，也不说明回答有外部证据。
- 失败、超时、恢复要求在 Run/Attempt 状态中如实保留；失败不得被改写成“没有提及”。
- 同一幂等键在同一 deployment/enterprise scope 下只能产生一次 Run；相同请求可以回放既有结果，变更请求必须冲突。

### 2.4 Quick Check（单问即时检查）

**定义。** Quick Check 是用户临时提出一个问题并立即询问当前可用模型的单次检查。它验证一个判断，不改变定时监测配置。

**现有落点。** legacy 入口 `POST /api/v1/monitor/check` 接收 `question`、可选 `monitor_id`/`company_name`、`engines`、`full`；当传入 `monitor_id` 时，后端只接受当前租户中启用的企业品牌，读取其 canonical company 与 aliases，并把 `monitor_id` 同时写入 `monitor_history` 的顶层和 `questions[]`。成功后追加一条 `monitor_history`（`h_*`），内含 `question`、`company_name`、`summary`、`engine_detail`；后续 Evidence 适配器沿用同一 `monitor_id`。多个启用品牌时 Client 必须明确勾选一个，不能猜第一个。

**规则。**

- Quick Check MUST be treated as ad-hoc check, not as a scheduled Monitoring Run；它不继承 Monitor 的趋势点、任务周期或对象计数。
- Quick Check 可以产生 Answer candidates；没有有效模型回答时，它只能报告“未回答/依赖不可用”，不能报告“未提及”。
- Quick Check 的结果只有在明确写入产品-owned Run/Observation 关联后，才能进入该 Monitor 的跨次趋势；当前 legacy 形状没有这条关联，默认不得混入。
- 空问题会直接返回空结果而不形成可计数的检查；模型服务完全不可用时，错误必须保留为错误，不创建伪回答。

### 2.5 Answer（模型回答）

**定义。** Answer 是一个模型/引擎针对一个问题，在一个 Run 或 Quick Check 中实际返回并完成最小解析的回答单元。一个问题被六个模型回答，原则上是六个 Answer；它们不能合并成一条“综合答案”。

**现有落点。** legacy `engine_detail[]` 行包含 `engine_name`、`mentioned`（可空）、`rank_est`、`sentiment`、`snippet`、`source`、`citations`、可选全文 `answer` 和 `error`。`full=false` 时全文可以不返回，但只要 `mentioned` 有布尔值，该行仍是有效模型回答。Product-owned 面没有 `answers` 表；`observations` 是 Provider 返回的原始文本记录，`observation_extractions`/`brand_mentions` 是后续解析表，因此 Answer 目前是兼容面行或未来投影概念，不得当作已落库的 Product-owned 权威对象。

**规则。**

- `mentioned=true` 是“回答中命中 Subject 的解析结果”；`mentioned=false` 是“有效回答中未命中”；`mentioned=null` 或带 `error` 的行是未回答/未判定，不能算 Answer 的负结果。
- 一个 Answer 只属于一个问题、一个模型来源、一个 Run 或 Quick Check；同一回答内重复出现 Subject 只算一个 Answer。
- `rank_est`、`sentiment`、`recognition` 是 Answer 的解析属性，不是 Subject 状态，也不能反向修改 Monitor。
- Answer 不等于 Provider Attempt：Attempt 记录调用生命周期；Provider 失败可有 Attempt 而没有 Answer。

### 2.6 Evidence（证据）

**定义。** Evidence 是能够回指来源和观察时间的原始材料或引用片段，用于支撑“回答中说了什么/引用了什么”的审计。Evidence 必须保留来源标识和原始内容；推测、指标和 UI 摘要不能冒充 Evidence。

**现有落点。** legacy `GeoEvidence` 的实际列为 `source_type`、`platform`、`url`、`subject_company`、`raw_text`、`context_json`、`parent_ref`、`observed_at` 和 `tenant_id`，当前 V1 默认接 `ai_answer`。Product-owned `observations` 强制 `source_key`、`raw_text`、`content_hash`、`observed_at`，可有 `platform`/`source_url`/`provider_payload`；代码明确注释“never accepts a Foundation Evidence ID”。因此 Product Observation 不是 Foundation Evidence，`foundation_object_ref` 只是引用槽位。

**规则。**

- Answer 可以有零个或多个引用/证据关联；没有 Evidence 不得把模型陈述升级为企业事实或“已核验”。
- `citations[]`、`brand_mentions`、`evidence_quote` 是关联/解析结果，不自动等于独立 Evidence 行；不能按它们的条数代替 Evidence count。
- GEO Product 不得复制、代管或重新命名 Foundation Evidence；需要 Foundation 证据时只能保留合法引用，不能从本地 Observation 推导 Foundation 权威。
- 空 `raw_text`、缺 `source_key`/`parent_ref`、缺 `observed_at` 的记录不是可用 Evidence；应保留失败/缺失状态或拒绝写入。

## 3. 允许关系

```text
Subject 1 ────< Monitor 1 ────< Monitoring Run
                         ▲             │
                         │             ├──< Provider Attempt
Task >────< Monitor      │             └──< Product Observation

Quick Check ────< Answer candidate ────< (0..*) Product Evidence / citation reference
Monitoring Run ──< Answer candidate ────< (0..*) Product Evidence / citation reference
```

关系约束：

1. `Monitor` 是 Subject 的长期观察配置；`Monitoring Run` 是执行事件；`Quick Check` 是没有调度语义的单问入口。
2. 当前 Product-owned schema 中 `monitor_runs.task_id` 与 `monitor_object_id` 可空，且 v2 纵切片 builder 把 `task_id` 留空；因此上图的 Run→Monitor/Task 只能在实际关联存在时成立。
3. `Provider Attempt` 只能挂在 Run 上；`Observation` 只能挂在 Run（或明确的无 Run 采集场景）并带自己的 source identity。
4. Answer 是对返回结果的最小解析单元；Evidence 是来源材料。二者允许引用关系，不允许类型合并。
5. 所有关系均受 ProductSession 的 `deployment_id`/`enterprise_id` 或 legacy tenant scope 约束；跨柜查询或跨企业拼接必须拒绝。

## 4. 明确禁止的合并

| 禁止合并 | 原因 | 证据锚点 |
|---|---|---|
| Subject = Monitor | Monitor 是配置/生命周期，Subject 是被观察业务身份 | `monitor_objects` 同时保存 subject 四列与 monitor 自身 `id/status`；legacy `monitor_id` 亦为对象身份 |
| Monitor = Task | Task 是调度配置；关系表可绑定多个 Monitor | `monitor_task_objects`、`GeoMonitorTasks.item_ids` |
| Monitoring Run = Quick Check | v2 Run 有幂等/Attempt/Observation；`/monitor/check` 没有 monitor_id/run_id | `product_monitor.py`、`monitor.py:check` |
| Provider Attempt = Answer | 调用可以失败/超时而没有回答 | `monitor_run.py` 的 `_call_provider` 与 `_finish_failure` |
| Answer = Evidence | 模型输出是观察/回答；Evidence 要有可回指来源 | `GeoEvidence` 列、`observations` `source_key/raw_text/content_hash` |
| Observation = Foundation Evidence | Product-owned 观察不接受 Foundation Evidence ID | `build_observation_insert` 注释与 P2 审计 |
| `engine_detail` 空壳 = Answer | `mentioned=None`、空 answer/snippet 表示未回答 | `test_geo_answer_denominator_audit.py` |
| 多模型行 = 一条综合答案 | 每行有独立 engine_name 与独立 mentioned/error | `monitor.py` 的逐引擎 `_run_check` |
| 重复引用/提及 = 多个对象 | 同一回答中重复 Subject 只能保留一次命中 | `test_geo_answer_denominator_audit.py`、`test_geo_subject_scope_and_top_words.py` |
| 失败/未知 = 0 分 | 无数据与真实 0 分必须分开 | denominator audit tests 对 `None` 与真实 0 的断言 |

## 5. 证据不足和失败行为

### 5.1 没有有效回答

- 引擎未配置、调用失败、超时或返回空文本：保留错误/未回答状态；`mentioned` 为 `null`（若现有行已如此表示），不进入“未提及”分母。
- 某问题所有引擎都未回答：`answered_count=0`，提及率/覆盖率为“未判定/无数据”；不得渲染成真实的 0%。现有 legacy 某些 summary 将无回答的 coverage 写成 `0`，该值在本草案下不具备业务分数含义，消费者必须同时看 answered 状态。
- Provider-owned v2 失败会把 Attempt、Run、ProductTask 标记失败；不得写入伪 Observation/Answer。

### 5.2 没有 Evidence 或引用

- 有 Answer 但无 citation/source：可以显示“回答存在、来源未提供”，不得声称“企业事实已核验”。
- GEO 本地知识检索无命中时必须返回空命中；不得拿“最新资料”凑数。该规则由 `test_geo_read_gate.py` 固定。
- Evidence 读取失败、快照未同步或来源过期时，结论必须保留“证据不足/不可判定”解释，不降级成肯定事实。

### 5.3 Subject 不明确

- 没有品牌 Subject、存在多个候选却未选择、或传入未知 `monitor_id`：拒绝猜测；返回待选择/未判定结果，不能拿第一个对象代替。
- `all` 是显式全选范围，不是默认合并；汇总必须保留范围说明。
- 归档 Monitor 不可运行但可读历史；暂停 Monitor 不得被偷偷当成 active。

## 6. 对象计数与指标分母

### 6.1 计数定义

| 名称 | 一项代表什么 | 计数单位 | 不得用什么代替 |
|---|---|---|---|
| `subject_count` | 去重后的业务 Subject | 稳定 Subject 身份 | 显示名、回答数；当前仓库无 Subject Authority 时不得伪造此数 |
| `monitor_count` | 长期监测配置 | `monitor_objects.id` 或 legacy `monitor_id` 一项 | Run、Task、Answer |
| `active_monitor_count` | 当前可运行 Monitor | `status=active` 一项 | `items.length`（它含 paused/archived） |
| `task_count` | 调度配置 | `monitor_tasks.id` 或 legacy `task_id` 一项 | 运行次数 |
| `run_count` | Product-owned 执行生命周期 | `monitor_runs.id` 一项 | Provider Attempt、Observation |
| `quick_check_count` | 已持久化的单问检查记录 | legacy `monitor_history.id` 中的单问记录一项 | 每个引擎行 |
| `probe_count` | 被尝试的“问题 × 引擎”单元 | `questions[]` × `engine_detail[]` 一项 | 批次条数；测试明确 2 问 × 6 引擎 = 12 probe rows |
| `answer_count` | 有效模型回答 | `engine_detail` 中 `mentioned != null` 且无错误的一项（当前统计口径） | 所有 engine rows、配置数量 |
| `not_mentioned_count` | 有效回答中未命中 | Answer 中 `mentioned=false` 一项 | 未回答行 |
| `evidence_count` | 持久化来源材料 | `GeoEvidence` 或明确的 Product Observation 行一项，必须标来源面 | citation、mention、quote 条数 |
| `provider_attempt_count` | Provider 调用生命周期 | `provider_attempts.id` 一项 | Answer、Run |

当前仓库没有独立 Subject 表和 Product-owned Answer/Evidence 表；因此 API 在没有明确 owner/迁移卡前 MUST 报告实际的 `monitor_count`、`run_count`、`probe_count`、`answer_count` 等可观测计数，并标明 legacy/Product 来源面，不能把它们包装成 `subject_count` 或 Foundation Evidence count。

### 6.2 提及率、覆盖率和趋势

- 单问题/单批次提及率的分母是**有效 Answer 数**，分子是其中 `mentioned=true`；未回答/失败/未配置的引擎不进分母。`test_geo_answer_denominator_audit.py` 固定了这一点。
- “没有回答”与“回答了但没有提及”是两种不同状态；前者不产生 0 分，后者才产生 `mentioned=false`。
- 跨次趋势一个点代表一个 Monitor 的一次批次/Run 时间点；同一批次的多个问题先按本次定义聚合，不把每个模型行画成一次运行。legacy `item_trend` 已按时间戳把同批问题合为一点。
- 未完成解析的 rank/sentiment/citation 只能为未知或空；不得从提及布尔值补出排名、情绪或引用。
- 竞品/行业/信源聚合必须保持 Subject/Monitor 过滤；“同一句话重复出现”不增加 Subject 命中数。

## 7. 实施边界与后续门

本文件只冻结语义。以下事项仍是后续施工卡，当前不得默认为已完成：

1. 建立 Subject Authority，并决定是否允许一个 Subject 拥有多个 Monitor、如何跨 legacy/Product 映射。
2. 决定 Product-owned Answer 是否落库，及其与 `observations`/`observation_extractions` 的关系。
3. 决定 Product Evidence 的正式 owner；在此之前，不能把 Product Observation 升格为 Foundation Evidence。
4. 把 Quick Check 从 legacy history 迁移到 Product-owned Run/Observation 合同；当前 `monitor_id` 已能约束 legacy 的主体范围，但仍不是 Product-owned Run 关联。
5. 统一“无回答”的 HTTP/Result 表达，修复现有 summary 把无回答 coverage 写成 0 的歧义。

任何实现必须先通过对象关系、计数分母、tenant/deployment 隔离和失败行为的回归测试，再进入产品门；本草案没有授权修改产品代码或数据库。
