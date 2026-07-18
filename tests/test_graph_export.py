"""Tests for engine.graph_export — the schema_version-1 graph contract."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from scholar_agent.engine.graph_export import build_graph_export, normalize_title
from scholar_agent.engine.paper_store import PaperStore

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every export test hermetic: never touch the real papers.db."""
    monkeypatch.setattr(
        "scholar_agent.engine.scholar_config.get_paper_db_path",
        lambda: tmp_path / "nonexistent.db",
    )


def _write_index(tmp_path: Path, docs: list[dict]) -> Path:
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({"documents": docs}), encoding="utf-8")
    return index_path


def _write_note(tmp_path: Path, rel: str, frontmatter: str) -> Path:
    note = tmp_path / rel
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(frontmatter, encoding="utf-8")
    return note


def _make_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PaperStore:
    """Initialized store at a tmp path, wired into scholar_config."""
    db_path = tmp_path / "papers.db"
    store = PaperStore(db_path)
    store.initialize()
    monkeypatch.setattr(
        "scholar_agent.engine.scholar_config.get_paper_db_path",
        lambda: db_path,
    )
    return store


def test_degradation_when_paper_relations_table_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An existing DB lacking paper_relations surfaces a degradation instead
    of silently reporting cloud_edges: 0 (I5 contract honesty)."""
    import sqlite3

    db_path = tmp_path / "partial.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE papers (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr("scholar_agent.engine.scholar_config.get_paper_db_path", lambda: db_path)
    index_path = _write_index(tmp_path, [{"doc_id": "d", "title": "T", "type": "knowledge", "search_text": "x"}])
    export = build_graph_export(index_path)
    assert export["degradations"] == [{"reason": "paper_relations_table_missing", "impact": "cloud_edges_dropped"}]
    assert export["stats"]["cloud_edges"] == 0


class TestSchema:
    def test_missing_index_returns_empty_graph(self, tmp_path: Path) -> None:
        export = build_graph_export(tmp_path / "nope.json")
        assert export["schema_version"] == 1
        assert export["nodes"] == []
        assert export["edges"] == []
        assert export["stats"] == {"local_nodes": 0, "local_edges": 0, "cloud_edges": 0}

    def test_invalid_index_json_returns_empty_graph(self, tmp_path: Path) -> None:
        index_path = tmp_path / "index.json"
        index_path.write_text("{not json", encoding="utf-8")
        export = build_graph_export(index_path)
        assert export["nodes"] == []

    def test_schema_keys_and_json_serializable(self, tmp_path: Path) -> None:
        index_path = _write_index(
            tmp_path,
            [
                {"doc_id": "a", "title": "A", "type": "knowledge", "topic": "ml", "links": ["b"]},
                {"doc_id": "b", "title": "B", "type": "knowledge", "topic": "ml", "links": []},
            ],
        )
        export = build_graph_export(index_path)
        assert set(export) == {"schema_version", "nodes", "edges", "stats", "degradations"}
        node = export["nodes"][0]
        assert set(node) == {
            "id",
            "title",
            "node_type",
            "topic",
            "domain",
            "tags",
            "year",
            "arxiv_id",
            "venue",
            "domains",
            "is_local",
        }
        edge = export["edges"][0]
        assert set(edge) == {"source", "target", "rel_type", "confidence", "origin"}
        # Round-trips through JSON unchanged.
        assert json.loads(json.dumps(export, ensure_ascii=False)) == export
        assert export["stats"] == {"local_nodes": 2, "local_edges": 1, "cloud_edges": 0}


class TestNodeType:
    def test_classification(self, tmp_path: Path) -> None:
        index_path = _write_index(
            tmp_path,
            [
                {"doc_id": "p1", "title": "P1", "path": "x/paper-notes/p1.md", "tags": []},
                {"doc_id": "p2", "title": "P2", "path": "elsewhere/p2.md", "tags": ["论文笔记"]},
                {"doc_id": "d1", "title": "D1", "path": "x/daily-notes/2026-01-01.md", "tags": []},
                {"doc_id": "k1", "title": "K1", "type": "knowledge", "path": "knowledge/k1.md", "tags": []},
                {"doc_id": "o1", "title": "O1", "type": "note", "path": "misc/o1.md", "tags": []},
            ],
        )
        export = build_graph_export(index_path)
        types = {node["id"]: node["node_type"] for node in export["nodes"]}
        assert types == {
            "p1": "paper-note",  # by path
            "p2": "paper-note",  # by tag
            "d1": "daily-note",
            "k1": "knowledge-card",
            "o1": "other",
        }


class TestArxivBridge:
    def test_bridge_from_frontmatter(self, tmp_path: Path) -> None:
        note = _write_note(
            tmp_path,
            "paper-notes/attn.md",
            """---
title: "Attention Is All You Need"
paper_id: "arXiv:1706.03762"
conference: "NeurIPS 2017"
date: "2017-06-12"
tags:
  - 论文笔记
---
# body
""",
        )
        index_path = _write_index(
            tmp_path,
            [{"doc_id": "attn", "title": "Attention Is All You Need", "path": str(note), "tags": ["论文笔记"]}],
        )
        export = build_graph_export(index_path)
        node = export["nodes"][0]
        assert node["node_type"] == "paper-note"
        assert node["arxiv_id"] == "1706.03762"  # arXiv: prefix stripped
        assert node["venue"] == "NeurIPS 2017"
        assert node["year"] == 2017

    def test_bridge_from_paperstore_title_match(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.upsert_paper({"arxiv_id": "1706.03762", "title": "Attention Is All You Need"})
        store.close()
        # Note has NO arxiv in frontmatter; index title differs in case/punctuation.
        note = _write_note(
            tmp_path,
            "paper-notes/attn.md",
            '---\ntitle: "Attention is all you need!"\ntags:\n  - 论文笔记\n---\n',
        )
        index_path = _write_index(
            tmp_path,
            [{"doc_id": "attn", "title": "Attention is all you need!", "path": str(note), "tags": ["论文笔记"]}],
        )
        export = build_graph_export(index_path)
        assert export["nodes"][0]["arxiv_id"] == "1706.03762"

    def test_unreadable_note_degrades_gracefully(self, tmp_path: Path) -> None:
        index_path = _write_index(
            tmp_path,
            [
                {
                    "doc_id": "ghost",
                    "title": "Ghost Paper",
                    "path": str(tmp_path / "paper-notes" / "ghost.md"),  # does not exist
                    "tags": ["论文笔记"],
                    "updated_at": "2024-03-01T10:00:00",
                }
            ],
        )
        export = build_graph_export(index_path)
        node = export["nodes"][0]
        assert node["node_type"] == "paper-note"
        assert node["arxiv_id"] is None
        assert node["venue"] is None
        assert node["year"] == 2024  # fell back to updated_at


class TestLocalEdges:
    def test_resolve_skip_dangling_and_self(self, tmp_path: Path) -> None:
        index_path = _write_index(
            tmp_path,
            [
                {"doc_id": "a", "title": "A", "links": ["b-card", "missing", "a", "b-card"]},
                {"doc_id": "b-card", "title": "B", "links": []},
            ],
        )
        export = build_graph_export(index_path)
        assert export["edges"] == [
            {"source": "a", "target": "b-card", "rel_type": "references", "confidence": 1.0, "origin": "local"}
        ]


class TestCloudEdges:
    def _two_note_index(self, tmp_path: Path) -> Path:
        note_a = _write_note(tmp_path, "paper-notes/a.md", '---\ntitle: "Paper A"\npaper_id: "1111.00001"\n---\n')
        note_b = _write_note(tmp_path, "paper-notes/b.md", '---\ntitle: "Paper B"\npaper_id: "2222.00002"\n---\n')
        return _write_index(
            tmp_path,
            [
                {"doc_id": "doc-a", "title": "Paper A", "path": str(note_a), "tags": ["论文笔记"]},
                {"doc_id": "doc-b", "title": "Paper B", "path": str(note_b), "tags": ["论文笔记"]},
            ],
        )

    def test_cloud_edges_only_when_both_ends_local(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.upsert_relation(
            {
                "source_key": "1111.00001",
                "target_key": "2222.00002",
                "target_title": "Paper B",
                "rel_type": "extends",
                "confidence": 0.85,
                "reason": "builds on the method",
            }
        )
        store.upsert_relation(
            {
                "source_key": "1111.00001",
                "target_key": "cloud-only-uuid",
                "target_title": "Cloud Only Paper",
                "rel_type": "cites",
                "confidence": 1.0,
            }
        )
        store.close()
        index_path = self._two_note_index(tmp_path)
        export = build_graph_export(index_path)
        cloud = [e for e in export["edges"] if e["origin"] == "paperpulse"]
        assert cloud == [
            {
                "source": "doc-a",
                "target": "doc-b",
                "rel_type": "extends",
                "confidence": 0.85,
                "reason": "builds on the method",
                "match_method": None,
                "origin": "paperpulse",
            }
        ]
        assert export["stats"] == {"local_nodes": 2, "local_edges": 0, "cloud_edges": 1}

    def test_include_cloud_false_skips_cloud_edges(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.upsert_relation(
            {
                "source_key": "1111.00001",
                "target_key": "2222.00002",
                "target_title": "Paper B",
                "rel_type": "cites",
                "confidence": 1.0,
            }
        )
        store.close()
        index_path = self._two_note_index(tmp_path)
        export = build_graph_export(index_path, include_cloud=False)
        assert export["edges"] == []
        assert export["stats"]["cloud_edges"] == 0

    def test_cloud_edge_resolved_via_paperstore_title(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Relation key with no local frontmatter arxiv still resolves via store title → doc title."""
        store = _make_store(tmp_path, monkeypatch)
        store.upsert_paper({"arxiv_id": "3333.00003", "title": "Paper B"})
        store.upsert_relation(
            {
                "source_key": "1111.00001",
                "target_key": "3333.00003",
                "target_title": "Paper B",
                "rel_type": "cites",
                "confidence": 1.0,
            }
        )
        store.close()
        note_a = _write_note(tmp_path, "paper-notes/a.md", '---\ntitle: "Paper A"\npaper_id: "1111.00001"\n---\n')
        # doc-b has no arxiv anywhere; only its title matches the store title.
        index_path = _write_index(
            tmp_path,
            [
                {"doc_id": "doc-a", "title": "Paper A", "path": str(note_a), "tags": ["论文笔记"]},
                {"doc_id": "doc-b", "title": "Paper B!", "path": "misc/b.md", "tags": []},
            ],
        )
        export = build_graph_export(index_path)
        cloud = [e for e in export["edges"] if e["origin"] == "paperpulse"]
        assert len(cloud) == 1
        assert cloud[0]["target"] == "doc-b"


class TestNormalizeTitle:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Attention Is All You Need!", "attention is all you need"),
            ("  BERT: Pre-training   of Deep\nTransformers ", "bert pre training of deep transformers"),
            ("", ""),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert normalize_title(raw) == expected
