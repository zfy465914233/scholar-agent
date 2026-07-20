"""Unit tests for scholar_agent.engine.knowledge_lifecycle pure functions.

Tests validate_card, transition_card, and detect_duplicates using direct
imports (no subprocess).
"""

import tempfile
import unittest
from pathlib import Path

from scholar_agent.engine.knowledge_lifecycle import (
    CONFIDENCE_LEVELS,
    ORIGINS,
    VALID_TRANSITIONS,
    CardIssue,
    LifecycleState,
    _card_signature,
    _normalize_for_comparison,
    detect_duplicates,
    scan_knowledge_dir,
    transition_card,
    validate_card,
)

# ── validate_card ──────────────────────────────────────────────────


class TestScanKnowledgeDir(unittest.TestCase):
    def test_skips_internal_snapshot_cards(self):
        import tempfile
        from pathlib import Path

        root = Path(tempfile.mkdtemp(prefix="knowledge_scan_"))
        real = root / "domain" / "real.md"
        real.parent.mkdir(parents=True)
        real.write_text("---\nid: real\ntitle: Real\n---\nBody\n", encoding="utf-8")
        snap = root / "_snapshots" / "source.md"
        snap.parent.mkdir(parents=True)
        snap.write_text("---\nid: snapshot\ntitle: Snapshot\n---\nArchived source\n", encoding="utf-8")

        cards = scan_knowledge_dir(root)

        self.assertEqual(["real"], [card["id"] for card in cards])


class TestValidateCardValid(unittest.TestCase):
    """Tests for a fully valid card."""

    def _valid_card(self, **overrides):
        base = {
            "id": "test-001",
            "title": "Test Card",
            "type": "knowledge",
            "topic": "testing",
            "confidence": "confirmed",
            "updated_at": "2026-04-01",
            "tags": ["test"],
            "source_refs": ["local:seed"],
            "review_status": "trusted",
        }
        base.update(overrides)
        return base

    def test_fully_valid_card_has_no_errors(self):
        issues = validate_card(self._valid_card())
        errors = [i for i in issues if i.severity == "error"]
        self.assertEqual(len(errors), 0)

    def test_valid_card_with_method_type(self):
        issues = validate_card(self._valid_card(type="method"))
        errors = [i for i in issues if i.severity == "error"]
        self.assertEqual(len(errors), 0)

    def test_valid_card_with_all_confidence_levels(self):
        for level in CONFIDENCE_LEVELS:
            with self.subTest(confidence=level):
                issues = validate_card(self._valid_card(confidence=level))
                errors = [i for i in issues if i.severity == "error" and i.field == "confidence"]
                self.assertEqual(len(errors), 0)

    def test_valid_card_with_all_origins(self):
        for origin in ORIGINS:
            with self.subTest(origin=origin):
                issues = validate_card(self._valid_card(origin=origin))
                errors = [i for i in issues if i.severity == "error" and i.field == "origin"]
                self.assertEqual(len(errors), 0)

    def test_generated_draft_card_values_are_valid(self):
        issues = validate_card(
            self._valid_card(
                confidence="draft",
                origin="web_research_with_synthesis",
                review_status="draft",
            )
        )
        self.assertEqual([], [i for i in issues if i.field == "confidence" and i.severity == "error"])
        self.assertEqual([], [i for i in issues if i.field == "origin"])


class TestValidateCardMissingRequired(unittest.TestCase):
    """Tests for missing required fields."""

    def test_missing_all_required_fields(self):
        issues = validate_card({})
        error_fields = {i.field for i in issues if i.severity == "error"}
        required = {"id", "title", "type", "topic", "confidence", "updated_at"}
        self.assertTrue(required.issubset(error_fields))

    def test_missing_id(self):
        card = {"title": "T", "type": "knowledge", "topic": "t", "confidence": "confirmed", "updated_at": "2026-04-01"}
        issues = validate_card(card)
        error_fields = [i.field for i in issues if i.severity == "error"]
        self.assertIn("id", error_fields)

    def test_missing_title(self):
        card = {"id": "x", "type": "knowledge", "topic": "t", "confidence": "confirmed", "updated_at": "2026-04-01"}
        issues = validate_card(card)
        error_fields = [i.field for i in issues if i.severity == "error"]
        self.assertIn("title", error_fields)

    def test_missing_type(self):
        card = {"id": "x", "title": "T", "topic": "t", "confidence": "confirmed", "updated_at": "2026-04-01"}
        issues = validate_card(card)
        error_fields = [i.field for i in issues if i.severity == "error"]
        self.assertIn("type", error_fields)

    def test_missing_topic(self):
        card = {"id": "x", "title": "T", "type": "knowledge", "confidence": "confirmed", "updated_at": "2026-04-01"}
        issues = validate_card(card)
        error_fields = [i.field for i in issues if i.severity == "error"]
        self.assertIn("topic", error_fields)

    def test_missing_confidence(self):
        card = {"id": "x", "title": "T", "type": "knowledge", "topic": "t", "updated_at": "2026-04-01"}
        issues = validate_card(card)
        error_fields = [i.field for i in issues if i.severity == "error"]
        self.assertIn("confidence", error_fields)

    def test_missing_updated_at(self):
        card = {"id": "x", "title": "T", "type": "knowledge", "topic": "t", "confidence": "confirmed"}
        issues = validate_card(card)
        error_fields = [i.field for i in issues if i.severity == "error"]
        self.assertIn("updated_at", error_fields)

    def test_empty_string_counts_as_missing(self):
        card = {"id": "", "title": "", "type": "", "topic": "", "confidence": "", "updated_at": ""}
        issues = validate_card(card)
        error_fields = [
            i.field
            for i in issues
            if i.severity == "error" and i.field in {"id", "title", "type", "topic", "confidence", "updated_at"}
        ]
        # All 6 should be flagged as missing (empty string is falsy)
        self.assertEqual(len(error_fields), 6)


class TestValidateCardInvalidValues(unittest.TestCase):
    """Tests for invalid values in optional/enum fields."""

    def _base(self, **overrides):
        base = {
            "id": "x",
            "title": "T",
            "type": "knowledge",
            "topic": "t",
            "confidence": "confirmed",
            "updated_at": "2026-04-01",
        }
        base.update(overrides)
        return base

    def test_invalid_type(self):
        issues = validate_card(self._base(type="invalid_type"))
        type_errors = [i for i in issues if i.field == "type" and i.severity == "error"]
        self.assertEqual(len(type_errors), 1)
        self.assertIn("invalid_type", type_errors[0].message)

    def test_invalid_confidence(self):
        issues = validate_card(self._base(confidence="absolutely"))
        conf_errors = [i for i in issues if i.field == "confidence" and i.severity == "error"]
        self.assertEqual(len(conf_errors), 1)

    def test_invalid_origin_gives_warning(self):
        issues = validate_card(self._base(origin="alien_source"))
        origin_issues = [i for i in issues if i.field == "origin"]
        self.assertEqual(len(origin_issues), 1)
        self.assertEqual(origin_issues[0].severity, "warning")

    def test_invalid_review_status(self):
        issues = validate_card(self._base(review_status="invalid_state"))
        rs_errors = [i for i in issues if i.field == "review_status" and i.severity == "error"]
        self.assertEqual(len(rs_errors), 1)

    def test_tags_not_a_list(self):
        issues = validate_card(self._base(tags="not-a-list"))
        tag_errors = [i for i in issues if i.field == "tags" and i.severity == "error"]
        self.assertEqual(len(tag_errors), 1)
        self.assertIn("must be a list", tag_errors[0].message)

    def test_tags_as_list_is_valid(self):
        issues = validate_card(self._base(tags=["a", "b"]))
        tag_errors = [i for i in issues if i.field == "tags" and i.severity == "error"]
        self.assertEqual(len(tag_errors), 0)

    def test_missing_recommended_tags_gives_warning(self):
        issues = validate_card(self._base())
        tag_warnings = [i for i in issues if i.field == "tags" and i.severity == "warning"]
        self.assertTrue(len(tag_warnings) >= 1)

    def test_missing_recommended_source_refs_gives_warning(self):
        issues = validate_card(self._base())
        sr_warnings = [i for i in issues if i.field == "source_refs" and i.severity == "warning"]
        self.assertTrue(len(sr_warnings) >= 1)

    def test_promoted_origin_without_review_status_warns(self):
        issues = validate_card(self._base(origin="promoted"))
        rs_warnings = [i for i in issues if i.field == "review_status" and i.severity == "warning"]
        self.assertEqual(len(rs_warnings), 1)

    def test_distilled_origin_without_review_status_warns(self):
        issues = validate_card(self._base(origin="distilled"))
        rs_warnings = [i for i in issues if i.field == "review_status" and i.severity == "warning"]
        self.assertEqual(len(rs_warnings), 1)

    def test_card_issue_dataclass_fields(self):
        issue = CardIssue("error", "test_field", "test message")
        self.assertEqual(issue.severity, "error")
        self.assertEqual(issue.field, "test_field")
        self.assertEqual(issue.message, "test message")


# ── transition_card ───────────────────────────────────────────────


class TestTransitionCardValid(unittest.TestCase):
    """Tests for valid lifecycle state transitions."""

    def test_draft_to_reviewed(self):
        meta = {"review_status": "draft"}
        updated, error = transition_card(meta, LifecycleState.REVIEWED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "reviewed")

    def test_draft_to_deprecated(self):
        meta = {"review_status": "draft"}
        updated, error = transition_card(meta, LifecycleState.DEPRECATED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "deprecated")

    def test_reviewed_to_trusted(self):
        meta = {"review_status": "reviewed"}
        updated, error = transition_card(meta, LifecycleState.TRUSTED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "trusted")

    def test_reviewed_to_stale(self):
        meta = {"review_status": "reviewed"}
        updated, error = transition_card(meta, LifecycleState.STALE)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "stale")

    def test_reviewed_to_deprecated(self):
        meta = {"review_status": "reviewed"}
        updated, error = transition_card(meta, LifecycleState.DEPRECATED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "deprecated")

    def test_trusted_to_stale(self):
        meta = {"review_status": "trusted"}
        updated, error = transition_card(meta, LifecycleState.STALE)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "stale")

    def test_trusted_to_deprecated(self):
        meta = {"review_status": "trusted"}
        updated, error = transition_card(meta, LifecycleState.DEPRECATED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "deprecated")

    def test_stale_to_reviewed(self):
        meta = {"review_status": "stale"}
        updated, error = transition_card(meta, LifecycleState.REVIEWED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "reviewed")

    def test_stale_to_trusted(self):
        meta = {"review_status": "stale"}
        updated, error = transition_card(meta, LifecycleState.TRUSTED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "trusted")

    def test_stale_to_deprecated(self):
        meta = {"review_status": "stale"}
        updated, error = transition_card(meta, LifecycleState.DEPRECATED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "deprecated")

    def test_missing_review_status_defaults_to_draft(self):
        meta = {}
        updated, error = transition_card(meta, LifecycleState.REVIEWED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "reviewed")


class TestTransitionCardInvalid(unittest.TestCase):
    """Tests for invalid lifecycle state transitions."""

    def test_trusted_to_draft(self):
        meta = {"review_status": "trusted"}
        updated, error = transition_card(meta, LifecycleState.DRAFT)
        self.assertIsNotNone(error)
        self.assertEqual(updated["review_status"], "trusted")

    def test_draft_to_trusted_is_valid(self):
        # draft → trusted is now legal: a user can vouch for a draft directly
        # via review_card. (Only the auto dead-link sweep opts out of staling
        # drafts — that's a product choice in _mark_stale, not a state-machine
        # rule.) Kept in this class to document the contrast with trusted→draft.
        meta = {"review_status": "draft"}
        updated, error = transition_card(meta, LifecycleState.TRUSTED)
        self.assertIsNone(error)
        self.assertEqual(updated["review_status"], "trusted")

    def test_deprecated_to_anything(self):
        for target in LifecycleState:
            with self.subTest(target=target):
                meta = {"review_status": "deprecated"}
                _updated, error = transition_card(meta, target)
                if target == LifecycleState.DEPRECATED:
                    # Transitioning to same state is also not in VALID_TRANSITIONS
                    self.assertIsNotNone(error)
                else:
                    self.assertIsNotNone(error)

    def test_invalid_current_state(self):
        meta = {"review_status": "nonexistent"}
        _updated, error = transition_card(meta, LifecycleState.REVIEWED)
        self.assertIsNotNone(error)
        self.assertIn("not a valid lifecycle state", error)

    def test_transition_mutates_metadata(self):
        """Verify transition_card mutates the passed dict."""
        meta = {"review_status": "draft"}
        updated, error = transition_card(meta, LifecycleState.REVIEWED)
        self.assertIsNone(error)
        self.assertIs(updated, meta)


# ── detect_duplicates ─────────────────────────────────────────────


class TestDetectDuplicates(unittest.TestCase):
    """Tests for duplicate card detection."""

    def test_exact_id_duplicate(self):
        cards = [
            {"id": "same", "title": "Card A", "topic": "t", "type": "knowledge"},
            {"id": "same", "title": "Card B", "topic": "t", "type": "knowledge"},
        ]
        dupes = detect_duplicates(cards)
        self.assertEqual(len(dupes), 1)
        self.assertEqual(dupes[0][0], 0)
        self.assertEqual(dupes[0][1], 1)
        self.assertEqual(dupes[0][2], 1.0)
        self.assertEqual(dupes[0][3], "identical_id")

    def test_identical_signature(self):
        cards = [
            {"id": "a", "title": "Same Title", "topic": "math", "type": "knowledge"},
            {"id": "b", "title": "Same Title", "topic": "math", "type": "knowledge"},
        ]
        dupes = detect_duplicates(cards)
        self.assertEqual(len(dupes), 1)
        self.assertEqual(dupes[0][3], "identical_signature")

    def test_similar_titles_same_topic(self):
        cards = [
            {"id": "a", "title": "What is a Markov Chain", "topic": "probability", "type": "knowledge"},
            {"id": "b", "title": "What is a Markov Chain process", "topic": "probability", "type": "method"},
        ]
        dupes = detect_duplicates(cards)
        self.assertTrue(len(dupes) >= 1)
        reasons = [d[3] for d in dupes]
        self.assertIn("similar_title", reasons)

    def test_similar_titles_different_topic_not_flagged(self):
        cards = [
            {"id": "a", "title": "What is a Markov Chain", "topic": "probability"},
            {"id": "b", "title": "What is a Markov Chain", "topic": "nlp"},
        ]
        dupes = detect_duplicates(cards, similarity_threshold=0.8)
        # Should not flag similar_title because topics differ
        similar_title_dupes = [d for d in dupes if d[3] == "similar_title"]
        self.assertEqual(len(similar_title_dupes), 0)

    def test_no_duplicates(self):
        cards = [
            {"id": "a", "title": "Card A", "topic": "math", "type": "knowledge"},
            {"id": "b", "title": "Card B", "topic": "physics", "type": "method"},
        ]
        dupes = detect_duplicates(cards)
        self.assertEqual(len(dupes), 0)

    def test_empty_list(self):
        dupes = detect_duplicates([])
        self.assertEqual(len(dupes), 0)

    def test_single_card(self):
        dupes = detect_duplicates([{"id": "a", "title": "Only One"}])
        self.assertEqual(len(dupes), 0)

    def test_custom_threshold(self):
        cards = [
            {"id": "a", "title": "Alpha Beta Gamma", "topic": "math"},
            {"id": "b", "title": "Alpha Beta Delta", "topic": "math"},
        ]
        # With a high threshold, these might not be flagged
        dupes_high = detect_duplicates(cards, similarity_threshold=0.99)
        similar_high = [d for d in dupes_high if d[3] == "similar_title"]
        # With a lower threshold, they should be flagged
        dupes_low = detect_duplicates(cards, similarity_threshold=0.5)
        similar_low = [d for d in dupes_low if d[3] == "similar_title"]
        self.assertGreaterEqual(len(similar_low), len(similar_high))

    def test_cards_with_empty_ids(self):
        cards = [
            {"id": "", "title": "Card A", "topic": "t", "type": "knowledge"},
            {"id": "", "title": "Card B", "topic": "t", "type": "knowledge"},
        ]
        # Empty IDs should not trigger identical_id (falsy check)
        dupes = detect_duplicates(cards)
        id_dupes = [d for d in dupes if d[3] == "identical_id"]
        self.assertEqual(len(id_dupes), 0)

    def test_three_cards_pairwise_check(self):
        cards = [
            {"id": "a", "title": "Alpha", "topic": "t1"},
            {"id": "b", "title": "Beta", "topic": "t1"},
            {"id": "a", "title": "Alpha Dupe", "topic": "t1"},
        ]
        dupes = detect_duplicates(cards)
        # Card 0 and Card 2 share the same id "a"
        id_dupes = [(i, j) for i, j, _, _ in dupes]
        self.assertIn((0, 2), id_dupes)

    def test_similarity_score_is_rounded(self):
        cards = [
            {"id": "a", "title": "Alpha Beta Gamma Delta", "topic": "math"},
            {"id": "b", "title": "Alpha Beta Gamma Epsilon", "topic": "math"},
        ]
        dupes = detect_duplicates(cards, similarity_threshold=0.5)
        for _i, _j, score, reason in dupes:
            if reason == "similar_title":
                # Score should be rounded to 2 decimal places
                self.assertEqual(score, round(score, 2))


# ── internal helpers ───────────────────────────────────────────────


class TestInternalHelpers(unittest.TestCase):
    """Tests for _card_signature and _normalize_for_comparison."""

    def test_card_signature_lowercases_and_joins(self):
        meta = {"title": "My Title", "topic": "My Topic", "type": "Knowledge"}
        sig = _card_signature(meta)
        self.assertEqual(sig, "my topic::knowledge::my title")

    def test_card_signature_missing_fields(self):
        sig = _card_signature({})
        # f"{topic}::{type}::{title}" with all empty => "::::"
        self.assertEqual(sig, "::::")

    def test_normalize_collapses_whitespace(self):
        self.assertEqual(_normalize_for_comparison("  hello   world  "), "hello world")

    def test_normalize_lowercases(self):
        self.assertEqual(_normalize_for_comparison("Hello WORLD"), "hello world")

    def test_normalize_strips(self):
        self.assertEqual(_normalize_for_comparison("  text  "), "text")


class TestLifecycleStateEnum(unittest.TestCase):
    """Tests for the LifecycleState enum."""

    def test_all_states_have_transitions_entry(self):
        for state in LifecycleState:
            self.assertIn(state, VALID_TRANSITIONS)

    def test_deprecated_has_empty_transitions(self):
        self.assertEqual(len(VALID_TRANSITIONS[LifecycleState.DEPRECATED]), 0)

    def test_state_string_values(self):
        self.assertEqual(LifecycleState.DRAFT.value, "draft")
        self.assertEqual(LifecycleState.REVIEWED.value, "reviewed")
        self.assertEqual(LifecycleState.TRUSTED.value, "trusted")
        self.assertEqual(LifecycleState.STALE.value, "stale")
        self.assertEqual(LifecycleState.DEPRECATED.value, "deprecated")


# ── deprecated terminal state at the index layer (I4) ──────────────


class TestDeprecatedExcludedFromIndex(unittest.TestCase):
    """The deprecated terminal state must land at the index layer.

    A deprecated card is known-bad (I4) and must never enter ``index.json`` —
    that way it can never be retrieved. The source ``.md`` stays on disk for
    provenance (I2). Guards the build_index / build_index_incremental filter.
    """

    @staticmethod
    def _card(directory: Path, name: str, *, review_status: str | None = None, confidence: str | None = None) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        body = "deep learning survey methods fundamentals " * 10
        lines = [
            "---",
            f"id: {name[:-3]}",
            "title: T",
            "type: knowledge",
            "topic: x",
        ]
        if confidence is not None:
            lines.append(f"confidence: {confidence}")
        if review_status is not None:
            lines.append(f"review_status: {review_status}")
        lines += ["---", "", body]
        path = directory / name
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_build_index_drops_deprecated_card(self) -> None:
        from scholar_agent.engine.local_index import build_index

        root = Path(tempfile.mkdtemp(prefix="dep_idx_"))
        self._card(root, "good.md", confidence="confirmed")
        # confidence == "deprecated" => trust tier deprecated
        self._card(root, "bad.md", confidence="deprecated")
        payload = build_index(root, extra_dirs=[])
        ids = {d["doc_id"] for d in payload["documents"]}
        self.assertIn("good", ids)
        self.assertNotIn("bad", ids)  # deprecated never enters the index

    def test_build_index_drops_deprecated_review_status(self) -> None:
        from scholar_agent.engine.local_index import build_index

        root = Path(tempfile.mkdtemp(prefix="dep_idx_"))
        self._card(root, "good.md", review_status="reviewed", confidence="confirmed")
        self._card(root, "bad.md", review_status="deprecated", confidence="confirmed")
        payload = build_index(root, extra_dirs=[])
        ids = {d["doc_id"] for d in payload["documents"]}
        self.assertIn("good", ids)
        self.assertNotIn("bad", ids)

    def test_incremental_index_drops_deprecated(self) -> None:
        from scholar_agent.engine.local_index import build_index_incremental

        root = Path(tempfile.mkdtemp(prefix="dep_inc_"))
        idx = root / "index.json"
        self._card(root, "good.md", confidence="confirmed")
        self._card(root, "bad.md", confidence="deprecated")
        # build_index_incremental returns the payload (the caller persists
        # index.json); deprecated cards must be absent from it on every pass.
        payload = build_index_incremental(root, idx, extra_dirs=[])
        ids = {d["doc_id"] for d in payload["documents"]}
        self.assertNotIn("bad", ids)
        self.assertIn("good", ids)
        # Second pass (manifest now exists): a deprecated entry that could
        # linger from an older persisted index is re-filtered here too.
        payload = build_index_incremental(root, idx, extra_dirs=[])
        ids = {d["doc_id"] for d in payload["documents"]}
        self.assertNotIn("bad", ids)


if __name__ == "__main__":
    unittest.main()
