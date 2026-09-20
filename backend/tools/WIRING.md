# Wiring the web-search fallback into the backend

Where it goes: `backend/app/pipeline.py`, inside `run_case`, in the inner
`judge(claim)` coroutine (about line 155). The literature step has already run
by then and `item["evidence"]` holds the passages. The fallback slots in after

```python
evidence = [Passage.model_validate(p) for p in item["evidence"]]
```

and before `adapter.judge(claim, evidence)`:

```python
from app.websearch_fallback import should_fallback, search_and_write

stances = [{"stance": p.stance} for p in evidence]   # or however stance is carried per passage
web = search_and_write(claim.text, stances, settings().openai_api_key) if should_fallback(stances) else None
```

Then feed the model's verdict as usual, and if `web` is not None:

1. Append one passage to `evidence` so the judge and the page see it:
   `provider="openai_web_search"`, `source_kind="guideline"`, `access_type="summary"`,
   text = `web["paragraph"]`, source_url = first citation url. This needs two
   one-word additions in `backend/app/schemas.py`: add `"openai_web_search"` to the
   `Passage.provider` Literal (line 80). `source_kind` already has `"guideline"` and
   `access_type` already has `"summary"` (lines 82 and 85), nothing to add there.
2. Map the stance into the `Verdict.label` vocabulary (line 109), which is
   `supports | contradicts | uncertain`: `unclear` and `insufficient` both become
   `uncertain`.
3. Add to `verdict.limitations` the sentence
   "Not enough peer-reviewed evidence was found. This assessment uses guidelines
   and public-health sources." That list already exists and the page renders it.
4. Store `web` itself on the claim item, `item["web_fallback"] = web`, so the
   citations with their quotes survive to the page and to replay.

The guard is inside `search_and_write` as well, so calling it unconditionally is
safe. It returns None whenever two or more studies took a side.

## What the page shows

A badge on the evidence card reading exactly `web["badge_text"]`:
"From guidelines and public-health sources, not the primary literature",
visually distinct from the `full_text` and `abstract_only` badges the resolver
work added today. Under it, the paragraph with its numbered citations, each
citation as publisher, title, and the quoted sentence with a link. Never a score.
The `confidence_note` goes in the same muted style as the other limitations.

## Cost

One call on `gpt-5.6-terra` with medium search context ran to roughly 1,200 input
and 300 output tokens in the documented example shape, about 0.006 dollars. The
team pot is 200 dollars, so this is not the thing that runs out. If it ever is,
swap `MODEL` to `gpt-5.6-luna`, ten times cheaper.

## Mock mode

With no `OPENAI_API_KEY` the function returns a canned alkaline-water result in
the same shape, `mode: "mock"`. Build the page against that, then flip the key.
