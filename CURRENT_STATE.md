# GEO 当前现场

最后核实：2026-10-12（北京时间），两工作树按功能保全提交，当前源码候选与历史打包候选分别保留，不推送；[收口报告](docs/audits/2026-10-12-geo-git-closeout/报告.md)。真实链审计与重构候选已交付，正式后端适配与端到端验收仍 PARTIAL。只读探测8090 GEO门401、8091未监听，未登录核验主环境数据。规范入口见 [docs/README](docs/README.md)；历史现场见[归档](docs/archive/INDEX.md)。

## 1. 主轴

服从 [Foundation MAIN-AXIS](../eios-foundation/docs/engineering/MAIN-AXIS.md)：知识网络在主环境搭起来，产品消费已生效正式事实。GEO 对应 C4，并参与 C5–C7；10-08 资料草稿计划是历史成果索引，不代替现行主轴。

## 2. 连调条件进度

| 条件 | GEO 状态 | 证据与边界 |
|---|---|---|
| C4 正式 Fact 取材与出处 | 未验证 | Foundation 10-11 现场记 GEO 仍读旧关系/历史快照；主环境真实生成未验 |
| C5 三产品一致 | 未验证 | 同批 Fact ID 与内容一致未验 |
| C6 撤权/失效 | 未验证 | 10-09 拒绝不借快照为隔离自测，不是三产品主环境验收 |
| C7 重启/默认 5 秒 | 未验证 | 临时库独立进程读回不等于主环境服务重启验收 |
| C8 七类扩面 | 未验证 | 依赖统一正式读口及同批资料重跑；不按内部合同演进猜测产品字段 |

## 3. 施工卡

| 事项 | 状态 | 依据 |
|---|---|---|
| GEO 治理文档对齐 | 文档检查通过 | [10-11 证据](docs/audits/2026-10-11-geo-docs-alignment/报告.md)，用户直接授权；不授权代码 |
| 内容链局部候选 | 自测通过待验收 | [10-09 证据](docs/audits/geo-local-seams-2026-10-09/REPORT.md)；原卡保留，未登记为新主轴已批卡 |
| A5 GEO 正式读口迁移 | 后端隔离候选 PARTIAL | 用户明确批准路径和“先做后端适配”；[本轮授权](docs/decisions/2026-10-11-geo-backend-authorization.md)、[391通过/5跳过证据](docs/audits/2026-10-11-geo-consumption-plan/后端报告.md)；中控登记、共享身份/F7接缝及联合验收待交付 |
| GEO 演示样本与功能接线盘点 | 自测通过待验收；完整审计 PARTIAL | [10-12直接授权](docs/decisions/2026-10-12-geo-demo-ui-authorization.md)、[报告](docs/audits/2026-10-12-geo-demo-ui/报告.md)；36槽位/33回答/3失败，5项样例测试及隔离浏览器检查通过，后端391通过/5跳过；共享登记、独立旅程走查和真实接线未完成 |
| GEO 真实接线审计与产品重构方案 | 审计交付 DONE；端到端及独立走查 PARTIAL | 本轮用户直接授权继续审计并给方案；[真实链报告](docs/audits/2026-10-12-geo-real-wiring/报告.md)、[重构候选](docs/engineering/GEO-PRODUCT-RESTRUCTURE-2026-10-12.md)；临时库逐阶段写读回、两仓门对照、59项定向测试通过；未授权实施重构 |

## 4. 代码与环境现场

| 对象 | 最后核实 | 状态 |
|---|---|---|
| GEO 当前源码候选 | /Users/tutu/eios-product-geo；codex/geo-ui-layout；从a432683按功能提交，提交号见收口commits.json及分支git log | 初始60 tracked/108 untracked文件保留；Git干净验收见收口verification.json；未合入main、未推送、不是主环境验收 |
| GEO 历史打包候选 | /Users/tutu/eios-geo-package-session2/geo；codex/geo-package-preserved-20261012；从4cb0725按功能提交 | 独有DOCX/模板企业名过滤/交付稿/打包输入保留；未反灌当前正式来源链，未删除树 |
| 已有备份 | /Users/tutu/eios-backups/geo-worktree-organize-20261008；/Users/tutu/eios-backups/geo-two-tree-closeout-20261012-150316 | 原备份保留；本轮变更tar、patch、bundle及ignored资产私有备份已核；不入源码提交 |
| 控制面 | Foundation HEAD 094fca274d1e632897c632c977401891371f9b7a，加工作树现行文档 | CURRENT/Freeze 登记优先，非仅凭 HEAD |
| 工作树登记 | Foundation WORKTREES 待 WT1 填充 | 唯一写者/运行引用未完整登记，不宣称 active |
| 主环境 | Foundation CURRENT_STATE §4（10-11 记 8090 未连通、DRIFT 未清、KO=0） | 引用控制面记录，未独立运行探测；当前业务可用性未验证 |
| GEO UI 制品 | 10-12 演示检查仅输出任务临时目录 | 类型/5项样例测试/隔离构建通过，未覆盖在用 packages/geo/dist；10-09误写尚无可靠原制品恢复，当前served版本仍未知 |

## 5. 阻塞

- 真实接线审计已复现：Product API缺intelligence/progress放行且UI吞错；认知评估无主体/稳定原话归属导致跨主体读分；效果统计含失败槽位、缺主体与发布后时间窗，无新轮次仍出neutral。责任修复待独立卡，不在审计中改业务。严格首次用户走查尚缺独立目标度量，产品重构目前为候选。
- 路径及后端施工已获用户批准；C4 合法逐请求 reader 委托、冻结 dossier/chunk 读面及有界对象范围仍待唯一负责人交付，中控 A5 登记待同步。部署级 system 凭证不能替代当前员工。
- 同批生效 Fact 与精确 Evidence/chunk 引用、组合基线及主环境对齐待 A 线交付；不把旧 10-09 缺口当新版合同不存在。
- 公共入口取消未保证传至 GEO；关页不等于底层请求终止，需集成负责人交付证据。
- 在用 UI 制品误写的恢复需可靠原制品与明确操作范围；已有证据保留。

## 6. 待拍板

- 🟡 读取方向已批准；具体服务委托/冻结读面接缝由共享唯一写者交付，GEO不改身份签发、不复制PDP。
- 🟡 A5 后端四文件已施工，UI未施工；[后端候选](docs/audits/2026-10-11-geo-consumption-plan/后端报告.md)待独立验收，中控确认登记和组合基线。历史稿列表显示规则仍待Authority确认，不删旧稿、不把历史标签当当前资格。
- 🟡 UI 制品恢复：获得可靠制品后由运行负责人按明确范围执行，不猜测回填。

## 7. 暂停与范围外

- 后端四文件隔离适配已完成；10-12另获准完成演示夹具与必要前端接线，未授权的正式读口UI/共享接缝迁移、旧 candidate 链删除、历史数据修补仍暂停。391通过/5跳过及演示浏览器自测只证明隔离环境，C4–C8主环境仍未验证。
- 自动升版、新 pin 续跑、第二 chunk、跨 DOCX 补证、自动实质纠错、非 current 历史投影、VideoPublish 按主轴暂停。
- 不改 Foundation、Product API、Integrations、Provider、Release 及部署配置；不真实调用模型。本轮用户已明确授权两树现有成果本地分批提交，此前“不提交”限制在该范围内解除；仍不推送，不自动合并，不实施产品级重构。
- 范围外债统一登记见 [Foundation DEBT](../eios-foundation/docs/cards/DEBT.md)，本仓不另造共享登记。
