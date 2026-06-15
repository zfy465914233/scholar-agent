"""Unit tests for the LLM cross-encoder reranker."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scholar_agent.engine.llm_client import LLMResponse
from scholar_agent.engine.rerank import _parse_score, rerank


class TestParseScore(unittest.TestCase):
    def test_plain_integer(self) -> None:
        self.assertEqual(_parse_score("7"), 7.0)

    def test_integer_with_whitespace(self) -> None:
        self.assertEqual(_parse_score("  8  "), 8.0)

    def test_max_score(self) -> None:
        self.assertEqual(_parse_score("10"), 10.0)

    def test_zero_score(self) -> None:
        self.assertEqual(_parse_score("0"), 0.0)

    def test_score_in_sentence(self) -> None:
        self.assertEqual(_parse_score("The relevance is 9 out of 10."), 9.0)

    def test_garbage_returns_neutral(self) -> None:
        self.assertEqual(_parse_score("not a number"), 5.0)

    def test_empty_returns_neutral(self) -> None:
        self.assertEqual(_parse_score(""), 5.0)

    def test_out_of_range_clamps_to_neutral(self) -> None:
        # "11" has no digit-bound 0-10 match → falls back to neutral
        self.assertEqual(_parse_score("11"), 5.0)


def _make_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="test", usage={}, provider_format="openai")


class TestRerank(unittest.TestCase):
    def _candidates(self) -> list[dict]:
        return [
            {"doc_id": "a", "title": "Doc A", "search_text": "alpha content"},
            {"doc_id": "b", "title": "Doc B", "search_text": "beta content"},
            {"doc_id": "c", "title": "Doc C", "search_text": "gamma content"},
        ]

    def test_empty_candidates(self) -> None:
        self.assertEqual(rerank("q", []), [])

    def test_zero_top_k(self) -> None:
        self.assertEqual(rerank("q", self._candidates(), top_k=0), [])

    def test_order_by_mocked_score(self) -> None:
        scores = {"alpha": "3", "beta": "9", "gamma": "5"}
        call_args: list[str] = []

        def fake_chat(messages, **kwargs):  # type: ignore[no-untyped-def]
            content = messages[0]["content"]
            call_args.append(content)
            for key, val in scores.items():
                if key in content:
                    return _make_response(val)
            return _make_response("5")

        with patch("scholar_agent.engine.rerank.chat", side_effect=fake_chat):
            result = rerank("query", self._candidates(), top_k=2, batched=False)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["doc_id"], "b")
        self.assertEqual(result[1]["doc_id"], "c")
        self.assertEqual(result[0]["rerank_score"], 9.0)
        self.assertEqual(result[1]["rerank_score"], 5.0)
        # Per-candidate mode: one call per candidate
        self.assertEqual(len(call_args), 3)

    def test_ties_break_by_original_order(self) -> None:
        with patch("scholar_agent.engine.rerank.chat", return_value=_make_response("7")):
            result = rerank("q", self._candidates(), top_k=3, batched=False)
        self.assertEqual([r["doc_id"] for r in result], ["a", "b", "c"])

    def test_llm_failure_falls_back_to_neutral(self) -> None:
        def fake_chat(messages, **kwargs):  # type: ignore[no-untyped-def]
            content = messages[0]["content"]
            if "alpha" in content:
                raise RuntimeError("LLM down")
            return _make_response("9")

        with patch("scholar_agent.engine.rerank.chat", side_effect=fake_chat):
            result = rerank("q", self._candidates(), top_k=3, batched=False)

        self.assertEqual([r["doc_id"] for r in result], ["b", "c", "a"])
        self.assertEqual(result[-1]["rerank_score"], 5.0)

    def test_top_k_truncation(self) -> None:
        with patch("scholar_agent.engine.rerank.chat", return_value=_make_response("8")):
            result = rerank("q", self._candidates(), top_k=1, batched=False)
        self.assertEqual(len(result), 1)


class TestRerankBatched(unittest.TestCase):
    """Tests for the batched single-call rerank path."""

    def _candidates(self) -> list[dict]:
        return [
            {"doc_id": "a", "title": "Doc A", "search_text": "alpha"},
            {"doc_id": "b", "title": "Doc B", "search_text": "beta"},
            {"doc_id": "c", "title": "Doc C", "search_text": "gamma"},
        ]

    def test_batched_single_call_scores_all(self) -> None:
        call_count = 0

        def fake_chat(messages, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            return _make_response("1 3\n2 9\n3 5\n")

        with patch("scholar_agent.engine.rerank.chat", side_effect=fake_chat):
            result = rerank("query", self._candidates(), top_k=2)

        # Single LLM call for batched mode
        self.assertEqual(call_count, 1)
        # Sorted: b(9), c(5), a(3)
        self.assertEqual([r["doc_id"] for r in result], ["b", "c"])

    def test_batched_falls_back_when_parse_incomplete(self) -> None:
        # Batched response missing most lines → fallback to per-candidate
        batch_response = _make_response("1 8\n")  # only 1 of 3 candidates
        per_candidate_responses = [
            _make_response("3"),  # a
            _make_response("7"),  # b
            _make_response("5"),  # c
        ]
        call_count = 0

        def fake_chat(messages, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return batch_response
            return per_candidate_responses[call_count - 2]

        with patch("scholar_agent.engine.rerank.chat", side_effect=fake_chat):
            result = rerank("q", self._candidates(), top_k=3)

        # 1 batched + 3 per-candidate
        self.assertEqual(call_count, 4)
        # Order from per-candidate: b(7), c(5), a(3)
        self.assertEqual([r["doc_id"] for r in result], ["b", "c", "a"])

    def test_batched_falls_back_on_llm_exception(self) -> None:
        # Batch call raises → fallback to per-candidate
        per_candidate = [
            _make_response("4"),  # a
            _make_response("6"),  # b
            _make_response("2"),  # c
        ]
        responses = iter([RuntimeError("batch failed"), *per_candidate])

        def fake_chat(messages, **kwargs):  # type: ignore[no-untyped-def]
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value

        with patch("scholar_agent.engine.rerank.chat", side_effect=fake_chat):
            result = rerank("q", self._candidates(), top_k=3)

        # b(6), a(4), c(2)
        self.assertEqual([r["doc_id"] for r in result], ["b", "a", "c"])


if __name__ == "__main__":
    unittest.main()
