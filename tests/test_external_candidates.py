from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[1]


ENGINE = _ROOT / "src" / "scholar_agent" / "engine"

from scholar_agent.engine.inputs.external_candidates import parse_external_candidate_batch


class ExternalCandidateBatchTest(unittest.TestCase):
    def test_parse_external_candidate_batch_accepts_minimal_host_results_without_url(self) -> None:
        payload = {
            "source": "claude_websearch",
            "query": "markov chain",
            "candidates": [
                {"title": "Intro", "snippet": "A short summary."},
            ],
        }

        batch = parse_external_candidate_batch(payload)

        self.assertEqual("claude_websearch", batch.source)
        self.assertEqual("markov chain", batch.query)
        self.assertEqual(1, len(batch.candidates))
        self.assertEqual("Intro", batch.candidates[0].title)
        self.assertIsNone(batch.candidates[0].url)
        self.assertEqual("A short summary.", batch.candidates[0].snippet)

    def test_parse_external_candidate_batch_rejects_non_dict_payload(self) -> None:
        with self.assertRaises(ValueError):
            parse_external_candidate_batch([])  # type: ignore[arg-type]

    def test_parse_external_candidate_batch_rejects_invalid_or_empty_candidates(self) -> None:
        base_payload = {"source": "claude_websearch", "query": "markov chain"}

        for payload in (
            {**base_payload, "candidates": []},
            {**base_payload, "candidates": None},
            {**base_payload},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_external_candidate_batch(payload)

    def test_parse_external_candidate_batch_rejects_non_dict_candidate_entries(self) -> None:
        payload = {
            "source": "claude_websearch",
            "query": "markov chain",
            "candidates": ["not-a-dict"],
        }

        with self.assertRaises(ValueError):
            parse_external_candidate_batch(payload)

    def test_parse_external_candidate_batch_rejects_invalid_candidate_url_values(self) -> None:
        base_payload = {
            "source": "claude_websearch",
            "query": "markov chain",
            "candidates": [{"title": "Intro", "snippet": "A short summary."}],
        }

        for payload in (
            {**base_payload, "candidates": [{**base_payload["candidates"][0], "url": 123}]},
            {**base_payload, "candidates": [{**base_payload["candidates"][0], "url": "   "}]},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_external_candidate_batch(payload)

    def test_parse_external_candidate_batch_rejects_missing_candidate_snippet(self) -> None:
        payload = {
            "source": "claude_websearch",
            "query": "markov chain",
            "candidates": [{"title": "Intro", "url": "https://example.com/a"}],
        }

        with self.assertRaises(ValueError):
            parse_external_candidate_batch(payload)


if __name__ == "__main__":
    unittest.main()
