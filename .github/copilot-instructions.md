# Global Instructions

## Project Context

This is Scholar Agent — a knowledge flywheel MCP server with an academic paper research pipeline. It combines domain knowledge retrieval, structured research synthesis, and academic paper analysis (arXiv/Semantic Scholar/DBLP).

## Core Constraints

1. Backend capabilities (search, crawl) run locally via SearXNG and Crawl4AI — zero API keys needed for the backend layer. Frontend reasoning uses online models (Claude, Copilot) which require their own API access.
2. No local LLM is needed.
3. Evidence-first. Never present conclusions without citing sources.
4. All outputs must include temporal context — when was the evidence retrieved, when was it published.
5. For "best option" questions, always state the evaluation criteria (freshness, engineering maturity, community activity, reproducibility).

## Output Principles

1. Prefer structured output over prose.
2. Explicitly mark uncertainty — distinguish "confirmed" from "likely" from "unknown".
3. Avoid marketing-style summaries. Prefer reproducibility and engineering maturity over hype.
4. When comparing options, use tables with consistent dimensions.

## Evidence Handling

1. All evidence must conform to the project evidence schema (`schemas/evidence.schema.json`).
2. Conclusions must explicitly link back to evidence items.
3. When evidence conflicts, surface the conflict rather than silently picking a side.

## Knowledge Organization

1. Organize `knowledge/` primarily by narrow topic folders such as `qpe/`, `markov_chain/`, `quantum_phase_estimation/`, `linear_programming/`, and `model_quantization/`.
2. Do not create deeper type-based folders like `definitions/`, `methods/`, or `theorems/` under a domain. Keep files directly inside the domain folder.
3. Use frontmatter metadata such as `type` to distinguish definitions, methods, theorems, derivations, comparisons, and decision records.
4. When draft-stage or promotion-stage files need to coexist with curated materials, distinguish them with filename prefixes such as `draft-` and `candidate-`.
5. Each topic folder should include a short `README.md` describing what belongs there and how filenames are used.
6. Keep `knowledge/templates/` as the only shared top-level support folder unless a new support folder has clear, repeated operational value.

## Language

Default working language is Chinese (zh-CN). Technical terms may remain in English.
