# 退役老仓 `EIOS-ai/eios-geo` 的冻结分支（2026-09-20）

老仓 `EIOS-ai/eios-geo` 于 2026-09-20 按 Owner 拍板退役。删除前把它的 **10 个分支全部**
按原样搬进本仓，命名空间 `legacy/eios-geo/*`，SHA 与老仓逐一核对一致。

本仓 `main` **不接**这套历史：`main` 是从老应用线的一个干净提交导入出来的一次性提交
（`95351c9`），与老仓两条线都没有 commit 祖先关系。老仓的历史在这里只作为**只读存证**。

## 老仓其实是两条互不相干的孤根历史

`git merge-base` 为空 —— 两条线没有共同祖先，各自根提交独立。

### A 线 · 老应用（被保留的那条）

| 分支 | SHA | 说明 |
|---|---|---|
| `legacy/eios-geo/codex/geo-product-p1-foundation` | `5afbf48` | 本仓 `main` 内容的来源：`apps/` + `services/` + `adapters/` + 产品门 |

### B 线 · 半成品 observation（Owner 判定不要，仅存证）

| 分支 | SHA | 说明 |
|---|---|---|
| `legacy/eios-geo/main` | `65ce407` | 半成品线 tip：根 `app/` observation/capability/setup/monitor + `contracts/product/geo/*` + `packages/geo`（`@eios-product/geo`）+ `product.manifest.json` |
| `legacy/eios-geo/codex/geo-foundation-kbc2-integration` | `c5be690` | B 线侧支（与 `main` 同根不同枝，独有提交） |
| `legacy/eios-geo/codex/geo-p0-closure` | `baa8d84` | 同上 |
| `legacy/eios-geo/codex/model-capability-wave0` | `b244dce` | 同上 |
| `legacy/eios-geo/codex/model-capability-wave4` | `11d7da9` | 同上 |
| `legacy/eios-geo/cursor/align-confluence-pins-670e` | `bbb59ca` | `main` 的祖先 |
| `legacy/eios-geo/cursor/geo-wave4-into-main-f00f` | `11d7da9` | `main` 的祖先 |
| `legacy/eios-geo/cursor/integrations-pin-model-adapters-872c` | `cfd2a21` | `main` 的祖先 |
| `legacy/eios-geo/fix/geo-citation-normalize-dedup` | `0bc90d0` | `main` 的祖先 |

## 规矩

1. **B 线是存证，不是施工面。** 不要从 `legacy/eios-geo/main` 或它的侧支往下接着建：
   它的 `product.manifest.json` / `contracts/product/geo/*` / `@eios-product/geo` 都不是
   本产品现在的注册口径，本仓现在的口径是 `docs/GEO_PRODUCT_DOOR_MATRIX.md` + 产品门。
2. **A 线也只作为历史。** 本仓 `main` 的内容已经是 A 线的成品形态；要往回找某个文件的历史
   （`git log legacy/eios-geo/codex/geo-product-p1-foundation -- <path>`）才可以，别拿它当基线继续开发。
3. 这组分支**只增不减**：要删其中任何一个，先问 Owner。
4. B 线里唯一的活引用是 `eios-product-api` 早期 `_GEO_ACTIONS`（P1 observation 面）与
   `/api/product/geo/monitor/objects`、`observation/*`、`capability/*`、`setup/*` 那批路由 ——
   那批路由已于 2026-09-20 退役，见 `eios-product-api` commit `901f347`。

## 为什么还留着 B 线

Owner 明确说半成品那套不要。**删的是仓**，不是把 38 个提交悄悄抹掉：老仓删除后
GitHub 只保留有限窗口可恢复，所以这里把 ref 原样留下，谁也找不回的东西才是真删历史。
若 Owner 要求连存证也去掉，删除方式：

```bash
git push origin --delete $(git branch -r --list 'origin/legacy/eios-geo/*' | sed 's|origin/||')
```

（这是本文件唯一要求 Owner 下令才能执行的动作。）
