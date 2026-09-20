export type Passage = {
  id: string; paper_id: string; title: string; source_url: string; published: string | null;
  study_types: string[]; access_type: 'full_text' | 'abstract_only' | 'summary';
  provider?: 'europe_pmc' | 'medlineplus'; source_kind?: string; section: string;
  text: string; context: string; start: number; end: number;
};
export type Claim = { id: string; text: string; start: number; end: number; search_terms: string[];
  details?: Partial<Record<'intervention' | 'formulation' | 'population' | 'outcome' | 'comparator' | 'dose' | 'timeframe', string | null>> | null };
export type PaperAssessment = { paper_id: string; applicability: 'direct' | 'partial' | 'mismatch' | 'unknown';
  finding: 'supports' | 'contradicts' | 'mixed' | 'does_not_address'; explanation: string;
  quote_ids: string[]; citations: { passage_id: string; quote: string }[]; access_types: string[];
  limitations: string[]; possible_overlap_with: string[] };
export type ClaimResult = {
  claim: Claim; status: string; evidence?: Passage[]; error?: string; timings?: Record<string, number>;
  discovered_sources?: { title: string; source_url: string; access_type: string }[];
  provenance?: { retrieval_mode?: string; papers_found?: number; sources_found?: number; cache_hits?: number;
    query?: string; provider: string; searched_at?: string;
    provider_failures?: { provider: string; error: string }[];
    providers?: { provider: string; query: string; searched_at: string }[] };
  verdict?: { label: 'supports' | 'contradicts' | 'uncertain'; explanation: string;
    citations: { passage_id: string; quote: string }[]; limitations: string[]; paper_assessments?: PaperAssessment[] };
};
export type Scan = {
  basis: 'verbatim' | 'filler_removed'; characters: number; predicted_class: string | null;
  document_classification: string | null; ai_probability: number | null;
  human_probability: number | null; mixed_probability: number | null;
  confidence_category: string | null; summary: string | null; flagged_share: number | null;
  subclass: { kind: 'ai' | 'mixed'; predicted_class: string; confidence_category: string | null;
    probabilities: Record<string, number> } | null;
  sentences: { text: string; generated_prob: number }[];
  paragraphs: { index: number; sentences: number; generated_prob: number }[];
};
export type Detection = {
  provider: string; status: 'scored' | 'skipped' | 'unavailable'; scanned_at: string;
  detector_version: string | null; prepared_transcript: boolean; script_threshold: number;
  fillers_removed: number; filler_ratio: number; removed_examples: string[];
  verbatim: Scan | null; cleaned: Scan | null; note: string | null;
};
export type Case = {
  id: string; source_url: string; status: string; created_at: string; updated_at: string;
  started_at: string | null; finished_at: string | null; sequence: number;
  error: { code: string; message: string } | null;
  result: { schema_version: number; model_mode: 'mock' | 'live'; input_mode?: string;
    video?: { status: 'pending' | 'rendering' | 'ready' | 'failed'; error?: string;
      duration_seconds?: number; captions_url?: string; url?: string; sources_url?: string;
      stage?: string; selected_claim?: string; selected_claim_id?: string; caption_timing?: string; error_code?: string };
    submitted_at?: string;
    timings?: Record<string, number>; limitations?: string[]; outcome?: string;
    analysis?: { transcript: { start: number; end: number; text: string }[]; claims: Claim[]; omitted_claims: number };
    detection?: Detection;
    claims?: Record<string, ClaimResult> };
};
export type Metrics = { total_cases: number; finished: number; complete: number; failed: number;
  queued: number; p50_seconds: number | null; p95_seconds: number | null; stages: Record<string, number> };
