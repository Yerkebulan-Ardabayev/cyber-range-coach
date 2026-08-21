import { defineConfig } from '@playwright/test'

const e2ePort = Number(process.env.CRC_E2E_PORT ?? 4173)
const e2eBaseUrl = `http://127.0.0.1:${e2ePort}`

export default defineConfig({
  testDir: './e2e',
  outputDir: process.env.CRC_E2E_OUTPUT_DIR ?? 'test-results',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: e2eBaseUrl,
    browserName: 'chromium',
    headless: true,
    trace: 'retain-on-failure',
  },
  webServer: process.env.CRC_E2E_EXTERNAL_SERVER ? undefined : {
      command: `npm run dev -- --host 127.0.0.1 --port ${e2ePort} --strictPort`,
      url: e2eBaseUrl,
      reuseExistingServer: false,
      timeout: 30_000,
    },
})
