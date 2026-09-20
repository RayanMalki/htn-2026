#!/usr/bin/env bash
# Copy the live scan output into the tracked datasets/ tree and push it.
# Safe to run repeatedly while scans are in flight: JSONL only ever grows.
set -euo pipefail
cd "$(dirname "$0")/.."
SCRATCH="${SLOP_SCRATCH:-}"
mkdir -p datasets/videos datasets/papers
[ -n "$SCRATCH" ] && [ -d "$SCRATCH" ] && rsync -a --exclude audio "$SCRATCH/" datasets/videos/
[ -d data/paper-scan ] && rsync -a data/paper-scan/ datasets/papers/
V=$(wc -l < datasets/videos/results.jsonl 2>/dev/null || echo 0)
P=$(wc -l < datasets/papers/results.jsonl 2>/dev/null || echo 0)
git add -f datasets >/dev/null
git diff --cached --quiet && { echo "no change"; exit 0; }
git commit -q -m "Scan data: ${V} video rows, ${P} paper rows"
git push -q origin gptzero-data
echo "pushed: ${V} video rows, ${P} paper rows"
