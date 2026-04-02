# Local Knowledge RAG Roadmap

Date: 2026-04-01

## 1. Goal Alignment

This project is not trying to replace online frontier models such as Codex or VS Code Copilot.  
The intended system is:

`local knowledge base + local retrieval layer + online model reasoning layer + optional web research`

The agreed target is:

1. Keep local knowledge as the preferred reusable memory.
2. Allow and often default to web search when local knowledge is missing, stale, or insufficient.
3. After web research, distill the useful findings back into reusable local materials.
4. Use the online model mainly for reasoning, explanation, synthesis, and structured answer generation.
5. Make answers evidence-linked rather than purely model-memory-driven.

In short:

- `local knowledge` is the long-term memory.
- `web research` is the freshness and gap-filling mechanism.
- `online model` is the reasoning and presentation engine.

This means the target is **not** a pure offline local RAG.  
It is a **hybrid local-first research and knowledge accumulation system**.

## 2. What The Current Repo Already Is

Current implementation status in this repository:

1. A lightweight search-and-fetch harness exists.
2. It can:
   - generate search queries
   - call SearXNG
   - fetch page content
   - cache fetched results
   - normalize evidence into JSON
   - validate evidence against a schema
3. It is already useful as a web evidence collection layer.

So the current repo is a good starting point, but it is still closer to:

`web research harness`

than to:

`local knowledge RAG system`

The missing parts are mainly:

1. local knowledge storage
2. local indexing and retrieval
3. reusable knowledge-card format
4. evidence citation protocol for answers
5. distillation flow from web findings into local knowledge

## 3. Product Intent

The system should support two complementary workflows.

### 3.1 Workflow A: Answer A Question

When a user asks a question:

1. search local knowledge first
2. if local knowledge is weak, outdated, or incomplete, run web research
3. merge local and external evidence
4. send structured context to the online model
5. produce an answer with explicit evidence references

### 3.2 Workflow B: Grow The Knowledge Base

After web research:

1. identify high-value findings
2. convert them into reusable local materials
3. store them in a stable knowledge format
4. reindex local retrieval

This second workflow matters just as much as question answering.  
Without it, the system becomes a repeated search tool instead of a compounding knowledge system.

## 4. Core Design Principles

### 4.1 Hybrid By Design

The system should not force a strict offline-first behavior.  
Instead, it should support:

1. `local-first` when reliable local material exists
2. `web-assisted` when local material is incomplete
3. `web-led` for fast-moving or unfamiliar topics

For many real questions, especially tooling and implementation questions, it is expected that web search will run early.

### 4.2 Local Knowledge Must Be Reusable

Raw search results are not enough.  
The project should accumulate:

1. topic notes
2. definition cards
3. method cards
4. comparison notes
5. decision records
6. verified evidence summaries

### 4.3 Evidence Over Memory

The online model should be guided by retrieved evidence, not trusted as the sole source of truth.

### 4.4 Distillation Is A First-Class Feature

The system should not just search and answer.  
It should also turn good research outputs into durable local knowledge.

### 4.5 RAG Improves Knowledge Access, Not Raw Reasoning Ability

This project should explicitly distinguish two different bottlenecks:

1. `knowledge access` problems:
   - missing private context
   - outdated public information
   - weak source grounding
2. `reasoning` problems:
   - weak derivation quality
   - incorrect symbolic manipulation
   - shallow multi-step inference

Hybrid local RAG is primarily meant to improve the first category.  
It can indirectly improve reasoning by feeding the model better inputs, but it does not by itself guarantee strong derivation quality.

For first-principles-heavy domains, the system should therefore combine:

1. stronger evidence retrieval
2. better answer protocol
3. structured derivation materials
4. when needed, stronger reasoning models or explicit solving workflows

## 5. Target Architecture

The recommended architecture is:

```text
User Question
  ->
Orchestrator
  ->
  [A] Local Knowledge Retrieval
  [B] Web Research Harness
  ->
Evidence Merger + Ranking
  ->
Prompt/Context Builder
  ->
Online Model (Codex / Copilot / other)
  ->
Answer + Evidence References
  ->
Knowledge Distillation Pipeline
  ->
Local Knowledge Base Update
```

## 6. Major System Components

### 6.1 Web Research Layer

This is the part you already started.

Responsibilities:

1. query generation
2. web search via SearXNG
3. page fetch and extraction
4. evidence normalization
5. caching
6. source scoring

This should remain in the system, not be replaced.

### 6.2 Local Knowledge Layer

This needs to be added.

Recommended content types:

1. `cards/definitions/`
2. `cards/methods/`
3. `cards/theorems/`
4. `cards/derivations/`
5. `cards/comparisons/`
6. `cards/decision_records/`
7. `notes/raw_distillations/`
8. `sources/` for imported local files or curated references

Recommended file format:

- Markdown with YAML frontmatter

Recommended metadata:

1. `id`
2. `title`
3. `type`
4. `topic`
5. `tags`
6. `source_refs`
7. `confidence`
8. `updated_at`
9. `origin`

For derivation-heavy domains, `derivation` cards should preserve ordered steps, prerequisite concepts, and source-level support for each important claim.

### 6.3 Local Retrieval Layer

This is the actual local RAG part.

Responsibilities:

1. index local cards and notes
2. support hybrid retrieval:
   - lexical retrieval
   - vector retrieval
   - metadata filtering
3. return stable chunk identifiers and source references

Important:

For this repo's target, hybrid retrieval should be the default, not optional.  
Keyword and exact-name matching matter a lot for technical terms, theorem names, package names, and implementation details.

### 6.4 Evidence Merger

This layer combines:

1. local evidence
2. web evidence

And decides:

1. which evidence is strongest
2. whether local evidence is sufficient
3. whether web evidence should override stale local evidence
4. whether the model should answer, hedge, or say evidence is insufficient

### 6.4.1 Problem Routing

Not every question should follow exactly the same path.

Recommended first-pass routing:

1. `latest / fast-moving / comparison` questions:
   - default to `web-led + local support`
2. `definition / theorem / derivation` questions:
   - default to `local-led + optional web support`
3. `project-specific code or repo questions`:
   - default to direct code/context inspection, with RAG only when background knowledge helps

Example categories:

1. `A: latest methods`
   - example: "What are the latest QPE improvements?"
   - path: web-led
2. `B: first-principles explanation or derivation`
   - example: "How do we derive this hedge formula?"
   - path: local-led, plus derivation cards and stronger reasoning prompts
3. `C: implementation or debugging`
   - example: "Why is this strategy script failing?"
   - path: direct repo inspection first

### 6.5 Prompt And Answer Protocol

The online model should receive structured context, not arbitrary text dumps.

Recommended answer protocol:

1. question framing
2. local evidence used
3. web evidence used
4. what is directly supported
5. what is inferred
6. uncertainty and gaps
7. final answer

This is important because otherwise the system cannot tell whether the model is actually using retrieved evidence.

For derivation-style answers, the protocol should additionally separate:

1. prerequisite definitions
2. derivation steps
3. source-backed steps
4. model-inferred steps
5. unresolved gaps

### 6.6 Knowledge Distillation Layer

This is the most important missing capability after local retrieval.

After answering or researching:

1. select valuable evidence
2. summarize it into reusable notes or cards
3. attach source references
4. mark confidence
5. save locally
6. trigger reindex

This is how the system compounds over time.

## 7. Recommended Repository Evolution

Recommended target structure:

```text
optimizer/
  docs/
  knowledge/
    cards/
      definitions/
      methods/
      theorems/
      derivations/
      comparisons/
      decision_records/
    notes/
      raw_distillations/
    sources/
  indexes/
    local/
  outputs/
    evidence/
    answers/
    distillations/
  schemas/
  scripts/
    research_harness.py
    local_index.py
    local_retrieve.py
    answer_builder.py
    distill_knowledge.py
    reindex_local.py
```

## 8. Roadmap

### Phase 0: Stabilize The Existing Web Research Harness

Goal:

Make the current web evidence pipeline reliable enough to serve as one half of the hybrid system.

Deliverables:

1. keep the existing `research_harness.py`
2. cleanly separate:
   - search
   - fetch
   - extraction
   - scoring
   - serialization
3. make output directories explicit
4. improve evidence fields so they are citation-friendly

Suggested upgrades:

1. add stable `evidence_id`
2. add `source_host`
3. add source location fields when possible
4. distinguish:
   - snippet-only evidence
   - fetched-page evidence
   - cached evidence
5. record which query produced each result

Success condition:

The harness can produce repeatable evidence bundles that are useful even before local RAG exists.

### Phase 1: Add The Local Knowledge Base

Goal:

Create a durable place for reusable knowledge.

Deliverables:

1. `knowledge/` directory
2. Markdown card templates
3. first batch of seed materials

Priority seed material:

1. repeated web research conclusions
2. tool comparison summaries
3. evaluation heuristics
4. frequently reused definitions and implementation notes
5. derivation-oriented seed cards for high-value domains

Success condition:

The repository contains enough local material that a future retriever has something meaningful to search.

### Phase 2: Build Local Retrieval

Goal:

Make local knowledge searchable as evidence.

Deliverables:

1. local ingestion script
2. chunking strategy
3. metadata schema for chunks
4. lexical index
5. vector index if needed
6. retrieval API or CLI

Recommended retrieval order:

1. metadata filters
2. lexical retrieval
3. vector retrieval
4. reranking

Success condition:

A local question can return top local knowledge chunks with IDs and source references.

### Phase 3: Build Hybrid Retrieval Orchestration

Goal:

Decide when to use local only, when to add web, and how to merge them.

Deliverables:

1. retrieval decision policy
2. evidence merge strategy
3. ranking and dedup logic
4. freshness rules

Suggested policy:

1. always run local retrieval first
2. run web research when:
   - local recall is weak
   - local evidence is stale
   - topic is fast-moving
   - user explicitly asks for latest information
3. allow “local + web” as the default mode for many technical research tasks

Success condition:

The system can produce a combined evidence pack from both local and web sources.

Additional success condition:

The system can classify a question into at least one of:

1. web-led
2. local-led
3. direct code/context-led

### Phase 4: Build The Prompt And Answer Layer

Goal:

Use the hybrid evidence pack to drive the online model.

Deliverables:

1. prompt builder
2. evidence-to-context formatter
3. answer schema
4. refusal / hedge rules when evidence is insufficient

Required output properties:

1. every important claim links to evidence IDs
2. direct support and inference are separated
3. insufficient evidence is explicitly stated

Success condition:

The model answer is visibly grounded in retrieved evidence rather than a generic freeform reply.

### Phase 5: Build Distillation Back Into Local Knowledge

Goal:

Turn web research into reusable local memory.

Deliverables:

1. distillation script or workflow
2. card generation template
3. review workflow for promoted local knowledge
4. reindex trigger

Recommended promotion rule:

Only promote web findings into stable cards when they are:

1. reused
2. high-confidence
3. generalizable
4. worth referencing again

Success condition:

Repeated web research gradually increases the quality and coverage of local knowledge.

## 9. What Should Not Be Done Yet

The following should stay out of the first implementation wave:

1. deep IDE plugin integration
2. heavy multi-agent orchestration
3. full autonomous browsing loops
4. complex graph database infrastructure
5. automatic code execution by the online model

These can come later if the basic hybrid workflow proves useful.

## 10. Key Risks

### 10.1 Confusing Search With Knowledge

If the system only searches and summarizes, it never compounds.

### 10.2 Weak Citation Protocol

If answers do not carry evidence IDs and source refs, the system cannot prove grounding.

### 10.3 No Distillation Discipline

If every search result gets saved, the local knowledge base becomes cluttered and low quality.

### 10.4 Staleness

Local knowledge can become outdated.  
The hybrid design must preserve the ability to refresh via web evidence.

### 10.5 Over-Automation Too Early

Trying to jump directly into IDE plugins or full automation may slow down the core system design.

## 11. Immediate Next Step

The most useful next implementation step is:

`turn the current web evidence harness into a clean subsystem, then add a minimal local knowledge directory and retrieval layer beside it`

Concretely, that means:

1. define the local knowledge file format
2. create the `knowledge/` tree
3. add a local indexing script
4. add a local retrieval script
5. keep web research as a parallel subsystem

Before scaling implementation too far, run a small validation loop:

1. create 5-10 seed knowledge cards
2. test whether injecting them improves answer quality on representative questions
3. only then expand indexing and orchestration depth

## 12. Final Agreement Summary

This document confirms the shared target:

1. local knowledge should be preferred when available
2. web search should still be available and in many cases run early
3. web findings should be distilled into reusable local materials
4. the system should evolve from a web research harness into a hybrid local knowledge and research engine

This is the roadmap the current repository should follow.

## 13. Bootstrap Usage

Current bootstrap workflow:

1. add or edit Markdown cards under `knowledge/cards/`
2. build the local index:
   - `python3 scripts/local_index.py --output indexes/local/index.json`
3. run lexical local retrieval:
   - `python3 scripts/local_retrieve.py "what is a markov chain" --index indexes/local/index.json --limit 5`
4. run minimal route-aware orchestration:
   - `python3 scripts/orchestrate_research.py "what is a markov chain" --index indexes/local/index.json`
5. merge local retrieval with an existing web evidence bundle:
   - `python3 scripts/orchestrate_research.py "markov chain overview" --mode mixed --index indexes/local/index.json --web-evidence path/to/evidence.json`
6. build a model-agnostic answer context with citations:
   - `python3 scripts/build_answer_context.py "what is a markov chain" --mode mixed --index indexes/local/index.json --research-script tests/fake_research_harness.py`
7. distill an answer context into a reusable Markdown draft:
   - `python3 scripts/distill_knowledge.py --answer-context path/to/answer-context.json --output knowledge/notes/raw_distillations/example-distilled-note.md`
8. promote a distilled draft into a local card candidate:
   - `python3 scripts/promote_draft.py --draft knowledge/notes/raw_distillations/example-distilled-note.md --knowledge-root knowledge`
9. rebuild the index so promoted candidates re-enter the local retrieval loop:
   - `python3 scripts/local_index.py --knowledge-root knowledge --output indexes/local/index.json`

Current bootstrap now includes seed material in multiple target directions:

1. stochastic processes
2. quantum computing
3. operations research
4. model quantization

This bootstrap layer is intentionally minimal:

1. local cards and templates exist
2. a JSON index can be built from local cards
3. lexical retrieval can return citation-friendly local matches
4. a minimal orchestrator can classify queries and build route-aware evidence packs
5. a structured answer context can separate direct support, inference notes, uncertainty notes, and citations
6. a deterministic distillation step can turn answer contexts into reusable Markdown drafts
7. distilled drafts can be promoted into candidate cards inside the local knowledge tree
8. promoted candidates can be reindexed and retrieved later, closing the local accumulation loop
9. answer-context notes can react to missing evidence, not just emit fixed scaffolding
10. promoted drafts can now map into definition, derivation, theorem, comparison, decision-record, and fallback method candidates
11. answer-context JSON can be rendered into a model-facing prompt bundle for downstream online models

Vector retrieval, hybrid ranking, and orchestration with the web harness come next.
