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
