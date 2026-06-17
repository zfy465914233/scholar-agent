"""Tests for F3: evidence-id resolution into readable source links."""

import unittest

from scholar_agent.engine.close_knowledge_loop import _build_body_sections, _build_evidence_map


class TestBuildEvidenceMap(unittest.TestCase):
    def test_maps_id_to_url_label(self) -> None:
        rd = {"evidence": [{"id": "e1", "url": "https://arxiv.org/abs/2301.1", "title": "Paper A"}]}
        m = _build_evidence_map(rd)
        self.assertEqual(m["e1"]["url"], "https://arxiv.org/abs/2301.1")
        self.assertEqual(m["e1"]["label"], "Paper A")

    def test_falls_back_to_positional_id(self) -> None:
        rd = {"evidence": [{"url": "https://x.com", "title": "X"}]}
        self.assertIn("e1", _build_evidence_map(rd))

    def test_label_falls_back_to_url(self) -> None:
        rd = {"evidence": [{"id": "e1", "url": "https://x.com"}]}
        self.assertEqual(_build_evidence_map(rd)["e1"]["label"], "https://x.com")

    def test_none_research_returns_empty(self) -> None:
        self.assertEqual(_build_evidence_map(None), {})


class TestClaimSourceLinks(unittest.TestCase):
    def _body(self, claims: list, emap: dict) -> str:
        return "\n".join(
            _build_body_sections(
                query="q",
                main_answer="ans",
                claims=claims,
                inferences=[],
                uncertainties=[],
                missing=[],
                next_steps=[],
                card_type="knowledge",
                expected_output="",
                example="",
                va_by_section={},
                evidence_map=emap,
            )
        )

    def test_claim_renders_readable_source(self) -> None:
        emap = {"e1": {"url": "https://arxiv.org/abs/2301.1", "label": "Paper A"}}
        claims = [
            {"claim": "This is a factual claim with enough detail.", "confidence": "high", "evidence_ids": ["e1"]}
        ]
        body = self._body(claims, emap)
        self.assertIn("[Paper A](https://arxiv.org/abs/2301.1)", body)
        # the opaque "(evidence: e1)" form must be gone
        self.assertNotIn("(evidence:", body)

    def test_unknown_id_falls_back_gracefully(self) -> None:
        claims = [
            {"claim": "This is a factual claim with enough detail.", "confidence": "high", "evidence_ids": ["eX"]}
        ]
        body = self._body(claims, {})
        self.assertIn("eX", body)
        self.assertIn("参考文献", body)


if __name__ == "__main__":
    unittest.main()
