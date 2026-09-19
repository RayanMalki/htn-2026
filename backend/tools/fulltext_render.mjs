// Legal full-text renderer for HypeCheck.
//
// Unpaywall hands us a URL for a LEGALLY FREE copy of a paper (open access at the
// publisher, or an author manuscript in a repository). A plain fetch of that URL
// often returns an empty JavaScript shell, so the text never arrives. This renders
// the page in a real browser, waits for the article body, and returns clean text.
//
// It only ever visits the free URL Unpaywall already resolved. No login, no cookie,
// no paywall bypass. If a page is not actually free it is skipped, not forced.
//
// Usage:
//   node fulltext_render.mjs <doi-or-url> [--email you@example.com]
// If given a DOI it asks Unpaywall for the free copy first, then renders it.

import { chromium } from 'playwright'

const args = process.argv.slice(2)
const target = args.find((a) => !a.startsWith('--'))
const emailIdx = args.indexOf('--email')
const email = emailIdx >= 0 ? args[emailIdx + 1] : 'ezekieljoseph2005@gmail.com'

if (!target) {
  console.error('give a DOI (10.xxxx/yyyy) or a full URL')
  process.exit(1)
}

// Ask Unpaywall for the best legally free location of a DOI.
async function freeCopyFromDoi(doi) {
  // Unpaywall wants the raw DOI in the path, slashes and all. Do not percent-encode it.
  const clean = doi.replace(/^https?:\/\/doi\.org\//i, '').trim()
  const r = await fetch(`https://api.unpaywall.org/v2/${clean}?email=${encodeURIComponent(email)}`)
  if (!r.ok) return { url: null, note: `unpaywall ${r.status}` }
  const j = await r.json()
  if (!j.is_oa) return { url: null, note: 'no free copy exists (paywalled everywhere)' }
  const loc = j.best_oa_location || {}
  return {
    url: loc.url_for_pdf || loc.url,
    host: loc.host_type,
    version: loc.version,
    isPdf: Boolean(loc.url_for_pdf),
    note: `free via ${loc.host_type}`,
  }
}

// Pull the readable article text out of a rendered page.
// Prefers the real article containers, falls back to the whole body.
function extractText() {
  const drop = ['nav', 'header', 'footer', 'script', 'style', 'aside', '.references', '#references']
  for (const sel of drop) document.querySelectorAll(sel).forEach((n) => n.remove())
  const containers = [
    'article', 'main', '.article-body', '.article__body', '#bodymatter',
    '.c-article-body', 'div.fulltext-view', '#abstract', '.hlFld-Fulltext',
  ]
  for (const sel of containers) {
    const el = document.querySelector(sel)
    if (el && el.innerText && el.innerText.length > 1500) return el.innerText
  }
  return document.body ? document.body.innerText : ''
}

async function main() {
  const isDoi = /^10\.\d{4,9}\//.test(target.replace(/^https?:\/\/doi\.org\//i, ''))
  let url = target
  let meta = { note: 'direct url' }
  if (isDoi) {
    meta = await freeCopyFromDoi(target)
    url = meta.url
    if (!url) {
      console.log(JSON.stringify({ ok: false, reason: meta.note }, null, 2))
      return
    }
  }

  // A rendered PDF cannot be read as DOM text, so hand those straight back as a link.
  if (meta.isPdf || /\.pdf($|\?)/i.test(url)) {
    console.log(JSON.stringify({ ok: true, kind: 'pdf', url, note: meta.note, hint: 'fetch and parse the PDF, do not render as HTML' }, null, 2))
    return
  }

  // --headed opens a real window instead of headless. Measured on the blue-light
  // studies: two free pages (Thapan 2001, West 2011) sit behind Cloudflare's
  // automatic check, which blocks headless and waves a normal headed browser
  // through on its own. No stealth flags, no challenge solving, just a browser
  // being a browser. If a page escalates to an interactive CAPTCHA, stop and let
  // a person click, do not add anything that fights it.
  const headed = args.includes('--headed')
  const t0 = Date.now()
  const browser = await chromium.launch({ headless: !headed, args: headed ? ['--mute-audio'] : [] })
  const page = await browser.newPage({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
  })
  let out = { ok: false, url, note: meta.note }
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 })
    // give the article body a moment to hydrate, then read it
    await page.waitForTimeout(2500)
    const text = await page.evaluate(extractText)
    const title = await page.title()
    out = {
      ok: text.length > 1500,
      url,
      title: title.slice(0, 120),
      note: meta.note,
      chars: text.length,
      seconds: Number(((Date.now() - t0) / 1000).toFixed(2)),
      // a short excerpt so a human can sanity-check it is the real paper, not a stub
      excerpt: text.replace(/\s+/g, ' ').slice(0, 400),
    }
  } catch (e) {
    out = { ok: false, url, note: meta.note, error: String(e.message).slice(0, 100) }
  } finally {
    await browser.close()
  }
  console.log(JSON.stringify(out, null, 2))
}

main()
