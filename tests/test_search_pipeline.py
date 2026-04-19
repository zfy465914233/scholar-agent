import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from search_providers.base import ProviderResult, SearchCandidate
from normalizers.evidence_normalizer import normalize_candidate
from search_providers.self_hosted_provider import SelfHostedProvider
from search_pipeline import (
    canonicalize_url,
    candidate_identity,
    run_search_pipeline,
)
import research_harness


class SelfHostedProviderTest(unittest.TestCase):
    def test_canonicalize_url_normalizes_case_and_fragment(self) -> None:
        self.assertEqual(
            "https://example.com/path",
            canonicalize_url("HTTPS://Example.com/path/#fragment"),
        )

    def test_candidate_identity_uses_fallback_for_url_less_candidates(self) -> None:
        first = {
            "provider": "claude_websearch",
            "query": "markov chain",
            "title": "Intro",
            "url": None,
            "snippet": "A short summary.",
            "published_at": None,
        }
        second = {
            "provider": "claude_websearch",
            "query": "markov chain",
            "title": "Intro",
            "url": None,
            "snippet": "Another summary.",
            "published_at": None,
        }

        self.assertNotEqual(candidate_identity(first), candidate_identity(second))

    def test_run_search_pipeline_merges_internal_and_external_candidates(self) -> None:
        class FakeProvider:
            provider_name = "fake_provider"

            def search(self, query: str, limit: int | None = None) -> ProviderResult:
                return ProviderResult(
                    provider=self.provider_name,
                    query=query,
                    candidates=[
                        SearchCandidate(
                            query=query,
                            url="https://example.com/a/",
                            title="Internal Result",
                            snippet="Internal summary",
                            published_at="2026-01-01",
                        )
                    ],
                )

        external_batch = {
            "source": "claude_websearch",
            "query": "markov chain",
            "candidates": [
                {
                    "title": "External Duplicate",
                    "url": "https://example.com/a#fragment",
                    "snippet": "Richer external summary",
                },
                {
                    "title": "External Unique",
                    "url": None,
                    "snippet": "No URL summary",
                },
            ],
        }

        payload = run_search_pipeline(
            query="markov chain",
            providers=[FakeProvider()],
            external_batch=external_batch,
        )

        self.assertEqual("markov chain", payload["query"])
        self.assertEqual(1, len(payload["provider_results"]))
        self.assertEqual(3, payload["summary"]["candidate_count"])
        self.assertEqual(2, payload["summary"]["deduped_count"])
        self.assertEqual(2, len(payload["merged_candidates"]))
        self.assertEqual(2, len(payload["evidence"]))
        merged_urls = {item["url"] for item in payload["merged_candidates"]}
        self.assertIn("https://example.com/a", merged_urls)
        self.assertTrue(any(url.startswith("urn:scholar-agent:candidate:") for url in merged_urls))
        evidence_urls = {item["url"] for item in payload["evidence"]}
        self.assertEqual(merged_urls, evidence_urls)

    def test_evidence_schema_exposes_optional_provenance_contract(self) -> None:
        schema_path = ROOT / "schemas" / "evidence.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        provenance = schema["properties"].get("provenance")
        self.assertIsNotNone(provenance, "evidence schema should expose an optional provenance object")
        self.assertEqual("object", provenance["type"])
        self.assertEqual({"provider", "query", "retrieved_at", "url"}, set(provenance["properties"]))
        self.assertEqual("string", provenance["properties"]["provider"]["type"])
        self.assertEqual("string", provenance["properties"]["query"]["type"])
        self.assertEqual("string", provenance["properties"]["retrieved_at"]["type"])
        self.assertEqual("date-time", provenance["properties"]["retrieved_at"]["format"])
        self.assertEqual(["string", "null"], provenance["properties"]["url"]["type"])
        self.assertEqual("uri", provenance["properties"]["url"]["format"])
        self.assertEqual(["provider", "query", "retrieved_at", "url"], provenance["required"])
        self.assertFalse(provenance.get("additionalProperties", True))
        self.assertNotIn("provenance", schema.get("required", []))

    def test_self_hosted_provider_returns_provider_result_shaped_output(self) -> None:
        provider = SelfHostedProvider()
        with (
            patch("search_providers.self_hosted_provider.search_searxng") as mock_searxng,
            patch("search_providers.self_hosted_provider.search_openalex") as mock_openalex,
            patch("search_providers.self_hosted_provider.search_semanticscholar") as mock_semanticscholar,
        ):
            mock_searxng.return_value = [
                {
                    "url": "https://example.com/a",
                    "title": "Search result",
                    "content": "Search snippet",
                    "publishedDate": "2026-01-01",
                }
            ]
            mock_openalex.return_value = [
                {
                    "url": "https://example.org/b",
                    "title": "Paper result",
                    "content": "",
                    "publishedDate": "2025-12-31",
                }
            ]
            mock_semanticscholar.return_value = []

            result = provider.search("markov chain", limit=2)

        self.assertIsInstance(result, ProviderResult)
        self.assertEqual("self_hosted", result.provider)
        self.assertEqual("markov chain", result.query)
        self.assertEqual(2, len(result.candidates))
        self.assertTrue(all(isinstance(candidate, SearchCandidate) for candidate in result.candidates))
        self.assertEqual("markov chain", result.candidates[0].query)
        self.assertEqual("https://example.com/a", result.candidates[0].url)
        self.assertEqual("Search result", result.candidates[0].title)
        self.assertEqual("Search snippet", result.candidates[0].snippet)
        self.assertEqual("2026-01-01", result.candidates[0].published_at)
        self.assertEqual("https://example.org/b", result.candidates[1].url)
        mock_searxng.assert_called_once_with("markov chain")
        mock_openalex.assert_called_once_with("markov chain")
        mock_semanticscholar.assert_not_called()

    def test_self_hosted_provider_stops_after_reaching_limit(self) -> None:
        provider = SelfHostedProvider()
        with (
            patch("search_providers.self_hosted_provider.search_searxng") as mock_searxng,
            patch("search_providers.self_hosted_provider.search_openalex") as mock_openalex,
            patch("search_providers.self_hosted_provider.search_semanticscholar") as mock_semanticscholar,
        ):
            mock_searxng.return_value = [
                {
                    "url": "https://example.com/a",
                    "title": "Search result",
                    "content": "Search snippet",
                    "publishedDate": "2026-01-01",
                }
            ]
            mock_openalex.return_value = [
                {
                    "url": "https://example.org/b",
                    "title": "Paper result",
                    "content": "",
                    "publishedDate": "2025-12-31",
                }
            ]
            mock_semanticscholar.return_value = [
                {
                    "url": "https://example.net/c",
                    "title": "Scholar result",
                    "content": "",
                    "publishedDate": "2025-12-30",
                }
            ]

            result = provider.search("markov chain", limit=1)

        self.assertEqual(1, len(result.candidates))
        mock_searxng.assert_called_once_with("markov chain")
        mock_openalex.assert_not_called()
        mock_semanticscholar.assert_not_called()

    def test_collect_candidates_uses_injected_provider(self) -> None:
        class FakeProvider:
            provider_name = "fake"

            def __init__(self) -> None:
                self.calls: list[tuple[str, int | None]] = []

            def search(self, query: str, limit: int | None = None) -> ProviderResult:
                self.calls.append((query, limit))
                return ProviderResult(
                    provider=self.provider_name,
                    query=query,
                    candidates=[
                        SearchCandidate(
                            query=query,
                            url="https://example.com/a",
                            title="Injected",
                            snippet="",
                            published_at=None,
                        )
                    ],
                )

        fake_provider = FakeProvider()
        with patch.object(research_harness, "SelfHostedProvider", side_effect=AssertionError("should not instantiate")):
            candidates = research_harness.collect_candidates(["markov chain"], fake_provider)

        self.assertEqual(1, len(candidates))
        self.assertEqual([("markov chain", None)], fake_provider.calls)

    def test_normalize_candidate_uses_snippet_summary_and_provenance(self) -> None:
        candidate = SearchCandidate(
            query="markov chain",
            url="https://github.com/example/repo",
            title="Markov Chain Notes",
            snippet="A short summary from search.",
            published_at="2026-01-01",
        )

        with patch("normalizers.evidence_normalizer.now_iso", return_value="2026-04-03T00:00:00+00:00"):
            evidence = normalize_candidate(candidate, fetched_text="")

        self.assertEqual("markov chain", evidence["query"])
        self.assertEqual("github", evidence["source_type"])
        self.assertEqual("https://github.com/example/repo", evidence["url"])
        self.assertEqual("Markov Chain Notes", evidence["title"])
        self.assertEqual("A short summary from search.", evidence["summary"])
        self.assertEqual("", evidence["content_md"])
        self.assertEqual("partial", evidence["retrieval_status"])
        self.assertEqual("2026-04-03T00:00:00+00:00", evidence["retrieved_at"])
        self.assertEqual(
            {
                "provider": "unknown",
                "query": "markov chain",
                "retrieved_at": "2026-04-03T00:00:00+00:00",
                "url": "https://github.com/example/repo",
            },
            evidence["provenance"],
        )

    def test_normalize_candidate_handles_missing_url_with_stable_fallback_source_type(self) -> None:
        candidate = SearchCandidate(
            query="markov chain",
            url=None,  # type: ignore[arg-type]
            title="Intro",
            snippet="A short summary.",
            published_at=None,
        )

        with patch("normalizers.evidence_normalizer.now_iso", return_value="2026-04-03T00:00:00+00:00"):
            evidence = normalize_candidate(candidate, fetched_text="")

        self.assertTrue(evidence["url"].startswith("urn:scholar-agent:candidate:"))
        self.assertEqual("Intro", evidence["title"])
        self.assertEqual("A short summary.", evidence["summary"])
        self.assertEqual("other", evidence["source_type"])
        self.assertEqual(
            {
                "provider": "unknown",
                "query": "markov chain",
                "retrieved_at": "2026-04-03T00:00:00+00:00",
                "url": None,
            },
            evidence["provenance"],
        )

    def test_normalize_candidate_uses_unique_fallback_url_for_url_less_candidates(self) -> None:
        first = SearchCandidate(
            query="markov chain",
            url=None,  # type: ignore[arg-type]
            title="Intro",
            snippet="A short summary.",
            published_at=None,
        )
        second = SearchCandidate(
            query="markov chain",
            url=None,  # type: ignore[arg-type]
            title="Intro",
            snippet="A different summary.",
            published_at=None,
        )

        with patch("normalizers.evidence_normalizer.now_iso", return_value="2026-04-03T00:00:00+00:00"):
            first_evidence = normalize_candidate(first, fetched_text="")
            second_evidence = normalize_candidate(second, fetched_text="")

        self.assertTrue(first_evidence["url"].startswith("urn:scholar-agent:candidate:"))
        self.assertTrue(second_evidence["url"].startswith("urn:scholar-agent:candidate:"))
        self.assertNotEqual(first_evidence["url"], second_evidence["url"])
        self.assertIsNone(first_evidence["provenance"]["url"])
        self.assertIsNone(second_evidence["provenance"]["url"])

    def test_normalize_candidate_normalizes_published_at_to_date_string(self) -> None:
        candidate = {
            "query": "markov chain",
            "url": "https://example.com/a",
            "title": "Intro",
            "snippet": "A short summary.",
            "published_at": datetime(2026, 4, 3, 12, 30, tzinfo=timezone.utc),
        }

        with patch("normalizers.evidence_normalizer.now_iso", return_value="2026-04-03T00:00:00+00:00"):
            evidence = normalize_candidate(candidate, fetched_text="", retrieval_status="succeeded")

        self.assertEqual("2026-04-03", evidence["published_at"])
        self.assertEqual("2026-04-03", evidence["freshness_signals"]["page_updated_date"])
        self.assertIsNone(evidence["freshness_signals"]["last_commit_date"])

    def test_normalize_candidate_drops_blank_published_at(self) -> None:
        candidate = {
            "query": "markov chain",
            "url": "https://example.com/a",
            "title": "Intro",
            "snippet": "A short summary.",
            "published_at": "   ",
        }

        with patch("normalizers.evidence_normalizer.now_iso", return_value="2026-04-03T00:00:00+00:00"):
            evidence = normalize_candidate(candidate, fetched_text="")

        self.assertIsNone(evidence["published_at"])
        self.assertIsNone(evidence["freshness_signals"]["page_updated_date"])

    def test_normalize_candidate_drops_malformed_published_at(self) -> None:
        candidate = {
            "query": "markov chain",
            "url": "https://example.com/a",
            "title": "Intro",
            "snippet": "A short summary.",
            "published_at": "not-a-date",
        }

        with patch("normalizers.evidence_normalizer.now_iso", return_value="2026-04-03T00:00:00+00:00"):
            evidence = normalize_candidate(candidate, fetched_text="")

        self.assertIsNone(evidence["published_at"])
        self.assertIsNone(evidence["freshness_signals"]["page_updated_date"])

    def test_run_discovery_uses_accurate_empty_results_error(self) -> None:
        with patch.object(research_harness, "run_search_pipeline", return_value={"evidence": []}):
            with self.assertRaisesRegex(RuntimeError, "No search results returned from configured provider"):
                research_harness.run_discovery("markov chain", "quick", None)

    def test_parse_args_accepts_external_candidates_path(self) -> None:
        batch_path = ROOT / "tests" / "fixtures" / "external_candidates.json"
        with patch.object(
            sys,
            "argv",
            ["research_harness.py", "markov chain", "--external-candidates", str(batch_path)],
        ):
            args = research_harness.parse_args()

        self.assertEqual(batch_path, args.external_candidates)

    def test_run_discovery_accepts_external_candidate_batch(self) -> None:
        class EmptyProvider:
            provider_name = "empty"

            def search(self, query: str, limit: int | None = None) -> ProviderResult:
                return ProviderResult(provider=self.provider_name, query=query, candidates=[])

        external_batch = {
            "source": "claude_websearch",
            "query": "markov chain",
            "candidates": [
                {
                    "title": "External Only",
                    "url": "https://example.com/external",
                    "snippet": "External summary",
                }
            ],
        }

        evidence = research_harness.run_discovery(
            "markov chain",
            "quick",
            None,
            provider=EmptyProvider(),
            external_batch=external_batch,
        )

        self.assertEqual(1, len(evidence))
        self.assertEqual("https://example.com/external", evidence[0]["url"])
        self.assertEqual("claude_websearch", evidence[0]["provenance"]["provider"])


if __name__ == "__main__":
    unittest.main()
