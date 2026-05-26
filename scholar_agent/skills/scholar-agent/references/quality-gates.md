# Quality Gates

## Hard fail markers
Any of the following should fail validation:
- `status: skeleton`
- `[SCORE]/10`
- `<!-- LLM:`
- duplicated frontmatter
- `unknown` placeholders in required metadata
- empty core sections
- output written outside staging or canonical target

## Core content requirements
A complete paper note must include:
- motivation
- method
- dataset or data range
- key findings
- limitations

## Minimum provenance requirement
At least one of the following should be present for a full note:
- a stable source identifier such as `arxiv_id`, `doi`, `paper_id`, or `pdf_path`
- an evidence anchor in the body such as `Figure 2`, `Table 3`, `Section 4`, `图 2`, `表 1`, or page references

## Type-specific expectations
- `empirical`: at least two quantitative results
- `theory`: a problem definition and a mechanism or proposition explanation
- `survey`: a taxonomy plus agreement/disagreement synthesis
- `benchmark`: task definition, evaluation protocol, baselines, and risk or bias notes

## Math depth requirements
Detected automatically via `math_depth` frontmatter field (set by `detect_math_depth()`).

### `math_depth: heavy` (mandatory)
Papers with significant mathematical content (optimization, statistics, control theory, etc.) MUST include:
- LaTeX formulas in method section (`$...$` inline, `$$...$$` block)
- A symbol definition table or inline symbol definitions
- Derivation logic for each math-heavy module (not just final results)

Failure markers:
- `heavy_math_requires_latex_formulas` — no LaTeX found in the entire note
- `heavy_math_requires_symbol_definitions` — no symbol table or inline definitions

### `math_depth: light` (recommended)
Papers with some mathematical content MUST include:
- At least one LaTeX formula in the method or analysis section

Failure markers:
- `light_math_requires_latex_formulas` — no LaTeX found

### `math_depth: none`
No math requirements. General NLP, vision, or applied papers.

## Content density requirements
- Method section must have at least one prose paragraph (not just bullet points)
- Findings section must have either a data table or substantive prose analysis

Failure markers:
- `method_section_lacks_prose` — method section is only bullet points
- `findings_section_lacks_substance` — findings section has no table or prose

## Image requirements
- When images are extracted, they MUST be embedded in the note via `![[images/filename]]`
- Method section gets framework/architecture images
- Experiments section gets results/ablation images

## Operator guidance
Validation should be machine-readable. Scripts should emit structured JSON and a non-zero exit code on failure.
