# EIOS GEO 产品（eios-product-geo）

GEO 产品**自己的**仓：后端与自带界面都在这里，不再寄生在别的仓里。

## 从这里开始

- [当前工作现场](CURRENT_STATE.md)：当前目标、源码基线、验证结果、未完成事项与下一张施工卡的唯一现场入口。
- [资料驱动内容交付开发方案与计划](docs/engineering/GEO-CONTENT-DELIVERY-PLAN-2026-10-08.md)：先打通上传资料到可追溯草稿，再接 Knowledge 和正式 Fact。
- [AI 工作规则](AGENTS.md)：开工、范围、产品门和验证要求。
- [产品门矩阵](docs/GEO_PRODUCT_DOOR_MATRIX.md)：允许的产品路由；历史验收不等于当前部署已验收。

开始任务先核对当前现场及任务卡。以下旧版状态、启动说明和历史完成清单仅作背景，不证明当前部署可用，也不自动授权新施工。

> 2026-09-20 从老 GEO 仓的干净提交 `5afbf48`（+ 产品门 `b8cbe3f` / `0bf2491`）原样导入，
> 界面从老 Client 的 `geo-advisor/frontend` 原样搬入。`main` 仍是导入出来的一次性提交，
> **历史在 `legacy/eios-geo/*` 这组冻结分支里**（见 `docs/LEGACY-REFS.md`）：老仓
> `EIOS-ai/eios-geo` 已按 Owner 拍板退役，它的 10 个分支一个不少地搬到这里，`main` 不接那套历史。

## 布局

| 路径 | 内容 |
|---|---|
| `apps/api/` | GEO 后端（FastAPI）：`/api/v1/*` 业务路由 + `/api/product/geo/*` 产品门 |
| `services/` `adapters/` | 采集 / 蒸馏 / 监测 / 内容 / 引擎适配。**必须留在仓根**：后端按 `services.x` / `adapters.y` import |
| `packages/geo/` | GEO 自带界面（vite，公开路径 `/product/geo/`），产物 `packages/geo/dist` |
| `packages/ui/` | 从老 yayu Client 原样搬来的 UI 套件（包名仍是 `@yayu/ui`）。只为让 GEO 的 15 个卡片一行不改 |
| `docs/` | 契约、产品门矩阵、审计记录；`LEGACY-REFS.md` 记录退役老仓的冻结分支 |

**`apps/geo.db`** 是老仓带过来的**开发用**库（本机 demo 数据，dev 栈默认读它，见
`eios-dev/lib/wrappers/geo.sh` 里的 `GEO_DB_PATH`）。它是 dev 夹具，**不是** canonical
GEO DB —— canonical 由谁持有、怎么初始化还没拍板，别把它当权威来源往外发。

## 与 EIOS 的接线（只有两条）

1. **界面**：Client 同源 `/product/geo/` —— Client 用 iframe 挂载，握手契约 `eios.product_host/v1`。
2. **数据**：Client → `eios-product-api` 的 `/api/product/geo/*` → 本仓 `/api/product/geo/*`（产品门）→ `/api/v1/*`。

产品门**默认关闭**（`GEO_PRODUCT_DOOR=off`）；打开之前先读 `docs/GEO_PRODUCT_DOOR_MATRIX.md`。
身份 / 存储没迁到 EIOS 的部署，`product.geo_health/v1` 会自报 `identity_mode=legacy`。

## 本地启动

```bash
# 界面制品（产物 → packages/geo/dist；dev 栈由 eios-dev 的 geo-ui wrapper 服务到 /product/geo/）
npm install && npm run build:ui

# 后端（dev 栈用 foundation venv；等价于 eios-dev/lib/wrappers/geo.sh）
cd apps/api && GEO_PRODUCT_DOOR=on GEO_DB_PATH=<db> "$EIOS_PRODUCT_PY" -m uvicorn app.main:app --port 8091

# 后端测试（仓库根目录，统一导入 app/services/adapters）
python -m pip install -r apps/api/requirements-dev.txt
python -m pytest

# 前端类型检查和生产构建
npm run check:ui
```

根目录的 `pyproject.toml` 为 pytest 配置 `apps/api` 和仓库根目录两个
导入路径，并将后端测试目录统一纳入收集。测试夹具会使用临时数据库，
如果 `GEO_DB_PATH` 指向仓库开发库则会拒绝启动，避免测试误删开发数据。

---

# EIOS GEO（企业外部智能感知）

> 文档主目录：~/Desktop/开发文档/geo开发文档/（架构基准：GEO_架构方案V2.md）

## 当前状态（2026-08-07 数据库化后）

**存储**：SQLite（`geo.db`，`apps/api/app/models/geo_models.py` 9 表：questions/gaps/content_plans/monitor_history/kb/watchlist/collect_raw/links/media_files）——2026-08-07 从 JSON 文件库迁入，JSON 已删除。
**媒体**：图片/文件存 `storage/media/`（上传 `POST /api/v1/knowledge/media/upload`，读取 `GET /api/v1/knowledge/media/{file}`）。
**测试**：`apps/api/tests/`（6 个：store roundtrip/租户隔离/迁移幂等/媒体/adapter 契约）。
**向量**：可选 Qdrant（geo_materials collection），降级内存/JSON 缓存。

## 已完成
- [x] 仓库骨架（apps/api + services/* + adapters/* + docs/*）
- [x] FastAPI + 统一 envelope + 全部路由
- [x] 6 国内引擎注册表（DeepSeek/Kimi/豆包/文心/通义/智谱）
- [x] 引擎连通性实测（DeepSeek 已配置）
- [x] 蒸馏（问题池/缺口/内容计划 + 证据等级 [A]/[B]/[C]）
- [x] 监测（6 引擎曝光检测/批量/历史/效果卡/引用追踪/导出）
- [x] 老板简报 Dashboard（V1 拍板验收 6 条全过）
- [x] 市场感知（关注列表/采集/信号确认→Kernel candidate）
- [x] 素材向量化混合检索（S1b）
- [x] 链接管理（收录检测）
- [x] Builder 代理 /api/geo/*

## 下一阶段（后置）
- S3 Memory 经验沉淀（等效果样本若干周）
- S4 交付完善（PDF/部署文档/引擎核验）

## 本地启动
```bash
cd ~/eios-geo
python3 -m venv .venv && .venv/bin/pip install -r apps/api/requirements.txt
bash scripts/run_dev.sh
# curl localhost:3002/health
```

## Engineering workflow

本仓的任务边界、产品门规则、测试和 Codex 完成报告要求见根目录 `AGENTS.md`。
跨仓任务应先创建施工卡，明确 Product API / Foundation 的契约和验证命令。
