import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

/**
 * GEO 产品自带界面的制品。
 *
 * 公开路径是 **Client 同源的 `/product/geo/`**：生产由 Client 容器自己的 nginx 把
 * `/product/geo/*` 转发到本产品的容器；dev 由 eios-product-api 的同一前缀转发到本
 * 产物的静态服务器（`eios-dev/lib/wrappers/geo-ui.sh`），与 advisor / semantic 同形。
 * 下面这个 dev server 只用于界面自己的迭代，**不是验收入口** —— 验收一律走 Client。
 */
export default defineConfig({
  base: '/product/geo/',
  // 隔离验收可将制品写入任务目录，避免覆盖正在使用的界面制品。
  build: { outDir: process.env.GEO_UI_OUT_DIR ?? 'dist' },
  plugins: [react(), tailwindcss()],
  resolve: {
    // 用带锚点的正则而不是字符串前缀：字符串形式下 `@geo-advisor` 会先吃掉
    // `@geo-advisor/geo-api`，把它解析成 `index.tsx/geo-api`（vite 8 / rolldown 下实测）。
    alias: [
      { find: /^@geo-advisor$/, replacement: path.resolve(import.meta.dirname, 'src/geo-advisor/index.tsx') },
      { find: /^@geo-advisor\//, replacement: path.resolve(import.meta.dirname, 'src/geo-advisor') + '/' },
      { find: /^@yayu\/ui\/theme\.css$/, replacement: path.resolve(import.meta.dirname, '../ui/src/tokens/theme.css') },
      { find: /^@yayu\/ui$/, replacement: path.resolve(import.meta.dirname, '../ui/src/index.ts') },
    ],
  },
  server: {
    host: '127.0.0.1',
    strictPort: false,
    proxy: {
      '/api/product/geo': {
        target: process.env.VITE_PRODUCT_API_TARGET ?? 'http://127.0.0.1:8090',
        timeout: 300_000,
        proxyTimeout: 300_000,
      },
    },
  },
})
