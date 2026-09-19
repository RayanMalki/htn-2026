"""Exercise a real deployed API/queue/media path without assuming external keys exist."""
import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://localhost")
args = parser.parse_args()
artifacts = Path("artifacts")
artifacts.mkdir(exist_ok=True)
clip = artifacts / "smoke-tone.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac",
                "-shortest", str(clip)], check=True)
with httpx.Client(base_url=args.base_url, timeout=20) as client:
    health = client.get("/healthz")
    health.raise_for_status()
    response = client.post("/api/cases", json={"source_url": "https://www.instagram.com/reel/HypeCheckSmokeFixture/"})
    response.raise_for_status()
    case = response.json()
    started = time.monotonic()
    uploaded = False
    observed = [case["status"]]
    while time.monotonic() - started < 180:
        response = client.get(f"/api/cases/{case['id']}")
        response.raise_for_status()
        case = response.json()
        if case["status"] not in observed:
            observed.append(case["status"])
        if case["status"] == "awaiting_upload" and not uploaded:
            with clip.open("rb") as stream:
                response = client.post(f"/api/cases/{case['id']}/media", files={"file": (clip.name, stream, "video/mp4")})
            response.raise_for_status()
            uploaded = True
        elif case["status"] in {"complete", "incomplete", "no_claims"}:
            break
        time.sleep(1)
    if case["status"] not in {"complete", "incomplete", "no_claims"}:
        raise SystemExit(f"Pipeline did not finish: {case['status']}")
    replay = client.get(f"/api/cases/{case['id']}/replay")
    replay.raise_for_status()
    (artifacts / "stack-replay.html").write_bytes(replay.content)
    recording = {"kind": "infrastructure_smoke", "input": "generated tone, not a medical video",
                 "observed_states": observed, "uploaded": uploaded, "case": case}
    (artifacts / "stack-smoke.json").write_text(json.dumps(recording, indent=2))
    print(json.dumps({"case_id": case["id"], "status": case["status"], "observed_states": observed,
                      "uploaded": uploaded, "model_mode": case["result"].get("model_mode"),
                      "note": "Infrastructure check only; no live medical verdict claimed."}, indent=2))
