"""Tests for the agent control loop (agent.py)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = ROOT / "tests" / "fake_research_harness.py"


def _inline(script: str) -> str:
    """Build inline Python that imports Path and agent module."""
    return (
        "from pathlib import Path; "
        "from agent import DomainAgent, Router, Researcher; "
        "import json; "
        + script
    )


class AgentStateMachineTest(unittest.TestCase):
    """Test that the agent follows the correct state transitions."""

    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "local_index.py"), "--knowledge-root", str(ROOT / "tests" / "fixtures"), "--output", str(INDEX_PATH)],
            capture_output=True,
            text=True,
        )

    def test_agent_routes_local_led_for_definition(self) -> None:
        code = _inline(
            f"a = DomainAgent(index_path=Path('{INDEX_PATH}'), research_script=Path('{FAKE_HARNESS}')); "
            "print(json.dumps(a.run('what is a markov chain', dry_run=True)))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("local-led", output["route"])
        self.assertEqual("dry_run", output["pipeline_status"])

        transitions = output["state_transitions"]
        states = [t["from"] for t in transitions]
        self.assertIn("route", states)
        self.assertIn("research", states)
        self.assertIn("synthesize", states)

    def test_agent_routes_web_led_for_freshness(self) -> None:
        code = _inline(
            f"a = DomainAgent(index_path=Path('{INDEX_PATH}'), research_script=Path('{FAKE_HARNESS}')); "
            "print(json.dumps(a.run('latest QPE methods', dry_run=True)))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("web-led", output["route"])


class RouterTest(unittest.TestCase):
    """Test the Router role in isolation."""

    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "local_index.py"), "--knowledge-root", str(ROOT / "tests" / "fixtures"), "--output", str(INDEX_PATH)],
            capture_output=True, text=True,
        )

    def test_classify_definition_query(self) -> None:
        code = (
            f"from pathlib import Path; from agent import Router; "
            f"r = Router(); print(r.classify('what is a markov chain', Path('{INDEX_PATH}')))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual("local-led", result.stdout.strip())

    def test_classify_freshness_query(self) -> None:
        code = (
            f"from pathlib import Path; from agent import Router; "
            f"r = Router(); print(r.classify('latest SOTA quantization', Path('{INDEX_PATH}')))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual("web-led", result.stdout.strip())

    def test_should_research_web(self) -> None:
        code = (
            "from agent import Router; r = Router(); "
            "print(r.should_research_web('local-led')); "
            "print(r.should_research_web('web-led')); "
            "print(r.should_research_web('mixed'));"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        lines = result.stdout.strip().split("\n")
        self.assertEqual("False", lines[0])
        self.assertEqual("True", lines[1])
        self.assertEqual("True", lines[2])


class ResearcherTest(unittest.TestCase):
    """Test the Researcher role in isolation."""

    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "local_index.py"), "--knowledge-root", str(ROOT / "tests" / "fixtures"), "--output", str(INDEX_PATH)],
            capture_output=True, text=True,
        )

    def test_gather_returns_structured_context(self) -> None:
        code = _inline(
            f"r = Researcher(index_path=Path('{INDEX_PATH}'), research_script=Path('{FAKE_HARNESS}')); "
            "ctx = r.gather('what is a markov chain', 'local-led'); "
            "print(json.dumps(sorted(ctx.keys())))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        keys = json.loads(result.stdout)
        for expected in ["query", "route", "direct_support", "inference_notes", "uncertainty_notes", "citations"]:
            self.assertIn(expected, keys)

    def test_evidence_sufficiency_check(self) -> None:
        code = _inline(
            f"r = Researcher(index_path=Path('{INDEX_PATH}'), research_script=Path('{FAKE_HARNESS}')); "
            "ctx = r.gather('what is a markov chain', 'local-led'); "
            "sufficient, reason = r.is_evidence_sufficient(ctx); "
            "print(sufficient, reason)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertTrue(result.stdout.strip().startswith("True"))

    def test_evidence_insufficient_on_empty(self) -> None:
        code = (
            "from agent import Researcher; "
            "r = Researcher(); "
            "sufficient, reason = r.is_evidence_sufficient({'direct_support': [], 'uncertainty_notes': []}); "
            "print(sufficient, reason)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertTrue(result.stdout.strip().startswith("False"))


if __name__ == "__main__":
    unittest.main()
