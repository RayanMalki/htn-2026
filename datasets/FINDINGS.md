# Findings

Every figure is counted from `datasets/`. Regenerate with `scripts/analyse_branch.py`.

**3454 papers and 521 videos scanned.**

## 1. Machine-written text in published papers, by year

| Year | Machine-written or mixed | n |
|---|---|---|
| 2022 | **0%** | 35 |
| 2023 | **0%** | 37 |
| 2024 | **16%** | 1664 |
| 2025 | **36%** | 334 |
| 2026 | **47%** | 1384 |

Zero in 2022 and 2023, then a rise that has not stopped. The early years are
the control: same journals, same academic register, nothing flagged.

## 2. Short-form health video

- **Topic sample (a population rate)**: 26 of 473 machine-written (5.5%), holding 134,823 of 17,063,638 views (0.790%)
- **Channel follow-up (not a rate)**: 44 of 48 machine-written (91.7%), holding 3,431 of 4,079 views (84.114%)

Machine-written health video exists and is published. Almost nobody watches it.

## 3. How it was made

| Subclass | Papers | Videos |
|---|---|---|
| `ai_paraphrased` | 12 | 0 |
| `concatenated` | 224 | 4 |
| `polished` | 110 | 3 |
| `pure_ai` | 690 | 63 |

## 4. Citation integrity

- **4894 citations checked** across 132 papers
- GPTZero flagged **62** as fabricated
- We resolved **58** of those ourselves on Crossref or ClinicalTrials.gov
- **4 unresolved**

The fabrication hunt is a negative result. Its `fake` label misfires on trial
registrations, on book chapters, and on ordinary journal articles. Every flag
is listed in `review/every-flagged-citation.md` with what we found.

- 113 claims extracted, **20 check-worthy but uncited**, 1 contradicted by their own citation

## 5. What is in this branch

| Path | What |
|---|---|
| `papers/results.jsonl` | one row per paper: verdict, subclass, bibliography, claims |
| `videos/results.jsonl` | one row per video: transcript, per-sentence scores, patterns |
| `showcase/` | a few papers with every sentence scored, for the interface |
| `review/` | the cases needing a human eye |

## 6. What this does not show

- Prestige versus broad venue is **confounded by year** in this sample. Do not quote it.
- Academic introductions are formulaic, so a sceptic will say the detector reads register.
  The answer is the 2022 and 2023 rows: same register, 0%.
- Video sampling is YouTube Shorts only, and not a random draw.
