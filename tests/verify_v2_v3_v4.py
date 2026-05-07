"""Verification script for V2 (freshness decay), V3 (date parsing), V4 (slugify dedup).

Run:  python -m tests.verify_v2_v3_v4
"""

from __future__ import annotations

import sys
import os
import re
from datetime import datetime, timezone, timedelta

# Ensure project root and scripts/ are importable
_project = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _project)
sys.path.insert(0, os.path.join(_project, "scripts"))

from academic.scoring import PaperScorer
from academic.arxiv_search import _slugify


# ========================================================================
# V2: Linear Freshness Decay Verification
# ========================================================================

def verify_v2():
    print("=" * 72)
    print("V2: LINEAR FRESHNESS DECAY VERIFICATION")
    print("=" * 72)

    age_days_list = [0, 1, 7, 14, 21, 30, 60, 90, 120, 180, 240, 300, 364, 365, 366, 400]

    # Compute freshness for each age
    ref = datetime.now()
    results = []
    for age in age_days_list:
        pub_dt = ref - timedelta(days=age)
        score = PaperScorer._freshness(pub_dt)
        results.append((age, score))

    # Print table
    print(f"\n{'age_days':>10}  {'freshness':>10}")
    print("-" * 24)
    for age, score in results:
        print(f"{age:>10}  {score:>10.2f}")

    # Check 1: monotonic decreasing
    monotonic = all(results[i][1] >= results[i + 1][1] for i in range(len(results) - 1))
    print(f"\n[CHECK] Monotonic decreasing: {'PASS' if monotonic else 'FAIL'}")

    # Check 2: value at 0 ~ 3.0
    score_0 = next(s for a, s in results if a == 0)
    near_3 = abs(score_0 - 3.0) < 0.01
    print(f"[CHECK] Score at age=0 is ~3.0 (actual={score_0:.2f}): {'PASS' if near_3 else 'FAIL'}")

    # Check 3: value at 365+ is 0.0
    score_365 = next(s for a, s in results if a == 365)
    score_366 = next(s for a, s in results if a == 366)
    score_400 = next(s for a, s in results if a == 400)
    zero_after_year = score_365 == 0.0 and score_366 == 0.0 and score_400 == 0.0
    print(f"[CHECK] Score at 365+ is 0.0 (365={score_365}, 366={score_366}, 400={score_400}): "
          f"{'PASS' if zero_after_year else 'FAIL'}")

    # OLD step-function reference values
    OLD_STEP = {0: 3.0, 30: 2.2, 90: 1.3, 180: 0.7, 240: 0.0, 300: 0.0, 364: 0.0}

    print(f"\n{'age_days':>10}  {'NEW':>8}  {'OLD':>8}  {'delta':>8}  {'rank_change':>14}")
    print("-" * 56)

    # We compare rankings: for which age ranges does the relative ordering differ?
    # We'll compute old scores for ALL test ages using the step function
    def old_freshness(age: int) -> float:
        if age <= 0:
            return 3.0
        elif age <= 30:
            return 2.2
        elif age <= 90:
            return 1.3
        elif age <= 180:
            return 0.7
        else:
            return 0.0

    rank_differences = []
    for age, new_score in results:
        old = old_freshness(age)
        delta = new_score - old
        # Determine if ranking relative to neighbors would change
        if abs(delta) > 0.01:
            rank_differences.append((age, new_score, old, delta))

    for age, new_score, old, delta in rank_differences:
        print(f"{age:>10}  {new_score:>8.2f}  {old:>8.1f}  {delta:>+8.2f}  {'DIFFERENT' if abs(delta) > 0.01 else 'same':>14}")

    # Summary of ranking differences
    print(f"\n  Age ranges where NEW ranking DIFFERS from OLD:")
    if rank_differences:
        # Group into ranges
        ages_diff = [a for a, _, _, _ in rank_differences]
        ranges = []
        start = ages_diff[0]
        end = ages_diff[0]
        for a in ages_diff[1:]:
            if a == end + 1 or (a <= 30 and end <= 30) or (a <= 90 and end <= 90):
                end = a
            else:
                ranges.append((start, end))
                start = a
                end = a
        ranges.append((start, end))
        for s, e in ranges:
            print(f"    - Days {s}-{e}")
    else:
        print("    (none)")

    # Acceptability check: new gives higher scores to newer papers?
    acceptable = True
    for i in range(len(results) - 1):
        for j in range(i + 1, len(results)):
            age_i, new_i = results[i]
            age_j, new_j = results[j]
            old_i = old_freshness(age_i)
            old_j = old_freshness(age_j)
            # If old ranking says i > j but new says i <= j, that's a problem
            if old_i > old_j and new_i <= new_j:
                acceptable = False
                print(f"  [WARNING] NEW reverses ordering: age {age_i} ({new_i:.2f}) vs age {age_j} ({new_j:.2f})")
                print(f"            OLD had: age {age_i} ({old_i}) > age {age_j} ({old_j})")

    print(f"\n[CHECK] New ranking preserves newer > older preference: {'PASS' if acceptable else 'FAIL'}")

    # Edge case: None input
    none_score = PaperScorer._freshness(None)
    print(f"[CHECK] freshness(None) = {none_score} (expected 0.0): {'PASS' if none_score == 0.0 else 'FAIL'}")

    return monotonic and near_3 and zero_after_year and acceptable


# ========================================================================
# V3: Date Parsing Compatibility
# ========================================================================

def verify_v3():
    print("\n" + "=" * 72)
    print("V3: DATE PARSING COMPATIBILITY")
    print("=" * 72)

    test_cases = [
        {
            "label": 'Case 1: publicationDate="2024-01-15"',
            "paper": {"publicationDate": "2024-01-15"},
            "expect_success": True,
            "expect_year": 2024,
            "expect_month": 1,
            "expect_day": 15,
        },
        {
            "label": 'Case 2: publicationDate="2024-01" (month only)',
            "paper": {"publicationDate": "2024-01"},
            "expect_success": True,
            "expect_year": 2024,
            "expect_month": 1,
            "expect_day": None,
        },
        {
            "label": 'Case 3: publicationDate="2024" (year only)',
            "paper": {"publicationDate": "2024"},
            "expect_success": True,
            "expect_year": 2024,
            "expect_month": None,
            "expect_day": None,
        },
        {
            "label": 'Case 4: published_date=datetime(2024,3,15) (direct)',
            "paper": {"published_date": datetime(2024, 3, 15)},
            "expect_success": True,
            "expect_year": 2024,
            "expect_month": 3,
            "expect_day": 15,
        },
        {
            "label": 'Case 5: publicationDate="2024-01-15T10:30:00Z" (ISO Z)',
            "paper": {"publicationDate": "2024-01-15T10:30:00Z"},
            "expect_success": True,
            "expect_year": 2024,
            "expect_month": 1,
            "expect_day": 15,
        },
        {
            "label": 'Case 6: publicationDate="2024-01-15T10:30:00+08:00" (tz)',
            "paper": {"publicationDate": "2024-01-15T10:30:00+08:00"},
            "expect_success": True,
            "expect_year": 2024,
            "expect_month": 1,
            "expect_day": 15,
        },
        {
            "label": 'Case 7: publicationDate="" (empty string)',
            "paper": {"publicationDate": ""},
            "expect_success": False,
        },
        {
            "label": 'Case 8: {} (no date field)',
            "paper": {},
            "expect_success": False,
        },
        {
            "label": 'Case 9: publicationDate=None',
            "paper": {"publicationDate": None},
            "expect_success": False,
        },
        {
            "label": 'Case 10: published="2024-06-01" (fallback field)',
            "paper": {"published": "2024-06-01"},
            "expect_success": True,
            "expect_year": 2024,
            "expect_month": 6,
            "expect_day": 1,
        },
    ]

    all_pass = True
    for tc in test_cases:
        result = PaperScorer._parse_date(tc["paper"])
        ok = False
        detail = ""

        if tc["expect_success"]:
            if result is not None:
                checks = []
                if tc.get("expect_year") is not None:
                    checks.append(("year", result.year, tc["expect_year"]))
                if tc.get("expect_month") is not None:
                    checks.append(("month", result.month, tc["expect_month"]))
                if tc.get("expect_day") is not None:
                    checks.append(("day", result.day, tc["expect_day"]))

                mismatches = [(n, g, e) for n, g, e in checks if g != e]
                if mismatches:
                    detail = f" -> parsed={result}, mismatch: {mismatches}"
                    ok = False
                else:
                    detail = f" -> parsed={result}"
                    ok = True
            else:
                detail = " -> returned None (UNEXPECTED)"
                ok = False
        else:
            ok = result is None
            detail = f" -> returned {result}"

        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  [{status}] {tc['label']}{detail}")

    return all_pass


# ========================================================================
# V4: _slugify Dedup Accuracy
# ========================================================================

def verify_v4():
    print("\n" + "=" * 72)
    print("V4: _SLUGIFY DEDUP ACCURACY")
    print("=" * 72)

    # Test the slugify function directly
    test_cases = [
        {
            "label": "Case 1: trailing punctuation",
            "titles": ["A Neural Network", "A Neural Network."],
            "should_dedup": True,
        },
        {
            "label": "Case 2: different content",
            "titles": ["Deep Learning for X", "Deep Learning for Y"],
            "should_dedup": False,
        },
        {
            "label": "Case 3: case insensitivity",
            "titles": ["Attention Is All You Need", "Attention is all you need"],
            "should_dedup": True,
        },
        {
            "label": "Case 4: hyphen removal (GPT-4)",
            "titles": ["GPT-4: A New Model", "GPT4 A New Model"],
            "should_dedup": None,  # just report
        },
        {
            "label": "Case 5: punctuation variation (BERT)",
            "titles": [
                "BERT: Pre-training of Deep Bidirectional Transformers",
                "BERT - Pre-training of Deep Bidirectional Transformers",
            ],
            "should_dedup": True,
        },
        {
            "label": "Case 6a: special char / (slash)",
            "titles": ["Model/A Framework", "Model A Framework"],
            "should_dedup": None,  # report
        },
        {
            "label": "Case 6b: special char ? (question mark)",
            "titles": ["What Is This?", "What Is This"],
            "should_dedup": True,
        },
        {
            "label": "Case 6c: special char * (asterisk)",
            "titles": ["All * Models", "All Models"],
            "should_dedup": True,
        },
        {
            "label": "Case 6d: special char | (pipe)",
            "titles": ["This | That", "This That"],
            "should_dedup": True,
        },
    ]

    all_pass = True
    for tc in test_cases:
        slugs = [_slugify(t) for t in tc["titles"]]
        actually_dedup = slugs[0] == slugs[1]

        print(f"\n  {tc['label']}")
        for i, (title, slug) in enumerate(zip(tc["titles"], slugs)):
            print(f"    Title {i+1}: \"{title}\"")
            print(f"    Slug  {i+1}: \"{slug}\"")

        if tc["should_dedup"] is not None:
            if actually_dedup == tc["should_dedup"]:
                status = "PASS"
            else:
                status = "FAIL"
                all_pass = False

            expected = "same slug (dedup)" if tc["should_dedup"] else "different slugs (no dedup)"
            actual = "same slug" if actually_dedup else "different slugs"
            print(f"    [{status}] Expected: {expected}, Got: {actual}")

            # Flag false positive / false negative
            if actually_dedup and not tc["should_dedup"]:
                print(f"    ** FALSE POSITIVE: these should NOT dedup but they do **")
            elif not actually_dedup and tc["should_dedup"]:
                print(f"    ** FALSE NEGATIVE: these SHOULD dedup but they don't **")
        else:
            print(f"    [INFO] Same slug: {actually_dedup}")

    # Additional edge cases
    print("\n  Additional edge cases:")
    edge_titles = [
        ("", '"" (empty)'),
        ("   ", '"   " (whitespace)'),
        ("12345", '"12345" (numbers only)'),
        ("---", '"---" (dashes only)'),
        ("a" * 500, '"a" x 500 (long)'),
    ]
    for title, desc in edge_titles:
        slug = _slugify(title)
        print(f"    {desc} -> slug=\"{slug[:60]}{'...' if len(slug) > 60 else ''}\"")

    return all_pass


# ========================================================================
# Main
# ========================================================================

if __name__ == "__main__":
    results = {}

    results["V2"] = verify_v2()
    results["V3"] = verify_v3()
    results["V4"] = verify_v4()

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for name, passed in results.items():
        print(f"  {name}: {'ALL PASS' if passed else 'HAS FAILURES'}")
    overall = all(results.values())
    print(f"\n  Overall: {'ALL PASS' if overall else 'HAS FAILURES'}")
    sys.exit(0 if overall else 1)
