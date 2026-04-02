# Local RAG Bootstrap Progress

Date: 2026-04-01

## 1. Goal Snapshot

The agreed target is a hybrid system:

1. local knowledge is the preferred reusable memory
2. web research remains available and often runs early
3. useful web findings should be distilled back into local materials
4. online frontier models remain the reasoning and presentation layer

This repository started as a web research harness and is now being extended toward a hybrid local knowledge and web-assisted RAG workflow.

## 2. What Was Completed

### 2.1 Roadmap And Plan Convergence

Completed:

1. wrote the roadmap document:
   - `docs/2026-04-01-local-rag-roadmap.md`
2. absorbed external review feedback into the roadmap:
   - clarified that RAG improves knowledge access more than raw reasoning ability
   - added `derivation` cards
   - added problem-routing guidance
   - added bootstrap usage notes
3. wrote the first execution plan:
   - `docs/2026-04-01-local-rag-bootstrap-plan.md`

### 2.2 Local Knowledge Bootstrap

Completed:

1. created the local knowledge directory tree under `knowledge/`
2. created card templates for:
   - definition
   - method
   - theorem
   - derivation
   - comparison
   - decision record
3. added 2 seed cards:
   - `knowledge/cards/definitions/markov-chain-definition.md`
   - `knowledge/cards/derivations/stationary-distribution-derivation.md`
4. created the local index output directory:
   - `indexes/local/`

### 2.3 Local Indexing

Completed:

1. added `scripts/local_index.py`
2. current behavior:
   - walks `knowledge/`
   - ignores template files
   - parses frontmatter-like metadata
   - builds `indexes/local/index.json`
   - emits citation-friendly document records

Current indexed fields:

1. `doc_id`
2. `path`
3. `title`
4. `type`
5. `topic`
6. `tags`
7. `source_refs`
8. `updated_at`
9. `search_text`

### 2.4 Local Retrieval

Completed:

1. added `scripts/local_retrieve.py`
2. current behavior:
   - reads `indexes/local/index.json`
   - performs minimal lexical retrieval
   - scores matches across title, tags, topic, and body text
   - includes a small definition-query heuristic for `what is / define / definition`
   - returns sorted JSON results

Current retrieval output fields:

1. `doc_id`
2. `path`
3. `title`
4. `type`
5. `topic`
6. `score`
7. `matched_terms`

### 2.5 Tests Added

Completed:

1. `tests/test_knowledge_scaffold.py`
2. `tests/test_local_index.py`
3. `tests/test_local_retrieve.py`
4. `tests/test_local_rag_smoke.py`
5. `tests/test_hybrid_evidence_pack.py`
6. `tests/test_research_orchestrator.py`
7. `tests/test_answer_context.py`
8. `tests/test_distill_knowledge.py`
9. `tests/test_promote_draft.py`
10. `tests/test_roundtrip_accumulation.py`
11. `tests/test_domain_seed_cards.py`
12. `tests/test_render_answer_bundle.py`

Coverage currently includes:

1. scaffold existence
2. index generation
3. lexical retrieval behavior
4. end-to-end `seed cards -> index -> retrieval`
5. hybrid evidence pack merge behavior
6. route classification and orchestrated evidence-pack generation
7. structured answer-context generation with citations
8. deterministic knowledge distillation into Markdown drafts
9. draft promotion into local card candidates
10. round-trip accumulation from promoted candidate back into retrieval
11. domain-seed indexing and retrieval checks
12. model-facing answer-bundle rendering

### 2.6 Hybrid Evidence Pack Bootstrap

Completed:

1. added `scripts/build_evidence_pack.py`
2. current behavior:
   - runs local retrieval against the local JSON index
   - optionally loads a web evidence JSON bundle
   - normalizes both sources into one `items` list
   - preserves evidence origin as `local` or `web`
   - emits citation-friendly identifiers for both source families

Current evidence pack fields:

1. `query`
2. `local_count`
3. `web_count`
4. `items`

### 2.7 Routing And Orchestration Bootstrap

Completed:

1. added `scripts/orchestrate_research.py`
2. current behavior:
   - classifies queries into `local-led`, `web-led`, `mixed`, or `context-led`
   - supports explicit mode override
   - builds an evidence pack using the existing local index
   - optionally merges web evidence bundles when provided
   - can invoke a research harness script automatically when web evidence is needed
   - degrades gracefully when web evidence generation fails
   - returns route decision metadata alongside the evidence pack

Current route heuristics:

1. `latest / recent / current / sota` -> `web-led`
2. `what is / define / derivation / theorem / proof` -> `local-led`
3. `bug / error / script / code / failing test` -> `context-led`
4. everything else -> `mixed`

Current orchestration behavior:

1. `local-led` uses local evidence only
2. `mixed` can merge local retrieval with a provided web evidence bundle
3. `web-led` or `mixed` can auto-generate web evidence by invoking a harness script
4. harness failures are surfaced as warnings instead of crashing the orchestrator

### 2.8 Answer Context Bootstrap

Completed:

1. added `scripts/build_answer_context.py`
2. current behavior:
   - builds on top of the route-aware evidence pack
   - separates `direct_support`, `inference_notes`, and `uncertainty_notes`
   - emits citation objects with `evidence_id`, `origin`, `title`, and source location fields
   - keeps the output model-agnostic so different online models can consume the same protocol

Current answer-context fields:

1. `query`
2. `route`
3. `direct_support`
4. `inference_notes`
5. `uncertainty_notes`
6. `citations`

### 2.9 Knowledge Distillation Bootstrap

Completed:

1. added `scripts/distill_knowledge.py`
2. current behavior:
   - reads a structured answer-context JSON
   - emits a reusable Markdown draft
   - preserves direct support, inference notes, uncertainty notes, and citations
   - writes a deterministic draft format suitable for later human review or promotion

Current distillation output sections:

1. frontmatter metadata
2. `## Query`
3. `## Route`
4. `## Direct Support`
5. `## Inference Notes`
6. `## Uncertainty Notes`
7. `## Citations`

### 2.10 Draft Promotion Bootstrap

Completed:

1. added `scripts/promote_draft.py`
2. current behavior:
   - reads a distilled Markdown draft
   - infers a minimal card type from the original query
   - writes a structured candidate card into the local knowledge tree
   - preserves source references and direct-support content

Current promotion behavior:

1. `what is ...` and definition-style queries -> `cards/definitions/`
2. derivation-style queries -> `cards/derivations/`
3. fallback -> `cards/methods/`

### 2.11 Round-Trip Accumulation Verified

Completed:

1. verified that promoted candidates can be reindexed
2. verified that reindexed promoted candidates can be retrieved in later local search

This means the current bootstrap now supports a real local accumulation loop:

1. retrieve local knowledge
2. add optional web evidence
3. build answer context
4. distill into draft
5. promote into candidate card
6. reindex and retrieve the promoted candidate later

### 2.12 Review Fixes And Domain Seeds

Completed:

1. stabilized web evidence IDs using URL-derived hashes
2. fixed the `local-led` + explicit `--web-evidence` inconsistency so explicit web bundles are preserved
3. ignored `indexes/local/index.json` as a build artefact
4. added domain-relevant seed cards for:
   - QPE error bound derivation
   - LP duality theorem
   - quantization-aware training
5. made `inference_notes` and `uncertainty_notes` more evidence-sensitive when support is missing
6. expanded promotion routing to theorem / comparison / decision-record candidates

This means the bootstrap is no longer only validated on Markov-chain placeholders; it now has first-pass domain content closer to the target use cases.

### 2.13 Quality Upgrades On Top Of The Closed Loop

Completed:

1. answer-context notes now react to evidence scarcity instead of always using the same fixed phrasing
2. draft promotion now covers:
   - definition
   - derivation
   - theorem
   - comparison
   - decision record
   - fallback method

This means the system is no longer just structurally complete; it now begins to reflect evidence quality in its intermediate outputs and supports a broader set of reusable card candidates.

### 2.14 Model-Facing Answer Bundle Rendering

Completed:

1. added `scripts/render_answer_bundle.py`
2. current behavior:
   - reads structured answer-context JSON
   - renders a deterministic prompt bundle with:
     - `system_prompt`
     - `user_prompt`
     - `metadata`
     - `citations`
   - supports stdin input for pipeline composition

This provides the first direct bridge from the structured internal pipeline to an online model workflow such as Codex or Copilot.

## 3. Verification Results

Passed:

```bash
python3 -m unittest tests.test_knowledge_scaffold tests.test_local_index tests.test_local_retrieve tests.test_local_rag_smoke tests.test_hybrid_evidence_pack tests.test_research_orchestrator tests.test_answer_context tests.test_distill_knowledge tests.test_promote_draft tests.test_roundtrip_accumulation tests.test_domain_seed_cards tests.test_render_answer_bundle -v
```

Passed:

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile \
  scripts/local_index.py \
  scripts/local_retrieve.py \
  scripts/build_evidence_pack.py \
  scripts/orchestrate_research.py \
  scripts/build_answer_context.py \
  scripts/distill_knowledge.py \
  scripts/promote_draft.py \
  scripts/render_answer_bundle.py \
  tests/test_knowledge_scaffold.py \
  tests/test_local_index.py \
  tests/test_local_retrieve.py \
  tests/test_local_rag_smoke.py \
  tests/test_hybrid_evidence_pack.py \
  tests/test_research_orchestrator.py \
  tests/test_answer_context.py \
  tests/test_distill_knowledge.py \
  tests/test_promote_draft.py \
  tests/test_roundtrip_accumulation.py \
  tests/test_domain_seed_cards.py \
  tests/test_render_answer_bundle.py \
  tests/fake_research_harness.py
```

## 4. Current Boundary

The repository now has a working local-to-web-to-local bootstrap loop, but it is still intentionally minimal.

What it can do now:

1. store local cards
2. build a local JSON index
3. retrieve local cards lexically
4. route questions across local-led, web-led, and mixed modes
5. build route-aware evidence packs
6. generate structured answer contexts with citations
7. distill answer contexts into reusable Markdown drafts
8. promote distilled drafts into local card candidates

What it does not do yet:

1. vector retrieval
2. hybrid ranking between lexical and vector retrieval
3. richer routing beyond keyword heuristics
4. richer promotion logic beyond keyword-based card typing
5. richer model-specific answer rendering or multi-model prompt styles

## 5. Immediate Next Step

The next implementation slice should be:

`improve retrieval quality and prompt quality beyond the current deterministic baseline`

That means:

1. improve scoring and ranking
2. improve prompt rendering for different downstream model styles
3. keep citations and uncertainty visible
4. preserve the current testable deterministic core

This is the natural bridge from the current bootstrap toward a full hybrid workflow.
