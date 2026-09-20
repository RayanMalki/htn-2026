import { test, expect } from '@playwright/test';

test('native sharing receives the saved case URL', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'share', { value: async (data: ShareData) => {
      document.body.dataset.sharedUrl = data.url;
    } });
  });
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: complete }));
  await page.goto(`/?case=${id}`);
  await page.getByRole('button', { name: 'Share results' }).click();
  await expect(page.locator('body')).toHaveAttribute('data-shared-url', `http://127.0.0.1:5173/?case=${id}`);
});

test('clipboard sharing copies the saved case URL', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'share', { value: undefined });
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (text: string) => {
      document.body.dataset.copiedUrl = text;
    } } });
  });
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: complete }));
  await page.goto(`/?case=${id}`);
  await page.getByRole('button', { name: 'Share results' }).click();
  await expect(page.locator('body')).toHaveAttribute('data-copied-url', `http://127.0.0.1:5173/?case=${id}`);
  await expect(page.getByText('Result link copied.')).toBeVisible();
});

const id = '11111111-1111-4111-8111-111111111111';
test('phone input focus stays on the container and sources remain accessible', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto('/');
  const input = page.getByLabel('Start with an Instagram Reel or YouTube Short');
  await input.focus();
  expect(await input.evaluate(el => getComputedStyle(el).outlineStyle)).toBe('none');
  expect(await page.locator('.input-row').evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid');
  const box = await input.boundingBox();
  const submit = await page.getByRole('button', { name: 'Check the evidence' }).boundingBox();
  expect(box!.y + box!.height).toBeLessThanOrEqual(submit!.y);
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: complete }));
  await page.goto(`/?case=${id}`);
  await page.getByRole('button', { name: 'Our sources & how we chose them' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Europe PMC');
  await expect(dialog).toContainText('MedlinePlus');
  await expect(dialog.getByRole('link', { name: /Vitamin C prevention review/ })).toHaveAttribute('href', 'https://europepmc.org/article/MED/123');
  await page.keyboard.press('Escape');
  await expect(page.locator('.evidence-segments')).toHaveCount(0);
  await expect(page.locator('.overview-counts .contradicts')).toHaveClass(/has-findings/);
  const share = await page.getByRole('button', { name: 'Share results' }).boundingBox();
  const save = await page.getByRole('link', { name: 'Save offline' }).boundingBox();
  expect(Math.abs(share!.y - save!.y)).toBeLessThan(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
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
test('saved applicability appears inside existing evidence cards without inventing missing details', async ({ page }) => {
  const data = structuredClone(complete);
  Object.assign(data.result.claims.c1.claim, { details: { intervention: 'vitamin C', dose: null } });
  Object.assign(data.result.claims.c1.verdict, { paper_assessments: [{ paper_id: 'MED:123',
    applicability: 'partial', finding: 'mixed', explanation: 'Only some participants match this claim.',
    quote_ids: ['q1'], citations: [{ passage_id: 'p1', quote: passageText }],
    access_types: ['abstract_only'], limitations: ['Dose was not reported.'], possible_overlap_with: [] }] });
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: data }));
  await page.goto(`/?case=${id}`);
  await page.locator('.claim-card .evidence-drawer > summary').click();
  await page.locator('.paper > summary').click();
  await expect(page.locator('.paper-body')).toContainText('Some details match');
  await expect(page.locator('.paper-body')).toContainText('Mixed findings');
  await expect(page.locator('.paper-body')).toContainText('Dose was not reported.');
  await page.getByText('Read full assessment', { exact: true }).click();
  await expect(page.locator('.full-assessment')).toContainText('What was used');
  await expect(page.locator('.full-assessment dt')).toHaveCount(1);
});

test('interactive controls fit the viewport and primary actions respond', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Check the evidence' })).toBeVisible();
  const controls = await page.locator('button:visible, a.button:visible, summary:visible').evaluateAll(elements => elements.map(element => {
    const box = element.getBoundingClientRect();
    return { label: (element.textContent || '').trim().slice(0, 40), width: box.width, height: box.height,
      right: box.right, viewport: window.innerWidth };
  }));
  expect(controls.every(control => control.width > 0 && control.height >= 40 && control.right <= control.viewport + 1)).toBeTruthy();
  await page.getByRole('button', { name: 'Meet MedBot' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'How it works' }).click();
  await expect(page.getByRole('dialog')).toContainText('Paste a short video');
  await page.keyboard.press('Escape');
});
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
  await expect(page.getByRole('heading', { name: /Seen online/ })).toBeVisible();
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
  await page.getByText('See the evidence', { exact: false }).click();
  await page.getByText('Vitamin C prevention review', { exact: false }).click();
  await expect(page.locator('mark')).toHaveText(passageText);
  await expect(page.getByRole('link', { name: 'Read the original paper' })).toHaveAttribute('href', 'https://europepmc.org/article/MED/123');
  await expect(page.getByRole('link', { name: 'Save offline' })).toBeVisible();
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

test('authorship is a separate uncertain signal, never a truth verdict', async ({ page }, testInfo) => {
  const scanned = { ...complete, result: { ...complete.result, detection } };
  await page.route('**/api/cases', route => route.fulfill({ status: 202, json: scanned }));
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: scanned }));
  await page.goto('/');
  await page.getByLabel('Start with an Instagram Reel').fill(complete.source_url);
  await page.getByRole('button', { name: 'Check the evidence' }).click();
  await expect(page.getByRole('heading', { name: 'Possible mix of human and AI text' })).toBeVisible();
  await expect(page.getByText('of 3 sentences flagged by the AI-text detector', { exact: false })).toBeVisible();
  await page.getByText('See the sentence-level signals').click();
  // Threshold categories describe detector output, not verified authorship.
  const spoken = page.locator('.sentence-map li', { hasText: adlib });
  await expect(spoken).toHaveClass(/spontaneous/);
  await expect(page.locator('.sentence-map li.scripted')).toHaveCount(2);
  await expect(page.getByText('It does not change the medical finding.', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: `../artifacts/authorship-${testInfo.project.name}.png`, fullPage: true });
});

test('GPTZero probabilities use API values and missing values never become zero', async ({ page }) => {
  const scored = { ...complete, result: { ...complete.result, detection } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: scored }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByLabel('GPTZero document probabilities')).toBeVisible();
  await expect(page.getByRole('meter', { name: 'GPTZero classification confidence' })).toHaveAttribute('value', '2');
  await expect(page.getByLabel('GPTZero document probabilities')).toContainText(`${(detection.verbatim.ai_probability * 100).toFixed(1)}%`);
  await page.getByText('How to read this signal').click();
  await expect(page.getByText('GPTZero hallucination detection is not enabled.', { exact: false })).toBeVisible();
  await page.unroute(`**/api/cases/${id}`);
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: { ...scored, result: { ...scored.result, detection: { ...detection, verbatim: { ...detection.verbatim, ai_probability: null } } } } }));
  await page.reload();
  await expect(page.getByLabel('GPTZero document probabilities')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Possible mix of human and AI text' })).toBeVisible();
});

test('compact claims retain the complete saved explanation on demand', async ({ page }) => {
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: complete }));
  await page.goto(`/?case=${id}`);
  const full = page.locator('.full-assessment');
  await expect(full.locator('p')).not.toBeVisible();
  await full.locator('summary').click();
  await expect(full.locator('p')).toHaveText(complete.result.claims.c1.verdict.explanation);
  await expect(page.getByRole('region', { name: 'Evidence overview' })).toContainText('not a score for how true');
});

test('long claim previews expand without losing the original qualifiers', async ({ page }) => {
  const text = 'This is a deliberately long claim about an intervention that was studied in a limited population under controlled conditions, and the result may not apply to everyone outside that population.';
  const longClaim = { ...claim, text };
  const result = { ...complete, result: { ...complete.result, analysis: { ...complete.result.analysis, claims: [longClaim] }, claims: { c1: { ...complete.result.claims.c1, claim: longClaim } } } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.goto(`/?case=${id}`);
  await expect(page.locator('.claim-quote')).toHaveClass(/claim-preview/);
  await page.getByRole('button', { name: 'Read full claim', exact: true }).click();
  await expect(page.locator('.claim-quote')).not.toHaveClass(/claim-preview/);
  await expect(page.locator('.claim-quote')).toHaveText(`“${text}”`);
});

test('homepage focuses on checking links without an observatory', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Observatory' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Check the evidence' })).toBeVisible();
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
  await page.getByText('See the evidence', { exact: false }).click();
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
  await page.getByRole('button', { name: 'About this clip' }).click();
  await expect(page.getByRole('link', { name: 'Original video' })).toHaveAttribute('href', source_url);
});

test('compact video opens accessible theater playback without download buttons', async ({ page }) => {
  const result = { ...complete, result: { ...complete.result, video: { status: 'ready', duration_seconds: 45 } } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.route(`**/api/cases/${id}/video**`, route => route.fulfill({ status: 200, body: '' }));
  await page.goto(`/?case=${id}`);
  const section = page.getByRole('region', { name: 'Generated fact-check video' });
  await expect(section).toBeVisible();
  await expect(section.locator('.mini-screen video')).toHaveCount(1);
  await expect(section.locator('video')).not.toHaveAttribute('controls', '');
  await expect(page.getByRole('link', { name: 'Download MP4' })).toHaveCount(0);
  const watch = section.getByRole('button', { name: 'Watch explanation' });
  await watch.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('video')).toHaveAttribute('controls', '');
  await expect(dialog.locator('track')).toHaveAttribute('src', `/api/cases/${id}/video/captions`);
  await expect(dialog).toContainText('AI-generated narration');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(watch).toBeFocused();
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
  await expect(page.getByRole('status').filter({ hasText: 'Creating video:' })).toContainText('Recording narration');
  await expect(page.locator('.claim-card').first()).toBeVisible();
});

test('a shared link in the address starts the check without a tap', async ({ page }) => {
  // The iPhone share-sheet shortcut opens the site as /?url=<short>. Nothing to fill, nothing to click.
  const shared = 'https://www.youtube.com/shorts/BaW_jenozKc';
  let posted = '';
  let submissions = 0;
  await page.route('**/api/cases', async route => {
    submissions += 1;
    posted = (route.request().postDataJSON() as { source_url: string }).source_url;
    await route.fulfill({ status: 202, json: complete });
  });
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: complete }));
  await page.goto(`/?url=${encodeURIComponent(shared)}`);
  await expect.poll(() => posted).toBe(shared);
  await expect(page).toHaveURL(new RegExp(`\\?case=${id}$`));
  await expect(page.getByLabel('Start with an Instagram Reel or YouTube Short')).toHaveValue(shared);
  expect(submissions).toBe(1);
});

test('MedBot dialogs close with Escape and restore focus', async ({ page }) => {
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'How it works' });
  await trigger.click();
  await expect(page.getByRole('dialog')).toContainText('up to 100 seconds');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test('three claim cards navigate and preserve distinct findings', async ({ page }) => {
  const second = { ...claim, id: 'c2', text: 'Another claim with insufficient evidence.' };
  const third = { ...claim, id: 'c3', text: 'A third claim with a research outage.' };
  const result = { ...complete, result: { ...complete.result,
    analysis: { ...complete.result.analysis, claims: [claim, second, third] },
    claims: { ...complete.result.claims,
      c2: { claim: second, status: 'complete', verdict: { label: 'uncertain', explanation: 'Not enough relevant evidence in this fixture.', citations: [], limitations: [] } },
      c3: { claim: third, status: 'incomplete', error: 'Research was interrupted.' },
    } } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByRole('button', { name: 'Previous claim' })).toBeDisabled();
  await page.getByRole('button', { name: 'Next claim' }).click();
  await expect(page.getByText('Claim 2 of 3', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Next claim' }).click();
  await expect(page.getByText('Claim 3 of 3', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Next claim' })).toBeDisabled();
  await expect(page.getByText('Research was interrupted.')).toBeVisible();
  await page.getByRole('button', { name: 'Previous claim' }).click();
  await page.locator('.claim-card').nth(1).locator('.verdict').click();
  await expect(page.locator('.claim-card').nth(1)).toContainText('not a verdict on every statement');
  await expect(page.locator('.overview-counts .contradicts b')).toHaveText('1');
  await expect(page.locator('.overview-counts .uncertain b')).toHaveText('1');
  await expect(page.locator('.overview-counts .pending b')).toHaveText('1');
});

test('live video completion nudges without stealing focus or hiding evidence', async ({ page }) => {
  const pending = { ...complete, status: 'rendering', sequence: 9, result: { ...complete.result, video: { status: 'rendering', stage: 'cards' } } };
  const ready = { ...complete, sequence: 10, result: { ...complete.result, video: { status: 'ready', duration_seconds: 45 } } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: pending }));
  await page.route(`**/api/cases/${id}/events**`, async route => {
    await route.fulfill({ contentType: 'text/event-stream', body: `event: case\ndata: ${JSON.stringify(ready)}\n\nevent: end\ndata: {}\n\n` });
  });
  await page.route(`**/api/cases/${id}/video**`, route => route.fulfill({ status: 410, body: '' }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByText('Your explanation is ready. Watch')).toBeVisible();
  await expect(page.locator('.claim-card')).toBeVisible();
  await page.getByRole('button', { name: 'Dismiss video notification' }).click();
  await expect(page.locator('.ready-nudge')).toHaveCount(0);
  await page.getByRole('button', { name: 'Watch explanation' }).click();
  await expect(page.getByText('It may have expired after 24 hours.', { exact: false })).toBeVisible();
});

test('sharing has a selectable URL fallback and no fabricated link', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'share', { value: undefined });
    Object.defineProperty(navigator, 'clipboard', { value: undefined });
  });
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: complete }));
  await page.goto(`/?case=${id}`);
  await page.getByRole('button', { name: 'Share results' }).click();
  await expect(page.getByLabel('Result link')).toHaveValue(`http://127.0.0.1:5173/?case=${id}`);
});

test('mock findings never offer a medical video generation button', async ({ page }) => {
  const result = { ...complete, result: { ...complete.result, model_mode: 'mock' } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByText('Prepared judgment')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry analysis and create video' })).toHaveCount(0);
  await expect(page.getByText('This is not an analysis of the submitted video.', { exact: false })).toBeVisible();
});

test('320px layout and reduced motion remain usable', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  expect(await page.locator('.hero').evaluate(el => getComputedStyle(el).animationName)).toBe('none');
  expect(await page.getByLabel('Start with an Instagram Reel').evaluate(el => getComputedStyle(el).fontSize)).toBe('16px');
});

test('older and unrelated SSE snapshots cannot replace newer findings', async ({ page }) => {
  const active = { ...complete, status: 'researching', sequence: 5 };
  const newer = { ...complete, status: 'judging', sequence: 10, result: { ...complete.result, outcome: 'Newest saved snapshot.' } };
  const unrelated = { ...complete, id: '22222222-2222-4222-8222-222222222222', sequence: 100 };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: active }));
  await page.route(`**/api/cases/${id}/events**`, route => route.fulfill({ contentType: 'text/event-stream',
    body: [newer, complete, unrelated].map(c => `event: case\ndata: ${JSON.stringify(c)}\n\n`).join('') + 'event: end\ndata: {}\n\n' }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByText('Newest saved snapshot.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Checking the evidence' })).toBeVisible();
});

test('no claims and unavailable GPTZero are explicit non-verdict states', async ({ page }) => {
  const result = { ...complete, status: 'no_claims', result: { schema_version: 1, model_mode: 'live',
    outcome: 'No usable spoken medical claims were found.', detection: { ...detection, status: 'unavailable', verbatim: null, note: 'Detector unavailable for this clip.' } } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByRole('heading', { name: 'No spoken medical claims' })).toBeVisible();
  await expect(page.locator('.claim-card')).toHaveCount(0);
  await page.getByText('Authorship check unavailable').click();
  await expect(page.getByText('Detector unavailable for this clip.')).toBeVisible();
});

test('compact homepage omits placeholder topics and explains the real workflow', async ({ page }) => {
  let requests = 0;
  await page.route('**/api/cases', route => { requests++; return route.fulfill({ json: complete }); });
  await page.goto('/');
  await expect(page.getByRole('region', { name: 'Example topics' })).toHaveCount(0);
  const topic = page.getByRole('button', { name: /Meet MedBot/ });
  await topic.click();
  await expect(page.getByRole('dialog')).toContainText('Elasticsearch');
  await page.keyboard.press('Escape');
  await expect(topic).toBeFocused();
  expect(requests).toBe(0);
});

test('GPTZero remains visible without a key and never changes the finding', async ({ page }) => {
  const result = { ...complete, result: { ...complete.result, detection: { ...detection, status: 'skipped', verbatim: null, note: 'GPTZERO_API_KEY is not configured.' } } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByRole('region', { name: 'Script authorship' })).toContainText('GPTZero');
  await page.getByText('Authorship check unavailable').click();
  await expect(page.getByText('This check has not been enabled yet.', { exact: false })).toBeVisible();
  await expect(page.locator('.verdict.contradicts')).toContainText('Contradicted');
  await page.getByRole('link', { name: 'Share ↗', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Share results' })).toBeInViewport();
});

test('detailed phone layout keeps rendering independent from evidence and GPTZero', async ({ page }, testInfo) => {
  const result = { ...complete, status: 'rendering', result: { ...complete.result, video: { status: 'rendering', stage: 'voice' } } };
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: result }));
  await page.route(`**/api/cases/${id}/events**`, route => route.fulfill({ contentType: 'text/event-stream', body: ': heartbeat\n\n' }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByText('Waiting for the authorship result')).toBeVisible();
  const pause = page.getByRole('button', { name: 'Pause scanner animation' });
  await pause.click();
  await expect(page.locator('.video-pending .scanner')).not.toHaveClass(/active/);
  await expect(page.getByRole('status').filter({hasText:'Creating video:'})).toContainText('Recording narration');
  await expect(page.locator('.verdict.contradicts')).toBeVisible();
  await page.getByRole('link', { name: 'Explore your findings' }).click();
  await expect(page.locator('#claim-c1')).toBeInViewport();
  await page.getByText('See the evidence', { exact: false }).click();
  await expect(page.getByText('Vitamin C prevention review', { exact: false })).toBeVisible();
  await page.getByText('See the evidence', { exact: false }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({path:`../artifacts/medbot-detailed-${testInfo.project.name}.png`, fullPage:true});
});

test('the investigation shows counted findings, a scored paper and working links', async ({ page }) => {
  await page.goto('/');
  const section = page.getByRole('region', { name: /We scanned the research/ });
  await expect(section).toBeVisible();
  await expect(section.getByText('papers scanned')).toBeVisible();
  expect(await section.locator('.year-bars li').count()).toBeGreaterThanOrEqual(3);
  await expect(section.locator('.findings-map').first().locator('li.scripted').first()).toBeVisible();
  await section.getByRole('button', { name: /control/ }).click();
  await expect(section.getByText(/This is the control/)).toBeVisible();
  await expect(section.getByRole('link', { name: 'Open the paper ↗' })).toHaveAttribute('href', /europepmc\.org/);
  await expect(section.getByRole('link', { name: 'Watch on YouTube ↗' })).toHaveAttribute('href', /youtu/);
  await expect(section.getByText('A signal, not a verdict.')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('the investigation stays off a saved result', async ({ page }) => {
  await page.route(`**/api/cases/${id}`, route => route.fulfill({ json: complete }));
  await page.goto(`/?case=${id}`);
  await expect(page.getByRole('heading', { name: /Your check|Analysis complete|Seen online/ }).first()).toBeVisible();
  await expect(page.getByRole('region', { name: /We scanned the research/ })).toHaveCount(0);
});
