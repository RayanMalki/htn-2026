# Experimental web-search fallback: integration proposal

This is not an installed app feature or a copy-and-paste patch. The implementation
in `websearch_fallback.py` is a standalone prototype. The app uses Europe PMC and
MedlinePlus with exact stored passages and citation validation.

## Why the previous wiring example was incorrect

`Passage` has no `stance` field. A claim verdict cannot supply the stance of every
paper or passage. The prototype's study-count guard therefore cannot be applied to
the app's retrieved passages without a separately designed and validated assessment.
Its no-key response is a canned alkaline-water fixture, regardless of the submitted
claim. That fixture must never enter a live medical judgment.

## Requirements before integration

1. Define an explicit evidence-insufficiency trigger using validated research state.
   A network failure remains incomplete research; it must not become uncertainty.
2. Fetch and retain original source material from approved guideline/public-health
   publishers. Store provenance, access type, retrieval time and exact text offsets.
   Generated summaries are not original passages and cannot validate their own quotes.
3. Extend the provider schema and UI deliberately. Keep research papers, health
   summaries and any generated synthesis distinguishable; never count them together.
4. Run source quotations through the existing citation validator. Preserve the claim's
   verdict and limitations; never replace them with an unvalidated fallback stance.
5. Add bounded async execution, cancellation, caching and provider-failure handling.
   No credentials means skipped/unavailable in live mode, not a fabricated result.
6. Test the guard, provenance, quote rejection, unavailable providers, retries and
   replay. Only then add the feature to the worker and report live acceptance.

The prototype's model names and cost estimates are historical and have not been
validated for deployment. Verify provider availability and pricing before enabling it.
This work is outside the staged-video completion scope.
