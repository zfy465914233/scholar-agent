"""V12: Paper Ranking Quality Verification

Constructs 10 diverse mock papers with known properties, runs PaperScorer.rank(),
and verifies the ranking order, score spread, dimension behavior, and edge cases.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from academic.scoring import PaperScorer, _CEILING

# Reproduce _norm for analysis
def _norm(v: float) -> float:
    if v <= 0:
        return 0.0
    ratio = v / _CEILING
    return 10.0 * ratio / (ratio + 0.3) * 1.3

# ---------------------------------------------------------------------------
# Config with a single domain that has clear keywords
# ---------------------------------------------------------------------------

DOMAIN_CONFIG = {
    "test-domain": {
        "keywords": [
            "quantum", "entanglement", "qubit", "superposition",
            "variational", "ansatz", "bell state", "quantum gate",
            " Measurement ", "quantum circuit",
        ],
        "arxiv_categories": ["quant-ph"],
    },
}

now = datetime.now()

# ---------------------------------------------------------------------------
# Paper construction helpers
# ---------------------------------------------------------------------------

def make_paper(
    letter: str,
    title: str,
    summary: str,
    categories: list[str],
    days_ago: int,
    citations: int,
    fit_desc: str,
    impact_desc: str,
    rigor_desc: str,
    expected_behavior: str,
):
    """Build a mock paper dict."""
    return {
        "_letter": letter,
        "_fit_desc": fit_desc,
        "_impact_desc": impact_desc,
        "_rigor_desc": rigor_desc,
        "_expected": expected_behavior,
        "title": title,
        "summary": summary,
        "categories": categories,
        "published_date": now - timedelta(days=days_ago),
        "influentialCitationCount": citations,
        "source": "arxiv",
    }


def build_mock_papers():
    papers = []

    # Paper A: fit=5, impact=high, rigor=high, fresh -> should rank #1
    papers.append(make_paper(
        "A",
        "Quantum Entanglement and Bell State Superposition in Variational Ansatz",
        (
            "We present a novel quantum entanglement framework using variational ansatz "
            "with state-of-the-art results on qubit superposition. Extensive ablation "
            "studies with benchmark evaluation show statistical significance. "
            "Our quantum gate architecture outperforms all baselines with superior "
            "accuracy and f1 score. We provide error analysis and cross-validation."
        ),
        ["quant-ph"],
        days_ago=10,
        citations=500,
        fit_desc="fit=5 (title+abstract+cat match)",
        impact_desc="impact=high (500 cites, 10 days)",
        rigor_desc="rigor=high (many quality terms)",
        expected_behavior="RANK #1",
    ))

    # Paper B: fit=4, impact=medium, rigor=medium -> should rank high
    papers.append(make_paper(
        "B",
        "Variational Quantum Gate Optimization with Entanglement",
        (
            "We study variational quantum gate optimization for entanglement. "
            "Benchmark experiments on qubit systems show improved performance. "
            "Our framework achieves better accuracy than previous methods."
        ),
        ["quant-ph"],
        days_ago=15,
        citations=50,
        fit_desc="fit=~4 (good keyword match)",
        impact_desc="impact=medium (50 cites, 15 days)",
        rigor_desc="rigor=medium (some quality terms)",
        expected_behavior="RANK HIGH (top 3)",
    ))

    # Paper C: fit=3, impact=medium, rigor=medium, older
    papers.append(make_paper(
        "C",
        "Quantum Circuit Design for Qubit Systems",
        (
            "A quantum circuit design methodology for qubit manipulation. "
            "We present baseline comparison results on standard benchmarks."
        ),
        ["quant-ph"],
        days_ago=60,
        citations=30,
        fit_desc="fit=~3 (moderate match)",
        impact_desc="impact=medium (30 cites, 60 days old)",
        rigor_desc="rigor=medium",
        expected_behavior="RANK MID",
    ))

    # Paper D: fit=2, impact=low, rigor=low
    papers.append(make_paper(
        "D",
        "A Note on Quantum Measurement",
        (
            "We discuss some aspects of quantum measurement."
        ),
        ["quant-ph"],
        days_ago=30,
        citations=5,
        fit_desc="fit=~2 (low match)",
        impact_desc="impact=low (5 cites, 30 days)",
        rigor_desc="rigor=low (no quality terms)",
        expected_behavior="RANK LOW",
    ))

    # Paper E: fit=5, impact=low, rigor=medium -> high relevance, no impact
    papers.append(make_paper(
        "E",
        "Quantum Entanglement Superposition Qubit Variational Ansatz Bell State",
        (
            "We propose a quantum entanglement superposition scheme with variational "
            "ansatz and bell state analysis. Framework with benchmark testing shows "
            "improved results."
        ),
        ["quant-ph"],
        days_ago=10,
        citations=2,
        fit_desc="fit=5 (max keyword match)",
        impact_desc="impact=low (2 cites, 10 days)",
        rigor_desc="rigor=medium",
        expected_behavior="HIGH fit but low impact -> should rank mid-high",
    ))

    # Paper F: fit=1, impact=high, rigor=high -> low relevance, popular
    papers.append(make_paper(
        "F",
        "A Measurement Technique",
        (
            "We present a novel measurement technique with state-of-the-art results. "
            "Extensive ablation studies with benchmark evaluation and statistical "
            "significance. Our approach outperforms all baselines with superior "
            "accuracy. Cross-validation and error analysis included."
        ),
        ["quant-ph"],
        days_ago=10,
        citations=500,
        fit_desc="fit=~1 (minimal keyword match)",
        impact_desc="impact=high (500 cites, 10 days)",
        rigor_desc="rigor=high (many quality terms)",
        expected_behavior="LOW fit but popular -> should rank mid-low (fit weight=0.38)",
    ))

    # Paper G: fit=4, impact=high, rigor=high, but OLD (200 days)
    papers.append(make_paper(
        "G",
        "Variational Quantum Entanglement with Bell State Ansatz",
        (
            "We present variational quantum entanglement with bell state ansatz. "
            "State-of-the-art results with ablation studies, benchmark evaluation, "
            "and statistical significance. Our framework outperforms baselines "
            "with superior accuracy and f1 score."
        ),
        ["quant-ph"],
        days_ago=200,
        citations=200,
        fit_desc="fit=~4 (good match)",
        impact_desc="impact=low (citations ignored for old papers, base=0.4)",
        rigor_desc="rigor=high",
        expected_behavior="OLD paper -> freshness penalty -> should rank mid",
    ))

    # Paper H: fit=3, impact=low, rigor=low, OLD (300 days)
    papers.append(make_paper(
        "H",
        "Quantum Circuit for Superposition",
        "A basic quantum circuit for superposition.",
        ["quant-ph"],
        days_ago=300,
        citations=3,
        fit_desc="fit=~3",
        impact_desc="impact=low",
        rigor_desc="rigor=low",
        expected_behavior="RANK LOW (old + low everything)",
    ))

    # Paper I: fit=0 -> should be FILTERED OUT
    papers.append(make_paper(
        "I",
        "A Totally Unrelated Paper About Cooking",
        (
            "We present a novel recipe for chocolate cake with state-of-the-art "
            "ablation studies and benchmark evaluation. Statistical significance "
            "demonstrated with cross-validation."
        ),
        [],
        days_ago=10,
        citations=500,
        fit_desc="fit=0 (no keyword match)",
        impact_desc="impact=high (would be high)",
        rigor_desc="rigor=high (quality terms but irrelevant)",
        expected_behavior="FILTERED OUT (fit=0)",
    ))

    # Paper J: fit=2, impact=medium, rigor=medium, VERY OLD (365 days)
    papers.append(make_paper(
        "J",
        "Quantum Gate Operations",
        (
            "We study quantum gate operations with benchmark comparison."
        ),
        ["quant-ph"],
        days_ago=365,
        citations=40,
        fit_desc="fit=~2",
        impact_desc="impact=medium",
        rigor_desc="rigor=medium",
        expected_behavior="VERY OLD -> freshness=0 -> should rank low",
    ))

    return papers


# ---------------------------------------------------------------------------
# Run verification
# ---------------------------------------------------------------------------

def run_ranking_verification():
    papers = build_mock_papers()

    scorer = PaperScorer(domains=DOMAIN_CONFIG)
    ranked = scorer.rank(papers)

    print("=" * 80)
    print("V12: PAPER RANKING QUALITY VERIFICATION")
    print("=" * 80)

    # -----------------------------------------------------------------------
    # Report 1: Filtered papers
    # -----------------------------------------------------------------------
    print("\n--- FILTERED PAPERS (fit <= 0, removed from ranking) ---")
    ranked_letters = {p.get("_letter") for p in ranked}
    for p in papers:
        if p["_letter"] not in ranked_letters:
            print(f"  Paper {p['_letter']}: {p['_expected']} -> {p['title'][:60]}")
            print(f"    Expected: {p['_expected']}")

    # -----------------------------------------------------------------------
    # Report 2: Full ranking with dimension scores
    # -----------------------------------------------------------------------
    print("\n--- FULL RANKING ---")
    print(f"{'Rank':>4} | {'Paper':>5} | {'Fit':>6} | {'Fresh':>6} | {'Impact':>6} | {'Rigor':>6} | {'Rec':>8} | Expected")
    print("-" * 95)

    rank_scores = []
    for i, p in enumerate(ranked, 1):
        s = p["scores"]
        rank_scores.append((p["_letter"], s["recommendation"]))
        print(f"{i:>4} |     {p['_letter']} | {s['fit']:>6.2f} | {s['freshness']:>6.2f} | {s['impact']:>6.2f} | {s['rigor']:>6.2f} | {s['recommendation']:>8.2f} | {p['_expected']}")

    # -----------------------------------------------------------------------
    # Report 3: Detailed per-paper breakdown
    # -----------------------------------------------------------------------
    print("\n--- DETAILED PER-PAPER BREAKDOWN ---")
    for i, p in enumerate(ranked, 1):
        s = p["scores"]
        print(f"\n  Rank #{i}: Paper {p['_letter']} — {p['title'][:60]}")
        print(f"    Design: {p['_fit_desc']}, {p['_impact_desc']}, {p['_rigor_desc']}")
        print(f"    Scores: fit={s['fit']:.2f}, freshness={s['freshness']:.2f}, impact={s['impact']:.2f}, rigor={s['rigor']:.2f}")
        print(f"    Recommendation: {s['recommendation']:.2f}")
        print(f"    Normalized contribution: fit={_norm(s['fit'])*0.38:.2f}, fresh={_norm(s['freshness'])*0.18:.2f}, impact={_norm(s['impact'])*0.32:.2f}, rigor={_norm(s['rigor'])*0.12:.2f}")

    # -----------------------------------------------------------------------
    # Check 1: Score spread
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("CHECK 1: Score Spread")
    print("=" * 80)
    recs = [p["scores"]["recommendation"] for p in ranked]
    spread = max(recs) - min(recs)
    print(f"  Max recommendation: {max(recs):.2f} (Paper {ranked[0]['_letter']})")
    print(f"  Min recommendation: {min(recs):.2f} (Paper {ranked[-1]['_letter']})")
    print(f"  Spread: {spread:.2f}")
    print(f"  Spread assessment: {'GOOD' if spread > 3.0 else 'POOR (too compressed)'}")

    # Check pairwise gaps
    print(f"\n  Pairwise gaps:")
    for i in range(len(ranked) - 1):
        gap = ranked[i]["scores"]["recommendation"] - ranked[i+1]["scores"]["recommendation"]
        print(f"    #{i+1}({ranked[i]['_letter']}) - #{i+2}({ranked[i+1]['_letter']}): {gap:.2f}")

    # -----------------------------------------------------------------------
    # Check 2: A > F (high-fit+high-impact > low-fit+high-impact)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("CHECK 2: High-Fit+High-Impact > Low-Fit+High-Impact")
    print("=" * 80)
    paper_map = {p["_letter"]: p for p in ranked}
    if "A" in paper_map and "F" in paper_map:
        rec_a = paper_map["A"]["scores"]["recommendation"]
        rec_f = paper_map["F"]["scores"]["recommendation"]
        rank_a = next(i for i, p in enumerate(ranked, 1) if p["_letter"] == "A")
        rank_f = next(i for i, p in enumerate(ranked, 1) if p["_letter"] == "F")
        if rec_a > rec_f:
            print(f"  PASS: Paper A (rank #{rank_a}, rec={rec_a:.2f}) > Paper F (rank #{rank_f}, rec={rec_f:.2f})")
        else:
            print(f"  FAIL: Paper A (rank #{rank_a}, rec={rec_a:.2f}) <= Paper F (rank #{rank_f}, rec={rec_f:.2f})")
            print(f"  This means a low-fit but popular paper outranks a high-fit high-impact paper!")

    # -----------------------------------------------------------------------
    # Check 3: Freshness correctly penalizes old papers
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("CHECK 3: Freshness Penalizes Old Papers")
    print("=" * 80)
    for letter in ["A", "G", "H", "J"]:
        if letter in paper_map:
            p = paper_map[letter]
            s = p["scores"]
            days = (now - p["published_date"]).days
            print(f"  Paper {letter}: {days} days old -> freshness={s['freshness']:.2f}")

    # Check that G (200 days) has lower freshness than B (15 days)
    if "G" in paper_map and "B" in paper_map:
        fresh_g = paper_map["G"]["scores"]["freshness"]
        fresh_b = paper_map["B"]["scores"]["freshness"]
        if fresh_b > fresh_g:
            print(f"  PASS: B (15d, fresh={fresh_b:.2f}) > G (200d, fresh={fresh_g:.2f})")
        else:
            print(f"  FAIL: B freshness ({fresh_b:.2f}) not > G freshness ({fresh_g:.2f})")

    # Check J (365 days) has freshness = 0
    if "J" in paper_map:
        fresh_j = paper_map["J"]["scores"]["freshness"]
        if fresh_j == 0.0:
            print(f"  PASS: J (365d) has freshness=0.00")
        else:
            print(f"  FAIL: J (365d) has freshness={fresh_j:.2f} (should be 0)")

    # -----------------------------------------------------------------------
    # Check 4: Paper I filtered out
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("CHECK 4: Paper I (fit=0) Filtered Out")
    print("=" * 80)
    if "I" not in ranked_letters:
        # Check if I was in original papers
        has_i = any(p["_letter"] == "I" for p in papers)
        if has_i:
            print("  PASS: Paper I was in input but removed from ranked output")
        else:
            print("  N/A: Paper I was not in input papers")
    else:
        print("  FAIL: Paper I should have been filtered out but appears in ranked results!")

    # -----------------------------------------------------------------------
    # Check 5: No sigmoid score inversions
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("CHECK 5: Sigmoid Score Inversions (dimension-level)")
    print("=" * 80)
    # Check if higher raw dimension always gives higher _norm contribution
    inversion_found = False
    for dim, weight in [("fit", 0.38), ("freshness", 0.18), ("impact", 0.32), ("rigor", 0.12)]:
        pairs = []
        for p in ranked:
            pairs.append((p["_letter"], p["scores"][dim], _norm(p["scores"][dim]) * weight))
        # Sort by raw score
        sorted_by_raw = sorted(pairs, key=lambda x: x[1])
        # Check if _norm ordering matches raw ordering
        for i in range(len(sorted_by_raw) - 1):
            raw_lo, norm_lo = sorted_by_raw[i][1], sorted_by_raw[i][2]
            raw_hi, norm_hi = sorted_by_raw[i+1][1], sorted_by_raw[i+1][2]
            if raw_lo < raw_hi and norm_lo > norm_hi + 1e-9:
                print(f"  INVERSION in {dim}: raw {sorted_by_raw[i][0]}={raw_lo:.2f} vs {sorted_by_raw[i+1][0]}={raw_hi:.2f}")
                print(f"    but norm contribution {sorted_by_raw[i][0]}={norm_lo:.4f} vs {sorted_by_raw[i+1][0]}={norm_hi:.4f}")
                inversion_found = True
    if not inversion_found:
        print("  PASS: No dimension-level sigmoid inversions detected")

    # -----------------------------------------------------------------------
    # Check 6: Overall ranking sanity
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("CHECK 6: Overall Ranking Sanity")
    print("=" * 80)
    print("  Expected order (roughly): A > B/E > G > C > F > D/H > J")
    print(f"  Actual order:   {' > '.join(p['_letter'] for p in ranked)}")

    # Specific checks
    checks = []

    # A should be #1
    if ranked[0]["_letter"] == "A":
        checks.append(("Paper A is #1", True))
    else:
        checks.append(("Paper A is #1", False))

    # A and E both have fit=5 but A has much higher impact
    if "A" in paper_map and "E" in paper_map:
        a_above_e = paper_map["A"]["scores"]["recommendation"] > paper_map["E"]["scores"]["recommendation"]
        checks.append(("Paper A > Paper E (both high fit, A has more impact)", a_above_e))

    # B should rank above C (higher fit, similar impact, fresher)
    if "B" in paper_map and "C" in paper_map:
        b_above_c = paper_map["B"]["scores"]["recommendation"] > paper_map["C"]["scores"]["recommendation"]
        checks.append(("Paper B > Paper C (higher fit, fresher)", b_above_c))

    # D and H should be near bottom
    bottom_letters = {ranked[-1]["_letter"], ranked[-2]["_letter"], ranked[-3]["_letter"]}
    d_near_bottom = "D" in bottom_letters or any(ranked[i]["_letter"] == "D" for i in range(max(0, len(ranked)-3), len(ranked)))
    h_near_bottom = "H" in bottom_letters or any(ranked[i]["_letter"] == "H" for i in range(max(0, len(ranked)-3), len(ranked)))
    checks.append(("Paper D near bottom", d_near_bottom))
    checks.append(("Paper H near bottom", h_near_bottom))

    # J should be at or near bottom (365 days old)
    j_last = ranked[-1]["_letter"] == "J"
    checks.append(("Paper J at bottom (365d old, freshness=0)", j_last))

    for desc, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {desc}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    total_checks = len(checks)
    passed_checks = sum(1 for _, p in checks if p)
    # Plus the individual checks
    extra_passed = 0
    extra_total = 0
    if "I" not in ranked_letters:
        extra_passed += 1
    extra_total += 1
    if not inversion_found:
        extra_passed += 1
    extra_total += 1

    print(f"\n{'=' * 80}")
    print(f"SUMMARY: {passed_checks}/{total_checks} sanity checks passed, {extra_passed}/{extra_total} structural checks passed")
    print(f"Score spread: {spread:.2f}")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    run_ranking_verification()
