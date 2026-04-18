"""Tests for the build_graph.py visualization module."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_graph import build_graph_data, generate_html


class BuildGraphDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.index_path = Path(self.tmpdir) / "index.json"

    def _write_index(self, docs: list[dict]) -> None:
        self.index_path.write_text(json.dumps({"documents": docs}), encoding="utf-8")

    def test_empty_index(self) -> None:
        self._write_index([])
        data = build_graph_data(self.index_path)
        self.assertEqual([], data["nodes"])
        self.assertEqual([], data["edges"])

    def test_single_node(self) -> None:
        self._write_index([{
            "doc_id": "card-1",
            "title": "Neural Networks",
            "topic": "ml",
            "links": [],
            "backlinks": [],
        }])
        data = build_graph_data(self.index_path)
        self.assertEqual(1, len(data["nodes"]))
        self.assertEqual("card-1", data["nodes"][0]["id"])
        self.assertEqual([], data["edges"])

    def test_edges_from_links(self) -> None:
        self._write_index([
            {"doc_id": "a", "title": "A", "topic": "ml", "links": ["b"], "backlinks": []},
            {"doc_id": "b", "title": "B", "topic": "ml", "links": [], "backlinks": ["a"]},
        ])
        data = build_graph_data(self.index_path)
        self.assertEqual(2, len(data["nodes"]))
        self.assertEqual(1, len(data["edges"]))
        edge = data["edges"][0]
        self.assertEqual("a", edge["from"])
        self.assertEqual("b", edge["to"])


class GenerateHtmlTest(unittest.TestCase):
    def test_generates_html_file(self) -> None:
        tmpdir = tempfile.mkdtemp()
        output = Path(tmpdir) / "graph.html"
        graph_data = {
            "nodes": [{"id": "a", "label": "A", "group": "ml"}],
            "edges": [],
        }
        generate_html(graph_data, output)
        self.assertTrue(output.exists())
        content = output.read_text(encoding="utf-8")
        self.assertIn("vis-network", content)
        self.assertIn('"id": "a"', content)


if __name__ == "__main__":
    unittest.main()
