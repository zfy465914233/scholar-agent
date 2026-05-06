# North Star: Zero-Derivative Rewrite

> **Goal**: Eliminate all code derived from evil-read-arxiv. Retain ideas (uncopyrightable), rewrite implementations from scratch. Same or better functionality. Zero legal risk.

## What Copyright Protects vs Not

| Protected (must rewrite) | Not protected (can keep) |
|---|---|
| Specific code, variable names, function signatures | Algorithms, ideas, workflows |
| Constants that encode domain knowledge identically | Mathematical formulas (Jaccard, BM25, scoring weights) |
| Comment text, docstring wording | API endpoints, file formats, data structures |
| SKILL.md prompt text | The concept of "skill files for Claude Code" |

## Inventory: What Must Be Rewritten

### Priority 1 — COPIED (~90% derivative)

| File | Lines | Issue | Strategy |
|---|---|---|---|
| `scripts/academic/scoring.py` | 305 | Four scoring functions extracted verbatim | Rewrite with different decomposition: unified scorer class with configurable dimensions, different constant names, different helper structure |
| `scripts/academic/arxiv_search.py` | 421 | Constants, function structure, XML parsing logic identical | Rewrite: different XML parsing approach (dataclass models instead of raw dict), different search orchestration, different parameter names |

### Priority 2 — HEAVILY_MODIFIED (50-65% derivative)

| File | Lines | Issue | Strategy |
|---|---|---|---|
| `scripts/academic/conf_search.py` | 412 | DBLP_VENUES dict identical, S2 enrichment logic same | Rewrite DBLP query builder, different S2 matching (embedding similarity vs Jaccard), different result structure |
| `scripts/academic/image_extractor.py` | 270 | Three-step extraction chain same | Rewrite with different priority model, different tar handling, different image filtering |
| `scripts/academic/note_linker.py` | 366 | Keyword scanning + linkification pattern same | Rewrite with different keyword extraction, different linking algorithm |

### Priority 3 — MODIFIED (45% derivative)

| File | Lines | Issue | Strategy |
|---|---|---|---|
| `scripts/academic/paper_analyzer.py` | 914 | Frontmatter template structure from original | Rewrite templates from scratch, different section names/structure |

### Priority 4 — BYTE-IDENTICAL COPIES (must delete or rewrite)

| File | Lines | Issue | Strategy |
|---|---|---|---|
| `skills/start-my-day/scripts/scan_existing_notes.py` | 260 | Byte-identical copy | Delete — functionality already in `daily_workflow.py` |
| `skills/start-my-day/scripts/common_words.py` | ~50 | Byte-identical copy | Delete — inline the word list into `note_linker.py` |
| `skills/start-my-day/scripts/link_keywords.py` | 307 | Near-identical to original | Delete — `note_linker.py` already covers this |
| `skills/start-my-day/scripts/search_arxiv.py` | 1204 | Copy of original monolith | Delete — `arxiv_search.py` covers this |
| `skills/extract-paper-images/scripts/extract_images.py` | 333 | Near-identical to original | Delete — `image_extractor.py` covers this |
| `skills/paper-analyze/scripts/generate_note.py` | 415 | Near-identical to original | Delete — `paper_analyzer.py` covers this |
| `skills/paper-analyze/scripts/update_graph.py` | — | Near-identical to original | Delete — `build_graph.py` covers this |
| `skills/conf-papers/scripts/search_conf_papers.py` | 799 | Near-identical to original | Delete — `conf_search.py` covers this |
| All `skills/*/SKILL.md` files | — | Copied prompt text | Rewrite from scratch or delete |

## Design Principles for Rewrite

1. **Different decomposition** — Don't just rename functions. Restructure modules with different class/function boundaries.
2. **Different naming** — New variable names, function names, constant names throughout.
3. **Different implementation** — Same end result, different code path to get there.
4. **Better where possible** — Use this opportunity to fix known issues, improve performance, add features.
5. **Attribution in commit** — Note "clean-room rewrite" in commit messages, not "adapted from".

## Acceptance Criteria

- [ ] `diff` against evil-read-arxiv shows no non-trivial identical code blocks
- [ ] All 266+ tests pass
- [ ] `skills/` directory contains no copies of original scripts
- [ ] No SKILL.md contains copied prompt text
- [ ] grep for original-specific patterns (e.g. `ARXIV_NS`, `SEMANTIC_SCHOLAR_API_URL`) returns zero hits
- [ ] Functional parity: search, scoring, analysis, image extraction, daily recommend all work
