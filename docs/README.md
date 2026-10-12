# GEO 文档导航

按 2026-10-11 Foundation 治理体系对齐。此页只导航，不授予业务施工权限；共享规范唯一正文留在 Foundation。有效性以其 [DOCUMENT_REGISTRY](../../eios-foundation/docs/DOCUMENT_REGISTRY.yaml)、[裁决](../../eios-foundation/docs/decisions/2026-10-11-main-axis.md)及[冻结登记](../../eios-foundation/docs/decisions/FREEZE-REGISTER.md)为准。

## 开工阅读

1. [本仓工作规则](../AGENTS.md)及[当前现场](../CURRENT_STATE.md)。
2. [Foundation AI 入口](../../eios-foundation/AGENTS.md)、[当前现场](../../eios-foundation/CURRENT_STATE.md)、[唯一主轴](../../eios-foundation/docs/engineering/MAIN-AXIS.md)。
3. Foundation 控制面的已批施工卡、[施工纪律](../../eios-foundation/docs/engineering/EIOS-CONVERGENT-CONSTRUCTION-PROTOCOL-2026-10-05.md)。该文件名保留 10-05，正文已是 10-11 版。
4. 按 [Foundation 任务阅读表](../../eios-foundation/docs/README.md#task-routing)加读；设计或下结论前查[系统认知层](../../eios-foundation/docs/system/README.md)及[术语表](../../eios-foundation/docs/system/GLOSSARY.md)。骨架中的 UNKNOWN 不等于能力不存在。

## 按工程任务查规范

| 任务 | 唯一正文 |
|---|---|
| 定位、修补、失败链、代码评审、测试 | [施工纪律](../../eios-foundation/docs/engineering/EIOS-CONVERGENT-CONSTRUCTION-PROTOCOL-2026-10-05.md) |
| 设计、复用举证、合同版本 | [设计方法](../../eios-foundation/docs/engineering/EIOS-DESIGN-METHOD.md) |
| 分工、预算、集成、成果收割 | [运行模型](../../eios-foundation/docs/engineering/EIOS-OPERATING-MODEL.md) |
| worktree、唯一写者、请求/回复单 | [分支与多会话](../../eios-foundation/docs/engineering/EIOS-BRANCH-WORKTREE-SESSION.md)；[登记](../../eios-foundation/docs/system/WORKTREES.md)、[请求登记](../../eios-foundation/docs/system/HANDOFFS.md)由中控维护 |
| 跨仓方案、母卡/子卡、组合基线 | [跨仓变更](../../eios-foundation/docs/engineering/EIOS-CROSS-REPO-CHANGE.md) |
| 审批与委托、独立验收 | [审批](../../eios-foundation/docs/engineering/APPROVAL-AND-DELEGATION.md)、[验收诚信](../../eios-foundation/docs/engineering/VERIFICATION-INTEGRITY.md) |
| 写代码、发布 | [编码](../../eios-foundation/docs/engineering/CODING-STANDARDS.md)、[发布与变更](../../eios-foundation/docs/engineering/RELEASE-AND-CHANGE.md) |
| 环境、资料、凭据 | [环境](../../eios-foundation/docs/runbooks/environments.md)、[数据与样本](../../eios-foundation/docs/runbooks/data-and-samples.md)、[秘密](../../eios-foundation/docs/runbooks/secrets.md)；[数据治理](../../eios-foundation/docs/engineering/DATA-GOVERNANCE.md)仍有待复核语义 |
| 事故、文档检查 | [事故](../../eios-foundation/docs/engineering/INCIDENT-AND-POSTMORTEM.md)、[治理自动检查](../../eios-foundation/docs/engineering/GOVERNANCE-AUTOMATION.md)（设计未实现） |
| 研究、新产品 | [研究方法](../../eios-foundation/docs/engineering/EIOS-RESEARCH-METHOD.md)、[立项](../../eios-foundation/docs/engineering/EIOS-PRODUCT-INCEPTION.md) |
| 方向、优先级、卡模板 | [路线图](../../eios-foundation/docs/engineering/ROADMAP.md)、[总优先级](../../eios-foundation/docs/engineering/MASTER-PRIORITIES.md)、[卡模板](../../eios-foundation/docs/engineering/CONSTRUCTION_CARD_TEMPLATE.md) |
| 在途任务切换 | [10-11 切换说明](../../eios-foundation/docs/engineering/ROLLOUT-2026-10-11.md)、[治理修订裁决](../../eios-foundation/docs/decisions/2026-10-11-governance-owner-revisions.md) |

## GEO 接缝与本仓资料

- C4：稿件只取材于已生效正式 Fact 并保留出处；C5：三产品读到同一批 Fact ID；C6/C7：撤权与 Evidence 失效、重启与默认 5 秒读回。条件是否达成只能凭主环境证据。
- 统一读口为 objects/dossier v2、relations/v5、Evidence detail/v2、chunk/v2（F7）。版本指定不等于 GEO 已接入，也不授予服务身份资格；GEO 路径及身份仍以 Foundation 当前待裁决事项为准。
- GEO 拥有草稿和内容资产；Document/Evidence/KO/Fact 归 Knowledge，Definition/Schema 归 Semantic。Provider 输出、历史快照、自上传草稿不替代正式 Fact。
- [产品门矩阵](GEO_PRODUCT_DOOR_MATRIX.md)保留；公共 Product API、Knowledge DOCX、Provider、Release 文件仍由各自唯一写者负责。
- [10-09 本地候选证据](audits/geo-local-seams-2026-10-09/REPORT.md)只证明其列出的自测；“冻结候选”是验收快照，不是新增治理 Freeze。
- [10-08 内容计划](engineering/GEO-CONTENT-DELIVERY-PLAN-2026-10-08.md)和[旧卡](engineering/CARD-GEO-CONTENT-01.md)保留作历史成果索引，不自动授权新主轴施工。当前卡/证据登记待中控确认，不在 GEO 另造第二套主轴、合同谱系或共享规则。
- 测试使用任务专属临时库；UI 验证显式设置 `GEO_UI_OUT_DIR=/tmp/eios-test/<任务名>/ui`。`packages/geo/dist` 可能正被静态服务使用，构建成功不等于获准替换它。

当前事实只写 [CURRENT_STATE](../CURRENT_STATE.md)，证据放 `docs/audits/`，被替代现场保留于 [历史索引](archive/INDEX.md)。
