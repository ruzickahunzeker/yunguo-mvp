import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1, timeout: 45000,
  reporter: 'list', use: { baseURL: 'http://127.0.0.1:8803', trace: 'off', screenshot: 'off', video: 'off' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    { command: '../.venv/bin/python ../scripts/e2e_server.py', url: 'http://127.0.0.1:8800/api/health', reuseExistingServer: false, timeout: 60000 },
    { command: 'API_PROXY_TARGET=http://127.0.0.1:8800 node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 8803 --strictPort', url: 'http://127.0.0.1:8803', reuseExistingServer: false },
  ],
})
