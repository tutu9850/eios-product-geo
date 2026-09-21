# GEO 产品门端点矩阵（GEO-01B · 2026-09-20；2026-09-21 整面放行）

基线：`eios-product-geo` 的 `apps/api/app/product/door.py`。本文件由该门的冻结清单与
实际 `app.openapi()` 路由机械比对生成，是「UI 调用 → 产品门 → 老 v1 use case」的唯一口径来源。

## 1. 冻结清单（135 条，全部落在真实 v1 路由上）

产品门只做路径适配：`/api/product/geo/<rest>` → `/api/v1/<rest>`，业务语义、存储与
`{ok,data,error}` envelope 完全由老 handler 决定。清单之外一律 404 `GEO_ROUTE_NOT_ALLOWED`。

2026-09-21 Owner 拍板「把 GEO 全部功能都连起来，通了他们」之后，这扇门不再只放行打包 UI
当天实际调用的那些，而是整张老 v1 面：139 条老路由里 135 条在下面这张表里。**不在表的四条**是
`geo/consumer/{knowledge,snapshots,summary}`（顾问交接面：自带验签、顾问直连，不属于本门的
授权范围）与 `health`（门自己答的契约路由，不走这张表）。

scope 判据只有三条，`eios-product-api` 的 `_GEO_ACTIONS` 用同一套：

- `read`：不改 GEO 任何记录、也不发起外部动作。纯计算与单次模型生成算读；`market/signals/*/confirm`
  也算读，因为它的答案就是「GEO 不写知识库」的拒绝 —— 拒绝写不是写。
- `run`：发起一个引擎或长任务（采集、解析、生成、复测、闭环、联网实测）。run 同时决定代理超时
  （180s，读是 35s），所以这是唯一一个改了会看得见的档。
- `manage`：新建 / 修改 / 删除 GEO 自己的记录（监测对象与任务、问题池、内容计划、素材、链接、关注项）。

| # | method | product door | owning legacy route | scope |
|---|---|---|---|---|
| 1 | `DELETE` | `/api/product/geo/distill/plans/[^/]+` | `/api/v1/distill/plans/[^/]+` | `manage` |
| 2 | `DELETE` | `/api/product/geo/distill/questions/[^/]+` | `/api/v1/distill/questions/[^/]+` | `manage` |
| 3 | `DELETE` | `/api/product/geo/knowledge/materials/[^/]+` | `/api/v1/knowledge/materials/[^/]+` | `manage` |
| 4 | `DELETE` | `/api/product/geo/links/[^/]+` | `/api/v1/links/[^/]+` | `manage` |
| 5 | `DELETE` | `/api/product/geo/market/watchlist/[^/]+` | `/api/v1/market/watchlist/[^/]+` | `manage` |
| 6 | `DELETE` | `/api/product/geo/monitor/items/[^/]+` | `/api/v1/monitor/items/[^/]+` | `manage` |
| 7 | `DELETE` | `/api/product/geo/monitor/tasks/[^/]+` | `/api/v1/monitor/tasks/[^/]+` | `manage` |
| 8 | `GET` | `/api/product/geo/analyze/reports/[^/]+` | `/api/v1/analyze/reports/[^/]+` | `read` |
| 9 | `GET` | `/api/product/geo/cognition/competitors` | `/api/v1/cognition/competitors` | `read` |
| 10 | `GET` | `/api/product/geo/cognition/coverage` | `/api/v1/cognition/coverage` | `read` |
| 11 | `GET` | `/api/product/geo/cognition/health` | `/api/v1/cognition/health` | `read` |
| 12 | `GET` | `/api/product/geo/cognition/portrait` | `/api/v1/cognition/portrait` | `read` |
| 13 | `GET` | `/api/product/geo/cognition/reasons` | `/api/v1/cognition/reasons` | `read` |
| 14 | `GET` | `/api/product/geo/cognition/sources` | `/api/v1/cognition/sources` | `read` |
| 15 | `GET` | `/api/product/geo/content/company` | `/api/v1/content/company` | `read` |
| 16 | `GET` | `/api/product/geo/distill/cognition-map` | `/api/v1/distill/cognition-map` | `read` |
| 17 | `GET` | `/api/product/geo/distill/cognition-profile` | `/api/v1/distill/cognition-profile` | `read` |
| 18 | `GET` | `/api/product/geo/distill/cognition/profile` | `/api/v1/distill/cognition/profile` | `read` |
| 19 | `GET` | `/api/product/geo/distill/gaps` | `/api/v1/distill/gaps` | `read` |
| 20 | `GET` | `/api/product/geo/distill/overview` | `/api/v1/distill/overview` | `read` |
| 21 | `GET` | `/api/product/geo/distill/plans` | `/api/v1/distill/plans` | `read` |
| 22 | `GET` | `/api/product/geo/distill/questions` | `/api/v1/distill/questions` | `read` |
| 23 | `GET` | `/api/product/geo/distill/questions/[^/]+/platforms` | `/api/v1/distill/questions/[^/]+/platforms` | `read` |
| 24 | `GET` | `/api/product/geo/eios/export/knowledge-index` | `/api/v1/eios/export/knowledge-index` | `read` |
| 25 | `GET` | `/api/product/geo/enterprise-profile/categories` | `/api/v1/enterprise-profile/categories` | `read` |
| 26 | `GET` | `/api/product/geo/enterprise-profile/export` | `/api/v1/enterprise-profile/export` | `read` |
| 27 | `GET` | `/api/product/geo/enterprise-profile/items/[^/]+` | `/api/v1/enterprise-profile/items/[^/]+` | `read` |
| 28 | `GET` | `/api/product/geo/enterprise-profile/overview` | `/api/v1/enterprise-profile/overview` | `read` |
| 29 | `GET` | `/api/product/geo/intelligence/analyses` | `/api/v1/intelligence/analyses` | `read` |
| 30 | `GET` | `/api/product/geo/intelligence/compare` | `/api/v1/intelligence/compare` | `read` |
| 31 | `GET` | `/api/product/geo/intelligence/evidence` | `/api/v1/intelligence/evidence` | `read` |
| 32 | `GET` | `/api/product/geo/intelligence/factor-gaps` | `/api/v1/intelligence/factor-gaps` | `read` |
| 33 | `GET` | `/api/product/geo/intelligence/gap-analysis` | `/api/v1/intelligence/gap-analysis` | `read` |
| 34 | `GET` | `/api/product/geo/intelligence/harvest/runs/[^/]+` | `/api/v1/intelligence/harvest/runs/[^/]+` | `read` |
| 35 | `GET` | `/api/product/geo/intelligence/humanize` | `/api/v1/intelligence/humanize` | `read` |
| 36 | `GET` | `/api/product/geo/intelligence/keywords` | `/api/v1/intelligence/keywords` | `read` |
| 37 | `GET` | `/api/product/geo/intelligence/matrix` | `/api/v1/intelligence/matrix` | `read` |
| 38 | `GET` | `/api/product/geo/intelligence/overview` | `/api/v1/intelligence/overview` | `read` |
| 39 | `GET` | `/api/product/geo/intelligence/perception` | `/api/v1/intelligence/perception` | `read` |
| 40 | `GET` | `/api/product/geo/intelligence/reports/latest` | `/api/v1/intelligence/reports/latest` | `read` |
| 41 | `GET` | `/api/product/geo/intelligence/reports/latest/pdf` | `/api/v1/intelligence/reports/latest/pdf` | `read` |
| 42 | `GET` | `/api/product/geo/intelligence/sov` | `/api/v1/intelligence/sov` | `read` |
| 43 | `GET` | `/api/product/geo/intelligence/stats` | `/api/v1/intelligence/stats` | `read` |
| 44 | `GET` | `/api/product/geo/intelligence/strategies` | `/api/v1/intelligence/strategies` | `read` |
| 45 | `GET` | `/api/product/geo/intelligence/trend-delta` | `/api/v1/intelligence/trend-delta` | `read` |
| 46 | `GET` | `/api/product/geo/knowledge/materials` | `/api/v1/knowledge/materials` | `read` |
| 47 | `GET` | `/api/product/geo/knowledge/materials/[^/]+` | `/api/v1/knowledge/materials/[^/]+` | `read` |
| 48 | `GET` | `/api/product/geo/knowledge/materials/search` | `/api/v1/knowledge/materials/search` | `read` |
| 49 | `GET` | `/api/product/geo/knowledge/media/[^/]+` | `/api/v1/knowledge/media/[^/]+` | `read` |
| 50 | `GET` | `/api/product/geo/knowledge/profile` | `/api/v1/knowledge/profile` | `read` |
| 51 | `GET` | `/api/product/geo/links` | `/api/v1/links` | `read` |
| 52 | `GET` | `/api/product/geo/market/signals` | `/api/v1/market/signals` | `read` |
| 53 | `GET` | `/api/product/geo/market/watchlist` | `/api/v1/market/watchlist` | `read` |
| 54 | `GET` | `/api/product/geo/meta/engines` | `/api/v1/meta/engines` | `read` |
| 55 | `GET` | `/api/product/geo/monitor/answers` | `/api/v1/monitor/answers` | `read` |
| 56 | `GET` | `/api/product/geo/monitor/citations` | `/api/v1/monitor/citations` | `read` |
| 57 | `GET` | `/api/product/geo/monitor/competitor` | `/api/v1/monitor/competitor` | `read` |
| 58 | `GET` | `/api/product/geo/monitor/effects` | `/api/v1/monitor/effects` | `read` |
| 59 | `GET` | `/api/product/geo/monitor/export` | `/api/v1/monitor/export` | `read` |
| 60 | `GET` | `/api/product/geo/monitor/fact-check` | `/api/v1/monitor/fact-check` | `read` |
| 61 | `GET` | `/api/product/geo/monitor/history` | `/api/v1/monitor/history` | `read` |
| 62 | `GET` | `/api/product/geo/monitor/industry` | `/api/v1/monitor/industry` | `read` |
| 63 | `GET` | `/api/product/geo/monitor/items` | `/api/v1/monitor/items` | `read` |
| 64 | `GET` | `/api/product/geo/monitor/items/[^/]+/trend` | `/api/v1/monitor/items/[^/]+/trend` | `read` |
| 65 | `GET` | `/api/product/geo/monitor/overview` | `/api/v1/monitor/overview` | `read` |
| 66 | `GET` | `/api/product/geo/monitor/pool` | `/api/v1/monitor/pool` | `read` |
| 67 | `GET` | `/api/product/geo/monitor/public-opinion` | `/api/v1/monitor/public-opinion` | `read` |
| 68 | `GET` | `/api/product/geo/monitor/rank-sentiment` | `/api/v1/monitor/rank-sentiment` | `read` |
| 69 | `GET` | `/api/product/geo/monitor/sentiment` | `/api/v1/monitor/sentiment` | `read` |
| 70 | `GET` | `/api/product/geo/monitor/sources` | `/api/v1/monitor/sources` | `read` |
| 71 | `GET` | `/api/product/geo/monitor/tasks` | `/api/v1/monitor/tasks` | `read` |
| 72 | `GET` | `/api/product/geo/monitor/tasks/[^/]+/overview` | `/api/v1/monitor/tasks/[^/]+/overview` | `read` |
| 73 | `GET` | `/api/product/geo/onboard/run-status` | `/api/v1/onboard/run-status` | `read` |
| 74 | `GET` | `/api/product/geo/onboard/status` | `/api/v1/onboard/status` | `read` |
| 75 | `GET` | `/api/product/geo/stats/overview` | `/api/v1/stats/overview` | `read` |
| 76 | `PATCH` | `/api/product/geo/monitor/items/[^/]+` | `/api/v1/monitor/items/[^/]+` | `manage` |
| 77 | `PATCH` | `/api/product/geo/monitor/tasks/[^/]+` | `/api/v1/monitor/tasks/[^/]+` | `manage` |
| 78 | `POST` | `/api/product/geo/analyze/diagnose` | `/api/v1/analyze/diagnose` | `run` |
| 79 | `POST` | `/api/product/geo/battle` | `/api/v1/battle` | `run` |
| 80 | `POST` | `/api/product/geo/collect/crawl` | `/api/v1/collect/crawl` | `run` |
| 81 | `POST` | `/api/product/geo/content/generate` | `/api/v1/content/generate` | `manage` |
| 82 | `POST` | `/api/product/geo/content/parse` | `/api/v1/content/parse` | `read` |
| 83 | `POST` | `/api/product/geo/content/quality` | `/api/v1/content/quality` | `read` |
| 84 | `POST` | `/api/product/geo/content/score` | `/api/v1/content/score` | `read` |
| 85 | `POST` | `/api/product/geo/diagnose` | `/api/v1/diagnose` | `run` |
| 86 | `POST` | `/api/product/geo/distill/analyze` | `/api/v1/distill/analyze` | `manage` |
| 87 | `POST` | `/api/product/geo/distill/cognition/evaluate` | `/api/v1/distill/cognition/evaluate` | `run` |
| 88 | `POST` | `/api/product/geo/distill/content-plan` | `/api/v1/distill/content-plan` | `manage` |
| 89 | `POST` | `/api/product/geo/distill/content-publish` | `/api/v1/distill/content-publish` | `manage` |
| 90 | `POST` | `/api/product/geo/distill/content-recheck` | `/api/v1/distill/content-recheck` | `manage` |
| 91 | `POST` | `/api/product/geo/distill/faq` | `/api/v1/distill/faq` | `read` |
| 92 | `POST` | `/api/product/geo/distill/faq/upgraded` | `/api/v1/distill/faq/upgraded` | `read` |
| 93 | `POST` | `/api/product/geo/distill/gaps` | `/api/v1/distill/gaps` | `manage` |
| 94 | `POST` | `/api/product/geo/distill/loop/run` | `/api/v1/distill/loop/run` | `run` |
| 95 | `POST` | `/api/product/geo/distill/opportunities` | `/api/v1/distill/opportunities` | `manage` |
| 96 | `POST` | `/api/product/geo/distill/plans` | `/api/v1/distill/plans` | `manage` |
| 97 | `POST` | `/api/product/geo/distill/plans/customer-gap` | `/api/v1/distill/plans/customer-gap` | `manage` |
| 98 | `POST` | `/api/product/geo/distill/plans/from-gaps` | `/api/v1/distill/plans/from-gaps` | `manage` |
| 99 | `POST` | `/api/product/geo/distill/plans/manual` | `/api/v1/distill/plans/manual` | `manage` |
| 100 | `POST` | `/api/product/geo/distill/questions` | `/api/v1/distill/questions` | `manage` |
| 101 | `POST` | `/api/product/geo/enterprise-profile/items/[^/]+/plans` | `/api/v1/enterprise-profile/items/[^/]+/plans` | `manage` |
| 102 | `POST` | `/api/product/geo/enterprise-profile/refresh` | `/api/v1/enterprise-profile/refresh` | `manage` |
| 103 | `POST` | `/api/product/geo/intelligence/analyze` | `/api/v1/intelligence/analyze` | `run` |
| 104 | `POST` | `/api/product/geo/intelligence/harvest/search` | `/api/v1/intelligence/harvest/search` | `run` |
| 105 | `POST` | `/api/product/geo/intelligence/recover` | `/api/v1/intelligence/recover` | `run` |
| 106 | `POST` | `/api/product/geo/intelligence/reports/run` | `/api/v1/intelligence/reports/run` | `run` |
| 107 | `POST` | `/api/product/geo/kb-init/apply` | `/api/v1/kb-init/apply` | `manage` |
| 108 | `POST` | `/api/product/geo/kb-init/scan` | `/api/v1/kb-init/scan` | `read` |
| 109 | `POST` | `/api/product/geo/keywords/expand` | `/api/v1/keywords/expand` | `run` |
| 110 | `POST` | `/api/product/geo/knowledge/materials` | `/api/v1/knowledge/materials` | `manage` |
| 111 | `POST` | `/api/product/geo/knowledge/materials/upload` | `/api/v1/knowledge/materials/upload` | `manage` |
| 112 | `POST` | `/api/product/geo/knowledge/materials/vectorize` | `/api/v1/knowledge/materials/vectorize` | `run` |
| 113 | `POST` | `/api/product/geo/knowledge/media/upload` | `/api/v1/knowledge/media/upload` | `manage` |
| 114 | `POST` | `/api/product/geo/knowledge/reset` | `/api/v1/knowledge/reset` | `manage` |
| 115 | `POST` | `/api/product/geo/links` | `/api/v1/links` | `manage` |
| 116 | `POST` | `/api/product/geo/links/check` | `/api/v1/links/check` | `manage` |
| 117 | `POST` | `/api/product/geo/links/check-all` | `/api/v1/links/check-all` | `manage` |
| 118 | `POST` | `/api/product/geo/market/collect` | `/api/v1/market/collect` | `run` |
| 119 | `POST` | `/api/product/geo/market/signals/[^/]+/confirm` | `/api/v1/market/signals/[^/]+/confirm` | `read` |
| 120 | `POST` | `/api/product/geo/market/signals/[^/]+/extract` | `/api/v1/market/signals/[^/]+/extract` | `manage` |
| 121 | `POST` | `/api/product/geo/market/signals/[^/]+/ignore` | `/api/v1/market/signals/[^/]+/ignore` | `manage` |
| 122 | `POST` | `/api/product/geo/market/signals/[^/]+/to-plan` | `/api/v1/market/signals/[^/]+/to-plan` | `manage` |
| 123 | `POST` | `/api/product/geo/market/watchlist` | `/api/v1/market/watchlist` | `manage` |
| 124 | `POST` | `/api/product/geo/meta/engines/[^/]+/ping` | `/api/v1/meta/engines/[^/]+/ping` | `run` |
| 125 | `POST` | `/api/product/geo/monitor/batch` | `/api/v1/monitor/batch` | `run` |
| 126 | `POST` | `/api/product/geo/monitor/check` | `/api/v1/monitor/check` | `run` |
| 127 | `POST` | `/api/product/geo/monitor/generate-questions` | `/api/v1/monitor/generate-questions` | `run` |
| 128 | `POST` | `/api/product/geo/monitor/items` | `/api/v1/monitor/items` | `manage` |
| 129 | `POST` | `/api/product/geo/monitor/items/[^/]+/run` | `/api/v1/monitor/items/[^/]+/run` | `run` |
| 130 | `POST` | `/api/product/geo/monitor/items/preview` | `/api/v1/monitor/items/preview` | `read` |
| 131 | `POST` | `/api/product/geo/monitor/pool` | `/api/v1/monitor/pool` | `manage` |
| 132 | `POST` | `/api/product/geo/monitor/tasks` | `/api/v1/monitor/tasks` | `manage` |
| 133 | `POST` | `/api/product/geo/monitor/tasks/[^/]+/run` | `/api/v1/monitor/tasks/[^/]+/run` | `run` |
| 134 | `POST` | `/api/product/geo/onboard/auto-config` | `/api/v1/onboard/auto-config` | `run` |
| 135 | `PUT` | `/api/product/geo/knowledge/materials/[^/]+` | `/api/v1/knowledge/materials/[^/]+` | `manage` |

total: 135 allowlisted routes

### 1.1 不在列的四条

| method | legacy route | 为什么不在列 |
|---|---|---|
| `GET` | `/api/v1/geo/consumer/knowledge` | 顾问交接面：自带验签，顾问直连，产品门不该给它签票 |
| `GET` | `/api/v1/geo/consumer/snapshots` | 顾问交接面：自带验签，顾问直连，产品门不该给它签票 |
| `GET` | `/api/v1/geo/consumer/summary` | 顾问交接面：自带验签，顾问直连，产品门不该给它签票 |
| `GET` | `/api/v1/health` | 门自己的 `product.geo_health/v1` 契约路由，由中间件直接答 |

### 1.2 仍然 fail-closed 的退役路径

P1 observation 面（`monitor/objects`、`observation/*`、`capability/*`、`setup/*`）2026-09-20
按 Owner 拍板退役。这些名字**没有老 v1 的主人**，所以整面放行也不会把它们打开；
`tests/test_geo_boundary.py::test_retired_p1_observation_routes_fail_closed` 钉住这一点。
注意 `monitor/overview` 已从那份退役名单里移出：同名路径是**老 v1 真实存在的一条读路由**
（数据总览驾驶舱），2026-09-21 起归它所有。


## 2. 本轮实测结论（2026-09-21）

- 冻结清单 135/135 条在 `app.openapi()` 里 fullmatch 到唯一一条 `/api/v1/*` 路由
  （`test_every_allowlisted_route_maps_onto_a_real_legacy_route` 机械守住「门不许发明端点」）。
- 两张表逐条一致：`eios-product-api` 的 `_GEO_ACTIONS` 与本门的 `_PRODUCT_ROUTES` 对老 v1 的
  139 条路由给出同一套结论 —— 136 条放行（135 条在表里 + 门自答的 `health`），3 条顾问面两边都不放行。
- 真服务实跑（私有 product-api `:3093` → 私有 GEO `:3092`，临时库）：136 条放行路由 **0 条**被门拒，
  没有任何一条回 404 `GEO_ROUTE_NOT_ALLOWED`。状态码分布 `200×108 / 422×24 / 500×4`：
  422 是我这一轮扫描故意送的 `{}` 空 body 触发的校验，500 见 2.2。
- 仍然关着：`geo/consumer/{knowledge,snapshots,summary}` 三条回 404 `GEO_ROUTE_NOT_ALLOWED`；
  退役 P1 名字（`observation/*`、`monitor/objects`、`capability/*`、`setup/*`）与
  `PUT /monitor/items/{id}` 同样 404。
- dev 栈真读（浏览器 `:4173` → Client `/app/geo` 内嵌 → product-api `:8090` → GEO `:8091`）：
  `/monitor/overview`、`/intelligence/sov`、`/meta/engines`、`/distill/overview`、`/market/watchlist`
  全部 200 —— 这五条在放行前都是 404。
- 私有栈真写（临时库）：`POST /knowledge/materials` 建素材 → `GET /knowledge/materials` 能列出来 →
  `POST /knowledge/materials/upload`（multipart，54 字符）→ `POST /battle` 返回**这个部署登记的 6 个模型**
  （DeepSeek / Kimi / 豆包 / 文心一言 / 通义千问 / 智谱）的作答，全部 200。

### 2.1 放行顺手撞出来并修掉的一条

`GET /enterprise-profile/export` 的 200 **不是 envelope，是 .docx**（python-docx 渲染的「企业资料总揽」，
带 `Content-Disposition`）。它以前不在门里，所以没人撞上；整面放行以后按 envelope 解析，它会变成
502 `GEO_INVALID_RESPONSE` —— 那不是「连上了」。

因此 `eios-product-api` 的 `_GEO_DOCUMENT_ACTIONS` 从「只有 PDF 一条」改成「每条声明自己的 media type 族」：

| method | route | 允许的 media type |
|---|---|---|
| `GET` | `intelligence/reports/latest/pdf` | `application/pdf` |
| `GET` | `enterprise-profile/export` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |

只有 200 + content type 对得上才按文档转发（bytes 与 `Content-Disposition` 原样送出）；对不上仍然
fail-closed 成 invalid response，绝不把一页错误页当文件递给浏览器。
实测：私有栈 `GET /enterprise-profile/export` → 200、37858 bytes、magic `PK\x03\x04`。

### 2.2 本卡没在真机上烧钱验的两条

`meta/engines`、`stats/overview`、`meta/engines/{id}/ping`、`monitor/generate-questions` 在
`GEO_RUNTIME_MODE=baseline` 的私有实例上回 500 `outbound_network_blocked` —— 那是我的测试实例禁了外网，
不是门的问题。关掉 baseline 后 `meta/engines`、`stats/overview` 实测 200；
`meta/engines/{id}/ping` 与 `monitor/generate-questions` 会真花企业模型额度，这两条只验到「门放行、不再 404」。

## 3. 已知差异与下一卡必须处理的事

1. **标准页面在无 Host 握手时回落到老 BFF 基址**
   `geo-advisor/frontend/geo-api.ts` 默认 `geoApiBase = '/api/geo/api/v1'`，
   只有收到 `eios.product_host/v1` 的 `host.session`/`host.hello` 才切到 `/api/product/geo`。
   独立页（无 iframe Host、无握手）会去请求老 BFF 并 404。产品正式入口经 Product Host 加载不受影响，
   但 GEO-02 需要决定：产品构建是否应显式声明「必须 Host 会话」，而不是回落到 yayu BFF。

2. **健康契约与身份模式**
   `/api/product/geo/health` 返回扁平 `product.geo_health/v1` 契约（不是老 envelope），
   `status` 只有在 `GEO_AUTH_MODE=auth_context` 且 `GEO_PRODUCT_STORAGE_MODE=postgres` 时才为 `ok`。
   未迁移前固定为 `compatibility`，因此 EIOS availability 不会在老租户口径上变绿。

3. **`knowledge/reset` 拿到了票，但没有界面入口**
   它随整面放行进了表（`manage`）。它只清 GEO 自己的库/媒体/向量，且必须显式 `confirm=true` 才动手，
   但它是全表里唯一一个「一次呼叫抹掉全部业务表」的动作。要不要保留放行，请 Owner 复核。

## 4. 复现

```bash
# 单元：门不许发明端点 + 冻结清单口径
cd ~/eios-product-geo
env -u GEO_DB_PATH PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_product_geo_door.py -q

# 真机：私有 GEO（临时库）+ 私有 product-api
T=/tmp/eios-test/<task>
cd ~/eios-product-geo/apps/api
PYTHONPATH="$HOME/eios-product-geo:$PYTHONPATH" \
GEO_DB_PATH=$T/geo.db GEO_PRODUCT_DOOR=on GEO_RUNTIME_MODE=baseline \
GEO_PRODUCT_DOOR_IDENTITY_ACK=compatibility \
EIOS_AUTH_PUBLIC_KEY_PATH=$HOME/eios-foundation/.dev-secrets/auth-public.pem \
  ~/eios-product-geo/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 3092
# 另一个终端：
cd ~/eios-product-api
EIOS_GEO_PRODUCT_URL=http://127.0.0.1:3092 ~/eios-foundation/.venv/bin/python start.py 3093
```

`PYTHONPATH` 必须**追加**而不是覆盖 `~/eios-dev/lib/env.sh` 里那串 foundation 包路径：
覆盖掉 `packages/auth` 之后任何要签票的路由（`meta/engines`、`stats/overview`…）都会以
`No module named 'eios_auth'` 回 500，看起来像门坏了，其实是测试壳缺了包。
