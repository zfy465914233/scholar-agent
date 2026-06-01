"""V13: Search recall quality — verify query construction logic."""

from scholar_agent.engine.academic.arxiv_search import _CATEGORY_PHRASES

# ============================================================
# Test 1: Query phrase construction from config domains
# ============================================================
print("=" * 80)
print("V13: SEARCH RECALL QUALITY — QUERY CONSTRUCTION")
print("=" * 80)

# Config with multiple domains
config = {
    "research_domains": {
        "deep-learning": {
            "keywords": ["deep learning", "neural network", "representation learning", "optimization"],
            "arxiv_categories": ["cs.LG"],
            "priority": 3,
        },
        "NLP": {
            "keywords": ["language model", "text generation", "transformer", "NLP"],
            "arxiv_categories": ["cs.CL"],
            "priority": 4,
        },
        "computer-vision": {
            "keywords": ["image recognition", "object detection", "visual understanding"],
            "arxiv_categories": ["cs.CV"],
            "priority": 3,
        },
        "single-kw": {
            "keywords": ["reinforcement-learning"],
            "arxiv_categories": ["cs.AI"],
            "priority": 2,
        },
    },
}

# Replicate the phrase-building logic from collect_hot_papers
phrases = []
for _domain_name, dcfg in config["research_domains"].items():
    kws = dcfg.get("keywords", [])
    cats = dcfg.get("arxiv_categories", [])
    if kws:
        query_parts = kws[:2]
        if _domain_name and len(query_parts) < 3:
            query_parts.append(_domain_name)
        phrases.append(" ".join(query_parts))
    elif cats:
        phrases.extend(_CATEGORY_PHRASES.get(c, c) for c in cats[:2])

print("\n--- Query Phrases Generated ---")
for i, p in enumerate(phrases, 1):
    print(f'  {i}. "{p}"')

# Verify
expected = [
    "deep learning neural network deep-learning",  # top 2 kw + domain_name
    "language model text generation NLP",  # top 2 kw + domain_name
    "image recognition object detection computer-vision",  # top 2 kw + domain_name
    "reinforcement-learning single-kw",  # 1 kw + domain_name (len < 3)
]
print("\n--- Verification ---")
for i, (got, exp) in enumerate(zip(phrases, expected, strict=False)):
    match = "PASS" if got == exp else "FAIL"
    print(f"  Query {i + 1}: {match}")
    if got != exp:
        print(f"    Expected: {exp}")
        print(f"    Got:      {got}")

# ============================================================
# Test 2: Old vs New query comparison
# ============================================================
print("\n--- OLD vs NEW Query Comparison ---")
old_phrases = []
for _domain_name, dcfg in config["research_domains"].items():
    kws = dcfg.get("keywords", [])
    if kws:
        old_phrases.append(" ".join(kws[:3]))  # OLD: top 3 keywords

print(f"{'Domain':<20} {'OLD (top 3 kw)':<45} {'NEW (top 2 kw + domain)':<45}")
print("-" * 110)
for (domain_name, dcfg), old_p in zip(config["research_domains"].items(), old_phrases, strict=False):
    kws = dcfg.get("keywords", [])
    new_parts = kws[:2]
    if domain_name and len(new_parts) < 3:
        new_parts.append(domain_name)
    new_p = " ".join(new_parts)
    print(f"{domain_name:<20} {old_p:<45} {new_p:<45}")

# ============================================================
# Test 3: Fallback to category phrases (no config)
# ============================================================
print("\n--- Fallback: Category Phrases (no config) ---")
categories = ["cs.AI", "cs.LG", "cs.CV"]
fallback_phrases = [_CATEGORY_PHRASES.get(c, c) for c in categories]
print(f"  Categories: {categories}")
print(f"  Phrases:    {fallback_phrases}")

# ============================================================
# Test 4: Dedup of duplicate phrases
# ============================================================
print("\n--- Phrase Dedup Test ---")
raw_phrases = ["deep learning optimization", "Deep Learning Optimization", "NLP text generation", "nlp text generation"]
seen = set()
unique = []
for q in raw_phrases:
    lk = q.lower()
    if lk not in seen:
        seen.add(lk)
        unique.append(q)
print(f"  Input:  {raw_phrases}")
print(f"  Output: {unique}")
print(f"  Dedup:  {'PASS' if len(unique) == 2 else 'FAIL'}")

# ============================================================
# Test 5: Impact on recall — simulate what S2 would receive
# ============================================================
print("\n--- Simulated S2 Query Quality Assessment ---")
queries_with_domain = [
    "deep learning neural network deep-learning",
    "language model text generation NLP",
    "image recognition object detection computer-vision",
    "reinforcement-learning single-kw",
]
for q in queries_with_domain:
    # Check: does the query contain meaningful search terms?
    parts = q.split()
    meaningful = [p for p in parts if (len(p) > 2 and "-" not in p) or len(p) > 5]
    domain_parts = [p for p in parts if "-" in p]
    print(f'  Query: "{q}"')
    print(f"    Meaningful terms: {meaningful}")
    print(f"    Domain labels:    {domain_parts}")
    print(f"    Assessment:       {'GOOD' if len(meaningful) >= 2 else 'WEAK'}")

print("\n" + "=" * 80)
print("V13 COMPLETE")
print("=" * 80)
