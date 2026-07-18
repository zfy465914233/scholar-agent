"""Tests for scholar_agent.engine.academic.conf_search pure functions."""

import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import requests

from scholar_agent.engine.academic.conf_search import (
    _build_dblp_url,
    _dice_title_overlap,
    _extract_s2_fields,
    _fetch_dblp_page,
    _fingerprint,
    _parse_dblp_hits,
    _VenueSpec,
)


class TestVenueSpecTocPath(unittest.TestCase):
    """Tests for _VenueSpec.toc_path(year)."""

    def test_with_format_string(self):
        spec = _VenueSpec(
            dblp_prefix="conf/cvpr",
            toc_fmt="cvpr{year}",
            venue_label="CVPR",
        )
        result = spec.toc_path(2025)
        self.assertEqual(result, "toc:db/conf/cvpr/cvpr2025.bht:")

    def test_with_format_string_different_year(self):
        spec = _VenueSpec(
            dblp_prefix="conf/nips",
            toc_fmt="neurips{year}",
            venue_label="NeurIPS",
        )
        result = spec.toc_path(2024)
        self.assertEqual(result, "toc:db/conf/nips/neurips2024.bht:")

    def test_none_format_returns_none(self):
        spec = _VenueSpec(
            dblp_prefix="conf/eccv",
            toc_fmt=None,
            venue_label="ECCV",
        )
        result = spec.toc_path(2025)
        self.assertIsNone(result)

    def test_iclr_spec(self):
        spec = _VenueSpec(
            dblp_prefix="conf/iclr",
            toc_fmt="iclr{year}",
            venue_label="ICLR",
        )
        result = spec.toc_path(2026)
        self.assertEqual(result, "toc:db/conf/iclr/iclr2026.bht:")


class TestFingerprint(unittest.TestCase):
    """Tests for _fingerprint(text)."""

    def test_lowercase(self):
        self.assertEqual(_fingerprint("Hello World"), "hello-world")

    def test_strips_special_chars(self):
        self.assertEqual(_fingerprint("Deep Learning: A Survey (2025)"), "deep-learning-a-survey-2025")

    def test_collapses_spaces_and_dashes(self):
        self.assertEqual(_fingerprint("a  b--c"), "a-b-c")

    def test_strips_leading_trailing_dashes(self):
        self.assertEqual(_fingerprint("---test---"), "test")

    def test_empty_string(self):
        self.assertEqual(_fingerprint(""), "")

    def test_preserves_numbers(self):
        self.assertEqual(_fingerprint("GPT-4 is great"), "gpt-4-is-great")

    def test_unicode_removed(self):
        result = _fingerprint("model")
        self.assertEqual(result, "model")


class TestDiceTitleOverlap(unittest.TestCase):
    """Tests for _dice_title_overlap(a, b)."""

    def test_identical_titles(self):
        score = _dice_title_overlap(
            "Deep Learning for Natural Language Processing",
            "Deep Learning for Natural Language Processing",
        )
        self.assertEqual(score, 1.0)

    def test_completely_different(self):
        score = _dice_title_overlap("Deep Learning", "Quantum Computing")
        self.assertEqual(score, 0.0)

    def test_partial_overlap(self):
        score = _dice_title_overlap(
            "Deep Learning for NLP",
            "Deep Learning for Computer Vision",
        )
        # Words: {deep, learning, for, nlp} vs {deep, learning, for, computer, vision}
        # shared=3, total=9, dice=6/9=0.6667
        self.assertAlmostEqual(score, 6 / 9, places=4)

    def test_empty_string_a(self):
        score = _dice_title_overlap("", "Some Title")
        self.assertEqual(score, 0.0)

    def test_empty_string_b(self):
        score = _dice_title_overlap("Some Title", "")
        self.assertEqual(score, 0.0)

    def test_both_empty(self):
        score = _dice_title_overlap("", "")
        self.assertEqual(score, 0.0)

    def test_case_insensitive(self):
        score = _dice_title_overlap("Deep Learning", "deep learning")
        self.assertEqual(score, 1.0)

    def test_single_word_overlap(self):
        score = _dice_title_overlap("Attention Is All You Need", "Attention Mechanisms")
        # {attention, is, all, you, need} vs {attention, mechanisms}
        # shared=1, total=7, dice=2/7
        self.assertAlmostEqual(score, 2 / 7, places=4)

    def test_special_chars_stripped(self):
        # Both normalize to {gpt4, a, review} after stripping non-alnum
        score = _dice_title_overlap("GPT-4: A Review", "GPT4 A Review")
        self.assertEqual(score, 1.0)


class TestBuildDblpUrl(unittest.TestCase):
    """Tests for _build_dblp_url(venue_key, year, offset, batch_size)."""

    def test_venue_with_toc_path(self):
        url = _build_dblp_url("CVPR", 2025, 0, 100)
        self.assertIsNotNone(url)
        self.assertIn("dblp.org", url)
        decoded = unquote(url)
        self.assertIn("toc:db/conf/cvpr/cvpr2025.bht:", decoded)
        self.assertIn("h=100", url)
        self.assertIn("f=0", url)

    def test_venue_without_toc_path(self):
        url = _build_dblp_url("ECCV", 2025, 0, 100)
        self.assertIsNotNone(url)
        decoded = unquote(url)
        self.assertIn("venue:ECCV", decoded)
        self.assertIn("year:2025", decoded)

    def test_offset_applied(self):
        url = _build_dblp_url("CVPR", 2025, 50, 100)
        self.assertIn("f=50", url)

    def test_batch_size_applied(self):
        url = _build_dblp_url("CVPR", 2025, 0, 500)
        self.assertIn("h=500", url)

    def test_unknown_venue_returns_none(self):
        url = _build_dblp_url("UNKNOWN", 2025, 0, 100)
        self.assertIsNone(url)

    def test_url_format_is_json(self):
        url = _build_dblp_url("CVPR", 2025, 0, 100)
        self.assertIn("format=json", url)

    def test_iclr_venue(self):
        url = _build_dblp_url("ICLR", 2024, 0, 200)
        self.assertIsNotNone(url)
        decoded = unquote(url)
        self.assertIn("toc:db/conf/iclr/iclr2024.bht:", decoded)


class TestParseDblpHits(unittest.TestCase):
    """Tests for _parse_dblp_hits(data, venue_key, year)."""

    def test_single_author_edge_case(self):
        """DBLP returns a dict (not list) when there's only one author."""
        data = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [
                        {
                            "info": {
                                "title": "Single Author Paper.",
                                "authors": {"author": {"text": "Alice Smith"}},
                                "year": "2025",
                                "doi": "10.1234/test",
                                "url": "https://dblp.org/rec/test",
                                "venue": "CVPR",
                            }
                        }
                    ],
                }
            }
        }
        papers, total = _parse_dblp_hits(data, "CVPR", 2025)
        self.assertEqual(total, 1)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["authors"], ["Alice Smith"])

    def test_multiple_authors(self):
        data = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [
                        {
                            "info": {
                                "title": "Multi Author Paper",
                                "authors": {
                                    "author": [
                                        {"text": "Alice"},
                                        {"text": "Bob"},
                                    ]
                                },
                                "year": "2025",
                            }
                        }
                    ],
                }
            }
        }
        papers, _total = _parse_dblp_hits(data, "CVPR", 2025)
        self.assertEqual(papers[0]["authors"], ["Alice", "Bob"])

    def test_strips_trailing_period_from_title(self):
        data = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [
                        {
                            "info": {
                                "title": "Paper Title...",
                                "authors": {"author": [{"text": "Alice"}]},
                                "year": "2025",
                            }
                        }
                    ],
                }
            }
        }
        papers, _ = _parse_dblp_hits(data, "CVPR", 2025)
        self.assertEqual(papers[0]["title"], "Paper Title")

    def test_skips_empty_title(self):
        data = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [
                        {
                            "info": {
                                "title": "...",
                                "authors": {"author": [{"text": "Alice"}]},
                                "year": "2025",
                            }
                        }
                    ],
                }
            }
        }
        papers, _ = _parse_dblp_hits(data, "CVPR", 2025)
        self.assertEqual(len(papers), 0)

    def test_missing_fields_use_defaults(self):
        data = {
            "result": {
                "hits": {
                    "@total": "0",
                    "hit": [],
                }
            }
        }
        papers, total = _parse_dblp_hits(data, "NeurIPS", 2024)
        self.assertEqual(total, 0)
        self.assertEqual(papers, [])

    def test_sets_conference_venue(self):
        data = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [
                        {
                            "info": {
                                "title": "Paper",
                                "authors": {"author": [{"text": "A"}]},
                                "year": "2025",
                            }
                        }
                    ],
                }
            }
        }
        papers, _ = _parse_dblp_hits(data, "ICLR", 2025)
        self.assertEqual(papers[0]["conference"], "ICLR")
        self.assertEqual(papers[0]["source"], "dblp")

    def test_extracts_categories_from_spec(self):
        data = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [
                        {
                            "info": {
                                "title": "Paper",
                                "authors": {"author": [{"text": "A"}]},
                                "year": "2025",
                            }
                        }
                    ],
                }
            }
        }
        papers, _ = _parse_dblp_hits(data, "ICLR", 2025)
        self.assertIn("cs.LG", papers[0]["categories"])
        self.assertIn("cs.AI", papers[0]["categories"])

    def test_year_defaults_to_passed_year(self):
        data = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [
                        {
                            "info": {
                                "title": "Paper",
                                "authors": {"author": [{"text": "A"}]},
                            }
                        }
                    ],
                }
            }
        }
        papers, _ = _parse_dblp_hits(data, "CVPR", 2023)
        self.assertEqual(papers[0]["year"], 2023)


class TestExtractS2Fields(unittest.TestCase):
    """Tests for _extract_s2_fields(match)."""

    def test_basic_fields(self):
        match = {
            "abstract": "A great paper.",
            "citationCount": 42,
            "influentialCitationCount": 10,
            "url": "https://s2.com/paper",
        }
        result = _extract_s2_fields(match)
        self.assertEqual(result["abstract"], "A great paper.")
        self.assertEqual(result["citationCount"], 42)
        self.assertEqual(result["influentialCitationCount"], 10)
        self.assertEqual(result["s2_url"], "https://s2.com/paper")
        self.assertTrue(result["s2_matched"])

    def test_extracts_arxiv_id(self):
        match = {
            "externalIds": {"ArXiv": "2501.12345"},
        }
        result = _extract_s2_fields(match)
        self.assertEqual(result["arxiv_id"], "2501.12345")

    def test_extracts_doi(self):
        match = {
            "externalIds": {"DOI": "10.1234/test"},
        }
        result = _extract_s2_fields(match)
        self.assertEqual(result["doi_ext"], "10.1234/test")

    def test_null_counts_default_to_zero(self):
        match = {
            "citationCount": None,
            "influentialCitationCount": None,
        }
        result = _extract_s2_fields(match)
        self.assertEqual(result["citationCount"], 0)
        self.assertEqual(result["influentialCitationCount"], 0)

    def test_missing_counts_default_to_zero(self):
        match = {}
        result = _extract_s2_fields(match)
        self.assertEqual(result["citationCount"], 0)
        self.assertEqual(result["influentialCitationCount"], 0)

    def test_similarity_preserved(self):
        match = {
            "_similarity": 0.85,
        }
        result = _extract_s2_fields(match)
        self.assertEqual(result["s2_similarity"], 0.85)

    def test_default_similarity_is_zero(self):
        match = {}
        result = _extract_s2_fields(match)
        self.assertEqual(result["s2_similarity"], 0.0)

    def test_extracts_author_affiliations(self):
        match = {
            "authors": [
                {"affiliations": [{"name": "MIT"}]},
                {"affiliations": [{"name": "Stanford"}]},
            ]
        }
        result = _extract_s2_fields(match)
        self.assertIn("affiliations", result)
        self.assertIn("MIT", result["affiliations"])
        self.assertIn("Stanford", result["affiliations"])

    def test_deduplicates_affiliations(self):
        match = {
            "authors": [
                {"affiliations": [{"name": "MIT"}]},
                {"affiliations": [{"name": "MIT"}]},
            ]
        }
        result = _extract_s2_fields(match)
        self.assertEqual(len(result["affiliations"]), 1)

    def test_no_authors_key(self):
        match = {}
        result = _extract_s2_fields(match)
        self.assertNotIn("affiliations", result)


class TestFetchDblpPage(unittest.TestCase):
    """_fetch_dblp_page: retry wrapper returning None on exhaustion."""

    @patch("scholar_agent.engine.retry.time.sleep")
    @patch("scholar_agent.engine.academic.conf_search._requests.get")
    def test_exhaustion_returns_none_with_warnings(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.ConnectionError("boom")
        with self.assertLogs("scholar_agent.engine.academic.conf_search", level="WARNING") as cm:
            result = _fetch_dblp_page("http://dblp.example/api")
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual([c[0][0] for c in mock_sleep.call_args_list], [4.0, 6.0])
        self.assertEqual(sum("dblp request failed try" in msg for msg in cm.output), 3)
        self.assertTrue(any("try 3/3" in msg for msg in cm.output))

    @patch("scholar_agent.engine.retry.time.sleep")
    @patch("scholar_agent.engine.academic.conf_search._requests.get")
    def test_success_after_retry(self, mock_get, mock_sleep):
        ok = MagicMock()
        ok.raise_for_status.return_value = None
        ok.json.return_value = {"result": {}}
        mock_get.side_effect = [requests.ConnectionError("boom"), ok]
        with self.assertLogs("scholar_agent.engine.academic.conf_search", level="WARNING"):
            result = _fetch_dblp_page("http://dblp.example/api")
        self.assertEqual(result, {"result": {}})
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(4.0)

    @patch("scholar_agent.engine.retry.time.sleep")
    @patch("scholar_agent.engine.academic.conf_search._requests.get")
    def test_non_dict_response_returns_none_without_retry(self, mock_get, mock_sleep):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [1, 2, 3]
        mock_get.return_value = resp
        with self.assertLogs("scholar_agent.engine.academic.conf_search", level="WARNING") as cm:
            result = _fetch_dblp_page("http://dblp.example/api")
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()
        self.assertTrue(any("not a dict" in msg for msg in cm.output))


class TestBatchSearchS2(unittest.TestCase):
    """_batch_search_s2 per-title retry/throttle semantics."""

    def _run_batch(self, titles, session):
        from scholar_agent.engine.academic.conf_search import _batch_search_s2

        session_cm = MagicMock()
        session_cm.__enter__.return_value = session
        session_cm.__exit__.return_value = False
        # conf_search.time and retry.time are the same module object, so one
        # patch covers both the retry-internal and the conf_search sleeps.
        with (
            patch("scholar_agent.engine.academic.conf_search._requests.Session", return_value=session_cm),
            patch("scholar_agent.engine.academic.conf_search.time.sleep") as mock_sleep,
        ):
            cache = _batch_search_s2(titles, {})
        return cache, mock_sleep

    @staticmethod
    def _ok_response(title):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"data": [{"title": title, "externalIds": {}}]}
        return resp

    @staticmethod
    def _throttled_response():
        resp = MagicMock()
        resp.status_code = 429
        resp.raise_for_status.side_effect = requests.HTTPError("429 Client Error: Too Many Requests")
        return resp

    def test_throttle_then_success(self):
        session = MagicMock()
        session.get.side_effect = [self._throttled_response(), self._ok_response("Deep Learning")]
        with self.assertLogs("scholar_agent.engine.academic.conf_search", level="WARNING") as cm:
            cache, mock_sleep = self._run_batch(["Deep Learning"], session)
        self.assertIn("deep learning", cache)
        self.assertEqual(cache["deep learning"]["_similarity"], 1.0)
        mock_sleep.assert_called_once_with(30.0)
        self.assertEqual(sum("s2 throttled" in msg for msg in cm.output), 1)

    def test_persistent_429_drops_title_after_throttle_sleeps(self):
        session = MagicMock()
        session.get.side_effect = [self._throttled_response() for _ in range(3)]
        with self.assertLogs("scholar_agent.engine.academic.conf_search", level="WARNING") as cm:
            cache, mock_sleep = self._run_batch(["Deep Learning"], session)
        self.assertEqual(cache, {})
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual([c[0][0] for c in mock_sleep.call_args_list], [30.0, 30.0, 30])
        self.assertEqual(sum("s2 throttled" in msg for msg in cm.output), 3)

    def test_non_429_errors_backoff_then_drop_silently(self):
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        cache, mock_sleep = self._run_batch(["Deep Learning"], session)
        self.assertEqual(cache, {})
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual([c[0][0] for c in mock_sleep.call_args_list], [1.0, 2.0])

    def test_low_similarity_match_dropped(self):
        session = MagicMock()
        session.get.return_value = self._ok_response("Completely Different Topic")
        cache, mock_sleep = self._run_batch(["Deep Learning"], session)
        self.assertEqual(cache, {})
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
