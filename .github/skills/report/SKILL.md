---
name: report
description: "Generate structured research reports from evidence. Use when synthesizing findings into a final deliverable, comparing tools or frameworks, summarizing literature survey results, producing experiment design proposals. Covers evidence assembly, comparison tables, risk assessment, and recommendation writing."
argument-hint: "Research topic and evidence to compile into a report"
---

# Report Skill

## Purpose

Assemble evidence and analysis into a structured, reproducible research report.

## Procedure

1. **Collect inputs**: Gather all evidence items produced by discovery and triage steps.

2. **Rank evidence**: Score each evidence item on:
   - **Freshness** (0-5): How recent is the source? Last 3 months = 5, 3-6 months = 4, 6-12 months = 3, 1-2 years = 2, older = 1, unknown = 0.
   - **Credibility** (0-5): Official docs = 5, peer-reviewed = 5, established blog = 4, personal blog = 3, forum = 2, unknown = 1.
   - **Reproducibility** (0-5): Code available + instructions = 5, code only = 4, partial code = 3, description only = 2, vague = 1.
   - **Community activity** (0-5): Active + growing = 5, active + stable = 4, slowing = 3, stale = 2, abandoned = 1, N/A = 0.

3. **Identify conflicts**: If evidence items contradict each other, list the conflict explicitly. Do not silently pick one side.

4. **Generate report** using the output format below.

5. **Self-check**:
   - Every conclusion has at least one linked evidence item.
   - Temporal context is present for all sources.
   - Uncertainty is explicitly marked.
   - Retrieval failures are noted.

## Output Format

```markdown
# {Report Title}

Report Date: {YYYY-MM-DD}
Query: {Original research question}

## Executive Summary

{2-3 sentence summary of findings}

## Comparison Table

| Candidate | Freshness | Credibility | Reproducibility | Community | Overall | Notes |
|---|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... | ... |

## Detailed Findings

### {Candidate 1}
- **Source**: {url}
- **Published**: {date}
- **Summary**: {3-5 sentences}
- **Strengths**: ...
- **Weaknesses**: ...
- **Evidence confidence**: confirmed / likely / unknown

### {Candidate 2}
...

## Evidence List

| # | Source Type | Title | URL | Published | Retrieved | Status | Confidence |
|---|---|---|---|---|---|---|---|
| 1 | ... | ... | ... | ... | ... | ... | ... |

## Freshness Assessment

{How current are the findings? Which areas are well-covered, which have stale data?}

## Risks and Open Questions

1. {Risk or unresolved question}
2. ...

## Evaluation Criteria

{State the criteria used for ranking: freshness weight, reproducibility weight, etc.}
```

## Notes

- The report must be self-contained — a reader should understand the conclusion without needing to re-read all sources.
- Default language: Chinese (zh-CN). Technical terms may remain in English.
- If insufficient evidence was gathered, state this explicitly rather than fabricating conclusions.
