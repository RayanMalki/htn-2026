# MedBot sponsor demo

The user-supplied prize descriptions guide this preparation; these notes do not
claim eligibility, judging approval, or a guaranteed prize.

## What the app actually does

GPTZero receives the spoken transcript through its text-prediction API. The UI
shows document classification probabilities, the returned confidence category,
and expandable sentence signals. Missing scores remain unavailable, not zero.
It cannot establish who wrote a script or whether a medical statement is true.
The API key stays on the backend. Detection failure does not stop evidence research.
GPTZero hallucination detection is **not integrated** and must not be claimed.

Elasticsearch indexes research passages discovered for each claim. The retrieval
path combines keyword and semantic search using reciprocal rank fusion, limits
results to eligible candidate passages, and reports keyword-only degradation.
The pipeline turns an unstructured clip into claims, retrieves context, creates
cited assessments, and triggers a video. This is a bounded automated pipeline,
not an implementation of Elastic Agent Builder or Workflows. Jina dense vectors
and reranking are not implemented and must not appear as completed features.

The UI preserves exact quotes, source access type, provider failures and research
queries behind expandable evidence panels. A compact finding summary precedes
sharing. There is no calibrated probability that a medical claim is true, so the
only confidence meter uses GPTZero's returned authorship confidence. Verdict
counts are not repurposed into a medical confidence score.

## Prepare outside the code

1. Confirm submission deadlines, team eligibility, required sponsor registration,
   API access, demo format and judging criteria with the organizers. The supplied
   descriptions name desirable examples, not proof every listed Elastic feature
   is mandatory.
2. Build a small, permissioned evaluation set: known human-written scripts,
   deliberately AI-written scripts, edited/mixed scripts, and independently
   reviewed health claims. Keep authorship labels separate from medical labels.
   An online creator's identity or a detector result is not authorship ground truth.
3. Have a qualified reviewer check representative medical findings against the
   exact quoted papers. Log disagreements, uncited claims, false positives,
   transcription errors and missing evidence. Do not advertise clinical accuracy.
4. Demonstrate the non-obvious case: a human-like transcript can still contain an
   unsupported health claim, and AI-written text can cite valid evidence. Open
   the sentence map and a quoted source to show why both signals matter.
5. For Elastic, label expected relevant papers, compare keyword-only with hybrid
   on the same inputs, and record retrieval quality, latency, cache hits and
   degraded runs. Do not claim hybrid superiority without measurements.
6. Record a short demo from submission through evidence, GPTZero and video.
   Prepare saved offline replays and downloaded media as an explicitly labeled
   fallback. Show which API requests were live and which tests use fixtures.
7. Include a simple architecture explanation and evidence of sponsor API use
   with credentials redacted. Explain the public-health information problem,
   who benefits, limitations, and what users can do with the result.

## Further work if time permits

Recommended medical ranking safeguards: extract population, intervention/exposure,
comparator, outcome, dose and duration from the claim and each candidate passage;
record match/mismatch/unknown rather than filling missing data with guesses.
Retrieve by relevance first, then evaluate applicability and study limitations.
Keep RRF relevance, study quality, citation validity and entailment separate. A
new paper or a systematic review is not automatically relevant or reliable.
Require direct support for causal claims; distinguish observational associations.
Return uncertain for unresolved conflicts or essential applicability mismatches,
and preserve the specific reasons. Test this with reviewed claim–paper pairs and
report error rates before claiming any accuracy improvement.

Implemented in the UI follow-up: saved retrieval order is visible, uncertainty
reasons remain available, and retraction flag changes refresh cached Elastic
documents. The richer applicability evaluation above is a proposal, not a new
implemented scoring system.

An independent hallucination/grounding pass over the app's generated explanation
could strengthen the GPTZero submission, after verifying the sponsor's actual
API access and its supported inputs. It needs its own saved result, UI label,
failure behavior and evaluation; the current detector is not that feature.

For Elastic, benchmark a reranker before adding it. A useful action workflow could
request broader research when retrieval is inadequate; it must preserve bounded
execution and explicit insufficient-evidence outcomes. Adding logos or a chat
window does not demonstrate retrieval quality or agentic behavior.

References:
- https://support.gptzero.me/articles/8947054519-how-do-i-use-and-interpret-the-results-from-your-api
- https://www.elastic.co/docs/solutions/search/hybrid-search
- https://www.elastic.co/docs/solutions/search/ranking
