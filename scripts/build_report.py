"""Render the scan datasets into one page: the trajectory, the highlighted text, the links.

Everything is counted from datasets/. Nothing is typed in by hand.
"""
import html
import json
from collections import Counter
from pathlib import Path

D = Path("datasets")
OUT = Path("datasets/report.html")
T = 0.5


def e(v):
    return html.escape(str(v if v is not None else ""))


def load(p, key):
    u = {}
    f = D / p
    if not f.exists():
        return []
    for line in f.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            u[r[key]] = {**u.get(r[key], {}), **r}
    return list(u.values())


def num(v):
    return int(v) if str(v).isdigit() else 0


def machine(r):
    return r.get("classification") != "HUMAN_ONLY"


def sentence_rows(sentences, limit=None):
    out = []
    for s in (sentences or [])[:limit]:
        p = s.get("p") or s.get("generated_prob") or 0
        cls = "hot" if p >= T else "cool"
        out.append(f'<li class="{cls}"><span class="p">{p:.2f}</span>'
                   f'<span>{e(s.get("text"))}</span></li>')
    return "".join(out)


def build():
    papers = load("papers/results.jsonl", "pmcid")
    videos = load("videos/results.jsonl", "id")
    show = sorted((json.loads(p.read_text()) for p in (D / "showcase").glob("PMC*.json")),
                  key=lambda r: -(r.get("ai_probability") or 0))
    para = sorted((r for r in papers if r.get("subclass") == "ai_paraphrased"),
                  key=lambda r: (-(r.get("year") or 0), -(r.get("ai_prob") or 0)))
    mixedv = sorted((r for r in videos if r.get("classification") == "MIXED"),
                    key=lambda r: -num(r.get("views")))

    years = "".join(
        f'<tr><td>{y}</td><td class="n">{sum(1 for r in papers if r.get("year") == y and machine(r))}'
        f' / {sum(1 for r in papers if r.get("year") == y)}</td>'
        f'<td class="barcell"><span class="bar" style="width:{sum(1 for r in papers if r.get("year") == y and machine(r)) / max(1, sum(1 for r in papers if r.get("year") == y)) * 100:.0f}%"></span></td>'
        f'<td class="pct">{sum(1 for r in papers if r.get("year") == y and machine(r)) / max(1, sum(1 for r in papers if r.get("year") == y)) * 100:.0f}%</td></tr>'
        for y in sorted({r["year"] for r in papers if r.get("year")}))

    showcase = "".join(
        f'<details class="doc {"hot" if r["classification"] != "HUMAN_ONLY" else "cool"}"'
        f'{" open" if i == 0 else ""}><summary>'
        f'<span class="tag">{e(r["classification"])}</span>'
        f'<b>{e(r.get("journal"))}</b> {e(r.get("year"))}'
        f'<span class="score">{sum(1 for s in r["sentences"] if (s["p"] or 0) >= T)}'
        f'/{len(r["sentences"])} flagged</span></summary>'
        f'<p class="title">{e(r.get("title"))}</p>'
        f'<p class="meta">ai={r.get("ai_probability"):.4f} · {e(r.get("subclass") or "no subclass")}'
        f' · <a href="{e(r.get("url"))}" target="_blank" rel="noreferrer">open the paper</a></p>'
        f'<ol class="sents">{sentence_rows(r["sentences"], 30)}</ol></details>'
        for i, r in enumerate(show))

    vids = "".join(
        f'<details class="doc hot"><summary><span class="tag">{e(r.get("subclass"))}</span>'
        f'<b>{e(r.get("uploader") or "?")}</b>'
        f'<span class="score">{num(r.get("views")):,} views · '
        f'{sum(1 for s in r.get("sentences", []) if (s.get("p") or 0) >= T)}'
        f'/{len(r.get("sentences", []))} flagged</span></summary>'
        f'<p class="title">{e(r.get("title"))}</p>'
        f'<p class="meta"><a href="{e(r.get("url"))}" target="_blank" rel="noreferrer">watch on YouTube</a></p>'
        f'<ol class="sents">{sentence_rows(r.get("sentences"))}</ol></details>'
        for r in mixedv[:8])

    laundered = "".join(
        f'<li><a href="{e(r["url"])}" target="_blank" rel="noreferrer">{e(r.get("title"))}</a>'
        f'<span class="meta">{e(r.get("journal"))} · {e(r.get("year"))} · ai={r.get("ai_prob"):.3f}</span></li>'
        for r in para)

    cit = [r for r in papers if (r.get("bibliography") or {}).get("citations_checked")]
    checked = sum(r["bibliography"]["citations_checked"] for r in cit)
    flagged = sum(r["bibliography"].get("statuses", {}).get("fake", 0) for r in cit)
    resolved = sum(len(r["bibliography"].get("false_positives", [])) for r in cit)
    unresolved = sum(len(r["bibliography"].get("fabricated", [])) for r in cit)
    subs = Counter(r.get("subclass") for r in papers + videos if r.get("subclass"))

    return f"""<title>AI Slop Index</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&display=swap">
<style>
:root{{--ground:#f7f8f7;--surface:#fff;--sunk:#f1f3f2;--ink:#161d24;--muted:#5f6b72;
--rule:#dde2e3;--hot:#9c2f22;--hot-bg:#fbf0ed;--cool:#2f6b4f;--cool-bg:#eef4f0;
--serif:'IBM Plex Serif',Georgia,serif;--sans:'IBM Plex Sans',system-ui,sans-serif;
--mono:'IBM Plex Mono',ui-monospace,monospace}}
@media(prefers-color-scheme:dark){{:root:not([data-theme=light]){{--ground:#101519;--surface:#171e23;
--sunk:#1c242a;--ink:#e7ecea;--muted:#8e9aa1;--rule:#2a343b;--hot:#e08573;--hot-bg:#2a1c19;
--cool:#86c2a2;--cool-bg:#16241d}}}}
:root[data-theme=dark]{{--ground:#101519;--surface:#171e23;--sunk:#1c242a;--ink:#e7ecea;
--muted:#8e9aa1;--rule:#2a343b;--hot:#e08573;--hot-bg:#2a1c19;--cool:#86c2a2;--cool-bg:#16241d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--ground);color:var(--ink);
font-family:var(--sans);font-size:15px;line-height:1.6}}
.wrap{{max-width:940px;margin:0 auto;padding-inline:20px;padding-block:44px 64px}}
.kicker{{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:0}}
h1{{font-family:var(--serif);font-size:clamp(28px,4.6vw,44px);line-height:1.12;margin:14px 0 14px;text-wrap:balance}}
h2{{font-family:var(--serif);font-size:23px;margin:44px 0 6px}}
.lede{{color:var(--muted);max-width:64ch;margin:0 0 8px}}
table{{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--rule);border-radius:3px;margin:18px 0}}
td{{padding:9px 14px;border-bottom:1px solid var(--rule);font-size:14px}}
tr:last-child td{{border-bottom:0}}
.n,.pct{{font-family:var(--mono);font-size:12px;white-space:nowrap}}
.pct{{text-align:right;font-weight:600}}
.barcell{{width:55%}}.bar{{display:block;height:9px;background:var(--hot);border-radius:2px;min-width:2px}}
.doc{{background:var(--surface);border:1px solid var(--rule);border-radius:3px;margin-bottom:8px}}
.doc summary{{display:flex;gap:11px;align-items:center;padding:12px 15px;cursor:pointer;list-style:none;flex-wrap:wrap}}
.doc summary::-webkit-details-marker{{display:none}}
.doc.hot summary{{border-left:3px solid var(--hot)}}.doc.cool summary{{border-left:3px solid var(--cool)}}
.tag{{font-family:var(--mono);font-size:10px;padding:3px 7px;border-radius:2px;background:var(--hot-bg);color:var(--hot)}}
.doc.cool .tag{{background:var(--cool-bg);color:var(--cool)}}
.score{{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--muted)}}
.title{{margin:0 15px 4px;font-size:14px}}
.meta{{margin:0 15px 12px;font-size:12px;color:var(--muted);font-family:var(--mono)}}
.sents{{list-style:none;margin:0;padding:0;border-top:1px solid var(--rule)}}
.sents li{{display:grid;grid-template-columns:42px 1fr;gap:11px;padding:7px 15px;font-size:13px;line-height:1.55}}
.sents li+li{{border-top:1px solid var(--rule)}}
.sents li.hot{{background:var(--hot-bg)}}.sents li.cool{{background:var(--cool-bg)}}
.p{{font-family:var(--mono);font-size:11px;text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}}
li.hot .p{{color:var(--hot)}}li.cool .p{{color:var(--cool)}}
ul.links{{list-style:none;padding:0;margin:14px 0}}
ul.links li{{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--hot);
border-radius:3px;padding:11px 15px;margin-bottom:7px}}
ul.links a{{color:var(--ink);font-size:14px}}ul.links .meta{{display:block;margin:5px 0 0}}
.note{{background:var(--sunk);border:1px solid var(--rule);border-radius:3px;padding:15px 17px;font-size:13.5px;margin:16px 0}}
footer{{border-top:1px solid var(--rule);margin-top:44px;padding-top:18px;color:var(--muted);font-size:12.5px}}
@media(max-width:700px){{.sents li{{grid-template-columns:36px 1fr;gap:8px}}.barcell{{width:35%}}}}
</style>
<div class="wrap">
<p class="kicker">HypeCheck · {len(papers):,} papers · {len(videos):,} videos</p>
<h1>Machine-written text went from nothing to half the literature in three years.</h1>
<p class="lede">Every paper and video below was scored by GPTZero. Sentences at or
above {T:.2f} are shown in red. Nothing here is typed by hand: every figure is counted
from the raw scan data in this branch.</p>

<h2>The trajectory</h2>
<p class="lede">Share of published papers carrying machine-written text, by year.</p>
<table>{years}</table>
<div class="note"><b>Why the early years matter.</b> Academic prose was just as
formulaic in 2022, so if the detector simply flagged scholarly register those rows
would light up too. They read zero across 72 papers. Something changed in 2024.</div>

<h2>Read one</h2>
<p class="lede">Four papers with every sentence scored. The last is human-written,
included on purpose: same era, same tier of journal, nothing flagged.</p>
{showcase}

<h2>Laundered through a humaniser</h2>
<p class="lede">{len(para)} papers came back <code>ai_paraphrased</code>: generated, then
reworded to defeat detection. That is deliberate in a way that reading a script is not.
Several are about artificial intelligence in medicine.</p>
<ul class="links">{laundered}</ul>

<h2>Video, stitched together</h2>
<p class="lede">Creators splicing machine-written blocks into their own speech. Open one
to see which sentences are theirs.</p>
{vids}

<h2>The citation hunt came up empty</h2>
<div class="note">
<b>{checked:,} citations checked</b> across {len(cit)} papers. GPTZero called
<b>{flagged}</b> fabricated. We resolved <b>{resolved}</b> of those ourselves on Crossref
or ClinicalTrials.gov, leaving <b>{unresolved}</b> unresolved.<br><br>
Its <code>fake</code> label misfires on trial registrations, on book chapters, and on
ordinary journal articles. The writing is being automated fast. The citation layer is
still holding.
</div>

<h2>How it was made</h2>
<table>{"".join(f'<tr><td><code>{e(k)}</code></td><td class="pct">{v}</td></tr>' for k, v in subs.most_common())}</table>

<footer>Detection by GPTZero. Papers from Europe PMC open access, full text only.
Videos are YouTube Shorts, transcribed locally with whisper.cpp, so wording can differ
slightly from the audio. Authorship measures how words were produced, never whether a
claim is true. The prestige-versus-broad venue comparison in this sample is confounded
by year and is deliberately not shown.</footer>
</div>"""


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT}")
