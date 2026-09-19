import { test, expect } from '@playwright/test';

const id = '11111111-1111-4111-8111-111111111111';
const passageText = 'Routine vitamin C supplementation did not reduce the incidence of the common cold.';
const claim = { id: 'c1', text: 'Vitamin C prevents the common cold.', start: 0, end: 12, search_terms: ['vitamin C cold'] };
const complete = {
  id, source_url: 'https://www.instagram.com/reel/test123/', status: 'complete', sequence: 8,
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  started_at: new Date().toISOString(), finished_at: new Date().toISOString(), error: null,
  result: { schema_version: 1, model_mode: 'live', timings: { total: 42.1 },
    analysis: { transcript: [{ start: 0, end: 12, text: claim.text }], claims: [claim], omitted_claims: 0 },
    claims: { c1: { claim, status: 'complete', verdict: { label: 'contradicts', explanation: 'This test fixture cites an exact passage.',
      citations: [{ passage_id: 'p1', quote: passageText }], limitations: ['Abstract-only evidence in this browser test.'] },
      evidence: [{ id: 'p1', paper_id: 'MED:123', title: 'Vitamin C prevention review', source_url: 'https://europepmc.org/article/MED/123',
        published: '2020-01-01', study_types: ['Systematic Review'], access_type: 'abstract_only', section: 'Abstract',
        text: passageText, context: passageText, start: 0, end: passageText.length }],
      provenance: { retrieval_mode: 'hybrid', papers_found: 15, cache_hits: 0, query: 'vitamin C cold', provider: 'Europe PMC', searched_at: new Date().toISOString() },
    } },
  },
};

const detection = {
  provider: 'GPTZero', status: 'scored', scanned_at: new Date().toISOString(),
  detector_version: '2026-09-13-base', prepared_transcript: false,
  fillers_removed: 17, filler_ratio: 0.148, removed_examples: ['basically', 'like', 'um'],
  verbatim: { basis: 'verbatim', characters: 718, predicted_class: 'human', ai_probability: 0.12,
    confidence_category: 'high', summary: 'Detector message.', top_sentences: [] },
  cleaned: { basis: 'filler_removed', characters: 605, predicted_class: 'ai', ai_probability: 0.94,
    confidence_category: 'high', summary: 'Detector message.',
    top_sentences: [{ text: 'However, emerging research suggests otherwise.', generated_prob: 0.97 }] },
  note: null,
};

test.beforeEach(async ({ page }) => {
  await page.route('**/api/config', route => route.fulfill({ json: { model_mode: 'mock' } }));
});

test('landing page, responsive layout, and backend error', async ({ page }, testInfo) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/cases', route => route.fulfill({ status: 429, json: { detail: 'The demo queue is full.' } }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Your feed moves fast/ })).toBeVisible();
  await expect(page.getByText('Infrastructure preview · mock AI adapters')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: `../artifacts/landing-${testInfo.project.name}.png`, fullPage: true });
  await page.getByLabel('Start with an Instagram Reel').fill('https://www.instagram.com/reel/test123/');
  await page.getByRole('button', { name: 'Check the evidence' }).click();
  await expect(page.getByRole('alert')).toHaveText('The demo queue is full.');
  expect(errors).toEqual([]);
});

test('submit a Reel, inspect evidence, and follow the original source', async ({ page }, testInfo) => {
  await page.route('**/api/cases', route => route.fulfill({ status: 202, json: complete }));
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: complete }));
  await page.goto('/');
  await page.getByLabel('Start with an Instagram Reel').fill(complete.source_url);
  await page.getByRole('button', { name: 'Check the evidence' }).click();
  await expect(page.getByRole('heading', { name: 'Analysis complete' })).toBeVisible();
  await expect(page.getByText('Contradicted by retrieved evidence')).toBeVisible();
  await page.getByText('Vitamin C prevention review', { exact: false }).click();
  await expect(page.locator('mark')).toHaveText(passageText);
  await expect(page.getByRole('link', { name: 'Read the original paper' })).toHaveAttribute('href', 'https://europepmc.org/article/MED/123');
  await expect(page.getByRole('link', { name: 'Download offline replay' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: `../artifacts/evidence-${testInfo.project.name}.png`, fullPage: true });
});

test('download failure offers upload and resumes the same case', async ({ page }) => {
  let uploaded = false;
  const waiting = { ...complete, status: 'awaiting_upload', sequence: 2, finished_at: null,
    error: { code: 'download_blocked', message: 'Instagram download unavailable. Upload the clip to continue.' },
    result: { schema_version: 1, model_mode: 'mock' } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: waiting }));
  await page.route(`**/api/cases/${id}/events?after=2`, route => route.fulfill({ contentType: 'text/event-stream', body: ': heartbeat\n\n' }));
  await page.route(`**/api/cases/${id}/media`, route => { uploaded = true; return route.fulfill({ status: 202, json: complete }); });
  await page.goto(`/?case=${id}`);
  await expect(page.getByRole('heading', { name: 'Video upload needed' })).toBeVisible();
  await page.getByLabel('Upload video').setInputFiles({ name: 'clip.mp4', mimeType: 'video/mp4', buffer: Buffer.from('browser fixture') });
  await expect(page.getByRole('heading', { name: 'Analysis complete' })).toBeVisible();
  expect(uploaded).toBeTruthy();
});

test('authorship panel shows both readings of the script', async ({ page }, testInfo) => {
  const scanned = { ...complete, result: { ...complete.result, detection } };
  await page.route('**/api/cases', route => route.fulfill({ status: 202, json: scanned }));
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: scanned }));
  await page.goto('/');
  await page.getByLabel('Start with an Instagram Reel').fill(complete.source_url);
  await page.getByRole('button', { name: 'Check the evidence' }).click();
  await expect(page.getByRole('heading', { name: 'The delivery and the script disagree' })).toBeVisible();
  await expect(page.getByText('Written by a person')).toBeVisible();
  await expect(page.getByText('Written by a machine')).toBeVisible();
  await expect(page.getByText('17 filler words removed (15% of the speech).')).toBeVisible();
  await expect(page.getByText('This measures authorship, not whether the claims are true.')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: `../artifacts/authorship-${testInfo.project.name}.png`, fullPage: true });
});

test('observatory renders recorded measurements', async ({ page }) => {
  await page.route('**/api/metrics', route => route.fulfill({ json: { total_cases: 5, finished: 4, complete: 3, failed: 1, queued: 1,
    p50_seconds: 42, p95_seconds: 80, stages: { research: 25, transcription: 10 } } }));
  await page.goto('/'); await page.getByRole('button', { name: 'Observatory' }).click();
  await expect(page.getByRole('heading', { name: 'Know where the seconds go.' })).toBeVisible();
  await expect(page.getByText('42s', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Average time by stage' })).toBeVisible();
});
