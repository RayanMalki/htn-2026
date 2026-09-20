#!/usr/bin/env bash
set -euo pipefail

# Submit one public Short through the running app and verify every persisted
# stage. With live credentials, this downloads and probes the generated MP4,
# captions, and source manifest. Mock/incomplete cases fail before pretending
# that a medical video exists.
base_url="${BASE_URL:-http://localhost}"
source_url="${1:-https://youtube.com/shorts/8DG6bEi6z-o?si=_TJYyGQZWm5cmFjg}"
run_dir="artifacts/e2e-short-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$run_dir"

curl -fsS "$base_url/healthz" > "$run_dir/health.json"
curl -fsS "$base_url/api/config" > "$run_dir/config.json"
curl -fsS -X POST "$base_url/api/cases" -H 'content-type: application/json' \
  --data "$(python3 -c 'import json,sys; print(json.dumps({"source_url":sys.argv[1]}))' "$source_url")" > "$run_dir/submission.json"
case_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$run_dir/submission.json")
echo "case=$case_id"

for _ in $(seq 1 90); do
  curl -fsS "$base_url/api/cases/$case_id" > "$run_dir/case.json"
  status=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$run_dir/case.json")
  video=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("result",{}).get("video",{}).get("status", "none"))' "$run_dir/case.json")
  echo "status=$status video=$video"
  case "$status" in complete|incomplete|no_claims) break;; esac
  sleep 2
done

curl -fsS --max-time 5 "$base_url/api/cases/$case_id/events" > "$run_dir/events.sse" || true
status=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$run_dir/case.json")
video=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("result",{}).get("video",{}).get("status", "none"))' "$run_dir/case.json")
if [[ "$status" != complete || "$video" != ready ]]; then
  python3 - "$run_dir/case.json" <<'PY'
import json, sys
case = json.load(open(sys.argv[1]))
result = case.get("result", {})
claim = next(iter((result.get("claims") or {}).values()), {})
print(json.dumps({"status": case.get("status"), "model_mode": result.get("model_mode"),
                  "video": result.get("video"), "claim_error": claim.get("error"),
                  "limitations": result.get("limitations")}, indent=2))
PY
  echo "No generated medical video is available; inspect $run_dir." >&2
  exit 2
fi

curl -fsS "$base_url/api/cases/$case_id/video?download=true" -o "$run_dir/response.mp4"
curl -fsS "$base_url/api/cases/$case_id/video/captions" -o "$run_dir/captions.vtt"
curl -fsS "$base_url/api/cases/$case_id/video/sources" -o "$run_dir/sources.json"
if command -v ffprobe >/dev/null 2>&1; then
  ffprobe -v error -show_entries format=duration:stream=codec_name,width,height \
    -of json "$run_dir/response.mp4" > "$run_dir/media-probe.json"
fi
echo "Generated video verified in $run_dir/response.mp4"
