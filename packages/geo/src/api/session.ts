/**
 * GEO 产品自己的会话取用点。
 *
 * 独立部署里 token 由 `eios.product_host/v1` 的 host.hello / host.session 送到
 * `configureGeoProductTransport`（见 geo-advisor/geo-api.ts），这里只是那条注入面
 * 之外的最后一道兜底：谁若在页面里用别的方式登录，可以 setAuthToken 告诉 geo-api。
 * 它**不读**旧 yayu Client 的模块状态，也不持有任何持久化凭据。
 */
let authToken: string | null = null

export function setAuthToken(token: string | null) {
  authToken = token
}

export function getAuthToken(): string | null {
  return authToken
}
