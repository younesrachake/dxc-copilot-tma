import { defineConfig, devices } from '@playwright/test';

/**
 * E2E against the real stack:
 *  - backend: uvicorn in LLM-simulation mode (no API keys → deterministic fallback
 *    replies) with DISABLE_LOCAL_ML/DISABLE_CHROMA so no model downloads happen in CI
 *  - frontend: ng serve (dev apiUrl already points at localhost:8000)
 * Admin credentials come from E2E_ADMIN_PASSWORD (seeded via INITIAL_ADMIN_PASSWORD).
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1, // shared backend DB — keep tests sequential
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:4200',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      command: 'python -m uvicorn app.main:app --host 127.0.0.1 --port 8000',
      cwd: './backend',
      url: 'http://127.0.0.1:8000/healthz',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        DISABLE_LOCAL_ML: '1',
        DISABLE_CHROMA: '1',
        DATABASE_URL: 'sqlite+aiosqlite:///./e2e_test.db',
        JWT_SECRET: 'e2e_test_secret_key_with_32_characters_min',
        INITIAL_ADMIN_PASSWORD: process.env.E2E_ADMIN_PASSWORD || 'E2eAdminPass1234!',
        LOG_DIR: './logs',
        ENV: 'development',
      },
    },
    {
      command: 'npm start',
      url: 'http://localhost:4200',
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
