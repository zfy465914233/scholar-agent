"""V1: Sigmoid Normalization Verification

Verifies the _norm function inside PaperScorer._evaluate:
  - Output values for a grid of inputs
  - Monotonicity (higher input -> higher output)
  - Output range [0, 10]
  - Effective spread vs old linear formula
  - Recommendation score sanity
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

# ---------------------------------------------------------------------------
# Reproduce the _norm function (copied from scoring.py for isolated testing)
# ---------------------------------------------------------------------------

def _norm(v: float) -> float:
    """Sigmoid-like mapping from [0, _CEILING] to [0, 10]."""
    if v <= 0:
        return 0.0
    ratio = v / _CEILING
    return 10.0 * ratio / (ratio + 0.3) * 1.3


def old_linear_norm(v: float) -> float:
    """Old linear formula: maps [0, _CEILING] to [0, 10]."""
    return 10.0 * v / _CEILING


# ---------------------------------------------------------------------------
# Check 1: Output values for grid
# ---------------------------------------------------------------------------

def check_grid_values():
    print("=" * 70)
    print("CHECK 1: Output values for input grid")
    print("=" * 70)
    grid = [0, 0.5, 1, 2, 2.5, 3, 4, 5]
    print(f"{'Input':>8} | {'Sigmoid':>10} | {'Linear':>10} | {'Diff':>10}")
    print("-" * 50)
    for v in grid:
        s = _norm(v)
        l = old_linear_norm(v)
        print(f"{v:>8.2f} | {s:>10.4f} | {l:>10.4f} | {s - l:>+10.4f}")
    print()


# ---------------------------------------------------------------------------
# Check 2: Monotonicity
# ---------------------------------------------------------------------------

def check_monotonicity():
    print("=" * 70)
    print("CHECK 2: Monotonicity")
    print("=" * 70)
    grid = [i * 0.1 for i in range(0, 51)]  # 0.0 to 5.0 in 0.1 steps
    prev = _norm(grid[0])
    violations = []
    for v in grid[1:]:
        cur = _norm(v)
        if cur < prev - 1e-9:
            violations.append((v, prev, cur))
        prev = cur

    if violations:
        print("FAIL: Non-monotonic at:")
        for v, p, c in violations:
            print(f"  input={v:.1f}, prev={p:.4f}, cur={c:.4f}")
    else:
        print("PASS: _norm is strictly monotonic on [0, 5]")
    print()


# ---------------------------------------------------------------------------
# Check 3: Output range [0, 10]
# ---------------------------------------------------------------------------

def check_range():
    print("=" * 70)
    print("CHECK 3: Output range [0, 10]")
    print("=" * 70)
    # Test dense grid including edge cases
    test_vals = [0, -1, -0.001, 0.001, 0.5, 1, 2, 3, 4, 4.999, 5, 5.001, 10, 100]
    violations = []
    for v in test_vals:
        out = _norm(v)
        if out < 0 - 1e-9 or out > 10 + 1e-9:
            violations.append((v, out))
        print(f"  input={v:>8.3f} -> output={out:>10.4f}")

    # Also check the actual maximum: _norm(5)
    max_out = _norm(_CEILING)
    print(f"\n  _norm({_CEILING}) = {max_out:.4f}")
    # Check what value asymptotes to as input -> infinity
    asymptote = _norm(1e6)
    print(f"  _norm(1e6) (asymptote) = {asymptote:.4f}")

    if violations:
        print(f"\nFAIL: {len(violations)} values outside [0, 10]:")
        for v, o in violations:
            print(f"  input={v}, output={o}")
    else:
        print("\nPASS: All outputs in [0, 10]")
    print()


# ---------------------------------------------------------------------------
# Check 4: Effective spread
# ---------------------------------------------------------------------------

def check_spread():
    print("=" * 70)
    print("CHECK 4: Effective spread")
    print("=" * 70)

    # Old linear: spread = 10 * (5 - 0) / 5 = 10.0
    linear_spread = old_linear_norm(_CEILING) - old_linear_norm(0)
    print(f"Old linear spread (0->5): {linear_spread:.2f}")

    # Sigmoid: spread between practical bounds
    sig_min = _norm(0.5)   # low-but-nonzero input
    sig_max = _norm(_CEILING)  # max input
    sig_spread = sig_max - sig_min
    print(f"Sigmoid spread (0.5->5):  {sig_spread:.2f}")

    # Full spread
    sig_full = _norm(_CEILING) - _norm(0)
    print(f"Sigmoid full spread (0->5): {sig_full:.2f}")

    # Spread in the "interesting" middle range (1-4)
    sig_mid_spread = _norm(4) - _norm(1)
    lin_mid_spread = old_linear_norm(4) - old_linear_norm(1)
    print(f"\nMid-range spread (1->4):")
    print(f"  Sigmoid: {sig_mid_spread:.2f}")
    print(f"  Linear:  {lin_mid_spread:.2f}")
    print(f"  Ratio (sig/lin): {sig_mid_spread / lin_mid_spread:.2%}")

    # Compression ratio
    print(f"\nCompression analysis:")
    print(f"  Linear maps [0,5] -> [0,10] with slope 2.0 everywhere")
    print(f"  Sigmoid maps [0,5] -> [0,{_norm(_CEILING):.2f}]")
    print(f"  Sigmoid 'loses' {10.0 - _norm(_CEILING):.2f} units of range")

    # Check derivative-like behavior: how much does _norm change per unit?
    print(f"\nLocal sensitivity (delta_norm / delta_input):")
    for lo, hi in [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]:
        delta_out = _norm(hi) - _norm(lo)
        print(f"  [{lo},{hi}]: delta_out = {delta_out:.4f}  (linear would be 2.0)")
    print()


# ---------------------------------------------------------------------------
# Check 5: Recommendation score sanity
# ---------------------------------------------------------------------------

def check_recommendation():
    print("=" * 70)
    print("CHECK 5: Recommendation score sanity")
    print("=" * 70)

    # Use actual PaperScorer with a simple config
    config = {
        "LLM": {
            "keywords": ["large language model", "LLM", "transformer", "GPT"],
            "arxiv_categories": ["cs.AI", "cs.CL"],
        },
    }
    scorer = PaperScorer(domains=config)

    now = datetime.now()

    # Paper with max-ish scores across all dimensions
    paper_max = {
        "title": "GPT-5 Large Language Model Transformer Architecture",
        "summary": (
            "We present a novel large language model with state-of-the-art results. "
            "Our transformer architecture includes a new attention mechanism. "
            "Extensive ablation studies with benchmark evaluation show statistical significance. "
            "Our model outperforms all baselines. Code and pipeline released."
        ),
        "categories": ["cs.AI", "cs.CL"],
        "published_date": now - timedelta(days=1),
        "influentialCitationCount": 500,
        "source": "arxiv",
    }

    # Paper with moderate scores
    paper_mid = {
        "title": "An LLM Study",
        "summary": "We study a transformer model with benchmark tests.",
        "categories": ["cs.AI"],
        "published_date": now - timedelta(days=30),
        "influentialCitationCount": 50,
        "source": "arxiv",
    }

    # Paper with minimal scores
    paper_min = {
        "title": "Brief LLM Note",
        "summary": "A short note about language models.",
        "categories": [],
        "published_date": now - timedelta(days=300),
        "influentialCitationCount": 0,
        "source": "arxiv",
    }

    results = scorer.rank([paper_max, paper_mid, paper_min])

    for p in results:
        s = p["scores"]
        print(f"\n  Title: {p['title']}")
        print(f"    fit={s['fit']}, freshness={s['freshness']}, impact={s['impact']}, rigor={s['rigor']}")
        print(f"    recommendation={s['recommendation']}")

    rec_vals = [p["scores"]["recommendation"] for p in results]
    print(f"\n  Score spread: {max(rec_vals) - min(rec_vals):.2f}")
    print(f"  Max recommendation: {max(rec_vals):.2f}")
    print(f"  Min recommendation: {min(rec_vals):.2f}")

    # Theoretical max recommendation: all dimensions at _CEILING, all weight sums to 1.0
    # rec = sum(_norm(5.0) * weight) = _norm(5.0) * 1.0
    theoretical_max = _norm(_CEILING)
    print(f"\n  Theoretical max recommendation (all dims=5, sum weights=1.0): {theoretical_max:.2f}")
    print(f"  Is this a reasonable ceiling? (should be < 10): {'YES' if theoretical_max < 10 else 'NO'}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    check_grid_values()
    check_monotonicity()
    check_range()
    check_spread()
    check_recommendation()
    print("=" * 70)
    print("V1 VERIFICATION COMPLETE")
    print("=" * 70)
