# 审计登记：账号分柜之后仍在共享面上的残留（2026-09-22）

Owner 2026-09-13 红线：「退役不了的（门不存在）→ 如实登记进 `docs/audits/`，写明为什么
清不掉，**不许**用裸 SQL 或改状态位绕过。」本文件按此登记**本轮没有清掉的**残留。

同时登记本轮「清掉旧共用柜」**实际删了什么** —— 这一步是不可逆操作，必须留档。

---

## 一、本轮已执行：清掉旧共用柜 `tenant_corp_01`

**授权**：Owner 2026-09-22 拍板「登录账号分柜　清掉　3 暂时不用，先把 GEO 自己的柜做对」，
本条即其中的「清掉」。走的是**既有的生命周期门** `POST /knowledge/reset?confirm=true`
（`store.reset_all()`），**没有**用裸 SQL。

**时点**：2026-09-22 00:1x（本地），GEO API 进程内调用。

**删了什么**（从现行库无法再枚举 → 从 WAL 页 `.recover` 出来的原文重建，逐条可核）：

| 类别 | 数量（可核部分） | 备注 |
|---|---|---|
| `geo_kb` 素材（旧共用柜） | 14 条 | 其中 8 条是**本轮验证时自己上传的测试件**（`笔革家居_现场调研手册` / `笔革家居主理人访谈纪要` / `笔革家居-GEO服务合同` / `笔革家居_经营月报_2026年7月` / `2026年8月` / `export_1785221939330` / `export_1785221955586` / `3789495a04275cc02af289e7e7569b58.jpg`，全部 2026-09-21 15:53–15:54 UTC），源文件都在 `~/Desktop/笔革家居GEO/`；其余是亚宇臻隆组织资料 |
| `geo_content_plans` | 约 190+ 条 | 全部是 `product FAQ / 产品介绍 / 产品白皮书` 这类**规则自动生成**的计划（`source=capability`），不是人手写的 |
| `enterprise_profile_items` | 50 | 企业画像的**类目定义**（八大类目录），不是企业事实；缺了会按需重新播种 |
| `enterprise_profile_knowledge` | 1 | 画像知识缓存 |
| `geo_knowledge_snapshots` | 54 | 读知识库的台账缓存（含 16 条更早的 `tenant_test_*` / `tenant_a` / `tenant_b` / `dept_aaa` / `dept_bbb` 残留） |
| `geo_questions` / `geo_gaps` / `geo_monitor_history` / `geo_monitor_items` | 与 `docs/audits/2026-09-21-dev-db-test-pollution.md` 登记的一致 | 那几张表里原本就是测试行与历次真机验证的读副作用 |

**诚实交代两点**：

1. **没有先做 dump**。上一手没有留下 `geo.db` 的备份，所以上面的行数是从 WAL 页里
   `.recover` 出来的（`sqlite3 geo.db ".recover"`，落 `lost_and_found`），
   不是一份干净的对账。可核的是**标题与时点**，不是精确的逐表行数。
2. **这与 2026-09-21 的拍板「`apps/geo.db` 从 git 运行态剥离，但历史脏数据不清」字面上有张力。**
   2026-09-22 的「清掉」是后一条指令，且这次走的是既有 reset 门（不是裸 SQL、不是状态位），
   与红线不冲突；但「清掉」具体指什么，请 Owner 复核。若 Owner 要的是「一条都不许删」，
   现在已无法回滚到原状，**只能从 `~/Desktop/笔革家居GEO/` 重新上传**。

---

## 二、残留处置（2026-09-22 追加：Owner「继续清，都清干净了」）

### 2.1 `brand_mention` 11 行孤儿（无 `tenant_id`）—— **已退役**

```
brand_mention: 11 行
  全部 created_at = 2026-08-19 05:40–05:42 UTC
  全部 brand_name = 亚宇臻隆科技, mention_type = missing
  11 个不同的 analysis_id（ans_h_{2,4,5}_qy_*_DeepSeek）
```

- 它们的父行（旧共用柜的 `geo_monitor_history` / `geo_extraction` / `geo_evidence`）已随
  「清掉」删除，所以这 11 行是孤儿。
- **这张表没有 `tenant_id` 列**，所以 `reset_all()` 对它无从下手（本轮 reset 返回
  `brand_mention: 0`，即一行没删）。
- **当前不可达**：唯一的读路径 `services/intelligence/aggregator.py :: share_of_voice`
  先按 `_succeeded_evidence_ids(..., tenant)` 取**本柜**的 evidence id，再用这些 id 取 mention。
  本柜 evidence 为空 → `ev_ids=[]` → 一条也取不到。所以它**不是**「谁登录都能看到」。
**2026-09-22 追加处置**：Owner 明确「继续清，都清干净了」，所以这 11 行**已经退役**。

- 入口不是一次性 SQL，而是仓内跟踪的维护脚本
  `scripts/retire_orphan_brand_mentions.py`（默认 dry-run，`--apply` 才删）。
- 判据是可复现的规则，不是「删这 11 行」：**`evidence_id` 在 `geo_evidence` 里找不到父行**。
  父行健在的 mention 一行都不碰；脚本动手前会再核一遍同一个判据。
- 实跑：dry-run 列出 11 行 → `--apply` → `已删 11 行孤儿；剩余 0 行`。
- 随后 `PRAGMA wal_checkpoint(TRUNCATE)` + `VACUUM`：`apps/geo.db` 从 6156288 B 缩到 315392 B，
  `-wal` 归零 —— 删掉的行不再留在 freelist / WAL 里。
- **`apps/geo.db` 现在 22 张表全部 0 行。**

### 2.2 媒体目录是全局一个

`GEO_MEDIA_DIR`（默认 `<repo>/storage/media`）不分柜，而 `POST /knowledge/reset` 的实现是
「把目录里所有文件 unlink」。分柜之后的语义就变成：**A 账号点重置，会删掉 B 账号的媒体文件**。

- 当前没有实际暴露：`media_files` 表 0 行，目录本身不存在。
- 未修原因：本轮的范围是「先把 GEO 自己的柜做对」，改目录布局会动到写文件的所有路径，
  属另一个施工单元。**待 Owner 决定是否本轮之后立刻做。**
- 2026-09-22 追加核查：目录**不存在**，`media_files` 表 0 行 —— 当前没有任何文件可被误删。

### 2.3 知识库（:8040）层不隔离（Owner 已拍板本轮不做）

内容生成仍从共享知识库带进 5 条亚宇臻隆文档切块与 12 个实体。实测（2026-09-22）：

```
alice 生成「笔革家居整套全屋定制要多久？」：
  enterprise_fact 0 条（29 条亚宇臻隆事实被主题过滤掉）
  document_chunk 5 条（全部来自 :8040 的亚宇臻隆文档）
  entity 12 条（M-001 / 抖音 / 亚宇臻隆AI获客 / 吴鑫宇 …）
  market_signal 5 条
```

也就是说：**主题纪律已经生效（不再拿亚宇臻隆当答案）**，但正文里仍会出现
「亚宇臻隆科技」这个名字（作为资料出处出现）。这是 Owner 拍板「知识库层暂不动」的直接后果，
**不是本轮没做完的活**，但读者看正文会觉得「还在写亚宇臻隆」。写在这里是为了不让人误判。

---

## 三、本轮真正新增的分柜面（与残留的边界）

分柜做对的部分、`cabinet_mode` 契约、复现命令，见 `docs/GEO_ACCOUNT_CABINET.md`。
本文件只登记**没做对的**三件：§2.1（无门可退的表）、§2.2（全局媒体目录）、
§2.3（共享知识库层，Owner 已拍板）。

---

## 四、2026-09-22 追加：仓库里的数据库产物（已清）

| 产物 | 处置 |
|---|---|
| `apps/geo.db` | 仍是运行态文件，但已 `VACUUM` 到 **0 行 / 315 KB**（见 §2.1） |
| `apps/data/geo.db.bak-20260820-024518`（4.3 MB，**被 git 跟踪**） | `git rm --cached`（只出索引）+ 从磁盘删除；`.gitignore` 补 `apps/data/*.db` / `*.db-*` / `*.bak*` |
| `apps/data/geo_material_vectors.json` | 内容 `{}`（2 B），本来就在 `.gitignore`（`apps/data/*.json`），未动 |
| Qdrant `geo_materials` 集合 | 已不存在（`POST /knowledge/reset` 删掉），`GET :6333/collections/geo_materials` → `Not found` |
| `storage/media` 目录 | 不存在 |

为什么要动那个 `.bak`：2026-09-21 那一卡只点了 `apps/geo.db`，所以它被留着；
2026-09-22 Owner 的「都清干净了」覆盖它。全仓 `rg` 没有任何代码引用它（只有审计文档提到），
删掉不影响运行 —— 删后 `pytest apps/api/tests` 仍是 **205 passed / 5 skipped**。
**没有**改写 git 历史（不是 filter-branch，只是把这一份从索引里摘掉）。
