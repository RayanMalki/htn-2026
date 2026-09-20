"""Batch scan short health videos for machine-written scripts.

search -> audio only -> whisper (punctuated) -> GPTZero detect + AI patterns.

Resumable: every stage writes to disk and is skipped when its output exists, so
an interrupted run continues instead of restarting. Nothing here touches the
HypeCheck pipeline; this is the investigation tool.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

KEY = os.environ["KEY"]
ROOT = Path(__file__).parent / "scan"
AUDIO, TEXT = ROOT / "audio", ROOT / "text"
RESULTS = ROOT / "results.jsonl"
# Roughly 70% of YouTube Shorts refuse the audio download, and the same ones refuse
# it every time, so remember them rather than paying for the attempt on each resume.
FAILED = ROOT / "failed.txt"
# Discovery is the memory-hungry step and its answers do not change between runs,
# so it happens once into a queue and every later run just drains that queue.
QUEUE = ROOT / "queue.jsonl"
COOKIE_BROWSER = os.environ.get("SCAN_COOKIE_BROWSER", "safari")
WHISPER_THREADS = "2"  # 8 GB machine; the default of one per core drove it into swap.
MODEL = Path.home() / ".cache/whisper/ggml-base.en.bin"
DETECT = "https://api.gptzero.me/v2/predict/text"
PATTERNS = "https://api.gptzero.me/v3/ai/patterns/stream"
MIN_CHARS = 200

QUERIES = [
    "seed oils inflammation", "cortisol belly fat", "gut health probiotics",
    "detox liver cleanse", "parasite cleanse", "raw milk benefits",
    "insulin resistance diet", "mthfr gene mutation", "alkaline water benefits",
    "carnivore diet results", "magnesium sleep deficiency", "adrenal fatigue symptoms",
    "leaky gut syndrome", "thyroid weight gain", "berberine blood sugar",
    "collagen supplement skin", "apple cider vinegar weight", "intermittent fasting autophagy",
    "blue light glasses sleep", "grounding earthing benefits", "fluoride water dangers",
    "microplastics detox", "heavy metal detox", "candida overgrowth diet",
    "histamine intolerance foods", "oxalate dumping", "vitamin d deficiency signs",
    "electrolytes hydration myth", "creatine women benefits", "ashwagandha cortisol",
    "estrogen dominance symptoms", "perimenopause belly fat", "testosterone boosting foods",
    "gut brain axis anxiety", "inflammation foods avoid", "glp1 natural alternative",
    "metabolism damage dieting", "sleep hygiene cortisol", "liver king supplements",
    "bioavailable nutrients absorption",
    # Higher-harm territory: claims where acting on them can injure someone.
    "vaccines cause autism", "vaccines are dangerous", "raw meat diet benefits",
    "raw milk raw dairy healing", "fascia release myofascial", "sucralose dangerous",
    "aspartame dangerous", "cigarettes healthy smoking benefits", "nicotine benefits",
    "seed oils worse than cigarettes", "sunscreen causes cancer", "fluoride lowers iq",
    "oscar patel health", "colloidal silver benefits", "urine therapy benefits",
    "black salve cancer", "apricot seeds cancer b17", "grounding sheets inflammation",
]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def discover(per_query: int) -> list[dict]:
    found, seen = [], set()
    for q in QUERIES:
        # Shorts-length only, so a transcript is one script rather than an interview.
        # Plain search returns mostly long-form, so ask for shorts and oversample by 3x
        # because the duration filter discards roughly half of what comes back.
        r = run(["yt-dlp", f"ytsearch{per_query * 3}:{q} #shorts", "--skip-download", "--no-warnings",
                 "--match-filter", "duration < 200 & duration > 15",
                 "--print", "%(id)s\t%(duration)s\t%(view_count)s\t%(uploader)s\t%(title)s"])
        for line in r.stdout.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) < 5 or parts[0] in seen:
                continue
            seen.add(parts[0])
            found.append({"id": parts[0], "duration": parts[1], "views": parts[2],
                          "uploader": parts[3], "title": parts[4], "query": q,
                          "url": f"https://www.youtube.com/watch?v={parts[0]}"})
        print(f"  {q}: {len(found)} total", flush=True)
    return found


def transcribe(video: dict) -> str | None:
    out = TEXT / f"{video['id']}.txt"
    if out.exists():
        return out.read_text().strip() or None
    wav = AUDIO / f"{video['id']}.wav"
    if not wav.exists():
        # A signed-in session lifts the 403 that refuses roughly three quarters of
        # shorts, and on that path YouTube offers no audio-only stream, so fall back
        # through the smallest combined formats. Paced, because this is a real account.
        r = run(["yt-dlp", video["url"], "--cookies-from-browser", COOKIE_BROWSER,
                 "-f", "bestaudio/91/18/worst", "-x", "--audio-format", "wav",
                 "--postprocessor-args", "-ar 16000 -ac 1", "--no-warnings", "-q",
                 "--sleep-requests", "1", "--min-sleep-interval", "1", "--max-sleep-interval", "3",
                 "-o", str(AUDIO / f"{video['id']}.%(ext)s")])
        if not wav.exists():
            print(f"    ! download failed {video['id']}: {r.stderr.strip()[:90]}", flush=True)
            with FAILED.open("a") as f:
                f.write(video["id"] + "\n")
            return None
    r = run(["whisper-cli", "-m", str(MODEL), "-f", str(wav), "-nt", "-np",
             "-t", WHISPER_THREADS])
    text = " ".join(r.stdout.split())
    wav.unlink(missing_ok=True)  # Audio is large and we only need the words.
    out.write_text(text)
    return text or None


async def score(client: httpx.AsyncClient, text: str) -> dict:
    d = (await client.post(DETECT, headers={"x-api-key": KEY},
                           json={"document": text, "multilingual": False})).json()["documents"][0]
    sub = (d.get("subclass") or {}).get(d.get("predicted_class"), {})
    hits = []
    async with client.stream("POST", PATTERNS, headers={"x-api-key": KEY},
                             json={"documents": [{"inputText": text}]}) as r:
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:].strip())
            for p in ev.get("patterns", []):
                hits.append({"name": p.get("display_name"), "id": p.get("pattern_id"),
                             "sentence": ev.get("sentence", "")[:300],
                             "why": p.get("explanation", "")[:300],
                             "k_times": p.get("k_times")})
    probs = d.get("class_probabilities") or {}
    return {
        "classification": d.get("document_classification"),
        "ai_prob": probs.get("ai"), "human_prob": probs.get("human"),
        "mixed_prob": probs.get("mixed"), "confidence": d.get("confidence_category"),
        "subclass": sub.get("predicted_class"),
        "scripted_share": d.get("average_generated_prob"),
        "sentences": [{"text": s.get("sentence", "")[:400], "p": s.get("generated_prob")}
                      for s in (d.get("sentences") or [])],
        "patterns": hits,
    }


async def main(per_query: int, batch: int):
    for p in (AUDIO, TEXT):
        p.mkdir(parents=True, exist_ok=True)
    done = set()
    if RESULTS.exists():
        done = {json.loads(line)["id"] for line in RESULTS.read_text().splitlines() if line.strip()}
    if FAILED.exists():
        done |= {line.strip() for line in FAILED.read_text().splitlines() if line.strip()}
    if QUEUE.exists():
        queued = [json.loads(line) for line in QUEUE.read_text().splitlines() if line.strip()]
        print(f"queue: {len(queued)} videos already discovered", flush=True)
    else:
        print(f"discovering ({per_query} per query, {len(QUERIES)} queries)...", flush=True)
        queued = discover(per_query)
        QUEUE.write_text("".join(json.dumps(v) + "\n" for v in queued))
        print(f"queue written: {len(queued)} videos", flush=True)
    videos = [v for v in queued if v["id"] not in done][:batch]
    print(f"{len(videos)} to process this run, {len(done)} already seen\n", flush=True)
    async with httpx.AsyncClient(timeout=120) as client:
        for i, v in enumerate(videos, 1):
            text = transcribe(v)
            if not text or len(text) < MIN_CHARS:
                print(f"[{i}/{len(videos)}] skip {v['id']} (transcript too short)", flush=True)
                continue
            try:
                result = await score(client, text)
            except Exception as exc:
                print(f"[{i}/{len(videos)}] ! score failed {v['id']}: {exc}", flush=True)
                continue
            row = {**v, **result, "transcript": text, "chars": len(text)}
            with RESULTS.open("a") as f:
                f.write(json.dumps(row) + "\n")
            pats = ", ".join(sorted({p["name"] for p in result["patterns"]})) or "-"
            print(f"[{i}/{len(videos)}] {result['classification']:<11} "
                  f"ai={result['ai_prob']:.3f}  {v['uploader'][:18]:<18} {pats[:50]}", flush=True)


if __name__ == "__main__":
    import asyncio
    per_query = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    batch = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    asyncio.run(main(per_query, batch))
