# Local RAG Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first usable local knowledge scaffold beside the existing web research harness so the repo can start evolving into a hybrid local knowledge and web-assisted RAG system.

**Architecture:** Keep the current `research_harness.py` as the web evidence subsystem. Add a parallel local knowledge subsystem with a stable on-disk knowledge tree, Markdown card templates, a local indexing script, and a minimal local retrieval CLI that returns citation-friendly results. Start with lexical retrieval and metadata parsing before adding vector retrieval.

**Tech Stack:** Python standard library, Markdown/YAML-style frontmatter parsing, JSON, unittest/pytest-compatible test execution

---

## File Structure

- Create: `indexes/local/.gitkeep`
- Create: `knowledge/cards/definitions/.gitkeep`
- Create: `knowledge/cards/methods/.gitkeep`
- Create: `knowledge/cards/theorems/.gitkeep`
- Create: `knowledge/cards/derivations/.gitkeep`
- Create: `knowledge/cards/comparisons/.gitkeep`
- Create: `knowledge/cards/decision_records/.gitkeep`
- Create: `knowledge/notes/raw_distillations/.gitkeep`
- Create: `knowledge/sources/.gitkeep`
- Create: `knowledge/cards/definitions/markov-chain-definition.md`
- Create: `knowledge/cards/derivations/stationary-distribution-derivation.md`
- Create: `knowledge/templates/definition-card.md`
- Create: `knowledge/templates/method-card.md`
- Create: `knowledge/templates/theorem-card.md`
- Create: `knowledge/templates/derivation-card.md`
- Create: `knowledge/templates/comparison-card.md`
- Create: `knowledge/templates/decision-record.md`
- Create: `scripts/local_index.py`
- Create: `scripts/local_retrieve.py`
- Create: `tests/__init__.py`
- Create: `tests/test_knowledge_scaffold.py`
- Create: `tests/test_local_index.py`
- Create: `tests/test_local_retrieve.py`
- Create: `tests/test_local_rag_smoke.py`
- Modify: `requirements.txt`
- Modify: `docs/2026-04-01-local-rag-roadmap.md`

### Task 1: Add The Knowledge Directory And Card Templates

**Files:**
- Create: `knowledge/...`
- Test: `tests/test_knowledge_scaffold.py`

- [ ] **Step 1: Write the failing test for template discovery**

Test behavior:
- the expected knowledge directories exist
- the expected template files exist
- the seed cards exist

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_knowledge_scaffold -v`
Expected: FAIL because the directories and templates do not exist yet

- [ ] **Step 3: Create the knowledge tree and template files**

Templates should include frontmatter-like fields:
- `id`
- `title`
- `type`
- `topic`
- `tags`
- `source_refs`
- `confidence`
- `updated_at`
- `origin`

`derivation-card.md` should also include:
- `prerequisites`
- `steps`
- `proof support / source support`

Seed cards should provide at least one realistic retrieval target.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_knowledge_scaffold -v`
Expected: PASS

### Task 2: Add A Minimal Local Index Builder

**Files:**
- Create: `scripts/local_index.py`
- Test: `tests/test_local_index.py`

- [ ] **Step 1: Write the failing test for indexing**

Test behavior:
- reads Markdown cards under `knowledge/`
- parses frontmatter-like metadata
- emits a JSON index with document IDs, paths, titles, types, topics, tags, and searchable text

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_local_index -v`
Expected: FAIL because `local_index.py` does not exist or cannot produce the expected output

- [ ] **Step 3: Write the minimal index builder**

Implementation scope:
- walk `knowledge/`
- parse Markdown files
- split metadata from body
- create a JSON index under `indexes/local/index.json`
- create parent directories if missing

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_local_index -v`
Expected: PASS

### Task 3: Add A Minimal Local Retrieval CLI

**Files:**
- Create: `scripts/local_retrieve.py`
- Test: `tests/test_local_retrieve.py`

- [ ] **Step 1: Write the failing test for retrieval**

Test behavior:
- loads the generated local index
- supports lexical matching over title, tags, topic, and body
- returns citation-friendly fields:
  - `doc_id`
  - `path`
  - `title`
  - `type`
  - `topic`
  - `score`
  - `matched_terms`
- does not rely on previous test order to create the index

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_local_retrieve -v`
Expected: FAIL because retrieval CLI does not exist yet

- [ ] **Step 3: Write the minimal retrieval implementation**

Implementation scope:
- read `indexes/local/index.json`
- normalize query text
- score documents using lexical overlap
- return sorted JSON results

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_local_retrieve -v`
Expected: PASS

### Task 4: Add An End-To-End Smoke Check

**Files:**
- Create: `tests/test_local_rag_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

Test behavior:
- create or use the seed cards
- build the index
- run retrieval
- verify the expected seed document is returned for a representative query

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_local_rag_smoke -v`
Expected: FAIL before the full path works

- [ ] **Step 3: Implement any missing glue**

Implementation scope:
- fix any path or invocation gaps between indexing and retrieval
- keep the smoke check independent from test execution order

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_local_rag_smoke -v`
Expected: PASS

### Task 5: Make The Bootstrap Slice Usable

**Files:**
- Modify: `requirements.txt`
- Modify: `docs/2026-04-01-local-rag-roadmap.md`

- [ ] **Step 1: Add any minimal dependency needed**

Only add a dependency if the implementation truly needs it. Prefer standard library first.

- [ ] **Step 2: Add a brief usage note to the roadmap or follow-up doc**

Document:
- how to create a card
- how to build the local index
- how to run local retrieval

- [ ] **Step 3: Run the focused test suite**

Run: `python3 -m unittest tests.test_knowledge_scaffold tests.test_local_index tests.test_local_retrieve tests.test_local_rag_smoke -v`
Expected: PASS

- [ ] **Step 4: Run a syntax sanity check**

Run: `PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile scripts/local_index.py scripts/local_retrieve.py`
Expected: PASS
