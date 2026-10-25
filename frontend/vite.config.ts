import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import AutoImport from 'unplugin-auto-import/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, '.', 'API_').API_PROXY_TARGET || 'http://127.0.0.1:8000'
  return {
  plugins: [vue(),
    AutoImport({ resolvers: [ElementPlusResolver()], dts: false }),
    Components({ resolvers: [ElementPlusResolver()], dts: false })],
  server: { proxy: { '/api': target } },
  preview: { proxy: { '/api': target } },
  }
})
