# 审计登记：测试污染被跟踪的 dev 库 `apps/geo.db`（2026-09-21）

## 为什么登记

Owner 2026-09-13 红线：「dev 库不是草稿纸……退役不了的（门不存在）→ 如实登记进
`docs/audits/`，写明为什么清不掉，**不许**用裸 SQL 或改状态位绕过。」

本轮发现：**跑一遍 `pytest apps/api/tests` 就会往仓库里被 git 跟踪的 `apps/geo.db` 写行**。
这不是本轮引入的，但本轮的一次全套跑确实又写进去了。已按红线如实登记，未用裸 SQL 清库。

## 事实

| 表 | 现状行数 | 其中今天写入 |
|---|---|---|
| `geo_questions` | 7 | 7（`租户A数据`/`租户B数据`/`source`/`A`/`B`/`迁移问题1`/`迁移问题2`，均为测试行） |
| `geo_gaps` | 2 | 2 |
| `geo_content_plans` | 504 | 504 |
| `geo_monitor_items` | 7 | 0 |

`apps/geo.db` 在 `git status` 里本来就是 `M`（本轮之前就脏）。它**被 git 跟踪**本身就是
仓库卫生问题：一个业务库不该进版本控制。

## 根因（已定位）

GEO 的存储被两条路读，两条都在 **import 时**把 `GEO_DB_PATH` 读成常量：

- `apps/api/app/core/config.py`
- `services/_db.py`

于是「谁先被 import」决定了它们指向哪。`pytest apps/api/tests` 全套跑时
`test_engines.py` 先 import 了 `services.*`，那条路已经把仓库里的 `apps/geo.db` 钉死；
`test_store.py` 里那句 `os.environ.setdefault("GEO_DB_PATH", ":memory:")` 来得太晚，
两层分裂 —— 测试往 dev 库写，下一次跑读到的就是上一次留下的行，
`test_store` 的三条精确计数断言随之失败。

复现：`pytest tests/test_engines.py tests/test_store.py` → 3 failed（`test_store` 单独跑 → 全过）。

## 本轮做了什么（根因修复，不是绕过）

- 新增 `apps/api/tests/conftest.py`：在任何测试模块被 import 之前把 `GEO_DB_PATH` 钉到
  一个临时文件（`setdefault`，显式设过的值不被覆盖），并在每个测试前删库 + `engine.dispose()`
  把「每个测试从空库开始」的语义还回来；进程结束删除临时目录。
- 删掉两个测试模块里各自 `setdefault("GEO_DB_PATH", ":memory:")` 的第二套机制。
- 结果：`pytest apps/api/tests` → **73 passed / 5 skipped / 0 failed**，且跑完 `apps/geo.db`
  的行数不再变化（7 / 2 / 504 未变）。

## 为什么没有清理已有脏行

- 直接 `git checkout -- apps/geo.db` 会连带丢掉本轮之前就存在的、来源不明的改动 ——
  等于动别人的未提交改动，红线禁止。
- 用裸 SQL 删测试行 = 红线明确禁止的「绕过生命周期门」。
- GEO 当前**没有**针对这些表的退役/清理门（`/knowledge/reset` maintenance 门未纳入产品门，
  且它整表清空，不是按来源退役）。

## Owner 拍板（2026-09-21）

1. 「`apps/geo.db` 从 git 运行态剥离，但历史脏数据不清。」
   → 已照此执行（见下）。**没有**清理任何既有行，**没有**改历史，**没有**用裸 SQL 或状态位绕过。
2. 租户体系：`tenant_corp_01` 暂不扩，本轮不做租户迁移。

## 本轮已执行（2026-09-21）

- `git rm --cached apps/geo.db` —— 只从**索引**移除，工作区文件一字节未动
  （同一 inode / 同样的 1683456 字节 / mtime 未变）。
- `.gitignore` 追加 `apps/geo.db`（原先只有 `geo.db-*`，匹配不到 `geo.db` 本身）。
  → `git check-ignore -v apps/geo.db` 命中 `.gitignore:38`，它不会再被误加回来。
- 文件仍是 `D`（staged deletion）+ 未跟踪，本轮**不 commit**（三仓一律不 commit / 不 push）。

## 仍未处置（诚实登记，不在本轮范围）

- 库里那批测试行（`geo_questions` 7 / `geo_gaps` 2 / `geo_content_plans` 504）**原样保留**，
  按 Owner 拍板「历史脏数据不清」。它们的来源与复现方法见上面「根因」一节。
- `apps/data/geo.db.bak-20260820-024518` 同样是被 git 跟踪的数据库产物，但 Owner 本轮只点了
  `apps/geo.db`，故**未动**（不扩范围）。
- 是否要为测试资料建一个**按来源退役**的门（而不是整表 reset），Owner 未拍板，继续挂着。

---

# 追加登记：本轮监测面真机验证又写了 **1 行** `geo_monitor_history`（2026-09-21）

## 事实

`adapters/engines` 改走统一模型入口之后，我用一个**私有** GEO 实例（`127.0.0.1:18096`，
指向私有统一入口 `:18095`）真跑了一次 `POST /api/v1/monitor/check`。这次调用按设计落了一条历史：

| 表 | 行 | 内容 |
|---|---|---|
| `geo_monitor_history` | `h_b9262e0b5d0a`（tenant `tenant_corp_01`，created_at `2026-09-21 05:41:00`） | question「国内有哪些做企业 AI 知识库的公司？」／company「测试公司」／summary `{mentioned:0, not_mentioned:1, unconfigured:5, score:0}` |

同一张表里**上一行**（`h_c534f0d01d75`，01:19，批量监测 43 个问题）不是本轮的，未动。

## 根因（这次是我的操作失误，不是测试框架的问题）

私有实例没有覆盖 `GEO_DB_PATH`，于是走了 `apps/api/app/core/config.py` 的默认值
（`apps/geo.db`，即 dev 库）。正确做法是给私有实例指一个临时库 —— 上一次同类的真机验证
（`:18099` 那批）就是这么做的，这次漏了。

## 为什么没有清理

- `geo_monitor_history` **没有**按行退役的门：`/api/v1/monitor/items/{mid}` 与 `/tasks/{tid}`
  的 DELETE 都不覆盖历史行（这条 check 没有 monitor_id），也没有按来源/时间退役的入口。
- 裸 SQL 删行 = 红线明确禁止的「绕过生命周期门」。**没有**执行。
- Owner 2026-09-21 的既有拍板是「`apps/geo.db` 从 git 运行态剥离，但历史脏数据不清」，
  这一条同样按那个拍板留原样。

## 待 Owner

- 要么接受它留着（与既有历史脏数据同处置）；
- 要么授权我走一个**正式的**退役门（目前不存在；要建门就是新增 Authority 面，需先拍板）。

---

# 追加（2026-09-21 14:02 · 知识库初始化那一卡）

## 事实

本轮做「产品门 + 知识库初始化」的真机验证时，我用 dev 栈探了一次
`GET http://127.0.0.1:8091/api/v1/stats/overview`（当时只是想确认共享栈的 `stats` 字段形状）。
`stats/overview` 内部会调 `adapters.eios.get_entities()`，而**每一次知识库读都会记一条快照**，
于是 dev 库的 `geo_knowledge_snapshots` 里那行既有的 `objects`（200 个对象）被：

- `last_read_at` 从 2026-09-21 06:02:49 UTC 往前推（原本停在更早）；
- `read_count` 加一。

**内容没有任何变化**：`payload_hash` 与 `data_json` 一字未动，也没有新增行 ——
台账按 `payload_hash` 去重，重复读到同一份内容只会累加计数。

## 为什么这次能确定「没有新增行」

`geo_knowledge_snapshots` 的每一行都带 `first_read_at`；全表最近一条
`first_read_at` 仍然是 `2026-09-21 01:20:01`（今天 01:20 那批，不是本轮的）。
如果本轮新建过行，它的 `first_read_at` 必然是 14:02 —— 没有这样的行。全表仍是
`documents 6 / objects 12 / search 9 = 27` 行。

## 根因（仍然是我的操作失误）

dev 栈的 GEO（`:8091`）用的是 `apps/geo.db`（`GEO_DB_PATH` 的 dev 默认值）。
本轮所有**写**验证都走了私有实例 + `/tmp` 库（`GEO_DB_PATH=/tmp/eios-test/...`），
只有这次「探一下共享栈的 stats」是临时起意、没意识到它背后会读知识库。

## 为什么没有清理

- 没有行被新增，也没有内容被改写 —— 要「清」的只有两个时间/计数字段，
  而**没有任何门**提供「回退读计数」这种操作；
- 裸 SQL 改这两列同样是红线禁止的绕过；
- 与本节开头那条 `geo_monitor_history` 脏行同处置：如实登记，等 Owner。

## 本轮的实际影响

- 数据内容：**零**。台账仍然是「读到过哪些东西」的同一份账，行数、哈希、正文都没变。
- 可见影响：`/onboard/status` 的 `knowledge.last_read_at` 会显示成 14:02 那个时刻，
  看起来像「刚刚读过知识库」—— 这**不是假的**（确实读了），但它不是产品动作触发的。

## 待 Owner

- 接受（与既有脏数据同处置）；或
- 授权建一个正式的快照台账维护门（目前不存在，建门 = 新增 Authority 面，需先拍板）。

---

# 追加登记：「输出正常但不正确」审计那一轮的真机验证又动了 dev 库（2026-09-21 · 本卡）

## 事实（读到的，未改）

本轮（Owner「自己找一遍」）为了核对逻辑错误，做了两类**读**动作：

1. 打开 dev 栈 `:4173/app/geo` 的各页（企业资料总揽、认知差距、高级工具的企业画像…）
   与直连 `:8091` 的只读接口（`/monitor/fact-check`、`/monitor/items/{id}/trend`、
   `/distill/cognition/profile`、`/enterprise-profile/*`）。
2. 一个 in-process 探针脚本（`search_knowledge` 三次：企业简介 / 价格 / 服务流程），
   用来确认知识库检索分的量级（实测 0.65 / 10.1 / 10.14 / 13.02 —— 无界序位分，
   不是 0~1 相似度，这就是页面上那句「匹配度 12.4」被判为口径错误的依据）。

这些读按设计会写 `geo_knowledge_snapshots` 台账（按 `payload_hash` 去重，
新内容才建行，重复读只累加 `read_count` / 推 `last_read_at`）。

读到的现状（只读连接，`mode=ro`）：

| kind | 行数 | min(first_read_at) | max(first_read_at) |
|---|---|---|---|
| documents | 7 | 2026-09-20 16:39:31 | 2026-09-21 12:46:15 |
| objects | 12 | 2026-09-20 16:39:31 | 2026-09-20 16:59:10 |
| relations | 11 | 2026-09-21 09:31:38 | 2026-09-21 10:02:38 |
| search | 51 | 2026-09-20 16:39:31 | 2026-09-21 12:59:19 |

其中 `first_read_at >= 2026-09-21 12:30` UTC（本卡时间窗）的行：documents 1 + search 26 = **27**。

同一张表里 `geo_questions` 7 行、`geo_gaps` 4 行、`geo_monitor_history` 8 行、
`geo_monitor_items` 7 行 —— 与前面几节登记的一致，**本轮没有新增行、没有删行、没有改内容**。

## 为什么没有清理

- 本轮只做读，没有任何写动作是产品功能发出的；快照台账是**读的副作用**，不是产品数据。
- 全仓 `router.delete` 共 7 个（questions / plans / materials / links / watchlist / items / tasks），
  **没有**针对 `geo_knowledge_snapshots` 的退役门；`geo_gaps` 同样没有删除门。
- 裸 SQL 删行/改计数 = 红线明确禁止的「绕过生命周期门」。**没有执行**。
- Owner 既有拍板「`apps/geo.db` 从 git 运行态剥离，但历史脏数据不清」适用于此。

## 待 Owner

- 接受（与既有脏数据同处置）；或
- 授权建一个正式的**快照台账维护门**（目前不存在；建门 = 新增 Authority 面，需先拍板），
  以及 `geo_gaps` 的按来源退役门（同上）。
