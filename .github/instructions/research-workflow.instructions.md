---
description: "Use when performing research tasks, literature surveys, tool comparisons, evidence gathering, cross-validation, and producing structured research reports. Covers algorithm research, operations research, optimization, xgboost, LLM tooling exploration."
applyTo: "**"
---

# Research Workflow

## Process Constraints

1. Gather evidence from at least two different source types (e.g. GitHub repos + blog posts, or arXiv papers + official docs) before forming conclusions.
2. Cross-validate claims — do not accept a single source as definitive.
3. Prioritize recent public information (last 3-6 months).
4. Explicitly mark uncertainty levels: confirmed, likely, unknown.
5. Every recommendation must link back to specific evidence items.

## Source Priority

1. Official documentation and release notes.
2. GitHub repositories (README, releases, changelogs, issues).
3. arXiv preprints, Papers with Code.
4. Technical blog posts from reputable authors or organizations.
5. Community discussions (GitHub Discussions, Stack Overflow, Reddit).

## Freshness Rules

1. For fast-moving topics (LLM tooling, agent frameworks), prefer sources from the last 3 months.
2. For stable topics (optimization algorithms, classical ML), older foundational sources are acceptable.
3. Always note when evidence was published and when it was retrieved.

## Retrieval Failure Handling

1. If a source cannot be retrieved, mark it as `retrieval_failed` in the evidence record.
2. Do not block the entire workflow for a single failed retrieval.
3. Note retrieval failures in the final report.

## Output Requirements

1. Conclusions must include a summary, comparison table (if applicable), evidence list, freshness notes, and risk/caveats section.
2. For "best option" questions, state evaluation criteria explicitly.
