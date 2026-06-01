"""Direct-import tests for build_evidence_pack and domain_router pure functions."""

import json
import tempfile
import unittest
from pathlib import Path

from scholar_agent.engine.build_evidence_pack import (
    build_evidence_pack,
    normalize_local_items,
    normalize_web_items,
)


class TestNormalizeLocalItems(unittest.TestCase):
    def test_converts_results(self) -> None:
        payload = {
            "results": [
                {
                    "doc_id": "d1",
                    "type": "knowledge",
                    "title": "Test",
                    "path": "/x.md",
                    "score": 0.9,
                    "matched_terms": ["a"],
                },
            ],
        }
        items = normalize_local_items("query", payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["origin"], "local")
        self.assertEqual(items[0]["evidence_id"], "d1")
        self.assertIsNone(items[0]["url"])

    def test_empty_results(self) -> None:
        self.assertEqual(normalize_local_items("q", {}), [])
        self.assertEqual(normalize_local_items("q", {"results": []}), [])


class TestNormalizeWebItems(unittest.TestCase):
    def test_converts_evidence(self) -> None:
        payload = {
            "query": "q",
            "evidence": [
                {"url": "https://example.com", "title": "Example", "source_type": "paper", "summary": "s"},
            ],
        }
        items = normalize_web_items(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["origin"], "web")
        self.assertTrue(items[0]["evidence_id"].startswith("web-"))

    def test_no_url_uses_empty(self) -> None:
        payload = {"evidence": [{"title": "No URL"}]}
        items = normalize_web_items(payload)
        self.assertEqual(items[0]["url"], "")


class TestBuildEvidencePack(unittest.TestCase):
    def test_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.json"
            index.write_text(
                json.dumps(
                    {
                        "documents": [
                            {"doc_id": "d1", "type": "k", "title": "T", "path": "/x.md", "topic": "t"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = build_evidence_pack("test query", index, None, 5)
            self.assertEqual(result["query"], "test query")
            self.assertGreaterEqual(result["local_count"], 0)

    def test_with_web_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.json"
            index.write_text(json.dumps({"documents": []}), encoding="utf-8")
            web = Path(tmp) / "web.json"
            web.write_text(
                json.dumps(
                    {
                        "query": "q",
                        "evidence": [{"url": "https://example.com", "title": "T"}],
                    }
                ),
                encoding="utf-8",
            )
            result = build_evidence_pack("q", index, web, 5)
            self.assertEqual(result["web_count"], 1)

    def test_bad_web_evidence_handled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.json"
            index.write_text(json.dumps({"documents": []}), encoding="utf-8")
            web = Path(tmp) / "bad.json"
            web.write_text("not json", encoding="utf-8")
            result = build_evidence_pack("q", index, web, 5)
            self.assertEqual(result["web_count"], 0)


if __name__ == "__main__":
    unittest.main()
