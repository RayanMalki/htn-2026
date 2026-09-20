# MedBot evidence retrieval

Medical claims need matching research, not just similar words. Retrieval relevance,
study limitations and the direction of a finding are separate. No numeric truth
score, paper-count vote or forced balance between opposing conclusions is used.

## Actual architecture

1. `backend/app/openai_models.py:OpenAIModels.analyze` transcribes speech, then
   extracts claims with validated transcript segment references. The existing
   extraction call now also supplies nullable intervention, formulation, population,
   outcome, comparator, dose and timeframe. Unspoken details remain null. Gemini
   and Backboard have the same additive contract; old saved claims remain valid.
2. `backend/app/literature.py:claim_terms` retains a broad intervention + outcome
   query, a separate qualifier query and a neutral model search phrase. Query
   operators are built by code, not accepted from the model. `_europe_pmc` searches
   title, selected study types and title/abstract in parallel using default
   relevance order, not citation count. Up to 15 deduplicated records are retained.
   Known retractions are excluded. Up to five available full texts are fetched.
3. `full_text_priority` is explicitly a **lexical applicability proxy**: core word
   matches, qualifier word matches, then study type and discovery tier. It cannot
   understand all synonyms or distinguish every animal/human mismatch. The later
   assessment checks these details. This heuristic is not formal medical grading.
4. `chunks` turns heterogeneous XML paragraphs and abstracts into traceable passages
   with stable hashes, paper IDs, URLs, section labels, exact character offsets and
   access metadata. Failed/unavailable full text stays labeled abstract-only.
   Optional MedlinePlus health summaries remain labeled summaries, not studies.
   A 24-hour local paper cache reduces repeat downloads.
5. `backend/app/search.py:ElasticSearch.index` deduplicates passages and uses `_mget`
   to avoid redundant indexing. The existing `semantic_text` field uses ELSER.
   Retraction/status metadata changes are refreshed. Index setup is a separate
   existing operation; this change performs no migration or endpoint provisioning.
6. `query` combines BM25 (`text`, `title^1.5`) and ELSER semantic retrieval with
   reciprocal rank fusion (window 50, constant 60). **Both branches restrict results
   to this claim's discovered candidate IDs and exclude known retractions.**
   Production does not search the entire historical corpus for each claim.
7. Optional `rerank` sends the first 20 eligible, distinct passages (title + text)
   to an existing Elasticsearch inference endpoint. It validates a complete index
   permutation and finite scores, then sorts before `diversify`: at most six
   passages, at most two per paper. Default remains disabled. Disabled/failure paths
   preserve the original RRF shortlist and existing diversification behavior.
8. `backend/app/models.py:GeminiModels.judge` is the shared judgment implementation
   inherited by OpenAI and Backboard. One existing call assesses every selected
   paper: direct/partial/mismatch/unknown applicability, independent finding,
   explanation, quote IDs, limitations and identifiable overlap with other supplied
   papers. Access labels and verbatim citations are derived by code. Health-summary
   context is not a primary research result. Missing evidence and nonsignificance
   must not be represented as proof of no effect.
9. `schemas.py:validate_verdict` rejects unknown/cross-paper/inexact/retracted
   quotations, invalid access labels and ungrounded conclusive findings. Exact text
   validation does not prove that the model interpreted a study correctly.
   Existing `supports` / `contradicts` / `uncertain` values remain unchanged.
10. `pipeline.py:run_case` keeps existing research and overall deadlines; stores
    retrieval mode, current-candidate scope and reranking diagnostics in provenance.
    Technical failures remain incomplete research, not scientific uncertainty.
    GPTZero stays separate and is never an input to medical judgment. The frontend
    adds optional match/details inside existing expandable evidence cards only.

No follow-up retrieval loop was added: preserving the current deadline and recovery
contract is safer than adding orchestration in this change. Review overlap detection
is limited to what is identifiable in supplied passages, not comprehensive deduplication
of trial populations. Retraction filtering only excludes **known** retractions.

## Queries and configuration

Redacted outline of both RRF branches (full payload: `ElasticSearch.query`):

```json
{
  "retriever": {"rrf": {
    "retrievers": [
      {"standard": {"query": {"bool": {
        "must": {"multi_match": {"query": "vitamin C common cold", "fields": ["text", "title^1.5"]}},
        "filter": [{"ids": {"values": ["<discovered-passage-id>"]}}, {"term": {"known_retracted": false}}]
      }}}},
      {"standard": {"query": {"bool": {
        "must": {"semantic": {"field": "semantic", "query": "vitamin C common cold"}},
        "filter": [{"ids": {"values": ["<discovered-passage-id>"]}}, {"term": {"known_retracted": false}}]
      }}}}
    ], "rank_window_size": 50, "rank_constant": 60
  }}
}
```

Existing server-side variables: `ELASTICSEARCH_URL`, `ELASTICSEARCH_API_KEY`,
`ELASTIC_INDEX`, `ELASTIC_SEMANTIC`, `ELASTIC_INFERENCE_ID`. Never expose the key to
the browser. ELSER is sparse semantic retrieval; it is **not Jina dense retrieval**.

New optional settings (also in Compose and `.env.example`):

```dotenv
ELASTIC_RERANK_ENABLED=false
ELASTIC_RERANK_INFERENCE_ID=
ELASTIC_RERANK_TIMEOUT_SECONDS=3
```

Timeout must be greater than zero and no more than three seconds, including network
wait, within the enclosing research deadline. No inference retries are made. Rerank
uses `POST /_inference/rerank/<existing-id>` with `query` and `input` strings. The
service account needs inference permission, endpoint capacity and an available model.
Reading endpoint metadata alone does not establish usable inference.

On 2026-09-20 a read-only inspection found Elasticsearch **9.5.4**, existing ELSER
endpoints and several rerank endpoints. A bounded live attempt against existing
`.rerank-v1-elasticsearch` timed out on all three benchmark queries. **Do not enable
reranking for the demo based on this test.** No endpoints/resources were created.
Availability and billing are deployment-specific.

Fallback diagnostics include `disabled`, `not_needed`, `applied`, or `fallback` with
`endpoint_not_configured`, `timeout`, `http_<status>`, or
`unavailable_or_invalid_response`, plus elapsed seconds when attempted. Hybrid query
HTTP failures covered by the existing fallback use BM25 and record `keyword_only`.
Failure of both search modes remains a technical error. Overall cancellation propagates.

References: [Europe PMC REST documentation](https://europepmc.org/RestfulWebService)
(default relevance without sort), [Elastic rerank API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-inference-rerank).

## Measured comparison and limits

Base commit `2201bba`, uncommitted working-tree changes, 2026-09-20. The live ranking
benchmark freezes up to 100 existing indexed candidates per query, then compares
baseline BM25 + ELSER + RRF with the optional reranking path on the same pool.
Pool construction is read-only and deliberately separate from production discovery.
No index writes, new cases, videos or deployments occur. Baseline runs first; the
index/model may be warm. This is not a controlled cold-start latency study.

| Claim | Direct passages, baseline → attempted rerank | Unique papers | Ranking seconds, baseline → attempted rerank |
|---|---:|---:|---:|
| Regular vitamin C / cold prevention / adults | 1/6 → 1/6 | 3 → 3 | 0.1463 → 3.1066 |
| Blue light versus brightness / sleep onset / adults | 0/6 → 0/6 | 6 → 6 | 0.1448 → 3.1131 |
| Melatonin / sleep onset / adults | 0/6 → 0/6 | 6 → 6 | 0.1739 → 3.1671 |

All optional rerank requests timed out and returned identical passage IDs, so there
is **no demonstrated relevance uplift**. Local cancellation took 3.002–3.048 seconds;
event-loop scheduling can slightly exceed the configured limit. Each variant/query
passed six sampled catalog-quotation checks (36/36 total); these are structural
verbatim checks, **not model-generated citation accuracy or clinical correctness**.

[Review labels and measured results](retrieval-benchmark-review.json) record each
selected passage ID, source link and reason. Codex read and labeled all 18 baseline
passages individually; these are editorial labels, **not independent human/clinician
validation**. Direct relevance requires the requested intervention, outcome,
population and comparator in the passage. Partial matches are not counted as direct.
Examples of misses include cold duration instead of incidence, mouse evidence,
children, endogenous melatonin instead of supplementation, and background passages
without a brightness-controlled result. Independent manual review remains required.

This narrow comparison does not measure the new Europe PMC discovery/full-text
selection against the old citation-sorted discovery. That requires a frozen source
snapshot and independent labels; current results must not be marketed as an end-to-end
retrieval accuracy improvement. Three claims are too few for generalization.

Separate live smoke checks used isolated temporary paper caches, with no app case:
Europe PMC discovery returned 257 passages from 15 papers in 1.495–2.371 seconds,
zero cache hits and no provider failures across four attempts. One final private
OpenAI judgment completed in 4.234 seconds and passed exact citation validation.
Earlier checks exposed an incomplete per-paper assessment and cross-paper reasoning;
the schema now restricts paper/quote IDs and assessment count, and the prompt groups
each paper's evidence separately. The final response correctly separated duration-only
excerpts as `does_not_address`, but some wording still generalized beyond the excerpts
and an overlap reference needs human review. **This is a structural/live smoke pass,
not clinical acceptance.** No generated explanation was published. The optional
Gemini/Backboard changes were fixture-tested only.

Verification: 187 backend tests passed, 10 media tests skipped because FFmpeg/FFprobe
(and required media runtime tools) were unavailable on the host PATH. Provider/schema
regressions were rerun after the final schema restriction. TypeScript/Vite production
build passed; 56 existing desktop/mobile browser fixtures and two new applicability
fixtures passed. Ruff and whitespace checks passed. Browser API responses were
fixtures; live Elastic/Europe PMC/OpenAI checks above are separate. No deployment,
container restart, new video acceptance run, commit or push was performed.

## Reproduce a short demo

1. Use an existing configured Elastic index and confirm endpoint metadata and
   inference permissions with its administrator. Do not run setup/provision commands
   merely to test this change.
2. Run the read-only comparison from the repository root:
   `PYTHONPATH=backend .venv/bin/python scripts/benchmark_retrieval.py --endpoint <existing-rerank-id>`.
   This makes potentially billed inference calls. Reports with full passage text go
   to ignored `artifacts/retrieval-benchmark.json`; no app case or video is created.
3. Review each returned passage against the claim and document labels before counting
   relevance. Compare final passage IDs and unique papers; inspect fallback status.
   Do not reuse old labels when passage IDs change.
4. In a locally approved app run, open a saved result, expand the existing assessment
   and evidence cards. New results display claim details, match, finding and reported
   limitations. Old results omit unavailable fields. Show original source links and
   access labels. Keep GPTZero authorship separate from medical evidence.

## Sponsor feature inventory

| Capability | Status |
|---|---|
| Speech → structured medical claims → real literature/XML passages | Implemented |
| BM25 + ELSER sparse semantics + RRF | Implemented, with visible keyword fallback |
| Candidate/retraction filters, metadata, caching, exact quotations | Implemented |
| Claim details and per-paper applicability/limitations | Implemented; model interpretation needs review |
| Elasticsearch-native existing-endpoint rerank | Optional, disabled; live attempts timed out |
| Jina dense vectors, dense index migration | Not implemented |
| Agent Builder, Workflows, ES\|QL | Not implemented |
| Formal GRADE or numerical medical credibility scoring | Not implemented |
| Targeted second retrieval pass | Not implemented |
| Comprehensive review/trial overlap detection | Not implemented |
