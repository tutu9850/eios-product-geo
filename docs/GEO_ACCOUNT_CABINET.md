# GEO 账号分柜（Owner 2026-09-22 拍板）· 契约与边界

Owner 原话：

> 「这个 geo 也要跟人帐号走，不能所有人都用这么一个数据库，每个人的存储在自己账号下，
> 这个产品注册一个人就开一份存储空间……假如 a 就做亚宇臻隆的 geo 内容，那就让他做，
> b 只做笔革家居的，就让他一个人做笔革家居」

追问三选之后 Owner 拍板：

> 「登录账号分柜　清掉　3 暂时不用，先把 GEO 自己的柜做对」

即：

1. 柜按**登录账号**分（不是按部门、不是按浏览器）；
2. 清掉旧共用柜（`tenant_corp_01`）里已经没人能读到的存量；
3. **知识库（:8040）层暂不隔离** —— 它是另一套权威，属跨域，本轮不动。

本文件是这件事的口径来源：**哪些面分了柜、哪些还没分、怎么验证**。

---

## 1. 柜是什么

柜 = GEO 自己那份 SQLite（`apps/geo.db`）里的 `tenant_id` 列的值。GEO 的 20 张业务表里
18 张带 `tenant_id`（见 §5 的两张不带）。

- 柜号的唯一来源是**已经过验签的会话主体**：`cabinet_for_session(session)`。
  - `human:alice` → `acct_human_alice`
  - 主体里没有可用的 ASCII 片段（纯中文 / 符号 / 空）→ `acct_<sha256 前 16 hex>`
  - **不回落默认柜**：回落等于把「分不清是谁」变成「大家一起用」。
- 调用方给的头**不参与**柜号。`X-Tenant-Id` 只在 `GEO_AUTH_MODE=legacy` 那条老路上还有意义。

实现点：

| 位置 | 作用 |
|---|---|
| `apps/api/app/product/session.py :: cabinet_for_session` | 从已验证会话推柜号（唯一算法） |
| `apps/api/app/main.py :: _tenant_context` | auth_context 模式下把当前请求钉到该柜 |
| `apps/api/app/services/store.py :: set_tenant / current_tenant` | 请求级 contextvar；业务层零改动读柜号 |
| `services/_db.py :: _tenant / current_tenant_or_default` | 给非 `app.*` 的 services 模块同一套解析（延迟 import，不建第二份状态） |

## 2. `cabinet_mode` 契约

`GET /api/product/geo/health`（`product.geo_health/v1`）新增一个字段：

| 字段 | 取值 | 含义 |
|---|---|---|
| `identity_mode` | `auth_context` / `legacy` | 要不要宿主票（未变） |
| `storage_mode` | `postgres` / `legacy` | 底层是不是 product-owned PostgreSQL（未变） |
| **`cabinet_mode`** | **`account` / `none`** | 数据按什么分柜 |

`cabinet_mode=account` **只在身份真被验过签时成立**（`auth_context` 模式）；
没验签时分不出「这个账号是谁」，那时报 `none`，不许把「没验」说成「按账号分了」。

`status` 的判据随之改：`auth_context + account` 即为 `ok`（本部署是 GEO 自己的库，
不等 P2 的 product PostgreSQL）。旧的两条 `migrated` / `acknowledged` 判据原样保留。

**这是本轮唯一对既有契约的改动，改了产品可见字段，需 Owner 复核。**

## 3. `GEO_AUTH_MODE=auth_context` 的语义变化

| | 改前（P1） | 改后（本轮） |
|---|---|---|
| 未带票 | 401 | 401（未变） |
| 票无效 / 验签器缺失 | 401 / 503 | 401 / 503（未变） |
| 票有效之后 | 503 `PRODUCT_STORAGE_NOT_READY`（拒绑旧 SQLite，等 P2） | 钉到 `acct_<principal>` 这个柜并服务 |

`env.sh` 的 `GEO_PDP_MODE` 那类**没有**被放宽：`EIOS_PDP_MODE=deployment_reads`、
`EIOS_PDP_BUSINESS_READERS`、`EIOS_PDP_BUSINESS_SCOPES` 一字未动。
本轮的改动只是「验过之后数据放哪个柜」——而这件事以前根本没有发生。

dev 栈默认值在 `eios-dev/lib/wrappers/geo.sh`：
`export GEO_AUTH_MODE="${GEO_AUTH_MODE:-auth_context}"`。要退回老行为：
`GEO_AUTH_MODE=legacy bash bin/eios-dev up`。

### 3.1 不参加宿主身份门的一条路径

`/api/v1/geo/consumer/*`（顾问只读交接面）**不套**宿主票，走它自己的
`app.product.consumer_auth`。理由是它与宿主门不是同一道门：拿宿主票在那里开柜会读错柜。
Owner 2026-09-21「顾问先不考虑查 GEO 数据」，所以这一面保持原样（默认柜），
等顾问真的接入读 GEO 数据时再单独定它读哪个柜。

## 4. 真实验收（2026-09-22 · 实跑）

| 项 | 命令 | 结果 |
|---|---|---|
| 无票直连产品门 | `curl :8091/api/product/geo/health` | **401** |
| 无票直连老 v1 面 | `curl :8091/api/v1/knowledge/materials` | **401** |
| 经 Client 同源路径 | `curl -b alice.jar :4173/api/product/geo/health` | `identity_mode=auth_context` / `cabinet_mode=account` / `status=ok` |
| 分柜（账号级） | alice 与 carol 各查自己的素材 | alice 见自己的 1 条 / carol 见自己的 1 条，互不可见 |
| 新账号是空柜 | `002` / `003` 各查素材 | **各 0 条**（不是「看到别人的」） |
| 伪造柜头不生效 | carol 带 `X-Tenant-Id: acct_human_alice` 查素材 | 返回**仍是 carol 自己的** 1 条 |
| 旧共用柜已清 | `select tenant_id,count(*) from geo_kb group by 1` | 只有 `acct_human_alice` / `acct_human_carol` |
| Client 内嵌页 | 浏览器 `:4173/app/geo` → 企业资料 → 内容资产 | 渲染正常，网络只打 `/api/product/geo/*` |

`002` / `003` 是 `host_users.dev.json` 里既有的两个 dev 账号 —— 用它们当「从没写过东西的
第三个账号」，就是为了排除「大家都在读同一个柜，只是恰好为空」这种解释。

### 4.1 主题优先（同一个 Owner 诉求的另一半）

Owner 原话：「要按主题来啊，我输入的什么主题，就是什么主题，不能根据公司名字来回答啊」。

在 `services/content/__init__.py`：

- 新增 `topic_rule(question, company_name)` 主题纪律块，三份 prompt（通用 / 默认 / SEO）
  都插入；「## 企业信息」改名「## 企业资料（用来支撑上面的题目，不是文章主角）」。
- `_official_fact_lines()` 的正式事实从「整包取前 30 条」改成**按主题 n-gram 选**
  （阈值 `_FACT_MIN_SCORE=2.0`，上限 `_MAX_TOPIC_FACTS=8`）。

实测（carol，主题「笔革家居主理人的经营理念是什么？」）：`enterprise_fact` **0 条**
（29 条亚宇臻隆事实被主题过滤掉），正文通篇答笔革。
实跑（alice，主题「笔革家居整套全屋定制要多久？行业内部流程拆解」）：
`enterprise_fact 0 条` / `知识库文档切块 5 条` / `知识库实体 12 条` / `历史内容资产 1 条`；
正文出现「企业知识库中没有对应数据，本文不作推测」——**没有编造天数**。

**被打分公式动过的地方：没有。** `build_context` 的排序口径、`_relevance_order`、
`n_gram_scores` 一字未动；本轮只改「注入哪些条目」和「按柜取数」。

## 5. 分柜做到哪、没做到哪（诚实清单）

### 已分柜

- GEO 自己库的 18 张带 `tenant_id` 的表（素材/问题池/缺口/计划/监测对象与历史/认知评估/
  链接/关注/画像/快照台账…）。
- `reset_all()` 的默认租户从写死的 `tenant_corp_01` 改成**当前柜** —— 改之前「登录账号点
  重置」清的是所有人共用的那个柜，自己的一点没动，分柜后这是个真错。
- 定时任务（`services/scheduler.py :: _for_each_tenant`）本来就按
  `list_tenant_ids()` 逐柜跑，未改。

### 没分柜（本轮刻意不做，Owner 拍板「3 暂时不用」/「知识库层暂不动」）

1. **知识库（:8040）层**。内容生成仍会从那里带进 5 条亚宇臻隆文档切块与 12 个实体
   （主体是亚宇臻隆）。Owner 拍板本轮不动；`enterprise_fact` 已按主题归零，
   但 `document_chunk` / `entity` 仍会带。**这是本轮最明显的一处「还没做对」。**
2. **`brand_mention` 表没有 `tenant_id` 列**，见 §6。
3. **媒体目录 `storage/media` 是全局一个**，`reset` 会把目录里所有文件删掉，不区分柜。
   当前 `media_files=0`、目录不存在，所以没有实际暴露；分柜做到底时目录也要按柜分。

## 6. 未处理的残留（已登记 `docs/audits/`，未用裸 SQL）

`geo.db` 现在只剩 11 行 2026-08-19 的 `brand_mention`（都是「亚宇臻隆科技 / missing」），
它们的父行（旧共用柜的 `geo_monitor_history`）已按 Owner「清掉」删除，于是成了孤儿行。
`brand_mention` 没有 `tenant_id`，也没有退役门，读路径（`aggregator.share_of_voice`）
按 `_succeeded_evidence_ids(..., tenant)` 先取本柜 evidence id 再取 mention，
所以这 11 行**当前不可达**，不是「谁登录都能看到」。按红线不许裸 SQL 删，登记在
`docs/audits/2026-09-22-account-cabinet-residue.md`。

## 7. 复现

```bash
# 1) dev 栈（正式 wrapper，不需要任何私有环境变量）
cd ~/eios-dev && bash bin/eios-dev up          # geo.sh 自己就会设 GEO_AUTH_MODE=auth_context

# 2) 分柜（同一个账号两把 cookie 互查）
curl -s -c /tmp/eios-test/alice.jar -X POST http://127.0.0.1:8090/api/product/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"alice","password":"alice-dev"}'
curl -s -b /tmp/eios-test/alice.jar http://127.0.0.1:4173/api/product/geo/knowledge/materials

# 3) fail-closed 不能松
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8091/api/product/geo/health   # 401

# 4) 单测
cd ~/eios-product-geo
env -u GEO_DB_PATH -u GEO_PRODUCT_DOOR -u EIOS_PDP_MODE -u GEO_AUTH_MODE \
  PYTHONPATH="apps/api:$HOME/eios-product-geo:$HOME/eios-integrations:$HOME/eios-foundation:$(ls -d $HOME/eios-foundation/packages/* | tr '\n' ':')" \
  .venv/bin/python -m pytest apps/api/tests -q
```

## 8. 单企业前提（写给以后的人）

柜号只用 `principal`，**没用** `enterprise`。本部署是单企业部署（`EIOS_ENTERPRISE_ID` 一个值），
所以两个企业里同名的 `alice` 不可能同时出现。**若以后一个 GEO 部署服务多企业，
柜号必须把 enterprise 加进去**，否则两个企业的 `alice` 会落进同一个柜。
`services/scheduler.py` 的逐柜遍历同理。
