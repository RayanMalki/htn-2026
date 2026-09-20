import { test, expect } from '@playwright/test';
import { parseEnvelope } from '@sentry/core';
import { unzipSync } from 'node:zlib';

test('an error sends a replay with masked text and inputs', async ({ page }) => {
  test.setTimeout(45000);
  const types: string[] = [];
  const recordings: string[] = [];
  await page.route('https://replay.invalid/**', async route => {
    const body = route.request().postDataBuffer();
    if (body) {
      const [, items] = parseEnvelope(body);
      for (const [header, payload] of items) {
        types.push(header.type);
        if (header.type === 'replay_recording') {
          const bytes = Buffer.from(payload as Uint8Array);
          // Replay recording items contain a JSON header followed by rrweb data.
          const data = bytes.subarray(bytes.indexOf(10) + 1);
          recordings.push(data[0] === 91 ? data.toString() : unzipSync(data).toString());
        }
      }
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  await page.route('**/api/config', route => route.fulfill({ json: { model_mode: 'mock' } }));
  await page.goto('/');
  const rates = await page.evaluate(async () => {
    const entry = '/src/main.tsx';
    const { sentryReady } = await import(entry);
    const sentry = await sentryReady;
    const options = sentry.getClient().getOptions();
    return [options.replaysSessionSampleRate, options.replaysOnErrorSampleRate, !!sentry.getReplay()];
  });
  expect(rates).toEqual([0, 1, true]);
  expect(types).not.toContain('replay_event');
  await page.evaluate(() => {
    const marker = document.createElement('p');
    marker.id = 'replay-probe';
    marker.textContent = 'PRIVATE_MEDBOT_REPLAY_TEXT';
    document.body.append(marker);
  });
  await page.getByLabel('Start with an Instagram Reel or YouTube Short').fill('https://private-input.invalid/secret');
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await page.evaluate(() => { setTimeout(() => { throw new Error('MedBot Replay fixture error'); }, 0); });
  await expect.poll(() => types, { timeout: 30000 }).toEqual(expect.arrayContaining(['event', 'replay_event', 'replay_recording']));
  const recording = recordings.join('\n');
  expect(recording).toContain('replay-probe');
  expect(recording).not.toContain('PRIVATE_MEDBOT_REPLAY_TEXT');
  expect(recording).not.toContain('private-input.invalid');
});
