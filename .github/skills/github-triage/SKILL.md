---
name: github-triage
description: "Evaluate and triage GitHub repositories for maturity, activity, and risk. Use when assessing open-source projects, comparing GitHub repos, checking maintenance status, license risk, community health, release frequency. Covers README analysis, release/changelog review, issue scanning."
argument-hint: "GitHub repository URL or name to triage"
---

# GitHub Triage Skill

## Purpose

Quickly assess the health, maturity, and suitability of a GitHub repository for a given research or engineering need.

## Procedure

1. **Fetch repo page**: Retrieve the GitHub repository main page.
   - Extract: description, star count, fork count, language, license, last commit date.
   - URL pattern: `https://github.com/{owner}/{repo}`

2. **Read README**: Fetch and summarize the README.
   - Look for: project purpose, installation instructions, usage examples, stated maturity level.
   - Note: missing README is a red flag.

3. **Check releases**: Fetch the releases page (`/releases`).
   - Extract: latest release tag, date, cadence (monthly / quarterly / irregular / none).
   - No releases → flag as "no formal release process".

4. **Scan recent issues**: Fetch the issues page (`/issues?sort=updated`).
   - Look for: open issue count, recent activity, unanswered issues, recurring complaints.
   - High open-to-closed ratio with recent activity → possibly active but overwhelmed.
   - No issues at all → either very stable or abandoned.

5. **License check**: Identify the license.
   - Flag: no license, AGPL, or non-standard licenses as potential risks.

6. **Output**: Return a triage record with:
   - `repo`: `{owner}/{repo}`
   - `url`: Full GitHub URL
   - `description`: Repo description
   - `stars`, `forks`, `language`, `license`
   - `last_commit_date`: Date of most recent commit
   - `latest_release`: Tag + date (or "none")
   - `release_cadence`: Monthly / quarterly / irregular / none
   - `open_issues_estimate`: Approximate count
   - `maintenance_status`: Active / slow / stale / abandoned
   - `risk_flags`: List of identified risks (e.g. "no license", "no releases in 12 months")
   - `summary`: 3-5 sentence assessment
   - `retrieved_at`: Current timestamp
   - `retrieval_status`: succeeded / failed / partial

## Maintenance Status Heuristics

| Signal | Status |
|---|---|
| Commits in last 30 days + recent release | Active |
| Commits in last 90 days, no recent release | Slow |
| No commits in 90-365 days | Stale |
| No commits in 365+ days | Abandoned |

## Fallback

If GitHub pages fail to load (rate limit, Cloudflare), mark `retrieval_status: failed` and note the failure. Do not block the overall workflow.

## Notes

- This skill triages repos only. It does not rank or compare repos — that is done by the Research Agent.
- For private repos or repos requiring authentication, mark as `retrieval_status: failed` with reason.
