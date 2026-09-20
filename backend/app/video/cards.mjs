// Renders the cards a rebuttal video is made of, from HTML to PNG, in a headless
// browser. Driven by cards.py, which writes a spec file and reads the JSON this
// script prints on the last line of stdout.
//
//   node cards.mjs <playwright package dir> <spec.json>
//
// The spec:
//   { "width": 720, "height": 1280, "out_dir": "...",
//     "cards":    [{ "id": "s2", "kind": "paper", ...Card fields from plan.py }],
//     "captions": [{ "id": "c0", "text": "on day seven", "emphasis": 2 }] }
//
// Paper cards are rendered at device scale 2 so the compositor's push-in has pixels
// to spare. Every other card is rendered at scale 1. The focus box reported for a
// paper card is in plan pixels, not PNG pixels, so the compositor divides by the
// PNG's own scale.
//
// Visual language, in one paragraph: the paper looks like a journal page, serif
// body, a small caps section heading, the evidence sentence physically marked inside
// its paragraph. Interface chrome is a clean sans. The only saturated colours on
// screen are the highlight and the finding. No monospace anywhere.

import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const [playwrightDir, specPath] = process.argv.slice(2)
if (!playwrightDir || !specPath) {
  console.error('usage: node cards.mjs <playwright package dir> <spec.json>')
  process.exit(2)
}

async function loadChromium(dir) {
  // The playwright package ships index.mjs. The @playwright/test package is
  // CommonJS and re-exports the same browsers, so either one works here.
  for (const entry of ['index.mjs', 'index.js']) {
    try {
      const mod = await import(pathToFileURL(join(dir, entry)).href)
      const chromium = mod.chromium ?? mod.default?.chromium
      if (chromium) return chromium
    } catch (error) {
      if (!String(error.message).includes('Cannot find module') && !String(error.code).includes('ERR_MODULE_NOT_FOUND')) throw error
    }
  }
  throw new Error(`no chromium export found under ${dir}`)
}

const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

// The paper page is kept off the right 15 percent and the bottom 25 percent of the
// frame, which is where TikTok's own buttons and caption sit once posted. Card
// content also stops at 58 percent, leaving the band from there to the platform zone
// for our own captions, so a caption never lands on a badge or a footer.
const SAFE_RIGHT = 0.15
const SAFE_BOTTOM = 0.25
const CONTENT_BOTTOM = 0.58
const CAPTION_CENTRE = 0.67

function baseCss(W, H) {
  return `
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=Inter:wght@400;500;600;700&display=swap">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { width: ${W}px; height: ${H}px; overflow: hidden; }
    body { font-family: Inter, "Helvetica Neue", Arial, sans-serif; color: #1b1a17; background: #f4efe6;
           -webkit-font-smoothing: antialiased; }
    .serif { font-family: "Source Serif 4", Georgia, "Times New Roman", serif; }
    .eyebrow { font-size: 15px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: #6d6558; }
    .pill { display: inline-block; padding: 8px 14px; border-radius: 999px; font-size: 15px; font-weight: 700;
            letter-spacing: .08em; text-transform: uppercase; }
    .badges { display: flex; flex-wrap: wrap; gap: 12px; }
    .badge { background: #ffffff; border: 1px solid #ddd5c6; border-radius: 12px; padding: 12px 16px; min-width: 150px; }
    .badge .k { font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: #8a8175; }
    .badge .v { font-size: 22px; font-weight: 600; margin-top: 4px; color: #1b1a17; }
    mark.hl { background: #ffd54a; color: #1b1a17; padding: 2px 0; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
  </style>`
}

function clipCard(c, W, H) {
  return `<div style="width:${W}px;height:${H}px;background:linear-gradient(160deg,#151a22,#2a2f3a 55%,#1a1e26);position:relative;color:#f2efe8">
    <div style="position:absolute;top:120px;left:40px;right:${Math.round(W * SAFE_RIGHT) + 20}px">
      <span class="pill" style="background:#f2efe8;color:#151a22"><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#e6433a;margin-right:8px"></span>Stitch incoming</span>
    </div>
    <div style="position:absolute;top:${Math.round(H * 0.36)}px;left:40px;right:${Math.round(W * SAFE_RIGHT) + 20}px">
      <div class="eyebrow" style="color:#b8b1a4">${esc(c.eyebrow || 'The claim')}</div>
      <div class="serif" style="font-size:44px;line-height:1.15;font-weight:600;margin-top:16px">${esc(c.title)}</div>
      ${c.footer ? `<div style="margin-top:20px;font-size:17px;color:#b8b1a4">${esc(c.footer)}</div>` : ''}
    </div>
  </div>`
}

function claimCard(c, W, H) {
  return `<div style="width:${W}px;height:${H}px;background:#1f2229;position:relative;display:flex;align-items:center;justify-content:center;padding:0 40px ${Math.round(H * SAFE_BOTTOM)}px 40px">
    <div style="background:#f4efe6;border-radius:22px;padding:36px 32px;width:100%;max-width:${W - 80}px">
      <div class="eyebrow" style="color:#b0502a">${esc(c.eyebrow || 'The claim')}</div>
      <div class="serif" style="font-size:40px;line-height:1.18;font-weight:600;margin-top:14px">${esc(c.title)}</div>
      ${c.footer ? `<div style="margin-top:18px;font-size:16px;color:#6d6558">${esc(c.footer)}</div>` : ''}
    </div>
  </div>`
}

function markHighlight(paragraph, highlight) {
  if (!highlight) return esc(paragraph)
  const idx = paragraph.indexOf(highlight)
  if (idx < 0) return esc(paragraph)
  return esc(paragraph.slice(0, idx)) + `<mark class="hl" id="focus">${esc(highlight)}</mark>` + esc(paragraph.slice(idx + highlight.length))
}

function paperCard(c, W, H) {
  const body = Array.isArray(c.body) ? c.body : []
  const hasHl = c.highlight && body.some((p) => p.includes(c.highlight))
  const paras = body.map((p) => `<p style="margin-top:14px">${markHighlight(p, c.highlight)}</p>`).join('')
  // If the sentence is not inside any paragraph, it gets its own, still marked, so the
  // camera always has something to push toward.
  const extra = c.highlight && !hasHl ? `<p style="margin-top:14px"><mark class="hl" id="focus">${esc(c.highlight)}</mark></p>` : ''
  // Badges are sized so three sit on one row inside the safe width, and the page is
  // clipped at the caption band so nothing on it can collide with a caption.
  const badges = (c.badges || []).map((b) => `<div class="badge" style="min-width:120px;padding:10px 14px"><div class="k" style="font-size:11px">${esc(b.label)}</div><div class="v" style="font-size:19px">${esc(b.value)}</div></div>`).join('')
  const rightPad = Math.round(W * SAFE_RIGHT) + 24
  const pageMax = Math.round(H * CONTENT_BOTTOM) - 44
  return `<div style="width:${W}px;height:${H}px;background:#e9e2d5;padding:44px ${rightPad}px 0 44px;position:relative">
    <div style="background:#fffdf8;border-radius:6px;padding:32px 32px 28px;box-shadow:0 1px 0 #d9d0c0;max-height:${pageMax}px;overflow:hidden">
      ${c.eyebrow ? `<div class="eyebrow" style="font-size:13px">${esc(c.eyebrow)}</div>` : ''}
      ${c.title ? `<div class="serif" style="font-size:22px;line-height:1.22;font-weight:600;margin-top:8px">${esc(c.title)}</div>` : ''}
      ${c.highlight_section ? `<div class="eyebrow" style="margin-top:18px;color:#8a8175;font-size:11px">${esc(c.highlight_section)}</div>` : ''}
      <div class="serif" style="font-size:18px;line-height:1.45;color:#2a2823">${paras}${extra}</div>
      ${badges ? `<div class="badges" style="margin-top:18px;gap:10px">${badges}</div>` : ''}
      ${c.footer ? `<div style="margin-top:14px;font-size:13px;color:#8a8175">${esc(c.footer)}</div>` : ''}
    </div>
  </div>`
}

function findingCard(c, W, H) {
  const counts = (c.badges || []).map((b) => `<div class="badge" style="min-width:120px"><div class="k">${esc(b.label)}</div><div class="v">${esc(b.value)}</div></div>`).join('')
  return `<div style="width:${W}px;height:${H}px;background:#f4efe6;padding:0 ${Math.round(W * SAFE_RIGHT) + 20}px ${Math.round(H * SAFE_BOTTOM)}px 44px;display:flex;flex-direction:column;justify-content:center">
    <div class="eyebrow" style="color:#0f6a72">${esc(c.eyebrow || 'What the research found')}</div>
    <div class="serif" style="font-size:42px;line-height:1.16;font-weight:600;margin-top:18px;color:#0f6a72">${esc(c.title)}</div>
    ${(c.body || []).map((p) => `<p class="serif" style="font-size:21px;line-height:1.45;margin-top:18px;color:#2a2823">${esc(p)}</p>`).join('')}
    ${counts ? `<div class="badges" style="margin-top:30px">${counts}</div>` : ''}
    ${c.footer ? `<div style="margin-top:22px;font-size:15px;color:#6d6558">${esc(c.footer)}</div>` : ''}
  </div>`
}

function closeCard(c, W, H) {
  return `<div style="width:${W}px;height:${H}px;background:#151a22;color:#f2efe8;display:flex;flex-direction:column;justify-content:center;padding:0 ${Math.round(W * SAFE_RIGHT) + 20}px ${Math.round(H * SAFE_BOTTOM)}px 44px">
    ${c.eyebrow ? `<div class="eyebrow" style="color:#b8b1a4">${esc(c.eyebrow)}</div>` : ''}
    <div class="serif" style="font-size:46px;line-height:1.14;font-weight:600;margin-top:16px">${esc(c.title)}</div>
    ${(c.body || []).map((p) => `<p style="font-size:20px;line-height:1.45;margin-top:16px;color:#d8d2c6">${esc(p)}</p>`).join('')}
    ${c.footer ? `<div style="margin-top:26px;font-size:16px;color:#b8b1a4">${esc(c.footer)}</div>` : ''}
  </div>`
}

function captionPage(p, W, H) {
  // The caption band: left 5 percent in, no wider than 80 percent, centred at 67
  // percent of the frame, which is below every card's content and above the bottom
  // 25 percent the platform draws over.
  const words = String(p.text || '').split(/\s+/).filter(Boolean)
  const emphasis = Number.isInteger(p.emphasis) ? p.emphasis : -1
  const inner = words.map((w, i) => `<span style="${i === emphasis ? 'color:#ffd54a' : ''}">${esc(w)}</span>`).join(' ')
  return `<div style="width:${W}px;height:${H}px;background:transparent;position:relative">
    <div style="position:absolute;left:${Math.round(W * 0.05)}px;top:${Math.round(H * CAPTION_CENTRE)}px;transform:translateY(-50%);max-width:${Math.round(W * 0.80)}px">
      <div style="display:inline-block;background:rgba(20,22,28,.88);color:#ffffff;font-weight:800;font-size:50px;line-height:1.15;padding:14px 22px;border-radius:18px;letter-spacing:.005em">${inner}</div>
    </div>
  </div>`
}

const RENDER = { clip: clipCard, claim: claimCard, paper: paperCard, finding: findingCard, close: closeCard }

async function main() {
  const spec = JSON.parse(readFileSync(specPath, 'utf8'))
  const { width: W, height: H, out_dir: outDir } = spec
  const chromium = await loadChromium(playwrightDir)
  const browser = await chromium.launch({ headless: true })
  const result = { cards: [], captions: [] }
  try {
    for (const card of spec.cards || []) {
      const scale = card.kind === 'paper' ? 2 : 1
      const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: scale })
      const page = await ctx.newPage()
      const html = `<!doctype html><html><head><meta charset="utf-8">${baseCss(W, H)}</head><body>${RENDER[card.kind](card, W, H)}</body></html>`
      await page.setContent(html, { waitUntil: 'load' })
      await Promise.race([page.evaluate(() => document.fonts.ready), page.waitForTimeout(2500)])
      const png = join(outDir, `card_${card.id}.png`)
      await page.screenshot({ path: png, omitBackground: false })
      let focus = null
      if (card.kind === 'paper') {
        focus = await page.evaluate(() => {
          const el = document.getElementById('focus')
          if (!el) return null
          const r = el.getBoundingClientRect()
          return { x: r.left, y: r.top, w: r.width, h: r.height }
        })
      }
      result.cards.push({ id: card.id, png, focus_box: focus, scale })
      await ctx.close()
    }
    if ((spec.captions || []).length) {
      const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 })
      const page = await ctx.newPage()
      for (const cap of spec.captions) {
        const html = `<!doctype html><html><head><meta charset="utf-8">${baseCss(W, H)}<style>body{background:transparent}</style></head><body>${captionPage(cap, W, H)}</body></html>`
        await page.setContent(html, { waitUntil: 'load' })
        await Promise.race([page.evaluate(() => document.fonts.ready), page.waitForTimeout(1500)])
        const png = join(outDir, `caption_${cap.id}.png`)
        await page.screenshot({ path: png, omitBackground: true })
        result.captions.push({ id: cap.id, png })
      }
      await ctx.close()
    }
  } finally {
    await browser.close()
  }
  writeFileSync(join(outDir, 'cards_result.json'), JSON.stringify(result))
  console.log(JSON.stringify(result))
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error))
  process.exit(1)
})
