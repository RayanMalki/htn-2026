// TikTok discovery scroller for HypeCheck. Logged out, one headed muted browser,
// human pacing. It visits a few public discovery pages, scrolls with jittered
// delays, and collects unique video links plus whatever metadata the page shows.
//
// It never logs in, never uses cookies, never fights a wall. When a route shows a
// login wall or a bot check it records that and moves on to the next route. Headed
// is used because today a headed browser passed automatic checks that blocked
// headless, with no stealth flags added.
//
// Usage:
//   node scroll_tiktok.mjs [--cap 30] [--out urls.jsonl] [--routes discover,tag,search,profile]
//
// Output: one JSON line per unique video in urls.jsonl, with the route that found it.

import { chromium } from 'playwright'
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const args = process.argv.slice(2)
const flag = (name, fallback) => {
  const i = args.indexOf(name)
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback
}
const CAP = Number(flag('--cap', '30'))
const OUT = flag('--out', join(HERE, 'urls.jsonl'))
const ROUTES = flag('--routes', 'discover,tag,search,profile').split(',')

// Health topics that carry a lot of confident advice. Each becomes a discover
// page, a hashtag page, and a search query.
const TOPICS = ['seed-oils', 'raw-milk', 'cortisol', 'blue-light']
const HASHTAGS = ['seedoils', 'rawmilk', 'cortisol', 'bluelight']
const SEARCHES = ['seed oils inflammation', 'raw milk benefits', 'cortisol belly', 'blue light sleep']
// Public science communicators whose stitches point at the videos worth checking.
const PROFILES = ['dr_idz']

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const jitter = (lo, hi) => lo + Math.random() * (hi - lo)

function loadSeen() {
  const seen = new Set()
  if (existsSync(OUT)) {
    for (const line of readFileSync(OUT, 'utf8').split('\n')) {
      if (!line.trim()) continue
      try { seen.add(JSON.parse(line).url) } catch {}
    }
  }
  return seen
}

// Reads the page for a wall before scrolling. TikTok's logged out walls are
// either a bot check page or a login prompt covering the feed.
async function wallCheck(page) {
  const title = (await page.title()).toLowerCase()
  const text = (await page.evaluate(() => document.body ? document.body.innerText.slice(0, 3000) : '')).toLowerCase()
  if (/just a moment|verify you are human|security verification|access denied/.test(title + ' ' + text)) return 'bot check'
  if (/log in to follow|log in to tiktok|sign up for tiktok/.test(text) && !/\/video\//.test(await page.content())) return 'login wall'
  return null
}

// Pull every video link on the page with the metadata sitting next to it.
async function harvest(page, route) {
  return page.evaluate((route) => {
    const out = []
    const anchors = Array.from(document.querySelectorAll('a[href*="/video/"]'))
    for (const a of anchors) {
      const m = a.href.match(/tiktok\.com\/(@[^/]+)\/video\/(\d+)/)
      if (!m) continue
      const card = a.closest('[data-e2e], div') || a
      const desc = card.querySelector('[data-e2e="search-card-desc"], [data-e2e="browse-video-desc"], [data-e2e*="desc"], img[alt]')
      const views = card.querySelector('[data-e2e="video-views"], [data-e2e*="views"], strong')
      out.push({
        url: `https://www.tiktok.com/${m[1]}/video/${m[2]}`,
        author: m[1],
        description: (desc ? (desc.innerText || desc.getAttribute('alt') || '') : '').trim().slice(0, 300),
        views: views ? (views.innerText || '').trim().slice(0, 20) : '',
        route,
      })
    }
    return out
  }, route)
}

async function scrollRoute(page, url, route, seen, budget, log) {
  let found = 0
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 })
  } catch (e) {
    log.push({ route, url, status: 'failed to load', error: String(e.message).slice(0, 80), found: 0 })
    return 0
  }
  await sleep(jitter(2500, 4000))
  const wall = await wallCheck(page)
  if (wall) {
    log.push({ route, url, status: wall, found: 0 })
    return 0
  }
  // Scroll in human sized steps with jittered pauses, harvesting as we go.
  for (let step = 0; step < 8 && found < budget; step++) {
    const items = await harvest(page, route)
    for (const it of items) {
      if (seen.has(it.url) || found >= budget) continue
      seen.add(it.url)
      appendFileSync(OUT, JSON.stringify(it) + '\n')
      found += 1
    }
    await page.evaluate(() => window.scrollBy(0, Math.round(window.innerHeight * (0.7 + Math.random() * 0.5))))
    await sleep(jitter(1500, 4000))
  }
  log.push({ route, url, status: found ? 'rendered' : 'rendered, no video links', found })
  return found
}

async function main() {
  const seen = loadSeen()
  const log = []
  let total = 0
  const browser = await chromium.launch({ headless: false, args: ['--mute-audio', '--window-size=900,1100'] })
  const ctx = await browser.newContext({ viewport: { width: 900, height: 1000 } })
  const page = await ctx.newPage()
  const plan = []
  if (ROUTES.includes('discover')) for (const t of TOPICS) plan.push(['discover', `https://www.tiktok.com/discover/${t}`])
  if (ROUTES.includes('tag')) for (const h of HASHTAGS) plan.push(['tag', `https://www.tiktok.com/tag/${h}`])
  if (ROUTES.includes('search')) for (const s of SEARCHES) plan.push(['search', `https://www.tiktok.com/search?q=${encodeURIComponent(s)}`])
  if (ROUTES.includes('profile')) for (const p of PROFILES) plan.push(['profile', `https://www.tiktok.com/@${p}`])

  for (const [route, url] of plan) {
    if (total >= CAP) break
    const budget = Math.min(CAP - total, Math.ceil(CAP / Math.max(1, plan.length)) + 2)
    const n = await scrollRoute(page, url, route, seen, budget, log)
    total += n
    console.log(`${route.padEnd(9)} ${log[log.length - 1].status.padEnd(26)} +${n}  ${url}`)
    await sleep(jitter(2000, 4000))
  }
  await browser.close()
  writeFileSync(join(HERE, 'routes.json'), JSON.stringify({ ran_at: new Date().toISOString(), cap: CAP, total, log }, null, 2))
  console.log(`\ncollected ${total} new videos, ${seen.size} total in ${OUT}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
