"""Tests for knowledge lifecycle management and governance."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

ENGINE = _ROOT / "src" / "scholar_agent" / "engine"
KNOWLEDGE_ROOT = _ROOT / "knowledge"


class CardValidationTest(unittest.TestCase):
    """Test card schema validation."""

    def test_validate_valid_card(self) -> None:
        code = (
            "from scholar_agent.engine.knowledge_lifecycle import validate_card; "
            "issues = validate_card({"
            "'id': 'test', 'title': 'Test', 'type': 'knowledge', "
            "'topic': 'test', 'confidence': 'confirmed', 'updated_at': '2026-04-02', "
            "'tags': ['test'], 'source_refs': ['local:seed'], 'review_status': 'trusted'"
            "}); "
            "errors = [i for i in issues if i.severity == 'error']; "
            "print(len(errors))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual("0", result.stdout.strip())

    def test_validate_missing_required_field(self) -> None:
        code = (
            "from scholar_agent.engine.knowledge_lifecycle import validate_card; "
            "issues = validate_card({'id': 'test'}); "
            "errors = [i for i in issues if i.severity == 'error']; "
            "fields = [e.field for e in errors]; "
            "import json; print(json.dumps(sorted(fields)))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        fields = json.loads(result.stdout.strip())
        for required in ["title", "type", "topic", "confidence", "updated_at"]:
            self.assertIn(required, fields)

    def test_validate_invalid_type(self) -> None:
        code = (
            "from scholar_agent.engine.knowledge_lifecycle import validate_card; "
            "issues = validate_card({"
            "'id': 't', 'title': 'T', 'type': 'invalid', "
            "'topic': 't', 'confidence': 'confirmed', 'updated_at': '2026-04-02'"
            "}); "
            "errors = [i for i in issues if i.field == 'type']; "
            "print(len(errors))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual("1", result.stdout.strip())


class LifecycleTransitionTest(unittest.TestCase):
    """Test lifecycle state transitions."""

    def test_valid_transition_draft_to_reviewed(self) -> None:
        code = (
            "from scholar_agent.engine.knowledge_lifecycle import transition_card, LifecycleState; "
            "meta = {'confidence': 'draft', 'review_status': 'draft'}; "
            "updated, error = transition_card(meta, LifecycleState.REVIEWED); "
            "print(error, updated.get('review_status'))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        parts = result.stdout.strip().split(" ", 1)
        self.assertEqual("None", parts[0])
        self.assertEqual("reviewed", parts[1])

    def test_invalid_transition_trusted_to_draft(self) -> None:
        code = (
            "from scholar_agent.engine.knowledge_lifecycle import transition_card, LifecycleState; "
            "meta = {'review_status': 'trusted'}; "
            "updated, error = transition_card(meta, LifecycleState.DRAFT); "
            "print(error is not None)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual("True", result.stdout.strip())

    def test_deprecated_is_terminal(self) -> None:
        code = (
            "from scholar_agent.engine.knowledge_lifecycle import transition_card, LifecycleState; "
            "meta = {'review_status': 'deprecated'}; "
            "updated, error = transition_card(meta, LifecycleState.DRAFT); "
            "print(error is not None)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual("True", result.stdout.strip())


class DuplicateDetectionTest(unittest.TestCase):
    """Test duplicate card detection."""

    def test_detect_identical_id(self) -> None:
        code = (
            "from scholar_agent.engine.knowledge_lifecycle import detect_duplicates; "
            "cards = ["
            "{'id': 'a', 'title': 'Card A', 'topic': 'test', 'type': 'definition'}, "
            "{'id': 'a', 'title': 'Card A', 'topic': 'test', 'type': 'definition'}"
            "]; "
            "dupes = detect_duplicates(cards); "
            "print(len(dupes), dupes[0][3])"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        parts = result.stdout.strip().split(" ")
        self.assertEqual("1", parts[0])
        self.assertEqual("identical_id", parts[1])

    def test_no_duplicates(self) -> None:
        code = (
            "from scholar_agent.engine.knowledge_lifecycle import detect_duplicates; "
            "cards = ["
            "{'id': 'a', 'title': 'Card A', 'topic': 'math', 'type': 'definition'}, "
            "{'id': 'b', 'title': 'Card B', 'topic': 'physics', 'type': 'method'}"
            "]; "
            "dupes = detect_duplicates(cards); "
            "print(len(dupes))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual("0", result.stdout.strip())


class GovernanceCLITest(unittest.TestCase):
    """Test the governance CLI tool."""

    def test_scan_command(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ENGINE / "knowledge_governance.py"), "scan"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertIn("Knowledge base:", result.stdout)

    def test_validate_command(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ENGINE / "knowledge_governance.py"), "validate", "-v"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        # May return 1 if there are errors, but should not crash
        self.assertIn("Validated", result.stdout)

    def test_duplicates_command(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ENGINE / "knowledge_governance.py"), "duplicates"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        # duplicates 命令输出 "Found N potential duplicate(s):" — 断言核心语义词,
        # 不绑定易变的人话措辞(原 "cards" 断言在措辞调整后失效)。
        self.assertIn("duplicate", result.stdout.lower())

    def test_transitions_command(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ENGINE / "knowledge_governance.py"), "transitions"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertIn("draft", result.stdout)
        self.assertIn("trusted", result.stdout)

    def test_lint_command(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ENGINE / "knowledge_governance.py"), "lint", "--stale-days", "365"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        # lint returns 1 if issues found, but should not crash
        self.assertIn("cards", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
