# GEO 前端 R1 预览授权

用户原文：“可以，先找一个工作树去重构前端，先把ui表现形式弄出来在cliet里，给我看一下”。

复用干净当前开发树 `/Users/tutu/eios-product-geo`，`codex/geo-ui-layout@c4ec5b9`。历史打包树保留不动。范围为前端导航、主线路径、总览重复内容整理、术语及 Client 内隔离预览；不修改后端、身份、数据口径、共享部署或正式产品可用性。没有删除业务能力、推送或合并。

Client 服务端 GEO 为 NOT_CONFIGURED。独立临时预览代理在 43818 使用真实 Client 前端和真实登录，只对 GEO 可用性读取提供显式界面夹具，并服务临时 GEO 构建；所有 GEO 业务请求返回 UI_PREVIEW_ONLY，不能据此声称真实产品已开放。独立走查与真实闭环仍待验收。
