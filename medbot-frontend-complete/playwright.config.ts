import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests', testIgnore: '**/sentry.spec.ts', fullyParallel: true, workers: 2,
  use: { baseURL: 'http://127.0.0.1:5173', channel: process.env.PLAYWRIGHT_EXECUTABLE_PATH ? undefined : 'chrome',
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH,
      args: ['--no-sandbox', '--disable-dev-shm-usage'] } : undefined, screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['iPhone 13'], viewport: { width: 402, height: 874 }, defaultBrowserType: 'chromium' } },
  ],
  webServer: { command: 'npm run dev', url: 'http://127.0.0.1:5173', reuseExistingServer: true },
});
