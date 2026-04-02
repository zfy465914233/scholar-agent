# Phase 4: Agent Control Loop Formalization — Changelog

Date: 2026-04-02

## What Changed

### New: `scripts/agent.py`

Formalized the agent architecture around four explicit roles with clear boundaries:

**Router** — Classifies queries and decides the execution path
- `classify(query)` → route type (local-led, web-led, mixed, context-led)
- `should_research_web(route)` / `should_research_local(route)` — routing decisions

**Researcher** — Gathers evidence from local and web sources
- `gather(query, route)` → structured answer context
- `is_evidence_sufficient(context)` → (bool, reason) — enables retry logic

**Synthesizer** — Produces structured answers from evidence
- `render_prompt(context)` → model-facing prompt bundle
- `synthesize(bundle)` → structured answer with citations

**Curator** — Manages knowledge lifecycle (placeholder for Phase 5)
- `distill(answer)` → draft knowledge card
- `promote(draft_path)` → knowledge tree

### State Machine

```
ROUTE → RESEARCH → SYNTHESIZE → (optional CURATE) → DONE
                       ↑
                       └── retry if evidence insufficient (max_retries)
```

Each state transition is tracked in `state_transitions` for debugging.

### DomainAgent

Top-level orchestrator:
```python
agent = DomainAgent(index_path=..., research_script=..., model=...)
result = agent.run("what is a markov chain", dry_run=True)
```

### New: `tests/test_agent.py`

8 tests covering:
- Agent state machine (route correctness, state transitions)
- Router in isolation (classification, routing decisions)
- Researcher in isolation (gather structure, evidence sufficiency)

## Next Step (Phase 5)

Knowledge Schema + governance — lifecycle states, dedup, conflict detection.
