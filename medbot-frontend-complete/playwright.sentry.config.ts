import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests', testMatch: 'sentry.spec.ts', workers: 1,
  use: { baseURL: 'http://127.0.0.1:4175', channel: 'chrome' },
  webServer: {
    command: 'npm run dev -- --port 4175 --strictPort',
    url: 'http://127.0.0.1:4175', reuseExistingServer: false,
    env: {
      VITE_SENTRY_DSN: 'https://public@replay.invalid/1',
      VITE_SENTRY_ENVIRONMENT: 'replay-test',
      VITE_SENTRY_TRACES_SAMPLE_RATE: '0',
      VITE_SENTRY_PROFILE_SESSION_SAMPLE_RATE: '0',
      VITE_SENTRY_REPLAY_SESSION_SAMPLE_RATE: '0',
      VITE_SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE: '1',
    },
  },
});
