"""Retrieval fidelity (I3): deprecated cards are filtered, stale ones penalized.

Guards the trust tier added in Batch 2 — the retrieval path must consume
``parse_card``'s ``trust`` field so known-bad cards never surface as matches
and stale ones sink below fresh ones at equal relevance.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scholar_agent.engine.local_index import _trust_tier, parse_card
from scholar_agent.engine.local_retrieve import retrieve

_QUERY = "deep learning survey methods"


def _write_card(path: Path, frontmatter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n{_QUERY} fundamentals", encoding="utf-8")


def _index(docs: list[dict]) -> Path:
    idx = Path(tempfile.mkdtemp(prefix="fid_")) / "index.json"
    idx.write_text(json.dumps({"documents": docs}), encoding="utf-8")
    return idx


def _docs(*specs: tuple[str, str]) -> list[dict]:
    # (doc_id, trust) with identical search_text so BM25 ties and trust decides.
    return [
        {"doc_id": did, "title": "topic", "search_text": _QUERY, "trust": trust}
        for did, trust in specs
    ]


class TestTrustTier(unittest.TestCase):
    def test_deprecated_via_review_status(self) -> None:
        self.assertEqual(_trust_tier({"review_status": "deprecated"}), "deprecated")

    def test_deprecated_via_confidence(self) -> None:
        self.assertEqual(_trust_tier({"confidence": "deprecated"}), "deprecated")

    def test_stale_status(self) -> None:
        self.assertEqual(_trust_tier({"review_status": "stale"}), "stale")

    def test_stale_flag_bool(self) -> None:
        self.assertEqual(_trust_tier({"stale": True}), "stale")

    def test_stale_flag_string(self) -> None:
        self.assertEqual(_trust_tier({"review_status": "reviewed", "stale": "true"}), "stale")

    def test_normal(self) -> None:
        self.assertEqual(_trust_tier({}), "normal")
        self.assertEqual(_trust_tier({"review_status": "reviewed", "stale": False}), "normal")


class TestParseCardTrust(unittest.TestCase):
    def test_deprecated_card(self) -> None:
        p = Path(tempfile.mkdtemp(prefix="pc_")) / "c.md"
        _write_card(p, "id: c\ntitle: T\ntype: knowledge\nconfidence: deprecated")
        self.assertEqual(parse_card(p)["trust"], "deprecated")

    def test_stale_flag_card(self) -> None:
        p = Path(tempfile.mkdtemp(prefix="pc_")) / "c.md"
        _write_card(p, "id: c\ntitle: T\ntype: knowledge\nstale: true")
        self.assertEqual(parse_card(p)["trust"], "stale")

    def test_normal_card(self) -> None:
        p = Path(tempfile.mkdtemp(prefix="pc_")) / "c.md"
        _write_card(p, "id: c\ntitle: T\ntype: knowledge\nconfidence: confirmed")
        self.assertEqual(parse_card(p)["trust"], "normal")


class TestRetrieveFidelity(unittest.TestCase):
    def test_deprecated_never_returned(self) -> None:
        idx = _index(_docs(("good", "normal"), ("bad", "deprecated")))
        result = retrieve(_QUERY, idx, 5)
        ids = [r["doc_id"] for r in result["results"]]
        self.assertIn("good", ids)
        self.assertNotIn("bad", ids)  # deprecated filtered out entirely

    def test_stale_score_penalized_below_fresh(self) -> None:
        # Equal BM25 (identical text) → the only score difference is the trust
        # penalty, so stale must report a strictly lower score than fresh.
        idx = _index(_docs(("fresh", "normal"), ("old", "stale")))
        result = retrieve(_QUERY, idx, 5)
        scores = {r["doc_id"]: r["score"] for r in result["results"]}
        self.assertIn("fresh", scores)
        self.assertIn("old", scores)
        self.assertGreater(scores["fresh"], scores["old"])

    def test_trust_annotated_on_every_result(self) -> None:
        idx = _index(_docs(("a", "normal"), ("b", "stale")))
        result = retrieve(_QUERY, idx, 5)
        self.assertTrue(result["results"])
        for r in result["results"]:
            self.assertIn("trust", r)


if __name__ == "__main__":
    unittest.main()
