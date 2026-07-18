"""Tests for the build_graph.py visualization module."""

import json
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

ENGINE = _ROOT / "src" / "scholar_agent" / "engine"

from scholar_agent.engine.build_graph import build_graph_data, generate_html


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
        self._write_index(
            [
                {
                    "doc_id": "card-1",
                    "title": "Neural Networks",
                    "topic": "ml",
                    "links": [],
                    "backlinks": [],
                }
            ]
        )
        data = build_graph_data(self.index_path)
        self.assertEqual(1, len(data["nodes"]))
        self.assertEqual("card-1", data["nodes"][0]["id"])
        self.assertEqual([], data["edges"])

    def test_edges_from_links(self) -> None:
        self._write_index(
            [
                {"doc_id": "a", "title": "A", "topic": "ml", "links": ["b"], "backlinks": []},
                {"doc_id": "b", "title": "B", "topic": "ml", "links": [], "backlinks": ["a"]},
            ]
        )
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


class ColorSchemeTest(unittest.TestCase):
    """Hash-based topic colors and cloud-edge styling (additive; A4)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.index_path = Path(self.tmpdir) / "index.json"

    def _write_index(self, docs: list[dict]) -> None:
        self.index_path.write_text(json.dumps({"documents": docs}), encoding="utf-8")

    def test_topic_color_is_deterministic(self) -> None:
        self._write_index(
            [
                {"doc_id": "a", "title": "A", "topic": "ml", "links": []},
                {"doc_id": "b", "title": "B", "topic": "ml", "links": []},
                {"doc_id": "c", "title": "C", "topic": "quantum", "links": []},
            ]
        )
        data = build_graph_data(self.index_path)
        colors = {n["id"]: n["color"] for n in data["nodes"]}
        self.assertEqual(colors["a"], colors["b"])  # same topic → same color
        # Deterministic across calls.
        again = build_graph_data(self.index_path)
        self.assertEqual(colors, {n["id"]: n["color"] for n in again["nodes"]})

    def test_paper_note_color_overrides_topic_hash(self) -> None:
        note = Path(self.tmpdir) / "paper-notes" / "p.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text('---\ntitle: "P"\npaper_id: "1706.03762"\n---\n', encoding="utf-8")
        self._write_index(
            [
                {"doc_id": "p", "title": "P", "topic": "ml", "path": str(note), "tags": ["论文笔记"], "links": []},
                {"doc_id": "k", "title": "K", "type": "knowledge", "topic": "ml", "links": []},
            ]
        )
        data = build_graph_data(self.index_path)
        colors = {n["id"]: n["color"] for n in data["nodes"]}
        self.assertNotEqual(colors["p"], colors["k"])  # paper-note stands out

    def test_cloud_edge_colored_and_dashed(self) -> None:
        from unittest.mock import patch

        from scholar_agent.engine.paper_store import PaperStore

        db_path = Path(self.tmpdir) / "papers.db"
        store = PaperStore(db_path)
        store.initialize()
        store.upsert_relation(
            {
                "source_key": "1706.03762",
                "target_key": "1810.04805",
                "target_title": "BERT",
                "rel_type": "baseline_for",
                "confidence": 0.9,
            }
        )
        store.close()

        notes = Path(self.tmpdir) / "paper-notes"
        notes.mkdir()
        note_a = notes / "a.md"
        note_a.write_text('---\ntitle: "A"\npaper_id: "1706.03762"\n---\n', encoding="utf-8")
        note_b = notes / "b.md"
        note_b.write_text('---\ntitle: "B"\npaper_id: "1810.04805"\n---\n', encoding="utf-8")
        self._write_index(
            [
                {"doc_id": "doc-a", "title": "A", "path": str(note_a), "tags": ["论文笔记"], "links": []},
                {"doc_id": "doc-b", "title": "B", "path": str(note_b), "tags": ["论文笔记"], "links": []},
            ]
        )
        with patch("scholar_agent.engine.scholar_config.get_paper_db_path", return_value=db_path):
            data = build_graph_data(self.index_path)
        cloud = [e for e in data["edges"] if e.get("color")]
        self.assertEqual(1, len(cloud))
        self.assertEqual({"from": "doc-a", "to": "doc-b"}, {k: cloud[0][k] for k in ("from", "to")})
        self.assertTrue(cloud[0]["dashes"])
        self.assertIn("baseline_for", cloud[0]["title"])


if __name__ == "__main__":
    unittest.main()
