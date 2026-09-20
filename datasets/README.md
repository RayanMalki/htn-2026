# Scan datasets

Raw output from the two GPTZero investigations. Regenerate summaries from these
rather than trusting any figure written elsewhere.

| Path | What |
|---|---|
| `videos/results.jsonl` | One row per YouTube Short: transcript, per-sentence scores, classification, subclass, pattern hits, views, channel, link |
| `videos/text/` | Every Whisper transcript as plain text |
| `videos/queue.jsonl` | Discovered candidates |
| `papers/results.jsonl` | One row per Europe PMC paper: classification of the paper's own prose, plus bibliography scan results where full text carried a reference list |

## Reading the paper rows

Two independent questions per paper, never to be added together:

- **`classification`** answers "was this paper's text written by a model"
- **`bibliography`** answers "do the sources it cites exist"

Inside `bibliography`:

- `fabricated` holds citations GPTZero called fake **and** that we could not find
  ourselves on Crossref or ClinicalTrials.gov
- `false_positives` holds citations GPTZero called fake that we **did** resolve.
  These are not fabrications and must not be counted as such.
- `exist_with_issues` in `statuses` is **not** a hallucination. It means some
  component did not match, which is usually reference formatting.

Papers are gated to publications after 2022, because a malformed citation in a
2007 paper is human sloppiness rather than fabrication.

Rerun the summary with `python scripts/scan_summary.py datasets/videos/results.jsonl`.
