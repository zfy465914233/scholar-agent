# Domain Routing Guide

This guide defines how AI should route knowledge cards into the knowledge tree.

## Target Structure

Cards may be routed into either:

- `knowledge/<major_domain>/<card>.md`
- `knowledge/<major_domain>/<subdomain>/<card>.md`

Examples:

- `knowledge/operations-research/inventory-planning/knowledge-...md`
- `knowledge/llm/mixture-of-experts/method-...md`

## Routing Principles

1. Choose the major domain first, then choose the subdomain.
2. Prefer existing folders when they already fit the query.
3. Major domains should be stable, but a new major domain may be created when the query clearly does not belong to any existing major domain.
4. If the major domain is clear but no subdomain is clearly justified, route directly under the major domain.
5. Prefer creating a meaningful new major domain over routing to `general`.
6. A new subdomain may be created when the existing subdomains in the chosen major domain clearly do not fit.
7. Avoid `general` as either a major domain or subdomain unless every clearer category would be misleading.
8. Route by the true subject of the question, not by incidental terms.
9. If the question is procedural, implementation-oriented, or step-by-step, the card type may be `method`, but routing still depends on subject matter.
10. If multiple subdomains are plausible, choose the one with the highest long-term reuse value.

## Decision Heuristics

### operations-research

Use this major domain for topics about optimization, inventory control, forecasting for decision-making, replenishment policies, supply planning, scheduling, and quantitative operations methods.

### llm

Use this major domain for topics about large language models, model architecture, routing, inference, training, evaluation, and systems.

### general

Use this major domain only when the query does not stably fit the existing major domains and creating a new major domain would still be misleading.

## Subdomain Selection

Within the chosen major domain:

1. Match to an existing subdomain if it is a strong semantic fit.
2. If no subdomain is a strong fit, prefer the major-domain root over a vague `general` subdomain.
3. Create a concise kebab-case subdomain only if policy allows new subdomains for that major domain and the query has stable reuse value.
4. Keep subdomains conceptually stable and reusable. Do not create overly narrow one-off subdomains.

## New Major Domain Default

If a query clearly does not belong to any existing major domain, prefer creating a new major domain slug instead of routing to `general`.

When creating a new major domain:

1. Use a concise kebab-case slug.
2. Prefer a reusable conceptual category, not a one-off question title.
3. Route to the major-domain root first unless a specific subdomain is already justified.

## Few-shot Examples

### Example 1

Query: 安全库存和再订货点应该怎么理解

Output:

```json
{"major_domain":"operations-research","subdomain":"inventory-planning","reason":"The query is about inventory control concepts used in replenishment decisions."}
```

### Example 2

Query: MoE 为什么需要 load balancing

Output:

```json
{"major_domain":"llm","subdomain":"mixture-of-experts","reason":"The query is about sparse expert model routing and load balancing in LLM architecture."}
```

### Example 3

Query: 量子纠缠的工程应用应该怎么分类

Output:

```json
{"major_domain":"quantum-computing","subdomain":"","reason":"The query does not fit the existing major domains, so a new major domain root is more appropriate than using general."}
```

## Output Contract

The AI router must return JSON with:

- `major_domain`
- `subdomain`
- `reason`

Set `subdomain` to an empty string when the card should live directly under the major domain.

The `reason` should briefly explain why that route is the best fit.