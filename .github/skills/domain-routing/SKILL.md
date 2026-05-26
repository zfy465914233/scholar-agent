---
name: domain-routing
description: "Use when deciding where a knowledge card should live in the knowledge tree, choosing a major domain and subdomain, designing routing policy, or diagnosing why a card was routed to the wrong folder. Reads the repository routing guide and policy before deciding."
---

# Domain Routing Skill

Use this skill when you need to decide or review where knowledge cards should be stored.

## Canonical Sources

Always read these files first:

- `src/scholar_agent/schemas/domain_routing_guide.md`
- `src/scholar_agent/schemas/domain_routing_policy.json`

## Goal

Route cards into:

- `knowledge/<major_domain>/<card>.md`
- `knowledge/<major_domain>/<subdomain>/<card>.md`

## Rules

1. Pick the major domain first.
2. Use a subdomain only when it is clearly justified.
3. Prefer existing subdomains over creating new ones.
4. If the major domain is clear but no subdomain is a strong fit, route to the major-domain root.
5. Avoid `general` unless no clearer category is defensible.

## Expected Output

Return:

- chosen major domain
- chosen subdomain, or an empty string when the card should live at the major-domain root
- concise reason