# Scholar-Agent Workflow

This skill now follows a fail-closed workflow for paper-note generation.

## State machine
1. Scope Contract
2. Inventory
3. Metadata Gate
4. Canary Generation
5. Validation
6. Batch Generation
7. Promotion
8. Blocked / Remediation

## Mandatory rules
- New jobs must pass a single-paper canary before batch generation.
- Initial outputs go to staging only.
- Validation is required before promotion.
- Validation failure blocks promotion.
- Missing metadata blocks full-note generation.
- Quick summaries are allowed only when explicitly requested and must be labeled as non-scholar deliverables.

## Suggested staging layout
- `paper-notes/.staging/<job-id>/`

## Suggested canonical layout
- `paper-notes/<domain>/<paper-folder>/<paper-folder>.md`
- or `paper-notes/<domain>/<paper-folder>/note.md`

The important property is uniqueness and stability, not the exact filename choice.
