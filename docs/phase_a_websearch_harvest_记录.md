# Phase A · 外网补搜验收记录

- 日期：2026-08-25
- 规格：`EIOS_社媒补搜进分析引擎_开发方案.md`（Phase A 已冻结）
- 主体：笔革家居

## 交付物

| 项 | 路径 |
|----|------|
| Harvest 服务 | `eios-geo/services/intelligence/harvest.py` |
| API | `POST /api/v1/intelligence/harvest/search` · `GET .../harvest/runs/{id}` |
| Adapter 字段 | `source_type=research_harvest` · `capture_mode=search_result` · `discovered_url` |
| UI | ~~顶栏 EIOS 分析~~ → **市场监测 → 全智解析 → 深度详情**（外网补搜 + 仅 AI/仅补搜/全部） |
| 环境 | `eios-all` geo 服务 `EIOS_TOOL_URL`（默认 host.docker.internal:3300） |

## 采集门禁（不依赖 LLM）

```bash
# 宿主需起 eios-tool :3300
cd ~/eios-tool && npm run dev

# 重建 GEO
cd ~/eios-all && docker compose up -d geo

curl -s -X POST http://127.0.0.1:3002/api/v1/intelligence/harvest/search \
  -H 'content-type: application/json' \
  -d '{"company":"笔革","keywords":["笔革家居","真皮沙发"],"platform":"sogou","max_per_keyword":5}'

# 轮询 run（status=done 且 written>=1 即采集过）
curl -s http://127.0.0.1:3002/api/v1/intelligence/harvest/runs/<run_id>
curl -s 'http://127.0.0.1:3002/api/v1/intelligence/stats'
```

期望：`research_harvest` 计数增加；evidence raw_text 含「搜索摘要 · 非网页正文」。

### 2026-08-25 冒烟

- `POST harvest/search` → `hrv_9db02e2ece18` → **done written=3**
- `stats.research_harvest=3`
- evidence：`capture_mode=search_result`，raw 含摘要标注

## 分析观察（价值评审，不挡交付）

- 筛选「仅补搜」看 matrix
- 报告 refs 若引用补搜，须可点回；文案不得把摘要说成正文

## 未做

定时（B）、Social（C）、打开网页正文（page_content）。
