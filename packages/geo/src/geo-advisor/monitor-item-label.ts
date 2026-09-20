/** 监测对象 config_json.product 可能是字符串（产品类型）或字符串数组（品牌/竞品）。 */
export function formatMonitorProductLine(product: unknown, fallback: string): string {
  if (Array.isArray(product)) {
    const parts = product.map((p) => String(p).trim()).filter(Boolean)
    return parts.length > 0 ? `产品：${parts.join('、')}` : fallback
  }
  if (typeof product === 'string' && product.trim()) {
    return `产品：${product.trim()}`
  }
  return fallback
}
