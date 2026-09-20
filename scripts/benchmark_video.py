"""Benchmark saved live analyses with fresh render/audio caches (no new medical research).

Run inside the worker: python /app/../... or copy this file to /tmp/benchmark_video.py.
Outputs JSON reports; never prints prompts, transcripts or credentials.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('case_json', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--concurrency', type=int, default=1)
    parser.add_argument('--source-clip')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)

    def run(i):
        root = args.output / str(i)
        root.mkdir()
        env = dict(os.environ, HYPECHECK_VOICE_CACHE=str(root / 'voice_cache'))
        command = [sys.executable, '-m', 'app.video.render', str(args.case_json), str(root)]
        if args.source_clip:
            command += ['--source-clip', args.source_clip]
        started = time.monotonic()
        with (root / 'render.log').open('w') as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=log)
        report = {'run': i, 'wall_seconds': round(time.monotonic() - started, 3),
                  'exit_code': result.returncode, 'fresh_audio_cache': True,
                  'saved_analysis': True, 'concurrency': args.concurrency}
        if (root / 'result.json').exists():
            video = json.loads((root / 'result.json').read_text())
            report.update({k: video.get(k) for k in ['duration_seconds', 'stage_timings', 'reused_stages', 'caption_timing']})
        (root / 'benchmark.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
        return report

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        reports = list(pool.map(run, range(args.runs)))
    (args.output / 'benchmark.json').write_text(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
