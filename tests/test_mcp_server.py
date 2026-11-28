"""Tests for MCP server tool functions (logic only, no MCP transport)."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]

ENGINE = _ROOT / "src" / "scholar_agent" / "engine"

from scholar_agent.engine import scholar_config
from scholar_agent.engine.close_knowledge_loop import (
    QUALITY_THRESHOLD_SAVE_RESEARCH,
    quality_score_answer_data,
)
from scholar_agent.server import (
    _embedding_index_path,
    capture_answer,
    ingest_source,
    lint_knowledge,
    list_knowledge,
    query_knowledge,
    save_research,
    scan_stale_knowledge,
    validate_knowledge,
)

# Force config to always resolve to scholar-agent's own directories
# regardless of cwd, so tests don't leak files into parent projects.
_TEST_INDEX = _ROOT / "indexes" / "local" / "index.json"
_TEST_KNOWLEDGE = _ROOT / "tests" / "fixtures"


def _pin_test_config() -> None:
    scholar_config._config_cache = {
        "knowledge_dir": str(_TEST_KNOWLEDGE),
        "index_path": str(_TEST_INDEX),
        "scholar_dir": str(_ROOT),
    }


class _PinnedConfigTestCase(unittest.TestCase):
    """Pin scholar_config to the fixture/index dirs above for every test.

    Done in setUp, not at module import or setUpClass: conftest.py clears the
    process-wide config cache before each test (SCHOLAR_HOME isolation), which
    wipes anything pinned earlier.
    """

    def setUp(self) -> None:
        _pin_test_config()


def _build_index() -> None:
    _pin_test_config()
    _TEST_INDEX.parent.mkdir(parents=True, exist_ok=True)
    stale_marker = _TEST_INDEX.with_suffix(_TEST_INDEX.suffix + ".stale")
    if stale_marker.exists():
        stale_marker.unlink()
    subprocess.run(
        [
            sys.executable,
            str(ENGINE / "local_index.py"),
            "--knowledge-root",
            str(_TEST_KNOWLEDGE),
            "--full-rebuild",
            "--output",
            str(_TEST_INDEX),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_ROOT,
    )


def _cleanup_card(card_path_str: str) -> None:
    card_path = Path(card_path_str)
    if card_path.exists():
        card_path.unlink()
    # Remove empty parent dirs including knowledge root
    parent = card_path.parent
    while parent.exists() and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent
    _build_index()


class QueryKnowledgeTest(_PinnedConfigTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_query_returns_results(self) -> None:
        result = json.loads(query_knowledge("Markov chain"))
        self.assertIn("results", result)
        self.assertGreater(len(result["results"]), 0)

    def test_query_missing_index(self) -> None:
        result = json.loads(query_knowledge("test", limit=1))
        self.assertIn("results", result)

    def test_query_with_limit(self) -> None:
        result = json.loads(query_knowledge("Markov chain", limit=2))
        self.assertLessEqual(len(result["results"]), 2)


class SaveResearchTest(_PinnedConfigTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_save_valid_research(self) -> None:
        answer = {
            "answer": "This is a test answer that is long enough to pass the quality gate threshold of 200 characters. It includes substantive content about testing the save_research function in the MCP server, including validation and card building.",
            "sources": ["local:test-source"],
            "supporting_claims": [
                {
                    "claim": "The save_research function creates knowledge cards from structured JSON data",
                    "evidence_ids": ["local:test-source"],
                    "confidence": "high",
                },
            ],
            "inferences": ["test inference"],
            "uncertainty": [],
            "missing_evidence": [],
            "suggested_next_steps": [],
        }
        result = json.loads(save_research("test mcp save query", json.dumps(answer)))
        self.assertEqual("ok", result["status"])
        self.assertEqual([], result["schema_warnings"])
        _cleanup_card(result["card_path"])

    def test_save_invalid_json(self) -> None:
        result = json.loads(save_research("test", "not json at all"))
        self.assertIn("error", result)

    def test_save_missing_required_fields_rejected(self) -> None:
        result = json.loads(save_research("test", json.dumps({"wrong": True})))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])

    def test_save_research_triggers_reindex(self) -> None:
        """E6: save_research 写卡成功后必须触发一次 _async_reindex 重建索引。

        验证 server.save_research 末尾的 ``_async_reindex(index_path)`` 调用,
        避免新卡片落盘后索引陈旧。用 spy mock 记录调用,断言至少被调用一次。
        """
        answer = {
            "answer": (
                "This is a substantive answer that is long enough to pass the "
                "quality gate threshold of 200 characters. It describes how "
                "save_research should trigger an async reindex of the knowledge "
                "base so newly written cards become searchable immediately."
            ),
            "sources": ["local:reindex-trigger"],
            "supporting_claims": [
                {
                    "claim": "save_research writes the card then calls _async_reindex to refresh the index",
                    "evidence_ids": ["local:reindex-trigger"],
                    "confidence": "high",
                },
            ],
            "inferences": ["Reindex keeps the embedding index fresh after writes"],
            "uncertainty": [],
            "missing_evidence": [],
            "suggested_next_steps": [],
        }
        with patch("scholar_agent.server._async_reindex") as spy:
            result = json.loads(save_research("e6 reindex trigger test", json.dumps(answer)))
        try:
            self.assertEqual("ok", result["status"])
            self.assertGreaterEqual(spy.call_count, 1)
        finally:
            if result.get("card_path"):
                _cleanup_card(result["card_path"])


class ListKnowledgeTest(_PinnedConfigTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_list_all_cards(self) -> None:
        result = json.loads(list_knowledge())
        self.assertIn("cards", result)
        self.assertGreater(result["total"], 0)
        for card in result["cards"]:
            self.assertIn("id", card)
            self.assertIn("topic", card)

    def test_list_filtered_by_topic(self) -> None:
        result = json.loads(list_knowledge(topic="examples"))
        self.assertIn("cards", result)
        for card in result["cards"]:
            self.assertEqual("examples", card.get("topic"))

    def test_list_nonexistent_topic_returns_empty(self) -> None:
        result = json.loads(list_knowledge(topic="nonexistent_xyz"))
        self.assertEqual(0, result["total"])


class CaptureAnswerTest(_PinnedConfigTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_empty_query_rejected(self) -> None:
        result = json.loads(capture_answer("", "some answer"))
        self.assertIn("error", result)

    def test_empty_answer_rejected(self) -> None:
        result = json.loads(capture_answer("what is BM25", ""))
        self.assertIn("error", result)

    def test_success_creates_card(self) -> None:
        result = json.loads(
            capture_answer(
                "test capture query",
                "BM25 is a probabilistic ranking function used in information retrieval systems to estimate the relevance of documents to a given search query based on term frequency and document length.",
            )
        )
        self.assertEqual("ok", result["status"])
        self.assertIn("card_path", result)
        _cleanup_card(result["card_path"])

    def test_tags_passthrough(self) -> None:
        result = json.loads(
            capture_answer(
                "test tags capture",
                "This is a substantive test answer that exceeds the minimum character threshold for the capture_answer quality gate to ensure tags are properly passed through.",
                tags="ml, search",
            )
        )
        self.assertEqual("ok", result["status"])
        # Verify tags appear in the card content
        card_path = Path(result["card_path"])
        if card_path.exists():
            content = card_path.read_text(encoding="utf-8")
            self.assertIn("ml", content)
            self.assertIn("search", content)
        _cleanup_card(result["card_path"])


class IngestSourceTest(unittest.TestCase):
    def test_url_ingest_writes_source_refs_and_snapshot(self) -> None:
        content = "# Example Article\n\n" + "This fetched article body is long enough to be useful. " * 8
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            index = Path(tmp) / "index.json"
            with (
                patch("scholar_agent.server.get_knowledge_dir", return_value=root),
                patch("scholar_agent.server.get_index_path", return_value=index),
                patch("scholar_agent.server._async_reindex"),
                patch(
                    "scholar_agent.engine.research_harness.fetch_content",
                    return_value={
                        "retrieval_status": "succeeded",
                        "content_md": content,
                        "title": "Example Article",
                        "failure_reason": "",
                        "images": [],
                    },
                ),
            ):
                result = json.loads(
                    asyncio.run(ingest_source("https://example.com/article", tags="web, test", language="en"))
                )

            self.assertEqual("ok", result["status"])
            self.assertEqual("url", result["source_type"])
            self.assertTrue(result["snapshot_path"])
            self.assertTrue(result["captured_at"])

            card_text = Path(result["card_path"]).read_text(encoding="utf-8")
            self.assertIn("source_refs:", card_text)
            self.assertIn("https://example.com/article", card_text)
            self.assertIn("ingested-url", card_text)

            snapshot = Path(result["snapshot_path"])
            self.assertTrue(snapshot.exists())
            self.assertIn("https://example.com/article", snapshot.read_text(encoding="utf-8"))


def _write_governance_card(
    path: Path,
    *,
    card_id: str,
    title: str = "Test Card",
    updated_at: str = "2026-06-01",
    source_date: str = "2026-06-01",
    body: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not body:
        body = "This is a substantial body for governance validation. " * 8
    path.write_text(
        "\n".join(
            [
                "---",
                f"id: {card_id}",
                f"title: {title}",
                "type: knowledge",
                "topic: test",
                "confidence: confirmed",
                f"updated_at: {updated_at}",
                "domain: ai",
                f"source_date: {source_date}",
                "source_refs:",
                "  - https://example.com/source",
                "---",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )


class KnowledgeGovernanceToolTest(unittest.TestCase):
    def test_validate_knowledge_reports_schema_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_governance_card(root / "valid.md", card_id="valid-card")
            bad = root / "bad.md"
            bad.write_text(
                "---\nid: bad-card\ntype: knowledge\ntopic: test\nconfidence: confirmed\nupdated_at: 2026-06-01\n---\n\nbody",
                encoding="utf-8",
            )
            with patch("scholar_agent.server.get_knowledge_dir", return_value=root):
                result = json.loads(validate_knowledge(verbose=True))
        self.assertEqual("error", result["status"])
        self.assertEqual(2, result["total"])
        self.assertGreater(result["errors"], 0)
        self.assertTrue(any(card["id"] == "bad-card" for card in result["cards"]))

    def test_lint_knowledge_reports_broken_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_governance_card(
                root / "source.md",
                card_id="source-card",
                body="See [[missing-card]] for the comparison. " + "Extra detail. " * 20,
            )
            with patch("scholar_agent.server.get_knowledge_dir", return_value=root):
                result = json.loads(lint_knowledge(stale_days=30))
        self.assertEqual("issues", result["status"])
        self.assertEqual(1, result["total"])
        self.assertGreaterEqual(result["issue_count"], 1)
        self.assertEqual("missing-card", result["issues"]["broken_links"][0]["target"])

    def test_scan_stale_knowledge_skips_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_governance_card(root / "old.md", card_id="old-card", source_date="2020-01-01")
            _write_governance_card(root / "_snapshots" / "old-source.md", card_id="snapshot", source_date="2020-01-01")
            with patch("scholar_agent.server.get_knowledge_dir", return_value=root):
                result = json.loads(scan_stale_knowledge())
        self.assertEqual("ok", result["status"])
        self.assertEqual(1, result["stale_count"])
        self.assertEqual("old-card", result["stale"][0]["id"])


class QualityGateTest(unittest.TestCase):
    """Tests for the quality gate enforcement on card creation."""

    def test_save_research_rejects_thin_answer(self) -> None:
        answer = {
            "answer": "Too short",
            "supporting_claims": [
                {
                    "claim": "this claim is substantive enough to pass validation",
                    "evidence_ids": ["e1"],
                    "confidence": "high",
                },
            ],
        }
        result = json.loads(save_research("thin answer test", json.dumps(answer)))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])
        self.assertIn("violations", result)
        self.assertGreater(len(result["violations"]), 0)

    def test_save_research_rejects_zero_claims(self) -> None:
        answer = {
            "answer": "This answer is long enough but has no supporting claims at all, which means it should be rejected by the quality gate since claims are required.",
            "supporting_claims": [],
        }
        result = json.loads(save_research("zero claims test", json.dumps(answer)))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])

    def test_save_research_rejects_short_claims(self) -> None:
        answer = {
            "answer": "This answer is long enough and has claims but the claim text is too short to be meaningful, so the quality gate should reject it.",
            "supporting_claims": [
                {"claim": "short", "evidence_ids": ["e1"], "confidence": "high"},
            ],
        }
        result = json.loads(save_research("short claim test", json.dumps(answer)))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])

    def test_capture_answer_rejects_brief_answer(self) -> None:
        result = json.loads(capture_answer("brief test", "Too short"))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])

    def test_save_research_accepts_quality_answer(self) -> None:
        answer = {
            "answer": "This is a high-quality answer with sufficient length to pass all quality gates. It provides substantive content about the topic being researched and includes enough detail for a useful knowledge card.",
            "supporting_claims": [
                {
                    "claim": "Quality gates enforce minimum content standards on knowledge cards",
                    "evidence_ids": ["local:quality-gate"],
                    "confidence": "high",
                },
                {
                    "claim": "The scoring function evaluates answer length, claim count, claim depth, and structural richness",
                    "evidence_ids": ["local:quality-score"],
                    "confidence": "high",
                },
            ],
            "sources": ["local:quality-gate", "local:quality-score"],
            "inferences": ["Quality gates should reduce the number of thin, uninformative cards"],
            "uncertainty": ["Threshold values may need tuning based on real-world usage"],
            "suggested_next_steps": ["Monitor rejection rates and adjust thresholds"],
        }
        result = json.loads(save_research("quality answer test", json.dumps(answer)))
        self.assertEqual("ok", result["status"])
        _cleanup_card(result["card_path"])

    def test_save_research_rejects_quality_answer_without_sources(self) -> None:
        answer = {
            "answer": (
                "This is a high-quality answer with enough detail to pass the quality gate, but it intentionally "
                "omits sources so the provenance gate should reject it before any card is written to disk. The "
                "content explains why source tracking matters for later audits, link refreshes, evidence review, "
                "and safe reuse by future research agents."
            ),
            "supporting_claims": [
                {
                    "claim": "The provenance gate requires every saved research card to cite traceable sources",
                    "evidence_ids": ["local:missing-source"],
                    "confidence": "high",
                },
            ],
            "inferences": ["Unsourced research belongs in capture_answer, not save_research"],
            "uncertainty": ["The user can add concrete sources and retry"],
            "suggested_next_steps": ["Add a sources array with concrete source references"],
        }
        result = json.loads(save_research("missing sources test", json.dumps(answer)))
        self.assertIn("error", result)
        self.assertIn("Provenance gate failed", result["error"])
        self.assertTrue(any("sources" in violation for violation in result["violations"]))

    def test_save_research_rejects_claim_without_evidence_id(self) -> None:
        answer = {
            "answer": (
                "This answer includes source references and enough substantive discussion to pass the quality gate, "
                "but one supporting claim deliberately lacks evidence_ids so provenance validation must block the "
                "save. The scenario represents a partially structured research result where the source list exists, "
                "yet claim-level traceability is still incomplete."
            ),
            "sources": ["local:source-a"],
            "supporting_claims": [
                {
                    "claim": "Every supporting claim should point back to at least one evidence id",
                    "evidence_ids": [],
                    "confidence": "high",
                },
            ],
            "inferences": ["The card should not be persisted until evidence ids are attached"],
            "uncertainty": ["The caller can repair the structured JSON and retry"],
            "suggested_next_steps": ["Attach evidence_ids from the sources array"],
        }
        result = json.loads(save_research("missing evidence id test", json.dumps(answer)))
        self.assertIn("error", result)
        self.assertIn("Provenance gate failed", result["error"])
        self.assertTrue(any("evidence_ids" in violation for violation in result["violations"]))

    def test_quality_score_calculation(self) -> None:
        # A fully-populated answer should score well
        full_answer = {
            "answer": "A" * 500,
            "supporting_claims": [
                {"claim": "B" * 50, "evidence_ids": ["e1"], "confidence": "high"},
                {"claim": "C" * 50, "evidence_ids": ["e2"], "confidence": "medium"},
                {"claim": "D" * 50, "evidence_ids": ["e3"], "confidence": "low"},
            ],
            "inferences": ["inf1"],
            "uncertainty": ["unc1"],
            "missing_evidence": ["miss1"],
            "suggested_next_steps": ["step1"],
        }
        quality = quality_score_answer_data(full_answer, source="save_research")
        self.assertTrue(quality["passed"])
        self.assertGreaterEqual(quality["score"], QUALITY_THRESHOLD_SAVE_RESEARCH)
        self.assertEqual(0, len(quality["violations"]))

        # A minimal answer should fail
        thin_answer = {
            "answer": "short",
            "supporting_claims": [],
        }
        quality = quality_score_answer_data(thin_answer, source="save_research")
        self.assertFalse(quality["passed"])
        self.assertGreater(len(quality["violations"]), 0)


class ToolTimeoutTest(unittest.TestCase):
    """C3: configurable per-tool timeout resolution."""

    def setUp(self) -> None:
        self._saved = {k: os.environ.pop(k, None) for k in ("SCHOLAR_TOOL_TIMEOUT", "SCHOLAR_ANALYZE_PAPER_TIMEOUT")}

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_timeout(self) -> None:
        from scholar_agent.server import _tool_timeout

        self.assertEqual(600.0, _tool_timeout("analyze_paper"))
        self.assertIsNone(_tool_timeout("unknown_tool"))

    def test_global_env_override(self) -> None:
        from scholar_agent.server import _tool_timeout

        os.environ["SCHOLAR_TOOL_TIMEOUT"] = "42"
        self.assertEqual(42.0, _tool_timeout("analyze_paper"))

    def test_per_tool_env_takes_precedence(self) -> None:
        from scholar_agent.server import _tool_timeout

        os.environ["SCHOLAR_TOOL_TIMEOUT"] = "42"
        os.environ["SCHOLAR_ANALYZE_PAPER_TIMEOUT"] = "10"
        self.assertEqual(10.0, _tool_timeout("analyze_paper"))

    def test_non_positive_disables_timeout(self) -> None:
        from scholar_agent.server import _tool_timeout

        os.environ["SCHOLAR_ANALYZE_PAPER_TIMEOUT"] = "0"
        self.assertIsNone(_tool_timeout("analyze_paper"))

    def test_invalid_env_ignored(self) -> None:
        from scholar_agent.server import _tool_timeout

        os.environ["SCHOLAR_ANALYZE_PAPER_TIMEOUT"] = "not-a-number"
        self.assertEqual(600.0, _tool_timeout("analyze_paper"))


class RunBlockingTest(unittest.TestCase):
    """C3: _run_blocking runs work off-thread with timeout + progress."""

    def test_returns_result_and_reports_progress(self) -> None:
        from scholar_agent.server import _run_blocking

        events: list[float] = []

        class _Ctx:
            async def report_progress(self, progress, total=None, message=None):
                events.append(progress)

        result = asyncio.run(_run_blocking(lambda: "done", tool_name="unknown_tool", ctx=_Ctx()))
        self.assertEqual("done", result)
        self.assertEqual([0.0, 1.0], events)

    def test_timeout_returns_error_payload(self) -> None:
        from scholar_agent.server import _run_blocking

        os.environ["SCHOLAR_TOOL_TIMEOUT"] = "0.05"
        try:

            def _slow() -> str:
                time.sleep(0.5)
                return "never"

            result = json.loads(asyncio.run(_run_blocking(_slow, tool_name="analyze_paper")))
        finally:
            os.environ.pop("SCHOLAR_TOOL_TIMEOUT", None)
        self.assertEqual("timeout", result["status"])
        self.assertIn("timed out", result["error"])

    def test_no_ctx_is_fine(self) -> None:
        from scholar_agent.server import _run_blocking

        result = asyncio.run(_run_blocking(lambda: "ok", tool_name="unknown_tool"))
        self.assertEqual("ok", result)


class EmbeddingIndexPathTest(unittest.TestCase):
    """_embedding_index_path: the build-once-auto-enable probe (decision D1)."""

    def test_returns_path_when_embedding_index_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            idx.write_text("{}", encoding="utf-8")
            emb = Path(tmp) / "embeddings.json"
            emb.write_text("{}", encoding="utf-8")
            self.assertEqual(_embedding_index_path(idx), emb)

    def test_returns_none_when_embedding_index_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            idx.write_text("{}", encoding="utf-8")
            self.assertIsNone(_embedding_index_path(idx))


class ReindexEmbeddingTest(unittest.TestCase):
    """reindex refreshes the embedding index when one exists (decision D1)."""

    def test_reindex_rebuilds_embedding_when_present(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import reindex

        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            emb = Path(tmp) / "embeddings.json"
            emb.write_text("{}", encoding="utf-8")
            with patch("scholar_agent.engine.local_index.write_index") as mock_w:
                self.assertTrue(reindex(Path(tmp), idx))
            mock_w.assert_called_once()
            kwargs = mock_w.call_args.kwargs
            self.assertTrue(kwargs["build_embedding_index"])
            self.assertEqual(kwargs["embedding_output"], emb)

    def test_reindex_skips_embedding_when_absent(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import reindex

        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            with patch("scholar_agent.engine.local_index.write_index") as mock_w:
                self.assertTrue(reindex(Path(tmp), idx))
            kwargs = mock_w.call_args.kwargs
            self.assertFalse(kwargs["build_embedding_index"])


class ConfidenceFromQualityTest(unittest.TestCase):
    """confidence_from_quality never auto-promotes — structural quality is not
    factual trust, so every card starts at draft regardless of score (I3)."""

    def test_high_quality_still_draft(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import confidence_from_quality

        # Quality measures structure, not correctness — must not auto-promote.
        self.assertEqual(confidence_from_quality({"passed": True, "score": 0.8}), "draft")

    def test_low_quality_is_draft(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import confidence_from_quality

        self.assertEqual(confidence_from_quality({"passed": True, "score": 0.4}), "draft")

    def test_failed_gate_is_draft_even_if_score_high(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import confidence_from_quality

        self.assertEqual(confidence_from_quality({"passed": False, "score": 0.9}), "draft")


if __name__ == "__main__":
    unittest.main()
