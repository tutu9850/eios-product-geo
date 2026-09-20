# 统一分析引擎 V1 · 笔革验收记录（收口）

- 日期：2026-08-25
- Owner：§十二 默认全接受；验收主体 **笔革家居**
- 冻结文档：`~/Desktop/开发文档/eios架构/EIOS_统一分析引擎_V1_冻结方案.md`（已勾冻结）
- 结果：**PASS_FIELD_GATE**（脚本 + 手工 API 核对）

## 本刀施工

1. **队列硬化**（`services/intelligence/queue.py`）
   - 无事件循环时不再静默丢弃，改 `deferred` + `flush_deferred`
   - 绑定 FastAPI 主循环，`call_soon_threadsafe` 跨线程入队
2. **启动恢复**（`apps/api/app/main.py`）
   - `bind_main_loop` + `ensure_worker` + `recover_pending`
3. **reports/run 兼容**（`apps/api/app/api/v1/intelligence.py`）
   - `company`/`days` 支持 query + JSON body
   - `reports/latest`：`company` 空 → 全局最新；有值 → 精确匹配；`report_json` 字符串自动 parse
4. **验收脚本**：`scripts/bige_intelligence_accept.py`
5. **镜像**：`eios-all` → `docker compose build geo && up -d geo`（库挂载 `eios-geo/apps/data/geo.db`）

## 如何复跑

```bash
# 重建 GEO（改代码后）
cd ~/eios-all && docker compose build geo && docker compose up -d geo

# 验收（宿主机缺 sqlalchemy 时 seed 会 WARN 回退，依赖库内已有种子亦可）
cd ~/eios-geo
GEO_DB_PATH=apps/data/geo.db PYTHONPATH=apps/api:. \
  python3 scripts/bige_intelligence_accept.py --wait 240

# reports/run 有 5min 限流；限流后仍可读 latest
curl -s "http://127.0.0.1:3002/api/v1/intelligence/reports/latest?company=%E7%AC%94%E9%9D%A9" | python3 -m json.tool | head
```

## §十 对照（2026-08-25 实测）

| 步 | 期望 | 实测 |
|----|------|------|
| 1 evidence | 种子 `ans_bige_accept_*`，subject=笔革 | ✅ matrix `evidence_count=6`（含验收种子） |
| 2 extraction + quote | succeeded + quote | ✅ `parsed 3/3`，`quote_ok=True`；竞品顾家/左右有 quote |
| 3 matrix | missing/dimensions 非空 | ✅ dims=3（展厅多/设计师渠道/意式案例），missing=4 |
| 4 Kernel gap | report gap，不编造 | ✅ `capability_gap.gap_summary` 有；含 kernel_has / external_perceives / support_refs |
| 5 actions+refs | ≥1 且可追溯 evidence_id | ✅ company=`笔革`，actions=2，均带 `ans_bige_accept_001_deepseek` |

脚本末行：`PASS_FIELD_GATE`。

## §八 Builder 四块（对照，非本刀改 UI）

`eios-runtime` → `IntelligenceWorkspace.tsx`（顶栏「EIOS 分析」）已有：

1. 外界怎么看我（perception / tags）
2. 差距矩阵（gap_matrix / matrix）
3. 该发什么文章 / 优先行动（actions）
4. 知识缺口（capability_gap / factor-gaps）

可点 refs 拉证据链。与冻结「四块」对齐；旧 6 Tab 监测统计保留。

## 已知瑕疵（不挡收口）

- 库内仍可能有一条「笔革=打字错误」类旧解析行（与好种子并存）；不以该噪声否定主路径。
- 宿主机 `python3.9` 直接 `import repo` 需容器/venv 依赖；脚本已有 HTTP 回退。
- `reports/run` 5 分钟限流；限流时读 `latest` 即可。

## 明确未做

多源 Adapter、Deep Research 主干、Semantic 收口、CS 渠道。
