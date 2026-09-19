"""Submit five real Reel links; report fresh/cache measurements without inventing successful runs."""
import argparse
import json
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument("links", type=Path, help="JSON array with five Reel URLs")
args = parser.parse_args()
links = json.loads(args.links.read_text())
if len(links) != 5:
    parser.error("Provide exactly five links")
rows = []
with httpx.Client(base_url=args.base_url, timeout=15) as client:
    for link in links:
        start = time.monotonic()
        response = client.post("/api/cases", json={"source_url": link})
        response.raise_for_status()
        case = response.json()
        while case["status"] not in {"complete", "incomplete", "no_claims", "awaiting_upload"}:
            if time.monotonic() - start > 240:
                break
            time.sleep(1)
            response = client.get(f"/api/cases/{case['id']}")
            response.raise_for_status()
            case = response.json()
        elapsed = round(time.monotonic() - start, 3)
        cached = sum(c.get("provenance", {}).get("cache_hits", 0) for c in case["result"].get("claims", {}).values())
        rows.append({"case_id": case["id"], "status": case["status"], "wall_seconds": elapsed,
                     "model_mode": case["result"].get("model_mode"), "cached_papers": cached,
                     "meets_target": case["status"] == "complete" and elapsed <= 90
                     and case["result"].get("model_mode") == "live"})
Path("artifacts").mkdir(exist_ok=True)
Path("artifacts/benchmark.json").write_text(json.dumps(rows, indent=2))
print(json.dumps({"live_completed_under_90s": sum(r["meets_target"] for r in rows),
                  "fresh_runs": sum(r["cached_papers"] == 0 for r in rows), "runs": rows}, indent=2))
