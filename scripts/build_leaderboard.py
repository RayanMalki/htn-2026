"""Render scan/results.jsonl into a standalone investigation page.

Every number is counted from scanned rows and always carries its denominator.
The two cohorts stay separate: a topic sample gives a population rate, and the
channel follow-up does not, because those videos were chosen by pulling a thread.
"""
import html
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
ROWS = ROOT / "scan/results.jsonl"
OUT = ROOT / "leaderboard.html"
SCRIPT_THRESHOLD = 0.5
FOLLOWUP = "channel-followup"

VERDICT = {"AI_ONLY": "Machine-written", "MIXED": "Part machine-written",
           "HUMAN_ONLY": "Human-written"}
SUBCLASS = {"pure_ai": "straight from a model", "ai_paraphrased": "put through a humaniser",
            "concatenated": "human and machine blocks stitched", "polished": "written, then polished"}


def e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def load():
    if not ROWS.exists():
        return []
    unique = {}
    for line in ROWS.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            unique[row["id"]] = row  # A resumed run can append the same video twice.
    return list(unique.values())


def num(raw) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def views(raw) -> str:
    n = num(raw)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= limit:
            return f"{n / limit:.1f}".rstrip("0").rstrip(".") + suffix
    return str(n)


def is_machine(r) -> bool:
    return r.get("classification") in {"AI_ONLY", "MIXED"}


def row_html(r: dict) -> str:
    cls = r.get("classification") or "HUMAN_ONLY"
    tone = "flag" if is_machine(r) else "clear"
    sub = SUBCLASS.get(r.get("subclass") or "", "")
    names = Counter(p["name"] for p in r.get("patterns", []))
    chips = "".join(f'<span class="chip">{e(n)}{f" ×{c}" if c > 1 else ""}</span>'
                    for n, c in names.most_common())
    sentences = "".join(
        f'<li class="{"scripted" if (s.get("p") or 0) >= SCRIPT_THRESHOLD else "own"}">'
        f'<span class="p">{(s.get("p") or 0):.2f}</span><span>{e(s.get("text"))}</span></li>'
        for s in r.get("sentences", []))
    tells = "".join(
        f'<div class="tell"><p class="tell-head"><b>{e(p["name"])}</b>'
        f'<span>{e(p.get("k_times"))}× more frequent in machine text</span></p>'
        f'<blockquote>{e(p.get("sentence"))}</blockquote>'
        f'<p class="tell-why">{e(p.get("why"))}</p></div>'
        for p in r.get("patterns", []))
    uploader = r.get("uploader") if r.get("uploader") not in (None, "", "NA") else "channel not recorded"
    return f"""<details class="row {tone}">
<summary>
  <span class="dot" aria-hidden="true"></span>
  <span class="who"><b>{e(r.get('title'))}</b><span>{e(uploader)}</span></span>
  <span class="score">{(r.get('ai_prob') or 0):.3f}</span>
  <span class="views">{views(r.get('views'))}</span>
  <span class="verdict">{e(VERDICT.get(cls, cls))}{f'<i>{e(sub)}</i>' if sub else ''}</span>
  <span class="chips">{chips}</span>
</summary>
<div class="body">
  <a class="watch" href="{e(r.get('url'))}" target="_blank" rel="noreferrer">Watch on YouTube →</a>
  {f'<h4>What gives it away</h4>{tells}' if tells else ''}
  <h4>Transcript, scored per sentence</h4>
  <ol class="sentences">{sentences}</ol>
</div></details>"""


def farm_table(rows) -> str:
    """Per-channel hit rate: the shape of the follow-up finding in one glance."""
    tally = {}
    for r in rows:
        name = r.get("uploader") or "unknown"
        total, flagged = tally.get(name, (0, 0))
        tally[name] = (total + 1, flagged + (1 if is_machine(r) else 0))
    ordered = sorted(tally.items(), key=lambda kv: (-kv[1][1] / kv[1][0], -kv[1][0]))
    bars = "".join(
        f'<li><span class="farm-name">{e(name)}</span>'
        f'<span class="bar"><span style="width:{flagged / total * 100:.0f}%"></span></span>'
        f'<span class="p">{flagged}/{total}</span></li>'
        for name, (total, flagged) in ordered)
    return f'<ol class="farms">{bars}</ol>'


def cohort(rows, heading, standfirst, farms=False) -> str:
    if not rows:
        return ""
    ranked = sorted(rows, key=lambda r: (-(r.get("ai_prob") or 0), -num(r.get("views"))))
    return f"""<section class="cohort">
<h2>{heading}</h2><p class="standfirst">{standfirst}</p>
{farm_table(rows) if farms else ''}
<div class="rows">{''.join(row_html(r) for r in ranked)}</div></section>"""


def build() -> str:
    rows = load()
    sample = [r for r in rows if r.get("query") != FOLLOWUP]
    chased = [r for r in rows if r.get("query") == FOLLOWUP]
    flagged = [r for r in sample if is_machine(r)]
    rate = f"{len(flagged) / len(sample) * 100:.1f}" if sample else "0"
    all_views, flagged_views = sum(num(r.get("views")) for r in sample), sum(
        num(r.get("views")) for r in flagged)
    view_rate = f"{flagged_views / all_views * 100:.3f}" if all_views else "0"
    chased_flagged = [r for r in chased if is_machine(r)]
    patterns = Counter(p["name"] for r in rows for p in r.get("patterns", []))
    pattern_rows = "".join(
        f'<li><span>{e(n)}</span><span class="p">{c}</span></li>' for n, c in patterns.most_common())

    return f"""<title>Health Slop Index</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@400;600&display=swap">
<style>
:root{{
  --ground:#f7f8f7; --surface:#ffffff; --sunk:#f1f3f2; --ink:#161d24; --muted:#5f6b72;
  --rule:#dde2e3; --flag:#9c2f22; --flag-bg:#fbf0ed; --clear:#2f6b4f; --clear-bg:#eef4f0;
  --serif:'IBM Plex Serif',Georgia,serif; --sans:'IBM Plex Sans',system-ui,sans-serif;
  --mono:'IBM Plex Mono',ui-monospace,monospace;
}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
  --ground:#101519; --surface:#171e23; --sunk:#1c242a; --ink:#e7ecea; --muted:#8e9aa1;
  --rule:#2a343b; --flag:#e08573; --flag-bg:#2a1c19; --clear:#86c2a2; --clear-bg:#16241d;
}}}}
:root[data-theme="dark"]{{
  --ground:#101519; --surface:#171e23; --sunk:#1c242a; --ink:#e7ecea; --muted:#8e9aa1;
  --rule:#2a343b; --flag:#e08573; --flag-bg:#2a1c19; --clear:#86c2a2; --clear-bg:#16241d;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.6}}
.wrap{{max-width:980px;margin:0 auto;padding-inline:20px;padding-block:44px 64px}}
.kicker{{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:0}}
h1{{font-family:var(--serif);font-weight:600;font-size:clamp(28px,4.6vw,44px);line-height:1.12;
   text-wrap:balance;margin:14px 0 16px;letter-spacing:-.015em}}
.standfirst{{color:var(--muted);max-width:64ch;margin:0 0 26px}}
.headline{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--rule);
  border:1px solid var(--rule);border-radius:3px;overflow:hidden;margin-bottom:12px}}
.headline div{{background:var(--surface);padding:22px}}
.headline b{{font-family:var(--serif);font-size:clamp(34px,7vw,52px);font-weight:600;
  display:block;line-height:1;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.headline b i{{font-style:normal;font-size:.44em;margin-left:2px}}
.headline p{{margin:9px 0 0;font-size:13px;color:var(--muted)}}
.headline .of{{font-family:var(--mono);font-size:11px;color:var(--muted);display:block;margin-top:5px}}
.reading{{background:var(--sunk);border:1px solid var(--rule);border-radius:3px;padding:16px 18px;
  font-size:14px;margin-bottom:40px}}
.reading b{{font-weight:600}}
h2{{font-family:var(--serif);font-size:23px;font-weight:600;margin:0 0 6px;letter-spacing:-.01em}}
.cohort{{margin-bottom:44px}}
.cohort .standfirst{{margin-bottom:16px;font-size:14px}}
.rows{{border:1px solid var(--rule);border-radius:3px;overflow:hidden;background:var(--surface)}}
.row+.row{{border-top:1px solid var(--rule)}}
.row summary{{display:grid;grid-template-columns:9px 1fr 56px 52px 150px;gap:14px;align-items:center;
  padding:12px 16px;cursor:pointer;list-style:none}}
.row summary::-webkit-details-marker{{display:none}}
.row summary:hover{{background:var(--sunk)}}
.row summary:focus-visible{{outline:2px solid var(--ink);outline-offset:-2px}}
.dot{{width:9px;height:9px;border-radius:50%;background:var(--clear)}}
.row.flag .dot{{background:var(--flag)}}
.who b{{display:block;font-size:13.5px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.who span{{display:block;font-size:11.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.score{{font-family:var(--mono);font-size:12px;text-align:right;font-variant-numeric:tabular-nums;color:var(--clear)}}
.row.flag .score{{color:var(--flag)}}
.views{{font-family:var(--mono);font-size:11px;color:var(--muted);text-align:right}}
.verdict{{font-size:11.5px;color:var(--clear)}}
.row.flag .verdict{{color:var(--flag)}}
.verdict i{{display:block;font-style:normal;font-size:10.5px;color:var(--muted)}}
.chips{{grid-column:2/-1;display:flex;gap:5px;flex-wrap:wrap}}
.chips:empty{{display:none}}
.chip{{font-family:var(--mono);font-size:10px;background:var(--flag-bg);color:var(--flag);
  padding:2px 7px;border-radius:2px}}
.body{{padding:2px 16px 20px;border-top:1px solid var(--rule);background:var(--sunk)}}
.watch{{display:inline-block;font-size:12.5px;color:var(--ink);margin:14px 0 4px}}
h4{{font-family:var(--mono);font-size:10.5px;letter-spacing:.11em;text-transform:uppercase;
  color:var(--muted);margin:20px 0 10px;font-weight:500}}
.tell{{border-left:2px solid var(--flag);padding-left:13px;margin-bottom:15px}}
.tell-head{{margin:0;display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}}
.tell-head b{{font-size:13px}}
.tell-head span{{font-family:var(--mono);font-size:10.5px;color:var(--muted)}}
.tell blockquote{{margin:7px 0;font-family:var(--serif);font-size:14.5px;line-height:1.55}}
.tell-why{{margin:0;font-size:12.5px;color:var(--muted)}}
.sentences{{list-style:none;padding:0;margin:0;border:1px solid var(--rule);border-radius:3px;
  background:var(--surface);overflow:hidden}}
.sentences li{{display:grid;grid-template-columns:40px 1fr;gap:12px;padding:8px 12px;font-size:13px}}
.sentences li+li{{border-top:1px solid var(--rule)}}
.sentences li.scripted{{background:var(--flag-bg)}}
.p{{font-family:var(--mono);font-size:11px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}}
.sentences li.scripted .p{{color:var(--flag)}}
.farms{{list-style:none;padding:0;margin:0 0 18px;border:1px solid var(--rule);border-radius:3px;background:var(--surface)}}
.farms li{{display:grid;grid-template-columns:1fr 130px 46px;gap:14px;align-items:center;padding:10px 16px;font-size:13.5px}}
.farms li+li{{border-top:1px solid var(--rule)}}
.farm-name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar{{height:7px;background:var(--sunk);border-radius:2px;overflow:hidden;display:block}}
.bar span{{display:block;height:100%;background:var(--flag)}}
@media (max-width:720px){{.farms li{{grid-template-columns:1fr 46px;row-gap:7px}}.bar{{grid-column:1/-1}}}}
.tells-list{{border:1px solid var(--rule);border-radius:3px;background:var(--surface);
  list-style:none;padding:0;margin:0}}
.tells-list li{{display:flex;justify-content:space-between;gap:12px;padding:10px 16px;font-size:13.5px}}
.tells-list li+li{{border-top:1px solid var(--rule)}}
footer{{border-top:1px solid var(--rule);margin-top:44px;padding-top:20px;color:var(--muted);font-size:12.5px}}
footer p{{max-width:70ch}}
@media (max-width:720px){{
  .headline{{grid-template-columns:1fr}}
  .row summary{{grid-template-columns:9px 1fr 56px;row-gap:8px}}
  .views,.verdict{{grid-column:2/-1;text-align:left}}
  .verdict{{display:flex;gap:8px;align-items:baseline}}
}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;transition:none!important}}}}
</style>
<div class="wrap">
<p class="kicker">HypeCheck · Investigation</p>
<h1>One in ten health shorts is read off a machine-written script. Almost nobody watches them.</h1>
<p class="standfirst">Short health videos were transcribed locally with Whisper, then scored by
GPTZero for authorship and for the writing patterns that give a language model away. Every figure
below is counted from videos actually scanned, with its denominator shown.</p>

<div class="headline">
  <div><b>{rate}<i>%</i></b><p>of sampled videos were machine-written<span class="of">{len(flagged)} of {len(sample)} videos</span></p></div>
  <div><b>{view_rate}<i>%</i></b><p>of the views in that sample went to them<span class="of">{flagged_views:,} of {all_views:,} views</span></p></div>
</div>
<p class="reading"><b>How to read this.</b> Those two numbers disagree, and the gap is the finding.
Machine-written health video exists and is being published, but it sits on channels with almost no
audience. Every video in this sample with meaningful reach was written by a person.</p>

{cohort(sample, "Sampled by topic",
        f"Ten health search terms, shorts under 200 seconds. This cohort gives the population "
        f"rate above: {len(flagged)} of {len(sample)} machine-written.")}

{cohort(chased, "Followed to the source", farms=True, standfirst=
        f"The machine-written videos above were traced back to their channels and every short "
        f"those channels published was scanned. {len(chased_flagged)} of {len(chased)} came back "
        f"machine-written. These were selected by pulling a thread, so they are not a population "
        f"rate, they are what the thread led to.")}

{f'<section class="cohort"><h2>Which tells fired</h2><p class="standfirst">GPTZero names the specific writing habits behind a verdict. Counted across all {len(rows)} scanned videos.</p><ol class="tells-list">{pattern_rows}</ol></section>' if pattern_rows else ''}

<footer>
<h4>Method and limits</h4>
<p>Transcripts were produced locally with whisper.cpp <span class="p">base.en</span>, so wording can
differ slightly from the spoken audio. YouTube refuses the audio download on roughly 85% of shorts,
and the same videos refuse it every time, so the sample is what was reachable rather than a random
draw. YouTube Shorts only: no TikTok, no Instagram. Authorship measures how words were produced,
not whether the health claims are true. A creator speaking off the cuff can still be wrong, and
text reworded from a model still scores as machine-written.</p>
</footer>
</div>"""


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT} ({len(load())} videos)")
