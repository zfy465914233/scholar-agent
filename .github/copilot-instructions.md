# Global Instructions

## Project Context

This is an agent engineering harness for algorithm research, experiment design, and LLM tooling exploration. The user is an algorithm engineer working in operations research, optimization, and machine learning (e.g. xgboost).

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

## Language

Default working language is Chinese (zh-CN). Technical terms may remain in English.
