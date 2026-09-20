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

const adlib = 'For me personally I get very strong heart palpitations when I take it.';
const detection = {
  provider: 'GPTZero', status: 'scored', scanned_at: new Date().toISOString(),
  detector_version: '2026-09-13-base', prepared_transcript: false, script_threshold: 0.5,
  fillers_removed: 9, filler_ratio: 0.08, removed_examples: ['basically', 'like', 'um'],
  verbatim: {
    basis: 'verbatim', characters: 880, predicted_class: 'mixed', document_classification: 'MIXED',
    ai_probability: 0.76, human_probability: 0, mixed_probability: 0.24,
    confidence_category: 'medium', summary: 'Detector message.', flagged_share: 0.6,
    sentences: [
      { text: 'Caffeine is the most widely consumed psychoactive substance in the world.', generated_prob: 0.9998 },
      { text: adlib, generated_prob: 0.1795 },
      { text: 'The practical implication is about timing rather than quantity.', generated_prob: 0.9938 },
    ],
    paragraphs: [{ index: 0, sentences: 3, generated_prob: 0.76 }],
  },
  cleaned: null, note: null,
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
  await page.getByLabel('Start with an Instagram Reel or YouTube Short').fill('https://www.instagram.com/reel/test123/');
  await page.getByRole('button', { name: 'Check the evidence' }).click();
  await expect(page.getByRole('alert')).toHaveText('The demo queue is full.');
  expect(errors).toEqual([]);
});

test('submit a Reel, inspect evidence, and follow the original source', async ({ page }, testInfo) => {
  await page.route('**/api/cases', route => route.fulfill({ status: 202, json: complete }));
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: complete }));
  await page.goto('/');
  await page.getByLabel('Start with an Instagram Reel or YouTube Short').fill(complete.source_url);
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

test('authorship panel separates scripted sentences from the creator own words', async ({ page }, testInfo) => {
  const scanned = { ...complete, result: { ...complete.result, detection } };
  await page.route('**/api/cases', route => route.fulfill({ status: 202, json: scanned }));
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: scanned }));
  await page.goto('/');
  await page.getByLabel('Start with an Instagram Reel').fill(complete.source_url);
  await page.getByRole('button', { name: 'Check the evidence' }).click();
  await expect(page.getByRole('heading', { name: 'Partly read from a script' })).toBeVisible();
  await expect(page.getByText('of 3 sentences read as written')).toBeVisible();
  // The one ad-libbed sentence must not be shaded as machine-written.
  const spoken = page.locator('.sentence-map li', { hasText: adlib });
  await expect(spoken).toHaveClass(/spontaneous/);
  await expect(page.locator('.sentence-map li.scripted')).toHaveCount(2);
  await expect(page.getByText('This measures how the words were produced', { exact: false })).toBeVisible();
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

test('health summaries have working citations and disclose supplemental outages', async ({ page }) => {
  const result = structuredClone(complete);
  const item = result.result.claims.c1;
  Object.assign(item.evidence[0], { title: 'Common Cold', source_url: 'https://medlineplus.gov/commoncold.html',
    access_type: 'summary', provider: 'medlineplus', study_types: ['Curated health topic'] });
  Object.assign(item.provenance, { sources_found: 16,
    provider_failures: [{ provider: 'MedlinePlus', error: 'TimeoutError' }] });
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByText('Health summary', { exact: true })).toBeVisible();
  await expect(page.getByText('16 sources discovered')).toBeVisible();
  await expect(page.getByText(/MedlinePlus unavailable/)).toBeVisible();
  await page.locator('summary').filter({ hasText: 'Common Cold' }).click();
  await expect(page.getByRole('link', { name: 'Read the health topic' })).toHaveAttribute('href', 'https://medlineplus.gov/commoncold.html');
});

test('required provider outage shows incomplete research and preserves source links', async ({ page }) => {
  const result = { ...complete, status: 'incomplete', result: { ...complete.result, claims: { c1: {
    claim, status: 'incomplete', error: 'Medical research could not complete. No verdict was assigned.',
    provenance: { provider: 'MedlinePlus', sources_found: 1,
      provider_failures: [{ provider: 'Europe PMC', error: 'ReadTimeout' }] },
    discovered_sources: [{ title: 'Common Cold health topic', source_url: 'https://medlineplus.gov/commoncold.html', access_type: 'summary' }],
  } } } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByText(/Europe PMC unavailable/)).toBeVisible();
  await expect(page.getByText('Retrieval not completed')).toBeVisible();
  await expect(page.getByText('Keyword only · degraded retrieval')).toHaveCount(0);
  await page.getByText('Sources discovered before the interruption').click();
  await expect(page.getByRole('link', { name: 'Common Cold health topic' })).toHaveAttribute('href', 'https://medlineplus.gov/commoncold.html');
});

test('submit a YouTube Short and preserve its original link', async ({ page }) => {
  const source_url = 'https://www.youtube.com/shorts/BGQWPY4IigY';
  const result = { ...complete, source_url };
  await page.route('**/api/cases', async route => {
    expect(route.request().postDataJSON()).toEqual({ source_url });
    await route.fulfill({ status: 202, json: result });
  });
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.goto('/');
  await page.getByLabel('Start with an Instagram Reel or YouTube Short').fill(source_url);
  await page.getByRole('button', { name: 'Check the evidence' }).click();
  await expect(page.getByRole('link', { name: 'Original video' })).toHaveAttribute('href', source_url);
});

test('completed generated video has playback, captions and download', async ({ page }) => {
  const result = { ...complete, result: { ...complete.result, video: { status: 'ready', duration_seconds: 45 } } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.route(`**/api/cases/${id}/video**`, route => route.fulfill({ status: 200, body: '' }));
  await page.goto(`/?case=${id}`);
  const section = page.getByRole('region', { name: 'Generated fact-check video' });
  await expect(section).toBeVisible();
  await expect(section.locator('video')).toHaveAttribute('controls', '');
  await expect(section.locator('track')).toHaveAttribute('src', `/api/cases/${id}/video/captions`);
  await expect(section.getByRole('link', { name: 'Download MP4' })).toHaveAttribute('href', `/api/cases/${id}/video?download=true`);
  await expect(section).toContainText('AI-generated narration');
});


test('video progress and render-only retry preserve evidence', async ({ page }) => {
  const failed = { ...complete, status: 'incomplete', result: { ...complete.result,
    video: { status: 'failed', stage: 'voice', error: 'OpenAI rejected narration. Check credits, then retry.' } } };
  const rendering = { ...failed, status: 'rendering', sequence: 99, finished_at: null,
    result: { ...failed.result, video: { status: 'rendering', stage: 'voice' } } };
  let current = failed;
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: current }));
  await page.route(`**/api/cases/${id}/retry`, route => { current = rendering as typeof failed; return route.fulfill({ status: 202, json: rendering }); });
  await page.route(`**/api/cases/${id}/events**`, route => route.fulfill({contentType:'text/event-stream',body:': heartbeat\n\n'}));
  await page.goto(`/?case=${id}`);
  await expect(page.getByText(/OpenAI rejected narration/)).toBeVisible();
  await page.getByRole('button', { name: 'Retry video generation' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Creating video:' })).toContainText('Creating video: voice');
  await expect(page.locator('.claim-card').first()).toBeVisible();
});
