# Path Policy

## Goal
Do not let generation tools write directly into final paper-note locations.

## Staging-first policy
- Initial outputs go under `paper-notes/.staging/<job-id>/`.
- Validation runs against the staging file.
- Only validated notes are promoted.

## Canonical target
Use one stable target per paper:
- `paper-notes/<domain>/<paper-folder>/<paper-folder>.md`
- or `paper-notes/<domain>/<paper-folder>/note.md`

Choose one convention and keep it global.

## Disallowed patterns
- nested auto-generated slug directories in final locations
- multiple competing notes for the same paper directory
- note paths that do not map cleanly to the PDF or paper identity

## Identity inputs
Promotion should require explicit `domain` and `paper-folder` inputs. Do not infer both from a free-form title if stable identifiers are available.
