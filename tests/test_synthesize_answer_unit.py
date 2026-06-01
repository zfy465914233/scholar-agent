"""Direct-import tests for synthesize_answer pure functions."""

import json
import tempfile
import unittest
from pathlib import Path

from scholar_agent.engine.synthesize_answer import (
    ANSWER_SYSTEM_PROMPT,
    build_chat_request,
    build_synthesis_output,
    load_prompt_bundle,
    parse_answer,
    synthesize,
    validate_claims,
)

SAMPLE_BUNDLE = {
    "system_prompt": "Answer from evidence.",
    "user_prompt": "What is X?",
    "metadata": {"query": "what is x", "route": "local"},
    "citations": [{"evidence_id": "ev-1", "origin": "local"}],
}


class TestBuildChatRequest(unittest.TestCase):
    def test_builds_three_messages(self) -> None:
        req = build_chat_request(SAMPLE_BUNDLE, "test-model")
        self.assertEqual(req["model"], "test-model")
        self.assertEqual(len(req["messages"]), 3)
        self.assertEqual(req["messages"][0]["role"], "system")
        self.assertIn("domain research assistant", req["messages"][0]["content"])
        self.assertEqual(req["messages"][2]["content"], "What is X?")

    def test_temperature_and_max_tokens(self) -> None:
        req = build_chat_request(SAMPLE_BUNDLE, "m")
        self.assertEqual(req["temperature"], 0.2)
        self.assertEqual(req["max_tokens"], 2048)


class TestParseAnswer(unittest.TestCase):
    def test_valid_json(self) -> None:
        raw = json.dumps({
            "answer": "test",
            "supporting_claims": [{"claim": "c", "evidence_ids": ["e1"], "confidence": "high"}],
            "inferences": ["i"],
            "uncertainty": ["u"],
            "missing_evidence": ["m"],
            "suggested_next_steps": ["s"],
        })
        result = parse_answer(raw)
        self.assertEqual(result["answer"], "test")
        self.assertEqual(len(result["supporting_claims"]), 1)

    def test_fenced_json(self) -> None:
        raw = "```json\n" + json.dumps({"answer": "from fence"}) + "\n```"
        result = parse_answer(raw)
        self.assertEqual(result["answer"], "from fence")

    def test_partial_json_in_text(self) -> None:
        raw = 'Here is my answer: {"answer": "partial"}'
        result = parse_answer(raw)
        self.assertEqual(result["answer"], "partial")

    def test_no_json_returns_raw(self) -> None:
        result = parse_answer("Just plain text, no JSON at all")
        self.assertEqual(result["answer"], "Just plain text, no JSON at all")
        self.assertTrue(result.get("_parse_error"))

    def test_defaults_for_missing_keys(self) -> None:
        result = parse_answer('{"answer": "hi"}')
        self.assertEqual(result["supporting_claims"], [])
        self.assertEqual(result["inferences"], [])


class TestValidateClaims(unittest.TestCase):
    def test_strips_invalid_ids(self) -> None:
        answer = {
            "supporting_claims": [
                {"claim": "c", "evidence_ids": ["ev-1", "ev-fake"], "confidence": "high"},
            ],
        }
        result = validate_claims(answer, {"ev-1"})
        claim = result["supporting_claims"][0]
        self.assertEqual(claim["evidence_ids"], ["ev-1"])
        self.assertIn("non-existent", result["uncertainty"][0])

    def test_marks_orphaned_claims(self) -> None:
        answer = {
            "supporting_claims": [
                {"claim": "c", "evidence_ids": ["ev-fake"], "confidence": "medium"},
            ],
        }
        result = validate_claims(answer, {"ev-1"})
        self.assertTrue(result["supporting_claims"][0].get("_orphaned"))

    def test_no_claims_returns_as_is(self) -> None:
        answer = {"supporting_claims": []}
        self.assertEqual(validate_claims(answer, {"ev-1"}), answer)

    def test_all_valid_ids_pass_through(self) -> None:
        answer = {
            "supporting_claims": [
                {"claim": "c", "evidence_ids": ["ev-1"], "confidence": "high"},
            ],
        }
        result = validate_claims(answer, {"ev-1"})
        self.assertEqual(result, answer)


class TestBuildSynthesisOutput(unittest.TestCase):
    def test_assembles_output(self) -> None:
        answer = {"answer": "test", "supporting_claims": []}
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        result = build_synthesis_output(answer, SAMPLE_BUNDLE, "model", usage)
        self.assertEqual(result["query"], "what is x")
        self.assertEqual(result["synthesis_meta"]["model"], "model")
        self.assertEqual(result["synthesis_meta"]["usage"]["total_tokens"], 30)

    def test_validates_claims_when_citations(self) -> None:
        answer = {
            "answer": "test",
            "supporting_claims": [
                {"claim": "c", "evidence_ids": ["ev-fake"], "confidence": "high"},
            ],
        }
        result = build_synthesis_output(answer, SAMPLE_BUNDLE, "m", {})
        # ev-fake is not in SAMPLE_BUNDLE citations (ev-1 is)
        self.assertIn("non-existent", result["answer"].get("uncertainty", [""])[0] if result["answer"].get("uncertainty") else "")


class TestSynthesizeDryRun(unittest.TestCase):
    def test_dry_run(self) -> None:
        result = synthesize(SAMPLE_BUNDLE, "test-model", dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertIn("request_payload", result)

    def test_local_answer(self) -> None:
        local = {"answer": "pre-written", "supporting_claims": []}
        result = synthesize(SAMPLE_BUNDLE, "m", local_answer=local)
        self.assertEqual(result["answer"]["answer"], "pre-written")
        self.assertEqual(result["synthesis_meta"]["usage"]["source"], "local")


class TestLoadPromptBundle(unittest.TestCase):
    def test_loads_from_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(SAMPLE_BUNDLE, f)
            f.flush()
            result = load_prompt_bundle(f.name)
        self.assertEqual(result["metadata"]["query"], "what is x")
        Path(f.name).unlink()


class TestConstants(unittest.TestCase):
    def test_system_prompt_exists(self) -> None:
        self.assertIn("domain research assistant", ANSWER_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
