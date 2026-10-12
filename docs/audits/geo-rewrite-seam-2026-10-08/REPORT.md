# GEO 改写出处接缝修复

2026-10-08。用户纠正：当前目标是 GEO 代码接缝，不是制作企业内容。本轮恢复 CONTENT-01 工程范围。

## 首偏离与修复

G-RW-01：生成结果包含具体原文选段，但 GeoContentGenForm 改写请求只传 source_material_ids。ImproveIn 没有 context_sources，服务重新 build_context 选段。虽然沿用文件ID，仍可能因题目、资料或知识变化换掉原稿依据。现有保存门已能校验段落、当前柜、块号和摘要，可复用，无需新表或权限。

修复：UI 将原稿 context_sources 随改写请求传回；API 复用保存出处校验；上传选段直接核对当前柜内原块，其他来源通过既有读取逻辑复核，不能验证则拒绝。服务对已校验来源按原投影组装改写依据，不重新排序或补充新来源。问题池/监测信号仍不作为企业事实。旧调用未提供出处时保持旧行为；提供空出处时明确没有原稿依据。知识读取状态保守返回 unknown，不宣称重新读取成功。

涉及 content.py、services/content/__init__.py、GeoContentGenForm.tsx 和 test_geo_content_provenance.py。前后两条改写路径与保存路径一并调查；不改变事实、权限或状态语义。

## 验证

全量 pytest：351 passed、5 skipped（监测PostgreSQL环境未配置）。UI类型与临时目录构建通过。新增六项覆盖改写原文保持、四类不可用出处在模型前拒绝，以及认证GEO产品门改写→保存→重新读取正文/出处一致。模型替身用于捕获真实提示内容，不调用Provider；测试全部任务临时库，不改开发库。git diff --check通过。

本轮没有跑完整Client→Product API→GEO浏览器链、真实Provider、部署更新或进程重启，因此不能把门内集成测试写成共享页面已上线。默认产品门off，测试显式on；现有清单/scope不变。相邻Product API/Foundation只读，未跨仓、迁移、提交或推送。

## 状态与下一步

本接缝代码和隔离验证DONE；CONTENT-01总体PARTIAL。继续核对Knowledge读取失败/快照失效与Product API模型预算，按实际部署契约修复；正式生产存储仍待裁决与交付。当前部署尚未使用本轮代码。

上一轮把用户继续施工误解为制作内容，新增三篇本机草稿及交付文档。这是执行偏离，不作为当前开发成果或用户业务授权；记录保留，未继续生成、修改或删除共享草稿。current已纠正。
