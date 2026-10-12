# EIOS Product GEO Working Agreement

本仓是独立 GEO 产品域，包含 GEO API、域内 services/adapters 和自带 UI。

## 开始任务

1. 先读本仓 `README.md`、[`CURRENT_STATE.md`](CURRENT_STATE.md)、`docs/GEO_PRODUCT_DOOR_MATRIX.md`（若任务涉及产品门）和任务 Card。
2. 检查 `git status --short --branch`；不覆盖已有未提交改动。
3. 涉及 EIOS 身份、产品接线或 Foundation 数据时，先确认 `eios-product-api` 与 Foundation 的既有契约。
4. 跨 EIOS 边界时阅读 Foundation 的[横向与纵向施工纪律](../eios-foundation/docs/engineering/EIOS-CONVERGENT-CONSTRUCTION-PROTOCOL-2026-10-05.md)：沿真实业务链证明首个偏离，进入责任模块最小修复，再回原链执行 WRITE → READ BACK → VERIFY。本文不复制该纪律，也不扩大当前用户授权。

当前事实只更新 `CURRENT_STATE.md`；开发方向见[内容交付方案与计划](docs/engineering/GEO-CONTENT-DELIVERY-PLAN-2026-10-08.md)。计划和历史任务卡不自动授权代码、跨仓、部署或真实运行；已授权范围内的普通工程问题按现行纪律连续收口，不逐项重复请示。

## 边界

- `apps/api` 提供 GEO 域 API；`services/` 和 `adapters/` 保持仓根布局，供后端按模块导入。
- `packages/geo` 是 GEO UI；`packages/ui` 是现有 UI 依赖，不把产品接线逻辑散落到组件中。
- 产品门默认关闭；只有矩阵允许的路由才可打开。
- 不绕过 `eios-product-api` 直接形成新的产品入口，不复制 Foundation canonical 数据。
- `apps/api/geo.db` 只是开发夹具，不是 canonical GEO DB，不可作为对外权威来源。
- 不把 legacy 数据、Provider 输出或 demo 数据描述为生产事实。

## 验证

```bash
python -m pytest
npm run check:ui
```

测试必须使用临时数据库和任务专用临时目录；不要修改开发库、提交构建产物或散落测试文件。

## 完成标准

报告实际修改、验证命令和结果、产品门状态、是否扩展范围、剩余风险，以及 `DONE`、`PARTIAL` 或 `BLOCKED` 状态。
