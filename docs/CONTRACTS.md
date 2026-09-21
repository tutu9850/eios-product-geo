# GEO 契约（固定，禁止随意改）

> ⚠️ 2026-08-07 更新：本清单为**历史 P0 路由草案**，大量生产路由已上线但未列于此
> （蒸馏 /distill/*、监测 /monitor/*、市场 /market/*、素材 /knowledge/materials、媒体 /knowledge/media、诊断 /diagnose、对战 /battle、链接 /links 等 49 个）。
> **权威路由清单以运行实例 openapi.json 为准**（http://localhost:3002/openapi.json）。
> 产品门对外的可见面（哪几条能被 Client 调到、各签哪个 scope）见 `docs/GEO_PRODUCT_DOOR_MATRIX.md`：
> 2026-09-21 起是整张老 v1 面（139 条里的 136 条），顾问交接面 `geo/consumer/*` 不在其中。
> 给前端 UI 设计用的「按用户任务重排 + 性质/入口」全清单见 `docs/GEO_FUNCTION_INVENTORY.md`。
> 存储：SQLite geo.db（2026-08-07 起，JSON 文件库已退役删除）。

## Envelope
{"ok": bool, "data": {}, "error": null|{code,message}, "request_id": "...", "trace": {"stage": "..."}}

## 路由清单（P0 stub，路径与 envelope 固定）
GET  /health
GET  /api/v1/meta/engines
POST /api/v1/monitor/questions
POST /api/v1/monitor/check
GET  /api/v1/monitor/results/{id}
POST /api/v1/collect/crawl
POST /api/v1/analyze/diagnose
GET  /api/v1/analyze/reports/{id}
POST /api/v1/keywords/expand
POST /api/v1/content/generate
GET  /api/v1/knowledge/outbox
POST /api/v1/knowledge/sync
GET  /api/v1/eios/export/knowledge-index

## 与 Kernel 的契约（详见 GEO_架构方案V2.md §5）
- 只调既有 Kernel API，不新增端点；外部情报默认 candidate
