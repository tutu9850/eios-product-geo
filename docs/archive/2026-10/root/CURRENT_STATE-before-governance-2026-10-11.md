> 已归档 2026-10-11，原因：现场改按统一治理七节格式记录。不作施工依据；原文保留如下。

# GEO 当前现场与开发交接

## 2026-10-09 本地接缝冻结候选（PARTIAL）

旧分析、读取失败及域内截止预算已修，隔离全仓 368 passed/5 skipped；前端临时构建和四种组件时序验证通过。真实模型 0，未提交/推送。Knowledge 精确引用联合链待 A 线补充，公共取消传递仍待集成负责人。首次 UI 检查误覆盖本机在用 dist，已停止制品写入、未猜测恢复；不能声称运行页面完全未变。详见 [冻结候选报告](docs/audits/geo-local-seams-2026-10-09/REPORT.md)。

更新日期：2026-10-08，北京时间。本页是 GEO 当前施工入口；架构、身份与契约仍由现行规范决定。**最新状态：代码接缝继续施工，原稿出处改写接缝隔离验证 DONE；本轮尚未部署，完整业务卡仍 PARTIAL。**

## 工作树整理：内容链后端已独立提交

用户授权整理81项未提交状态。整理前已完整备份102个实际文件（Git将目录折叠为单条状态），备份在 `/Users/tutu/eios-backups/geo-worktree-organize-20261008/`。误做的内容稿及其卡移至该备份目录，未删除共享GEO中的稿件，未改业务库。全部既有代码字节与备份一致。

内容链后端及必需名称识别修复共14个文件，形成独立本地提交 `a432683`。用原HEAD加这14文件单独验证325 passed/5 skipped，证明不依赖其他未提交改动；完整工作树351 passed/5 skipped，check:ui通过。未推送、部署或改变产品门配置。

- [逐文件分组与Release阻塞清单](docs/engineering/GEO-WORKTREE-GROUPS-2026-10-08.json)
- 剩余分为界面与Host、监测与情报、企业资料与Knowledge、工程文档、开发启动配置。前端部分文件混合旧界面与内容链修复，未整文件误提交。架构草案仍是Draft，不作为正式规则或已批准Release声明。

本轮整理及后端分组DONE，完整Release准备仍PARTIAL。下一步应审阅并拆出UI内容链接线，再处理资料模式与GEO产品包；不能用当前工作树测试通过宣称这些未提交内容已进入release。

## 最新施工：回到代码接缝，修复改写原稿出处

用户明确纠正当前任务是 GEO 代码接缝。上一轮错误制作并保存了三篇草稿，属于执行偏离；保留记录，不据此推进内容业务或视为用户授权。当前目标仍为 CONTENT-01 及后续 Knowledge/Fact 消费接缝。

本轮修复 G-RW-01：改写此前只传文件ID并重新选段，现在前端传原稿出处，API核验当前柜原块及摘要后服务沿用具体选段。资料删除、篡改或不可读时模型调用前明确拒绝。六项新增测试含认证GEO产品门改写→保存→读回；351 passed/5 skipped，check:ui通过。没有部署本轮修改，也没有新增共享业务数据。

- [接缝报告与验证边界](docs/audits/geo-rewrite-seam-2026-10-08/REPORT.md)
- 下一步：Knowledge失败与快照失效、Product API模型时间预算；按既有开发计划继续，完整工程卡仍PARTIAL。

## 最新接线：共享本机页面已更新

用户在上一轮修复后明确“可以，继续”，授权接到现有页面。已安装本轮 UI 制品并按既有 wrapper 重启 GEO :8091；Client :4173 → Product API :8090 → GEO 的正式入口生成笔革 FAQ 成功，约 3.5 秒，来源及人工核验提醒实际显示。Foundation、Product API、Client 和静态服务未重启，身份、账号柜、scope 和清单不变。默认产品门仍 off，本机部署沿用原有显式 on。

25 份素材、5 份上传文件、180 段、93,013 字保留；没有新增测试资料或保存测试稿。正常页面读取刷新了一行企业知识缓存的元数据，缓存内容完全一致，其余 21 张表逐行摘要一致。没有重新解析历史上传；新上传才使用表格解析修复。

- [共享页面更新及运行验收](docs/audits/geo-shared-update-2026-10-08/REPORT.md)
- [本轮非敏感摘要](docs/audits/geo-shared-update-2026-10-08/evidence-summary.json)

**现在可刷新本机 GEO 页面使用资料驱动草稿链。** storage_mode 仍 legacy，不能宣称生产 canonical 存储已验收。评分仍是参考，正式 Fact/Evidence/Semantic、撤权和时间预算等待后续对应链验收。临时回退副本和验收浏览器清理，共享 GEO 持续运行。

## 最新施工结果

依据用户明确授权，三位 gpt-6-luna 修复文档读取、内容取材/改稿、UI；根 agent 整合来源校验、有限正文筛查和正式入口实走。DOCX 表格能完整读取，多问 FAQ 不再漏掉尺寸/颜色/面料、30—45 天、免费设计及售后；同篇素材贯穿改稿、保存、重开，待核验提醒也保留。历史生成稿不作独立企业事实，Knowledge 候选不混作正式依据，读取失败有真实提示。

- [本轮施工、真实链结果和剩余风险](docs/audits/geo-content-fleet-2026-10-08/REPORT.md)
- [非敏感验收摘要](docs/audits/geo-content-fleet-2026-10-08/evidence-summary.json)
- [下一步开发计划](docs/engineering/GEO-CONTENT-DELIVERY-PLAN-2026-10-08.md)与[施工卡](docs/engineering/CARD-GEO-CONTENT-01.md)

验证：全量 pytest **345 passed、5 skipped**（监测 PostgreSQL 环境未提供）；`npm run check:ui` 通过；笔革两份 DOCX 浏览器上传、真模型品牌介绍/改稿/FAQ、保存/正式读回、独立账号反例及私有进程重启读回成立。原文件只读、任务库隔离，临时服务/账号与测试产物验收后清理。审计目录的小量截图/摘要/问题样稿作为整链证据保留。

**上一轮隔离修复结束时共享页面尚未更新；本轮已按上节授权完成本机接线。Foundation/Product API 仍未修改，未提交/推送。** GEO 产品门默认 off，私有验收显式 on，清单/scope 不变。正文筛查有限，仍需人工核对，不能把结构评分或没有提示当全文正确。真实 FAQ 暴露了品牌与所属企业混写，已作为待核验条目保存；标题解析漏读也已修复并用同形返回测试。Foundation 正式 Fact/Evidence/Semantic、撤权/快照生命周期、代理35s/模型120s预算及正式部署验收仍待后续。

下方为此前调查与历史基线，不覆盖本节。

## 最新调查：笔革资料实走

用户授权先走一遍、定位问题并分析修改。本轮使用独立登录账号、临时数据库及 Client 34173 → Product API 38090 → GEO 38091，复用部署 GEO UI 18093 与统一 Model Capability 8094。完成品牌介绍生成、一次改写、一次 FAQ 生成；八类输入/读取反例；私有 GEO 实际进程重启读回。测试服务随后关闭，原文件和共享服务保留。

- [实走报告、首断点与修改顺序](docs/audits/geo-content-walkthrough-2026-10-08/REPORT.md)。
- [非敏感证据摘要](docs/audits/geo-content-walkthrough-2026-10-08/evidence-summary.json)及报告内浏览器截图/样稿；FAQ 未通过质量验收，不可直接发布。
- 最新 Product API 实际源码现场为 `/Users/tutu/eios-product-api-kn-v5`，HEAD `6e7c2304de8ef4d95354ae0980d4bda83076d23b`；前轮参考仓不代表当前运行。真实默认模型目录为 deepseek；未修改绑定。

已证明：访谈 2243 字/4 段完整上传；手册 7288 字/15 段上传但漏三张表格中的 69 个非空单元格文本；选材只截一段 400 字，FAQ 遗漏原文的 DIY、30—45天交付、免费设计和售后；改稿事实区没带上传选段（隔离 prompt 证据）；保存重开正文一致但没有本篇来源。上传资料在 UI 的参考资料数/依据评分被漏算。

35s/120s 时间预算风险仍在，但本轮 FAQ 3.45s 成功，**不认定它为当前实测超时阻塞**。本轮未测全量失败、Knowledge 撤权、正式 Fact 或共享部署验收。原卡业务 PARTIAL，后续优先资料解析/多段取材，再同篇来源贯穿，最后评分/核验及时间预算。以下前轮现场记录是历史基线，不覆盖本节。

## 当前目标与下一步

2026-10-08 用户补充：后续测试使用桌面 `/Users/tutu/Desktop/笔革家居GEO/` 的真实资料，对用户说明用大白话。已核对目录存在，包含主理人访谈纪要、现场调研手册、三品牌调研 PDF、两个 Markdown 导出、图片及服务合同。优先核对访谈纪要与调研资料；合同不默认作为可对外使用的宣传依据。测试读取原文件副本或只读原文件，写入仍使用任务专用临时库，不修改桌面原件或开发库。本次仅确认目录及上传代码，未上传、解析或调用模型。

优先交付：**企业资料 → 按主题取材 → 生成 → 按要求改写 → 保存草稿 → 重新打开并查来源 → 人工发布**。

- [开发方案与分阶段计划](docs/engineering/GEO-CONTENT-DELIVERY-PLAN-2026-10-08.md)：范围、Foundation 最低消费条件、接缝、依赖、验收与风险。
- [施工卡：GEO-CONTENT-01](docs/engineering/CARD-GEO-CONTENT-01.md)：调查已完成，业务 PARTIAL；最新实走结果及未验收项见卡末。
- [本仓工作规则](AGENTS.md)及[Foundation 唯一施工纪律](../eios-foundation/docs/engineering/EIOS-CONVERGENT-CONSTRUCTION-PROTOCOL-2026-10-05.md)：横向定位、纵向修复、回真实链验收。不得据此自行新增架构。

## 源码与运行现场

| 对象 | 2026-10-08 核对结果 | 结论边界 |
|---|---|---|
| GEO 工作树 | `/Users/tutu/eios-product-geo`；分支 `codex/geo-ui-layout`；HEAD `4cb07251e10601d2294b826ee5bdcb6d5f22aa83` | 大量既有未提交修改和未跟踪文件；研究依据是当前工作树，不是纯 HEAD |
| Product API 参考工作树 | `/Users/tutu/eios-product-api`；HEAD `e81f7742c423747e6131255517165669068139fa` | 只读参考，未修改；HEAD 不证明对应部署 |
| Foundation 文档控制面 | `/Users/tutu/eios-foundation`；HEAD `acc783f1a4002790dfd6ca9e79ab60c497819b50` | README 指向其 CURRENT_STATE；真实产品源码、恢复 worktree 与部署组合须按该现场重新核实 |
| 正在运行的 GEO / Product API / Model 服务 | 未核验 | 不宣称服务可用或业务上线 |
| GEO 正式业务存储 | 持有、初始化及部署选择未在本轮验收 | 开发 `geo.db` 不能直接当正式业务库 |

已有 dirty 涉及 API、UI、身份、情报及测试；本轮全部保留。下一轮修改前重新记录 HEAD、dirty、目标文件摘要、运行配置及对应任务范围。禁止用 reset、clean、整文件覆盖或未经核验的 worktree 切换制造干净基线。

## 已核对的源码事实

- 生成、改写、保存均有现成接口；上传文件 `source_type=file` 已进入生成素材，不重复建设。
- 模型调用经 `adapters/llm.py` / `adapters/model_entry.py` 使用部署统一 Model Capability；没有必要增加 GEO 自有 Provider 或凭据。
- GEO 默认消费账号柜内 Knowledge 快照；手动同步持有 `knowledge_read_grant("kb_sync")` 才允许实时 Knowledge 读取。
- 产品入口应为 Client → Product Host → Product API → GEO 产品门。生成、改写、保存已在现有门清单内；本轮未改变门或配置。门自身默认关闭，dev wrapper 有显式默认打开逻辑，两者不能混为当前部署状态。

## 待闭环接缝（源码候选，不是运行首断点证明）

| ID | 已观察的问题 | 后续证明与处理 |
|---|---|---|
| C01 | Product API 对 manage 请求通常给 35s，模型入口给 120s，生成另有重试 | 沿正式入口实测时间预算；耗时分类与 scope 分开，不为超时扩权 |
| C02 | 生成取上传素材，改写仅使用 `ctx.materials` 的 Knowledge 材料 | 证明同篇上传资料在改写时丢失，复用本篇资料上下文 |
| C03 | 生成来源中部分 Knowledge 元数据被压成文本；保存只收标题、正文和问题 | 保留选段、来源层次、版本/摘要；沿合法读门重开核对 |
| C04 | 本地 search 的 candidates 参数未过滤全部切块；快照补充和资产排序可能保留零相关项 | 核对现行 governed/material 含义，不机械关掉候选；筛选和标注须一致 |
| C05 | strict 主要查输入问题；输出正文与改稿尚无完整依据核验 | 金额、客户、案例、资质逐主张回指本篇资料；未知不冒充已核验 |
| C06 | 快照为空、失败、未同步、过期及当前权限变化尚未形成完整用户表达 | 不把旧快照当当前 active 事实；接 Knowledge 前验收生命周期 |
| C07 | 出站票默认 subject=`system:eios-geo`，不是登录用户；账号柜不等于 Foundation ACL | 核对执行身份、真实 Actor、enterprise/department/personal 可见性与撤权 |

具体源码入口、最小实现选择和范围见开发计划。候选问题须经真实或隔离原链定位 FIRST DIVERGENCE，不能按表一次性改所有模块。

## 验证证据与限制

2026-10-08 前轮研究使用 pytest 临时数据库，未修改开发库：

```bash
env -u GEO_DB_PATH PYTHONPATH=/Users/tutu/eios-foundation/packages/auth:/Users/tutu/eios-foundation/packages/policy \
  .venv/bin/python -m pytest apps/api/tests/test_geo_content_improve_save.py apps/api/tests/test_geo_knowledge_consumer.py apps/api/tests/test_model_entry.py -q
# 31 passed

env -u GEO_DB_PATH PYTHONPATH=/Users/tutu/eios-foundation/packages/auth:/Users/tutu/eios-foundation/packages/policy \
  .venv/bin/python -m pytest apps/api/tests/test_product_geo_door.py -q
# 21 passed

npm run typecheck:ui
# 通过
```

首次定向测试未提供 Foundation 包路径，有环境导入失败；补齐路径后通过。上述 Knowledge consumer 测试包含 GEO 向顾问提供快照的交接面，**不证明 GEO → Foundation 的实际身份和读取链通过**。模型测试也不证明真实 Provider 调用。

未执行：全量 `python -m pytest`、完整 `npm run check:ui`、真模型生成、浏览器整链、跨账号真实业务验收、保存后服务重启读回。本轮仅验证文档链接与 diff，详细记录见下一卡的 Result。源码具备入口、局部测试通过和历史 HTTP 200 均不能替代业务验收。

## Foundation 依赖与范围

第一阶段上传资料草稿只依赖正式身份/产品门和统一模型能力，不以完整 Knowledge/Fact/Semantic 治理为前置。第二阶段手动同步至少要在正式授权下读取一份真实原文、版本及来源；第三阶段正式 Fact 消费必须验证相关事实链与失效语义。

Foundation 2026-10-08 CURRENT_STATE 报告的 Phase 1 READY 限定于源码/隔离证据，未 GREEN_PHASE_1，部分历史样本已移除。不得复述历史样本为当前可见数据，也不得据此阻塞上传资料草稿。GEO 的旧 instance-relations 消费迁移属于另轮收口，不在第一阶段顺手迁移。

## 本轮结果与接手要求

**DONE：文档入口、方案与计划已建立。业务交付仍未验收。**

本轮文件：`CURRENT_STATE.md`、开发计划、下一张施工卡、README 导航、AGENTS 开工入口。未扩大到业务代码或跨仓写入。下一轮按当前请求确认具体执行范围，更新卡状态及本页，完成纵向修复结果与横向验收报告后再标业务 DONE。真实调用、共享服务重启、部署或数据迁移须在当前有效授权与纪律内执行。
