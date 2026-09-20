# GEO 产品门端点矩阵（GEO-01B · 2026-09-20）

基线：`eios-geo` commit `5afbf48`（`codex/geo-product-api-p0` 隔离 worktree）。
本文件由 `apps/api/app/product/door.py` 的冻结清单与实际 `app.openapi()` 路由机械比对生成，
是「UI 调用 → 产品门 → 老 v1 use case」的唯一口径来源。

## 1. 冻结清单（40 条，全部落在真实 v1 路由上）

产品门只做路径适配：`/api/product/geo/<rest>` → `/api/v1/<rest>`，业务语义、存储与
`{ok,data,error}` envelope 完全由老 handler 决定。清单之外一律 404 `GEO_ROUTE_NOT_ALLOWED`，
即使老路由存在（例：`/knowledge/reset`、`/knowledge/materials` 新增、`/monitor/batch`、`/stats/overview`）。

| # | method | product door | owning legacy route | v1 matches |
|---|---|---|---|---|
| 1 | `GET` | `/api/product/geo/monitor/items` | `/api/v1/monitor/items` | 1 |
| 2 | `GET` | `/api/product/geo/monitor/tasks` | `/api/v1/monitor/tasks` | 1 |
| 3 | `GET` | `/api/product/geo/monitor/answers` | `/api/v1/monitor/answers` | 1 |
| 4 | `GET` | `/api/product/geo/monitor/sentiment` | `/api/v1/monitor/sentiment` | 1 |
| 5 | `GET` | `/api/product/geo/monitor/citations` | `/api/v1/monitor/citations` | 1 |
| 6 | `GET` | `/api/product/geo/cognition/competitors` | `/api/v1/cognition/competitors` | 1 |
| 7 | `GET` | `/api/product/geo/cognition/health` | `/api/v1/cognition/health` | 1 |
| 8 | `GET` | `/api/product/geo/cognition/portrait` | `/api/v1/cognition/portrait` | 1 |
| 9 | `GET` | `/api/product/geo/cognition/coverage` | `/api/v1/cognition/coverage` | 1 |
| 10 | `GET` | `/api/product/geo/cognition/reasons` | `/api/v1/cognition/reasons` | 1 |
| 11 | `GET` | `/api/product/geo/cognition/sources` | `/api/v1/cognition/sources` | 1 |
| 12 | `GET` | `/api/product/geo/distill/gaps` | `/api/v1/distill/gaps` | 1 |
| 13 | `GET` | `/api/product/geo/distill/plans` | `/api/v1/distill/plans` | 1 |
| 14 | `GET` | `/api/product/geo/distill/questions` | `/api/v1/distill/questions` | 1 |
| 15 | `GET` | `/api/product/geo/distill/cognition/profile` | `/api/v1/distill/cognition/profile` | 1 |
| 16 | `GET` | `/api/product/geo/knowledge/materials` | `/api/v1/knowledge/materials` | 1 |
| 17 | `GET` | `/api/product/geo/knowledge/materials/search` | `/api/v1/knowledge/materials/search` | 1 |
| 18 | `GET` | `/api/product/geo/knowledge/materials/[^/]+` | `/api/v1/knowledge/materials/{}` | 2 |
| 19 | `GET` | `/api/product/geo/onboard/run-status` | `/api/v1/onboard/run-status` | 1 |
| 20 | `GET` | `/api/product/geo/onboard/status` | `/api/v1/onboard/status` | 1 |
| 21 | `POST` | `/api/product/geo/onboard/auto-config` | `/api/v1/onboard/auto-config` | 1 |
| 22 | `POST` | `/api/product/geo/monitor/items` | `/api/v1/monitor/items` | 1 |
| 23 | `POST` | `/api/product/geo/monitor/items/preview` | `/api/v1/monitor/items/preview` | 1 |
| 24 | `POST` | `/api/product/geo/monitor/items/[^/]+/run` | `/api/v1/monitor/items/{}/run` | 1 |
| 25 | `POST` | `/api/product/geo/monitor/tasks` | `/api/v1/monitor/tasks` | 1 |
| 26 | `POST` | `/api/product/geo/monitor/tasks/[^/]+/run` | `/api/v1/monitor/tasks/{}/run` | 1 |
| 27 | `POST` | `/api/product/geo/distill/gaps` | `/api/v1/distill/gaps` | 1 |
| 28 | `POST` | `/api/product/geo/distill/plans/from-gaps` | `/api/v1/distill/plans/from-gaps` | 1 |
| 29 | `POST` | `/api/product/geo/distill/content-plan` | `/api/v1/distill/content-plan` | 1 |
| 30 | `POST` | `/api/product/geo/distill/cognition/evaluate` | `/api/v1/distill/cognition/evaluate` | 1 |
| 31 | `POST` | `/api/product/geo/content/generate` | `/api/v1/content/generate` | 1 |
| 32 | `POST` | `/api/product/geo/content/score` | `/api/v1/content/score` | 1 |
| 33 | `PATCH` | `/api/product/geo/monitor/items/[^/]+` | `/api/v1/monitor/items/{}` | 1 |
| 34 | `PATCH` | `/api/product/geo/monitor/tasks/[^/]+` | `/api/v1/monitor/tasks/{}` | 1 |
| 35 | `DELETE` | `/api/product/geo/monitor/items/[^/]+` | `/api/v1/monitor/items/{}` | 1 |
| 36 | `DELETE` | `/api/product/geo/monitor/tasks/[^/]+` | `/api/v1/monitor/tasks/{}` | 1 |
| 37 | `DELETE` | `/api/product/geo/distill/plans/[^/]+` | `/api/v1/distill/plans/{}` | 1 |
| 38 | `DELETE` | `/api/product/geo/distill/questions/[^/]+` | `/api/v1/distill/questions/{}` | 1 |
| 39 | `DELETE` | `/api/product/geo/knowledge/materials/[^/]+` | `/api/v1/knowledge/materials/{}` | 1 |
| 40 | `PUT` | `/api/product/geo/knowledge/materials/[^/]+` | `/api/v1/knowledge/materials/{}` | 1 |

total: 40 allowlisted routes

## 2. 本轮实测结论

- 40/40 条清单路径在 `app.openapi()` 中都能 fullmatch 到唯一一条 `/api/v1/*` 路由（本表 `v1 matches` 全为 1）。
- 真服务实跑 parity：20 条读端点响应体（去掉 `request_id`）逐字相同；20 条写端点状态码与
  envelope 错误码相同；写闭环（door 建监测对象 → 老路由可见 → door 归档）通过。
- 拒绝面：清单外路径 404 `GEO_ROUTE_NOT_ALLOWED`，老链 `/api/v1/*` 行为不变。

## 3. 已知差异与下一卡必须处理的事

1. **product-api 的 GEO 白名单口径不一致（GEO-03 阻塞）**
   `eios-product-api/app/main.py` 的 `_GEO_ACTIONS` 描述的是 P1 observation 面
   （`monitor/objects`、`observation/*`、`capability/*`、`setup/*`），与本表这张老 v1 面**零交集**。
   照现状，即使 GEO 产品门接上，product-api 也会对老 UI 的每一次调用回
   `404 GEO_ROUTE_NOT_ALLOWED`。GEO-03 必须按本表重写该白名单并映射 method/path→scope。
   本卡未改 product-api 一个字节。

2. **标准页面在无 Host 握手时回落到老 BFF 基址**
   `geo-advisor/frontend/geo-api.ts` 默认 `geoApiBase = '/api/geo/api/v1'`，
   只有收到 `eios.product_host/v1` 的 `host.session`/`host.hello` 才切到 `/api/product/geo`。
   独立页（无 iframe Host、无握手）会去请求老 BFF 并 404。产品正式入口经 Product Host 加载不受影响，
   但 GEO-02 需要决定：产品构建是否应显式声明「必须 Host 会话」，而不是回落到 yayu BFF。

3. **健康契约与身份模式**
   `/api/product/geo/health` 返回扁平 `product.geo_health/v1` 契约（不是老 envelope），
   `status` 只有在 `GEO_AUTH_MODE=auth_context` 且 `GEO_PRODUCT_STORAGE_MODE=postgres` 时才为 `ok`。
   未迁移前固定为 `compatibility`，因此 EIOS availability 不会在老租户口径上变绿。

## 4. 复现

```bash
cd <geo worktree>
GEO_DB_PATH=/tmp/eios-test/<task>/geo.db GEO_PRODUCT_DOOR=on GEO_RUNTIME_MODE=baseline \
  .venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 3092
env -u GEO_DB_PATH .venv/bin/python -m pytest apps/api/tests/test_product_geo_door.py -q
```
