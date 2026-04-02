---
name: discovery
description: "Search and discover public sources for a research topic. Use when finding candidate tools, frameworks, papers, blog posts, patents, or open-source projects. Covers web search via SearXNG, URL fetching, patent search, and initial source triage. Use for algorithm research, operations research, optimization, LLM tooling exploration."
argument-hint: "Research topic or question to discover sources for"
---

# Discovery Skill

## Purpose

Search the public web for candidate sources relevant to a research question. Produce a list of candidate URLs with initial summaries and metadata.

## Search Depth

Search depth controls the trade-off between coverage and speed. The user can override via prompt (e.g. "快速搜索" or "深度搜索").

| Depth | SearXNG Queries | Mandatory Sources | Snowball Rounds | Crawl Top-N | Typical Time |
|---|---|---|---|---|---|
| **quick** | 2 | SearXNG only | 0 | 3 | < 1 min |
| **medium** (default) | 3-4 | SearXNG + mandatory sources | 1 | 5-8 | 2-5 min |
| **deep** | 5-6 | SearXNG + mandatory + patent | 2 | 10-15 | 5-15 min |

Default depth is **medium**. Adjust when the user says:
- "快速" / "quick" / "概览" → quick
- "深入" / "deep" / "全面" / "彻底" → deep

## Procedure

### Step 1: Formulate queries

Break the research question into targeted search queries (count depends on depth). Include:
- The core topic keywords.
- Time-scoped terms (e.g. "2026", "recent", "latest").
- Variant terms (e.g. both "OR solver" and "optimization solver").
- For **deep**: add Chinese-language query variants.

### Step 2: SearXNG search

Execute queries against `http://localhost:8080/search?q={query}&format=json`.
- Collect top 10-15 results per query.
- Deduplicate by URL.

### Step 3: Mandatory source queries

Always query these high-value sources directly, regardless of SearXNG results:

**Code & projects** (all depths except quick):
- GitHub search: `https://github.com/search?q={query}&type=repositories`
- Papers with Code: `https://paperswithcode.com/search?q={query}`

**Papers** (all depths except quick):
- arXiv search: `https://arxiv.org/search/?query={query}`
- arXiv API (best effort): `http://export.arxiv.org/api/query?search_query=all:{query}&max_results=10`
  - arXiv API rate-limits unauthenticated requests (429). If it fails, rely on SearXNG's arXiv engine results instead. Do not block the workflow.

**Patents** (deep only):
- Google Patents: `https://patents.google.com/?q={query}`
- Espacenet: `https://worldwide.espacenet.com/patent/search?q={query}`

### Step 4: Fetch and extract

For the top candidates (count depends on depth), fetch page content and extract:
- Title
- Published date (if available)
- Key content summary (first 500 words or abstract)

**Skip these domains — frequently block automated access:**
- `sciencedirect.com` (CAPTCHA)
- `wiley.com` / `onlinelibrary.wiley.com` (Cloudflare)
- `ieee.org` / `ieeexplore.ieee.org` (paywall + bot detection)
- `nature.com` (paywall)

> Note: actual accessibility varies by time, IP, and request headers. If a domain below unexpectedly returns full content, accept it. The list is a safe default, not an absolute block.

For these paywalled sources: record title, URL, and abstract from SearXNG snippet only. Mark `retrieval_status: partial`.

**Reliable open-access domains:**
- `arxiv.org` — full abstract and PDF links
- `mdpi.com` — full open access
- `github.com` — full page content
- `paperswithcode.com` — full page content
- `patents.google.com` — full patent text
- `springer.com` / `link.springer.com` — often accessible, may redirect for full text
- Official project docs (readthedocs, github.io, etc.)

### Step 5: Snowball expansion (medium and deep)

After initial results, scan collected content for references to related projects, tools, or papers not yet in the candidate list. Add them as new search targets.

- **Round 1** (medium + deep): Extract project names, library names, and citations mentioned in README files, blog posts, or paper abstracts. Search for each.
- **Round 2** (deep only): Repeat for newly discovered sources.

### Step 6: Completeness check

After all search rounds, check coverage by `source_type` distribution:

1. Count how many evidence items exist for each `source_type` (github, arxiv, docs, blog, patent, etc.).
2. Flag any category with **zero** entries as a gap:
   - 0 `github` → add a GitHub-specific search query.
   - 0 `arxiv` or `paper` → add an arXiv/Papers with Code query.
   - 0 `docs` → search for official documentation of any tool/library already found.
   - 0 `patent` (deep mode only) → add patent queries.
3. If total unique sources < 5 (medium) or < 10 (deep), add broader query variants.
4. Log the gap analysis in the coverage summary.

### Step 7: Initial filter

Remove results that are:
- Duplicates of already-collected content.
- Clearly irrelevant (e.g. marketing pages with no technical content).
- From blocked domains with no usable snippet.

### Step 8: Output

Return a list of candidate evidence items with fields:
- `query`: The search query used.
- `source_type`: One of `github`, `arxiv`, `blog`, `docs`, `forum`, `patent`, `other`.
- `url`: Source URL.
- `title`: Page title.
- `summary`: 2-3 sentence summary.
- `published_at`: Estimated publication date.
- `retrieved_at`: Current timestamp.
- `retrieval_status`: `succeeded` / `failed` / `partial` / `cached`.

Include a **coverage summary** at the end:
- Total sources found / fetched / failed.
- Which mandatory source categories were queried.
- Whether snowball rounds were executed.
- Known gaps or missing coverage areas.

## Caching

Before fetching a URL, check if a cached version exists in the local cache directory (resolved by `cache_helper.py`: project `.cache/` by default, configurable via `HARNESS_CACHE_DIR` env var). Cache format: URL hash → Markdown file with TTL metadata.

- If cached and TTL not expired (default 24h): use cached version, mark `retrieval_status: cached`.
- If cached but expired: re-fetch, update cache.
- If not cached: fetch and write to cache.

## Notes

- Do not evaluate or rank results in this step. Ranking is done by the report skill.
- Always record `retrieval_status` — failed fetches must not be silently dropped.
- For patent results, extract: patent number, title, assignee, filing date, abstract.
