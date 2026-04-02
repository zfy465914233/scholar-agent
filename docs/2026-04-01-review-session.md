# Bootstrap Progress Review Session

Date: 2026-04-01  
Reviewer: Antigravity (AI)

This document records the live review sessions conducted against `2026-04-01-bootstrap-progress.md`.

---

## Review 1 — Bootstrap Phase Complete (≈16:40)

### Scope

Initial review after Tasks 1–4 of the bootstrap plan were completed.

### State At Review

| Component | Status |
|---|---|
| `knowledge/` directory tree | ✅ Created |
| 6 card templates | ✅ Created |
| 2 seed cards (Markov Chain / Stationary Distribution) | ✅ Created |
| `scripts/local_index.py` | ✅ Created |
| `scripts/local_retrieve.py` | ✅ Created |
| 4 test files | ✅ All passing |

### Test Result

`Ran 4 tests — OK`

### Findings

**Positive:**
- `local_index.py` implements its own lightweight YAML frontmatter parser without external dependencies; a deliberate and good choice.
- Scoring weights in `local_retrieve.py` are well-reasoned: title=4 > tag=3 > topic=2 > body=1.
- The definition-query heuristic (+5 for `what is / define`) is a useful early specialisation for algorithm-domain lookups.
- The `derivation` card format already includes structured `steps` with `claim` and `support` fields, matching the recommended format proposed in the discussion notes.

**Issues:**
- Seed cards use Markov Chain content, not the actual domain (QPE / Operations Research). The system cannot yet be validated against real algorithm questions.
- `indexes/local/` is a build artefact and should be reviewed for `.gitignore` inclusion.

**Verdict:** Engineering bootstrap is complete. Core gap is content, not code.

---

## Review 2 — Hybrid Evidence Pack + Orchestration (≈16:48)

### New Since Review 1

| Component | Status |
|---|---|
| `scripts/build_evidence_pack.py` | ✅ Created |
| `scripts/orchestrate_research.py` | ✅ Created |
| `tests/test_hybrid_evidence_pack.py` | ✅ Passing |
| `tests/test_research_orchestrator.py` | ✅ Passing |

### Test Result

`Ran 9 tests — OK`

### Findings

**Positive:**
- Evidence pack normalises local and web items into a single schema with `origin`, `evidence_id`, `source_type`, `title`, and source location fields. This is citation-ready.
- Four-way routing (`local-led / web-led / mixed / context-led`) is the correct model and matches the problem-routing guidance added to the roadmap.
- `--mode` override flag makes the orchestrator easy to test without live network access.
- Graceful degradation when `research_harness.py` fails (surfaces as warning, does not crash).

**Issues:**
- `evidence_id` for web items uses an enumeration index (`web-1`, `web-2`). This is not stable across runs: the same URL may receive a different ID if the order of results changes. Recommend switching to a URL-derived hash.
- When route is `local-led` and the user explicitly passes `--web-evidence`, the current logic discards the bundle. The `build_decision` output still reports `web_available=True`, creating an inconsistency.
- Seed card content remains Markov Chain only; no domain-relevant material exists yet.

**Verdict:** Pipeline backbone is solid. The two issues above should be addressed before the evidence_id is relied upon for citation anchoring.

---

## Review 3 — Answer Context + Distillation + Promotion + Round-Trip (≈17:53 and ≈17:59)

### New Since Review 2

| Component | Status |
|---|---|
| `scripts/build_answer_context.py` | ✅ Created |
| `scripts/distill_knowledge.py` | ✅ Created |
| `scripts/promote_draft.py` | ✅ Created |
| `tests/test_answer_context.py` | ✅ Passing |
| `tests/test_distill_knowledge.py` | ✅ Passing |
| `tests/test_promote_draft.py` | ✅ Passing |
| `tests/test_roundtrip_accumulation.py` | ✅ Passing |
| `tests/fake_research_harness.py` | ✅ Used for harness injection |

### Live Test Result (independently re-run by reviewer)

```
Ran 13 tests in 0.813s — OK
```

All 13 tests confirmed passing by live execution.

### Findings

**Positive:**
- The answer context protocol (`direct_support` / `inference_notes` / `uncertainty_notes` / `citations`) matches the recommended answer protocol from the roadmap exactly.
- `build_answer_context.py` stays model-agnostic; any downstream LLM can consume the same JSON.
- `uncertainty_notes` automatically flags the presence of web evidence for quality review — this is a good default safety rail.
- `promote_draft.py` correctly routes definition-style queries to `cards/definitions/` and derivation-style queries to `cards/derivations/`.
- `test_roundtrip_accumulation.py` is the strongest test in the suite: it runs the full loop end-to-end in an isolated `tempfile` directory, using subprocess calls against the real scripts with `fake_research_harness.py` as the network stub. The approach is correct and CI-safe.
- The loop is now architecturally closed: retrieve → answer → distill → promote → reindex → retrieve again.

**Issues:**

| Issue | Severity | Notes |
|---|---|---|
| `web-{index}` evidence_id instability | Medium | Carried forward from Review 2. Remains unaddressed. |
| `inference_notes` are hardcoded strings | Low | Same two lines for every query. Should vary when evidence is empty. |
| Knowledge base has no domain content | High | Still only Markov Chain seed cards. Cannot validate against QPE / OR problems. |
| `promote_draft.py` only handles definition / derivation / method | Low | theorem / comparison / decision-record fallback is missing; documented in boundary section. |

### Architecture State After This Review

The full local-to-web-to-local accumulation loop is working:

```
User query
  → orchestrate_research   (route classification)
  → build_evidence_pack    (local retrieval + optional web merge)
  → build_answer_context   (citation protocol)
  → distill_knowledge      (markdown draft)
  → promote_draft          (candidate card into knowledge/)
  → local_index            (reindex)
  → local_retrieve         (card is now searchable)
```

---

## Cumulative Issue Tracker

| # | Issue | First Raised | Status |
|---|---|---|---|
| 1 | Seed cards not in target domain (QPE / OR) | Review 1 | ⚠️ Open |
| 2 | `web-{index}` evidence_id not stable across runs | Review 2 | ⚠️ Open |
| 3 | `local-led` route discards explicit `--web-evidence` bundle | Review 2 | ⚠️ Open |
| 4 | `inference_notes` are hardcoded; no empty-evidence variant | Review 3 | ⚠️ Open |
| 5 | `promote_draft.py` only handles 3 of 6 card types | Review 3 | ⚠️ Open (documented) |

---

## Recommended Next Actions (Priority Order)

1. **Add 2–3 domain-relevant cards** (e.g. a QPE error bound derivation, an LP duality theorem, a quantization method card). This is the only way to validate the system's usefulness against the original problem.
2. **Fix `web-{index}` evidence_id**: use `hashlib.md5(url.encode()).hexdigest()[:8]` or similar to produce a stable, URL-derived identifier.
3. **Fix the `local-led` + `--web-evidence` inconsistency** in `orchestrate_research.py`.
4. **Expand `promote_draft.py`** to handle theorem / comparison / decision-record card types.
5. **Run a manual end-to-end session**: use `build_answer_context.py` with a real QPE query, paste the JSON into the target LLM, and record whether the grounded answer is meaningfully better than an ungrounded one.
