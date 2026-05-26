"""Tests for the agent control loop (agent.py)."""

import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

ENGINE = _ROOT / "scholar_agent" / "engine"
INDEX_PATH = _ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = _ROOT / "tests" / "fake_research_harness.py"

# Ensure scripts/ is importable

from scholar_agent.engine.agent import DomainAgent, Router, Researcher  # noqa: E402


def _build_index() -> None:
    """Build the test index once."""
    import subprocess
import sys
    subprocess.run(
        [sys.executable, str(ENGINE / "local_index.py"),
         "--knowledge-root", str(_ROOT / "tests" / "fixtures"),
         "--output", str(INDEX_PATH)],
        capture_output=True, text=True,
    )


class AgentStateMachineTest(unittest.TestCase):
    """Test that the agent follows the correct state transitions."""

    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_agent_routes_local_led_for_definition(self) -> None:
        a = DomainAgent(
            index_path=INDEX_PATH,
            research_script=FAKE_HARNESS,
        )
        output = a.run("what is a markov chain", dry_run=True)
        self.assertEqual("local-led", output["route"])
        self.assertEqual("dry_run", output["pipeline_status"])

        transitions = output["state_transitions"]
        states = [t["from"] for t in transitions]
        self.assertIn("route", states)
        self.assertIn("research", states)
        self.assertIn("synthesize", states)

    def test_agent_routes_web_led_for_freshness(self) -> None:
        a = DomainAgent(
            index_path=INDEX_PATH,
            research_script=FAKE_HARNESS,
        )
        output = a.run("latest QPE methods", dry_run=True)
        self.assertEqual("web-led", output["route"])

    def test_curate_flag_triggers_curate_state(self) -> None:
        a = DomainAgent(
            index_path=INDEX_PATH,
            research_script=FAKE_HARNESS,
        )
        output = a.run("what is a markov chain", dry_run=True, curate=True)
        transitions = output["state_transitions"]
        to_states = [t["to"] for t in transitions]
        self.assertIn("curate", to_states)

    def test_max_retries_refines_query(self) -> None:
        a = DomainAgent(
            index_path=INDEX_PATH,
            research_script=FAKE_HARNESS,
            max_retries=1,
        )
        # Even with retries, the agent should complete
        output = a.run("what is a markov chain", dry_run=True)
        self.assertIn(output["pipeline_status"], ("dry_run", "complete"))


class RouterTest(unittest.TestCase):
    """Test the Router role in isolation."""

    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_classify_definition_query(self) -> None:
        r = Router()
        route = r.classify("what is a markov chain", INDEX_PATH)
        self.assertEqual("local-led", route)

    def test_classify_freshness_query(self) -> None:
        r = Router()
        route = r.classify("latest SOTA quantization", INDEX_PATH)
        self.assertEqual("web-led", route)

    def test_should_research_web(self) -> None:
        r = Router()
        self.assertFalse(r.should_research_web("local-led"))
        self.assertTrue(r.should_research_web("web-led"))
        self.assertTrue(r.should_research_web("mixed"))

    def test_should_research_local(self) -> None:
        r = Router()
        self.assertTrue(r.should_research_local("local-led"))
        self.assertTrue(r.should_research_local("mixed"))
        self.assertTrue(r.should_research_local("web-led"))
        self.assertFalse(r.should_research_local("context-led"))


class ResearcherTest(unittest.TestCase):
    """Test the Researcher role in isolation."""

    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_gather_returns_structured_context(self) -> None:
        r = Researcher(index_path=INDEX_PATH, research_script=FAKE_HARNESS)
        ctx = r.gather("what is a markov chain", "local-led")
        for expected in ["query", "route", "direct_support", "inference_notes", "uncertainty_notes", "citations"]:
            self.assertIn(expected, ctx)

    def test_evidence_sufficiency_check(self) -> None:
        r = Researcher(index_path=INDEX_PATH, research_script=FAKE_HARNESS)
        ctx = r.gather("what is a markov chain", "local-led")
        sufficient, reason = r.is_evidence_sufficient(ctx)
        self.assertTrue(sufficient)

    def test_evidence_insufficient_on_empty(self) -> None:
        r = Researcher()
        sufficient, reason = r.is_evidence_sufficient({"direct_support": [], "uncertainty_notes": []})
        self.assertFalse(sufficient)
        self.assertEqual("No direct evidence found.", reason)


if __name__ == "__main__":
    unittest.main()
