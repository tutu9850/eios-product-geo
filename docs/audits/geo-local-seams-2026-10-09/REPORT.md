# GEO 本地接缝冻结候选 · 2026-10-09

状态：PARTIAL。GEO 已有生成、改写、保存、读回入口；本轮修复旧分析、具名读取失败及域内截止预算，用受控替身验证。Knowledge→GEO 的真实同份精确版本资料联合验收仍未通过，不能据此宣布业务闭环。

## 有效范围与计划

沿用 2026-10-08 GEO-CONTENT-DELIVERY-PLAN 与 CARD-GEO-CONTENT-01，不新建整套系统。授权依据是 Owner 2026-10-09 本地隔离修补及露娜舰队指令。四产品总方案仍 PROPOSED。本轮没有提交、推送、真实模型调用、业务数据写入、公共接口修改或服务重启。

工作树 /Users/tutu/eios-product-geo；branch codex/geo-ui-layout；HEAD a432683beb8739b85a27acdde1fbcdb4dc1e1a35。开工前 66 条 dirty（50 tracked、16 untracked 折叠项），见 status-before.txt；既有备份 /Users/tutu/eios-backups/geo-worktree-organize-20261008。本候选基于原 dirty 工作树，不是从 HEAD 独立构建的提交。

## 最小修改面

- GeoContentGenForm.tsx / geo-api.ts：正文变更清空分析；稿件版本与取消信号挡住迟到评分/质检；保存期间锁住正文操作；展示具名读取状态。
- adapters/eios/__init__.py / kb_init.py / knowledge_snapshot.py：保留未同步、空、部分、拒绝、不可达、坏响应；实时拒绝不回退历史资格；历史快照仍保留，部分状态继续传递。
- services/content/__init__.py：传递原错误；当前拒绝清空本次知识来源；实时读取不借旧快照填空。
- adapters/llm.py / model_entry.py / content.py：复用 35 秒域内上限与有限重试；每次尝试前核剩余时间，超时/任务取消停止后续尝试，迟到结果不返回成功。
- 六个测试文件：覆盖上述接缝及保存后独立进程读回。完整路径、前后摘要见 manifest.json。

round.patch 是相对开工前文件的最小差异。selected-source.tar.gz 仅包含选定 15 个代码/测试文件的 before/after，不混装其余 dirty，也不是 Release 制品。

## 实际验证

全仓隔离测试：368 passed、5 skipped、6 warnings；跳过为 PostgreSQL 监测验收未配置。完整输出 pytest-final.log。环境使用已有 .venv 和 Foundation auth/policy/contracts Python 依赖，GEO_DB_PATH 指向任务临时库。

前端 check:ui 类型检查与构建通过；最终输出 /tmp/eios-test/geo-seams-20261009/ui-final，存在原有大 chunk 警告。实际组件闭包时序替身四种场景通过，见 ui-timing.log / ui-timing-check.cjs；这不等于浏览器/Host 联合验收。保存→两个独立 Python 进程读回正文和既有引用通过，不等于实际服务重启验收。

已验证新稿无旧分析、迟到评分/质检不覆盖新稿、保存时禁止正文竞态；读取状态与原错误保留；拒绝不借旧快照；域内截止及任务取消后不新增尝试、晚结果不成功落地。

## 尚未完成及公共入口需求

用户取消 fetch 不保证公共代理把取消传给 GEO ASGI 任务。GEO 会按原 35 秒截止停止等待；底层同步线程可能继续到 HTTP 自身超时。不得把 asyncio.to_thread 的取消描述成底层请求终止。公共入口负责人需统一传递剩余截止时间和取消，禁止代理重试扩大预算，并提供客户端断开后的后端尝试证据；本轮未改公共文件。

kb_init 的上游 detect 已将部分异常压成字符串，scan 此层只能报告 knowledge_unreadable；精确保真还需定位其责任读门，不猜造错误合同。

A 线已交付文件下载精确 version/hash；正文/chunk 读面尚未闭合精确历史版本、位置、Evidence 引用。需补合法 GEO 服务+Actor 资格、隔离地址、同企业同文档精确版本正文/chunk/hash/locator/Evidence 的现行合同及正式 canonical Fact 读门、删除/变版/撤权/恢复规则与样本。未实现猜测映射；错企业、错版本、错摘要、伪造选段的 Knowledge 联合拒绝及重开验证仍待这些条件，GEO 自上传测试不可替代。

不修改 Foundation、Integrations 三文件、Product API app/main.py、app/contracts.py、app/knowledge_network.py、tests/test_knowledge_network.py、app/domain.py；Provider 和 Release 副本亦未修改。Product API 预算/取消接缝交集成负责人，Knowledge DOCX 公共入口交知识库施工会话。

## 边界偏离记录

UI 子代理第一次运行 check:ui 未指定临时输出，覆盖了本机静态服务正在使用的 packages/geo/dist，可能影响随后页面加载。这是本轮非预期运行制品写入，不能无条件声称“运行页面未改变”。已停止继续写该目录，未重启服务，最终验证改用临时输出；未取得可确认的旧制品，不猜测恢复。需要已知可靠的原制品及明确恢复范围后处理。候选尚未按部署流程发布，后端服务未替换。

产品门配置未改；未扩展 Authority、公共合同或生命周期语义。整体保持 PARTIAL，停在候选审阅。
