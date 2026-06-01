#!/usr/bin/env python3
"""
Real end-to-end verification of scholar-agent modules.
All API calls are LIVE -- no mocks.

Tests:
  A: arXiv search + scoring
  B: Semantic Scholar search
  C: Note generation (Chinese)
  D: Note generation (English)
  E: Conference search (DBLP)
  F: Full search + score pipeline
"""

import json
import os
import traceback
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

OUTPUT_DIR = "/tmp/scholar_test_notes"
os.makedirs(OUTPUT_DIR, exist_ok=True)

SEPARATOR = "=" * 80


def print_sep(label: str):
    print(f"\n{SEPARATOR}")
    print(f"  {label}")
    print(SEPARATOR)


def safe_json(obj):
    """Pretty-print a truncated version of a large object."""
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if len(s) > 2000:
        return s[:2000] + "\n... [truncated]"
    return s


# ===========================================================================
# Config
# ===========================================================================

print_sep("LOADING CONFIG")

# Use default config since no YAML exists
from scholar_agent.engine.academic.arxiv_search import _load_config

config_path = str(_ROOT / "src" / "scholar_agent" / "config_data" / "config.yaml")
if os.path.exists(config_path):
    config = _load_config(config_path)
    print(f"Loaded config from: {config_path}")
else:
    config = _load_config("/nonexistent.yaml")  # triggers default fallback
    print("No YAML config found, using default fallback config")

print(f"Research domains: {list(config.get('research_domains', {}).keys())}")
print(f"Excluded keywords: {config.get('excluded_keywords', [])}")
for domain, dcfg in config.get("research_domains", {}).items():
    print(f"  {domain}: keywords={dcfg.get('keywords', [])}, categories={dcfg.get('arxiv_categories', [])}")

# ===========================================================================
# Test A: arXiv search + scoring
# ===========================================================================

print_sep("TEST A: arXiv SEARCH + SCORING")

try:
    from scholar_agent.engine.academic.arxiv_search import query_arxiv
    from scholar_agent.engine.academic.scoring import score_papers

    now = datetime.now()
    week_ago = now - timedelta(days=7)

    print(f"Searching arXiv for cs.AI + cs.LG papers from {week_ago.date()} to {now.date()}...")
    arxiv_results = query_arxiv(
        categories=["cs.AI", "cs.LG"],
        from_dt=week_ago,
        to_dt=now,
        limit=10,
    )

    print(f"\narXiv returned {len(arxiv_results)} papers")

    if arxiv_results:
        print("\n--- Raw papers (before scoring) ---")
        for i, p in enumerate(arxiv_results[:5]):
            print(f"  [{i + 1}] {p.get('title', 'N/A')[:100]}")
            print(f"      arxiv_id={p.get('arxiv_id')}, published={p.get('published', 'N/A')[:10]}")

        print("\n--- Scoring papers ---")
        scored = score_papers(arxiv_results, config)

        print(f"Papers after scoring (filtering): {len(scored)}")
        print("\n--- Top 3 Scored Papers ---")
        for i, p in enumerate(scored[:3]):
            scores = p.get("scores", {})
            print(f"\n  [{i + 1}] {p.get('title', 'N/A')[:120]}")
            print(f"      arxiv_id: {p.get('arxiv_id')}")
            print(
                f"      fit={scores.get('fit', 0)}, freshness={scores.get('freshness', 0)}, "
                f"impact={scores.get('impact', 0)}, rigor={scores.get('rigor', 0)}"
            )
            print(f"      recommendation={scores.get('recommendation', 0)}")
            print(f"      domain={p.get('best_domain')}, keywords={p.get('domain_keywords')}")

        # Save top paper for note generation tests
        top_paper_a = scored[0] if scored else None
        print("\n--- Assessment ---")
        if scored:
            print(f"Papers are relevant to research domains: {bool(scored)}")
            print("Ranking uses recommendation score (weighted sum of fit/freshness/impact/rigor)")
        else:
            print("WARNING: No papers scored above threshold -- config may need tuning")
    else:
        print("WARNING: arXiv returned no results -- API may be down or date range too narrow")
        top_paper_a = None

except Exception as e:
    print(f"FAILED: {e}")
    traceback.print_exc()
    top_paper_a = None

# ===========================================================================
# Test B: Semantic Scholar search
# ===========================================================================

print_sep("TEST B: SEMANTIC SCHOLAR SEARCH")

try:
    from scholar_agent.engine.academic.arxiv_search import query_semantic_scholar

    now = datetime.now()
    three_months_ago = now - timedelta(days=90)

    print(f"Searching S2 for 'large language model agent' from {three_months_ago.date()} to {now.date()}...")
    s2_results = query_semantic_scholar(
        phrase="large language model agent",
        from_dt=three_months_ago,
        to_dt=now,
        top_k=5,
    )

    print(f"\nSemantic Scholar returned {len(s2_results)} papers")

    if s2_results:
        print("\n--- Top 3 S2 Results ---")
        for i, p in enumerate(s2_results[:3]):
            print(f"\n  [{i + 1}] {p.get('title', 'N/A')[:120]}")
            print(
                f"      arxiv_id={p.get('arxiv_id')}, citations={p.get('citationCount', 0)}, "
                f"influential={p.get('influentialCitationCount', 0)}"
            )
            print(f"      source={p.get('source')}")
            print(f"      abstract: {(p.get('abstract') or '')[:200]}...")
    else:
        print("WARNING: S2 returned no results -- API may be rate-limited or down")

except Exception as e:
    print(f"FAILED: {e}")
    traceback.print_exc()

# ===========================================================================
# Test C: Note generation (Chinese)
# ===========================================================================

print_sep("TEST C: NOTE GENERATION (CHINESE)")

paper_for_note = top_paper_a
if not paper_for_note:
    # Fallback: construct a minimal paper dict
    paper_for_note = {
        "title": "Deep Reinforcement Learning for Autonomous Agent Systems",
        "authors": ["Alice Zhang", "Bob Li", "Charlie Wang"],
        "arxiv_id": "2501.00001",
        "summary": "We propose a novel deep reinforcement learning framework for autonomous agent systems that achieves state-of-the-art performance on multiple benchmarks.",
        "published": "2025-01-15",
        "categories": ["cs.AI", "cs.LG"],
        "pdf_url": "https://arxiv.org/pdf/2501.00001",
        "best_domain": "deep-learning",
        "scores": {"recommendation": 7.5, "fit": 3.2, "freshness": 2.8, "impact": 2.1, "rigor": 1.8},
        "affiliations": ["MIT", "Stanford"],
    }
    print("Using fallback paper (no arXiv results for note generation)")

try:
    from scholar_agent.engine.academic.paper_analyzer import check_note_quality, generate_note

    print(f"Generating Chinese note for: {paper_for_note.get('title', 'N/A')[:100]}")
    zh_note_path = generate_note(
        paper=paper_for_note,
        output_dir=OUTPUT_DIR,
        language="zh",
    )
    print(f"Note written to: {zh_note_path}")

    with open(zh_note_path, encoding="utf-8") as f:
        zh_content = f.read()

    lines = zh_content.split("\n")
    print(f"\n--- Chinese Note (first 200 lines / {len(lines)} total) ---")
    for i, line in enumerate(lines[:200]):
        print(f"  {i + 1:3d} | {line}")

    # Quality check
    quality = check_note_quality(zh_note_path)
    print("\n--- Note Quality ---")
    print(f"  Has issues: {quality['has_issues']}")
    print(f"  Placeholder count: {quality['placeholder_count']}")
    for issue in quality.get("issues", []):
        print(f"  Issue: {issue}")

    # Validate frontmatter
    print("\n--- Frontmatter Validation ---")
    if zh_content.startswith("---"):
        end = zh_content.index("---", 3)
        frontmatter = zh_content[3:end].strip()
        print(frontmatter)
        # Try YAML parse
        try:
            import yaml

            fm = yaml.safe_load(frontmatter)
            print(f"\nYAML parse OK: {list(fm.keys())}")
        except ImportError:
            print("  (yaml not available for validation)")
        except Exception as ye:
            print(f"  YAML parse FAILED: {ye}")
    else:
        print("  WARNING: No frontmatter found!")

except Exception as e:
    print(f"FAILED: {e}")
    traceback.print_exc()

# ===========================================================================
# Test D: Note generation (English)
# ===========================================================================

print_sep("TEST D: NOTE GENERATION (ENGLISH)")

try:
    print(f"Generating English note for: {paper_for_note.get('title', 'N/A')[:100]}")
    en_note_path = generate_note(
        paper=paper_for_note,
        output_dir=OUTPUT_DIR,
        language="en",
    )
    print(f"Note written to: {en_note_path}")

    with open(en_note_path, encoding="utf-8") as f:
        en_content = f.read()

    lines = en_content.split("\n")
    print(f"\n--- English Note (first 200 lines / {len(lines)} total) ---")
    for i, line in enumerate(lines[:200]):
        print(f"  {i + 1:3d} | {line}")

    # Quality check
    quality = check_note_quality(en_note_path)
    print("\n--- Note Quality ---")
    print(f"  Has issues: {quality['has_issues']}")
    print(f"  Placeholder count: {quality['placeholder_count']}")

    # Validate frontmatter
    print("\n--- Frontmatter Validation ---")
    if en_content.startswith("---"):
        end = en_content.index("---", 3)
        frontmatter = en_content[3:end].strip()
        print(frontmatter)
        try:
            import yaml

            fm = yaml.safe_load(frontmatter)
            print(f"\nYAML parse OK: {list(fm.keys())}")
        except ImportError:
            print("  (yaml not available for validation)")
        except Exception as ye:
            print(f"  YAML parse FAILED: {ye}")
    else:
        print("  WARNING: No frontmatter found!")

except Exception as e:
    print(f"FAILED: {e}")
    traceback.print_exc()

# ===========================================================================
# Test E: Conference search (DBLP)
# ===========================================================================

print_sep("TEST E: CONFERENCE SEARCH (DBLP)")

try:
    from scholar_agent.engine.academic.conf_search import gather_venue_papers

    print("Searching NeurIPS 2024 via DBLP (max 5 papers)...")
    conf_results = gather_venue_papers(2024, venues=["NeurIPS"], max_per_venue=5)

    print(f"\nDBLP returned {len(conf_results)} papers")

    if conf_results:
        print("\n--- Sample NeurIPS 2024 Papers ---")
        for i, p in enumerate(conf_results[:5]):
            print(f"\n  [{i + 1}] {p.get('title', 'N/A')[:120]}")
            print(f"      authors: {', '.join(p.get('authors', [])[:3])}...")
            print(f"      venue={p.get('venue')}, year={p.get('year')}, source={p.get('source')}")
    else:
        print("WARNING: DBLP returned no results -- API may be down")

except Exception as e:
    print(f"FAILED: {e}")
    traceback.print_exc()

# ===========================================================================
# Test F: Full search + score pipeline
# ===========================================================================

print_sep("TEST F: FULL SEARCH + SCORE PIPELINE")

try:
    from scholar_agent.engine.academic.arxiv_search import search_and_score

    print("Running full pipeline: arXiv recent + hot papers, categories=cs.AI+cs.LG, max=10, top=5")
    print("(This may take 30-60 seconds due to S2 API calls...)")

    pipeline_result = search_and_score(
        config=config,
        categories=["cs.AI", "cs.LG"],
        max_results=10,
        top_n=5,
    )

    papers = pipeline_result.get("papers", [])
    total = pipeline_result.get("total_found", 0)
    windows = pipeline_result.get("date_windows", {})

    print("\nPipeline complete:")
    print(f"  Total unique papers found: {total}")
    print(f"  Top papers returned: {len(papers)}")
    print(f"  Date windows: {safe_json(windows)}")

    if papers:
        print("\n--- Top 3 Pipeline Results ---")
        for i, p in enumerate(papers[:3]):
            scores = p.get("scores", {})
            print(f"\n  [{i + 1}] {p.get('title', 'N/A')[:120]}")
            print(f"      arxiv_id={p.get('arxiv_id')}, source={p.get('source')}")
            print(
                f"      fit={scores.get('fit', 0)}, freshness={scores.get('freshness', 0)}, "
                f"impact={scores.get('impact', 0)}, rigor={scores.get('rigor', 0)}"
            )
            print(f"      recommendation={scores.get('recommendation', 0)}")
            print(f"      domain={p.get('best_domain')}, trending={p.get('trending')}")
    else:
        print("WARNING: Pipeline returned no papers")

except Exception as e:
    print(f"FAILED: {e}")
    traceback.print_exc()


# ===========================================================================
# Summary
# ===========================================================================
print_sep("TEST SUMMARY")
print("""
All tests completed. Review output above for:
  - API connectivity (arXiv, Semantic Scholar, DBLP)
  - Scoring quality (are recommendations sensible?)
  - Note structure (frontmatter, sections, placeholders)
  - Pipeline correctness (dedup, ranking)
""")
