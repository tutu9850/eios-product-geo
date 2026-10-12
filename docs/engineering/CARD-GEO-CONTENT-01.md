# CARD-GEO-CONTENT-01 · 资料驱动内容草稿交付

- Owner：当前用户；具体执行范围以接续请求为准。
- Repository/repositories：主责 `eios-product-geo`；Product API 时间预算风险记录为后续依赖，本轮不改相邻 dirty 工作树；Foundation 只读契约核对。
- Status：**PARTIAL（本轮本地修复与资料草稿隔离链 DONE；本机共享页面已接线，正式业务/完整验收尚未完成）**。
- Created：2026-10-08，北京时间。
- 本轮实际范围：修复已证实的 DOCX 漏表格、多段取材、同篇改稿/保存/读回出处、有限正文筛查及 UI 真实反馈；Foundation 保持只读；后续用户授权本机共享 GEO 更新见新增验收结果。

## Background

生成、改写、保存、上传切块和统一模型入口已存在。工作树静态观察发现改稿未注入上传资料、保存未保留本篇来源、代理与模型时间预算不一致、候选/快照层次及输出主张核验未闭环。它们是候选接缝，尚未证明当前部署首偏离。

详见[开发方案](GEO-CONTENT-DELIVERY-PLAN-2026-10-08.md)与[当前现场](../../CURRENT_STATE.md)。

## Goal / MISSION

经正式 EIOS 入口，用当前账号一份真实企业资料生成企业介绍及产品 FAQ，按要求改写，保存并重新打开；正文具体主张有对应资料依据，来源仍可查，账号隔离和错误传播成立。最终为人工审核发布的草稿。

五问：用户是企业内容负责人；动作是上传、选材、生成、改稿、保存、重开；输入是授权资料和主题；预期是同篇依据贯穿；最终可见正文、来源、待核验项和真实保存状态。

## Existing authority and evidence

- Architecture：本仓 AGENTS、产品门矩阵；Foundation 总/架构宪法及产品连接标准。
- Discipline：引用[唯一施工纪律](../../../eios-foundation/docs/engineering/EIOS-CONVERGENT-CONSTRUCTION-PROTOCOL-2026-10-05.md)，不新建架构规范。
- Contracts：现有 Product Host、ProductSession/AuthContext、GEO 路由 envelope、Model catalog/invocation；开工逐项核对实际版本与约束。
- Ownership：GEO 拥有草稿资产与产品诊断；Knowledge 拥有 Document/Evidence/Fact；Semantic 拥有 Definition；模型 Provider/binding 由统一能力入口治理。
- Existing implementation：`content.py`、`services/content/__init__.py`、`knowledge.py`、`knowledge_snapshot.py`、`adapters/eios`、模型适配与相关 UI。
- Tests：前轮定向 31 + 产品门 21 项通过，UI 类型检查通过；证明范围见 CURRENT_STATE，不视为真实整链证据。

## Allowed changes / IN（后续执行候选）

1. 先核实际现场与链路，逐跳留输入/输出、身份、scope、版本、错误和副作用证据。
2. 在已明确语义和获准文件范围内修现有内容链：主题相关选段、同篇资料贯穿生成/改写/保存/读取、来源分层及输出主张诊断。
3. 核对现有产品字段是否可保留来源元数据；复用素材和切块能力，不重做 file 支持。
4. 必经 Product API 时间预算接缝在对应仓范围明确后收口，不通过改 scope 解决超时。
5. 在任务专用临时库与端口执行正反例、正式入口 UI 和获准重启读回。

本列表不是文档轮对代码/跨仓/运行的自动授权；开始执行时依据当前用户请求更新 Status、范围和 REAL CHAIN GATE。

## Forbidden changes / OUT

不绕 Product API；不直接接 Provider/凭据；不新增 Authority、Evidence Registry、Ledger、正式状态或架构代际；不复制 canonical；不越权读写 Foundation DB；不扩大权限；不把模型核验结果激活成 Fact；不修改开发库或清理历史；不迁移监测/情报/旧关系；不建设自动发布、队列、Foundation 治理流水线。

## Contract and data impact

- API/schema：保持现有语义，来源投影扩展须核对上下游；是否需要 schema 变化尚未证明，不能预先决定新增表。
- Persistence/migration：首选现有 GEO 产品记录；不回填旧稿引用，不改历史；旧稿无来源就明确无记录。
- Auth/PDP：全部复用验证后的当前 scope/cabinet；素材请求字段不授予可见性；服务主体不冒充登录用户。
- Cross-repo：Product API 超时是拟议依赖；Foundation 当前真实源码/部署须按其 CURRENT_STATE 核查，文档控制面不等于运行代码。

## 当前有效授权 · 2026-10-08

Owner 明确请求“开启露娜舰队施工”。三位 gpt-6-luna 分别负责文档解析、取材改稿、UI，根 agent 整合保存校验和验收。用户指定真实资料并已授权实走，续测限两份 DOCX、独立两个测试账号、任务库/媒体/制品和私有 Client/Product API/GEO 进程；复用统一模型入口，目标品牌介绍/FAQ/改稿各一次，额外调用仅用于已证实阻塞的有限复验，不启动 worker 或改共享服务。当前 dirty 全保留，不提交或部署。本轮新增制品临时输出开关属于测试卫生，产品门名单/scope/默认关闭不变。

## REAL CHAIN GATE

用户已指定 `/Users/tutu/Desktop/笔革家居GEO/` 为测试资料来源；真实样本优先访谈纪要及调研材料。原件只读，写入仍限任务专用临时库。此补充明确资料选择，不自动表示共享部署、重启或无限模型调用预算已获授权。前端经“内容资产 · 文件管理 → 上传文件”进入，核对 DOCX 表格是否完整提取及各文件实际解析结果；对用户用大白话说明。

执行前记录：GEO/Product API/Model 源码与部署组合、隔离库/媒体路径/端口、Actor 与服务执行身份、可用默认模型、调用预算与停止条件、允许的数据、是否允许共享服务重启。未获准真实调用时仅做只读或隔离验证，标记真模型/真实写入/重启未验证。不得加载旧任务授权来启动 Provider 或 worker。

## Acceptance criteria

- [x] 证明实际 FIRST DIVERGENCE，完成责任模块及同层同类/双实现调查。
- [ ] 用户已明确身份且有上传资料时能进入合法草稿链，不以缺 Semantic 或 Knowledge 实体统一阻塞。
- [ ] 真模型生成企业介绍和 FAQ；主题及产品/公司归属正确。
- [ ] 金额、客户、案例、资质等主张可回指本篇资料；未支持项删去或标待核验，不显示全文已验证。
- [ ] 上传资料、Knowledge 原文、正式 Fact、历史稿层次清楚；历史稿不当独立事实依据。
- [x] 改写沿用同篇材料；修改后的正文和来源对应。
- [x] 保存后正式读门及 UI 重开得到相同正文、来源与诊断；获准的专用服务重启后再次读回。
- [ ] 两账号及跨企业反例无素材/草稿泄露；tenant/body 不覆盖已验证身份。
- [ ] 十一类失败矩阵逐项记录，通过原调用链显示真实错误；未测/不适用明确说明。
- [ ] 所有要求的回归完成，最终纵向结果与横向验收报告链接回 CURRENT_STATE。

## Verification commands

执行前在 `/tmp/eios-test/geo-content-01/<session>/` 创建专用目录，显式设置 GEO_DB_PATH 和经核实的媒体/缓存路径。保留部署要求的 Foundation 包路径。至少运行：

```bash
python -m pytest
npm run check:ui
```

另运行定向内容、产品门、账号隔离、来源和模型契约测试；Product API 修改按该仓纪律验证代理超时和身份。完整 UI 检查涉及构建，执行前核对输出目录，使用临时输出，不覆盖既有产物，不提交构建文件。命令输出不是验收替代物；补 WRITE → READ BACK → VERIFY 的五层证据。

## Risks and stop conditions

dirty/部署组合不明先调查；来源保存复用不可行、需要新 schema、正式身份/权限/合同语义裁决时停在该接缝，附最小待决；不因普通字段漏传或错误投影机械请示。Provider 连续失败不得无限重试；保存失败不能伪装成功；过期/撤权快照不能作当前权威事实。范围外问题记录，不顺手施工。

## 本轮施工结果 · 2026-10-08

Owner 明确授权露娜舰队施工，实际落地解析、多问取材、同篇改稿/来源保存校验、有限主张提醒与 UI。三位 Luna 的代码由根整合，完成正式产品门隔离真模型与浏览器验收，详见[施工验收报告](../audits/geo-content-fleet-2026-10-08/REPORT.md)。完整 pytest 345 passed/5 skipped；check:ui 和 diff check 通过。既有 dirty 保留，默认产品门关闭、私有门显式打开，scope/清单不变；未跨仓、未改共享部署或开发库。额外修复真实 FAQ 暴露的标题解析、增加隔离制品输出开关，未扩大产品能力。

本轮代码修复 DONE；整卡 PARTIAL。真实 FAQ 仍有品牌归属写法和承诺待人工核验，不勾选“归属正确”；有限筛查不是全部主张验真。完整十一类失败矩阵、Foundation 正式链/撤权和共享部署验收未完成。

## Result（历史轮次）

### 2026-10-08 · 用户授权的先实走后分析

最新结果见[实走报告](../audits/geo-content-walkthrough-2026-10-08/REPORT.md)，覆盖本节下方旧文档轮的 PROPOSED 状态。真实品牌介绍与改写走浏览器，FAQ 走同一正式 HTTP 产品门；八个失败/隔离反例及私有 GEO 进程重启读回已执行。上传访谈完整、手册漏表格；生成选材遗漏已存在信息；改稿未注入上传来源；保存正文但丢本篇出处；UI 资料数/评分漏算。Sources/正文主张检查仍未过，因此上方整体验收项不勾选，业务 PARTIAL。

Actual files：current、计划、本卡、实走报告与非敏感证据/截图/问题样稿；没有业务代码修改。Actual verification：浏览器操作、正式 HTTP、原文比对、隔离 prompt 捕获、私有进程重启读回及文档检查；没有全量 pytest/check:ui。Scope expansion：no，未改相邻仓代码或共享部署，真实测试数据仅任务库。下一步修改按报告优先级，不把本轮调查当已完成修复。

2026-10-08 文档轮：新增 CURRENT_STATE、本开发计划和施工卡；README 与 AGENTS 增加入口。文档相对链接及新增内容 diff 检查通过；未运行本卡的业务测试、模型、部署或业务写入。本卡维持 PROPOSED，不勾选业务验收项。

- Actual files：`CURRENT_STATE.md`、`docs/engineering/GEO-CONTENT-DELIVERY-PLAN-2026-10-08.md`、本卡、`README.md`、`AGENTS.md`。
- Actual verification：本轮文档链接存在性及 `git diff --check`；前轮局部测试另见 current。
- Scope expansion：no；仅 GEO 文档，未改相邻仓与既有业务 dirty。
- Final status：**DONE（文档交付）；业务卡 PROPOSED，整链未验收。**


## 续接结果：共享本机页面更新 · 2026-10-08

Owner “可以，继续”确认前轮所述下一步，授权安装已有验证制品并更新共享 GEO。现有 wrapper 重启 :8091，界面沿用正式 /product/geo/；浏览器正式链生成笔革 FAQ 成功约3.5秒，来源/提醒显示；数据25份素材保持，未保存测试稿。正常读取刷新企业知识缓存元数据，缓存内容一致，其他21张表一致。详见[运行验收](../audits/geo-shared-update-2026-10-08/REPORT.md)。本次更新 DONE，整卡仍 PARTIAL（正式存储/完整失败与Foundation链未完成）。范围扩展仅由本次用户明确授权进入本机接线；没有跨仓修改、权限改变、数据迁移或生产部署。

## 当前续接：G-RW-01

用户纠正当前工作是代码接缝。原稿具体选段在改写请求中漏传，已修复 UI→API→服务来源贯穿并复用当前柜校验。[报告](../audits/geo-rewrite-seam-2026-10-08/REPORT.md)记录351 passed/5 skipped、UI通过、认证产品门改写保存读回及四类反例。源码修复DONE；共享部署与完整Client/Product API链尚未复验，整卡PARTIAL。后续按原计划收口Knowledge读取/失效与模型预算，不执行业务稿交付。
