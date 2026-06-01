"""Tests for scholar_agent.engine.academic.arxiv_search pure functions."""

import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from scholar_agent.engine.academic.arxiv_search import (
    DateWindow,
    PaperRecord,
    _enrich_s2_author_affiliations,
    _normalize_s2_results,
    _s2_paper_to_dict,
    _slugify,
)


class TestDateWindow(unittest.TestCase):
    """Tests for DateWindow.from_target(target)."""

    def test_default_uses_now(self):
        dw = DateWindow.from_target()
        now = datetime.now()
        # recent_start should be ~30 days ago
        self.assertLessEqual(abs((now - dw.recent_start).days), 31)
        self.assertLessEqual(abs((now - dw.recent_end).total_seconds()), 60)

    def test_custom_target_date(self):
        target = datetime(2025, 6, 15, 12, 0, 0)
        dw = DateWindow.from_target(target)
        self.assertEqual(dw.recent_start, target - timedelta(days=30))
        self.assertEqual(dw.recent_end, target)
        self.assertEqual(dw.year_start, target - timedelta(days=365))
        self.assertEqual(dw.year_end, target - timedelta(days=31))

    def test_recent_window_is_30_days(self):
        target = datetime(2025, 1, 1)
        dw = DateWindow.from_target(target)
        delta = dw.recent_end - dw.recent_start
        self.assertEqual(delta.days, 30)

    def test_year_window_starts_365_days_back(self):
        target = datetime(2025, 1, 1)
        dw = DateWindow.from_target(target)
        delta = target - dw.year_start
        self.assertEqual(delta.days, 365)

    def test_year_end_is_31_days_before_target(self):
        target = datetime(2025, 1, 1)
        dw = DateWindow.from_target(target)
        delta = target - dw.year_end
        self.assertEqual(delta.days, 31)

    def test_none_target_same_as_default(self):
        dw_none = DateWindow.from_target(None)
        dw_default = DateWindow.from_target()
        # Both should be close to now
        self.assertLessEqual(abs((dw_none.recent_end - dw_default.recent_end).total_seconds()), 5)


class TestPaperRecordToDict(unittest.TestCase):
    """Tests for PaperRecord.to_dict()."""

    def test_basic_fields_mapped(self):
        rec = PaperRecord(
            arxiv_id="2501.12345",
            title="Test Paper",
            summary="A summary.",
            authors=["Alice", "Bob"],
            affiliations=["MIT"],
            published="2025-01-15T00:00:00Z",
            categories=["cs.AI"],
            pdf_url="https://arxiv.org/pdf/2501.12345",
            url="https://arxiv.org/abs/2501.12345",
        )
        d = rec.to_dict()
        self.assertEqual(d["arxiv_id"], "2501.12345")
        self.assertEqual(d["title"], "Test Paper")
        self.assertEqual(d["summary"], "A summary.")
        self.assertEqual(d["authors"], ["Alice", "Bob"])
        self.assertEqual(d["affiliations"], ["MIT"])
        self.assertEqual(d["categories"], ["cs.AI"])
        self.assertEqual(d["pdf_url"], "https://arxiv.org/pdf/2501.12345")
        self.assertEqual(d["url"], "https://arxiv.org/abs/2501.12345")
        self.assertEqual(d["source"], "arxiv")

    def test_id_field_uses_url_when_available(self):
        rec = PaperRecord(url="https://arxiv.org/abs/2501.99999", arxiv_id="2501.99999")
        d = rec.to_dict()
        self.assertEqual(d["id"], "https://arxiv.org/abs/2501.99999")

    def test_id_field_falls_back_to_arxiv_id(self):
        rec = PaperRecord(arxiv_id="2501.99999", url="")
        d = rec.to_dict()
        self.assertEqual(d["id"], "2501.99999")

    def test_default_values(self):
        rec = PaperRecord()
        d = rec.to_dict()
        self.assertEqual(d["authors"], [])
        self.assertEqual(d["affiliations"], [])
        self.assertEqual(d["categories"], [])
        self.assertEqual(d["source"], "arxiv")
        self.assertIsNone(d["published_date"])


class TestPaperRecordFromAtomEntry(unittest.TestCase):
    """Tests for PaperRecord.from_atom_entry(entry, ns)."""

    from typing import ClassVar

    NS: ClassVar[dict[str, str]] = {
        "a": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    def _make_entry(self, title="Test Paper", summary="A summary.", arxiv_id="2501.12345"):
        entry = ET.Element("{http://www.w3.org/2005/Atom}entry")
        ET.SubElement(entry, "{http://www.w3.org/2005/Atom}id").text = f"http://arxiv.org/abs/{arxiv_id}v1"
        ET.SubElement(entry, "{http://www.w3.org/2005/Atom}title").text = title
        ET.SubElement(entry, "{http://www.w3.org/2005/Atom}summary").text = summary
        ET.SubElement(entry, "{http://www.w3.org/2005/Atom}published").text = "2025-01-15T10:30:00Z"
        return entry

    def test_parses_basic_fields(self):
        entry = self._make_entry()
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertEqual(rec.title, "Test Paper")
        self.assertEqual(rec.summary, "A summary.")
        self.assertEqual(rec.arxiv_id, "2501.12345")
        self.assertEqual(rec.published, "2025-01-15T10:30:00Z")

    def test_parses_published_date(self):
        entry = self._make_entry()
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertIsNotNone(rec.published_date)
        self.assertEqual(rec.published_date.year, 2025)
        self.assertEqual(rec.published_date.month, 1)
        self.assertEqual(rec.published_date.day, 15)

    def test_parses_arxiv_id_from_url(self):
        entry = self._make_entry(arxiv_id="2405.67890")
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertEqual(rec.arxiv_id, "2405.67890")

    def test_parses_arxiv_id_with_prefix(self):
        entry = self._make_entry()
        id_elem = entry.find("{http://www.w3.org/2005/Atom}id")
        id_elem.text = "arXiv:2501.12345v2"
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertEqual(rec.arxiv_id, "2501.12345")

    def test_extracts_authors(self):
        entry = self._make_entry()
        author1 = ET.SubElement(entry, "{http://www.w3.org/2005/Atom}author")
        ET.SubElement(author1, "{http://www.w3.org/2005/Atom}name").text = "Alice"
        author2 = ET.SubElement(entry, "{http://www.w3.org/2005/Atom}author")
        ET.SubElement(author2, "{http://www.w3.org/2005/Atom}name").text = "Bob"
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertEqual(rec.authors, ["Alice", "Bob"])

    def test_extracts_affiliations(self):
        entry = self._make_entry()
        author = ET.SubElement(entry, "{http://www.w3.org/2005/Atom}author")
        ET.SubElement(author, "{http://www.w3.org/2005/Atom}name").text = "Alice"
        ET.SubElement(author, "{http://arxiv.org/schemas/atom}affiliation").text = "MIT"
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertEqual(rec.affiliations, ["MIT"])

    def test_deduplicates_affiliations(self):
        entry = self._make_entry()
        for _ in range(2):
            author = ET.SubElement(entry, "{http://www.w3.org/2005/Atom}author")
            ET.SubElement(author, "{http://www.w3.org/2005/Atom}name").text = "Author"
            ET.SubElement(author, "{http://arxiv.org/schemas/atom}affiliation").text = "Stanford"
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertEqual(rec.affiliations, ["Stanford"])

    def test_extracts_categories(self):
        entry = self._make_entry()
        cat1 = ET.SubElement(entry, "{http://www.w3.org/2005/Atom}category")
        cat1.set("term", "cs.AI")
        cat2 = ET.SubElement(entry, "{http://www.w3.org/2005/Atom}category")
        cat2.set("term", "cs.LG")
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertEqual(rec.categories, ["cs.AI", "cs.LG"])

    def test_extracts_pdf_link(self):
        entry = self._make_entry()
        link = ET.SubElement(entry, "{http://www.w3.org/2005/Atom}link")
        link.set("title", "pdf")
        link.set("href", "https://arxiv.org/pdf/2501.12345v1")
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertEqual(rec.pdf_url, "https://arxiv.org/pdf/2501.12345v1")

    def test_empty_entry_returns_record(self):
        entry = ET.Element("{http://www.w3.org/2005/Atom}entry")
        rec = PaperRecord.from_atom_entry(entry, self.NS)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.title, "")
        self.assertEqual(rec.authors, [])


class TestPaperRecordParseFeed(unittest.TestCase):
    """Tests for PaperRecord.parse_feed(xml_text)."""

    ATOM_NS = "http://www.w3.org/2005/Atom"

    def _make_feed(self, entries):
        """Build an Atom feed XML string from a list of (title, id) tuples."""
        root = ET.Element(f"{{{self.ATOM_NS}}}feed")
        for title, paper_id in entries:
            entry = ET.SubElement(root, f"{{{self.ATOM_NS}}}entry")
            ET.SubElement(entry, f"{{{self.ATOM_NS}}}id").text = paper_id
            ET.SubElement(entry, f"{{{self.ATOM_NS}}}title").text = title
            ET.SubElement(entry, f"{{{self.ATOM_NS}}}summary").text = "Abstract."
        return ET.tostring(root, encoding="unicode")

    def test_parses_multiple_entries(self):
        xml = self._make_feed(
            [
                ("Paper One", "http://arxiv.org/abs/2501.11111v1"),
                ("Paper Two", "http://arxiv.org/abs/2501.22222v1"),
            ]
        )
        records = PaperRecord.parse_feed(xml)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].title, "Paper One")
        self.assertEqual(records[1].title, "Paper Two")

    def test_empty_feed(self):
        xml = self._make_feed([])
        records = PaperRecord.parse_feed(xml)
        self.assertEqual(records, [])

    def test_invalid_xml_returns_empty(self):
        records = PaperRecord.parse_feed("<not valid xml")
        self.assertEqual(records, [])

    def test_skips_entries_without_title(self):
        root = ET.Element(f"{{{self.ATOM_NS}}}feed")
        entry = ET.SubElement(root, f"{{{self.ATOM_NS}}}entry")
        ET.SubElement(entry, f"{{{self.ATOM_NS}}}id").text = "http://arxiv.org/abs/2501.11111v1"
        # No title element
        xml = ET.tostring(root, encoding="unicode")
        records = PaperRecord.parse_feed(xml)
        self.assertEqual(len(records), 0)

    def test_extracts_arxiv_ids(self):
        xml = self._make_feed(
            [
                ("Paper", "http://arxiv.org/abs/2405.99999v1"),
            ]
        )
        records = PaperRecord.parse_feed(xml)
        self.assertEqual(records[0].arxiv_id, "2405.99999")


class TestSlugify(unittest.TestCase):
    """Tests for _slugify(text)."""

    def test_lowercase(self):
        self.assertEqual(_slugify("Hello World"), "hello-world")

    def test_strips_special_chars(self):
        self.assertEqual(_slugify("Hello, World! (2025)"), "hello-world-2025")

    def test_collapses_dashes_and_spaces(self):
        self.assertEqual(_slugify("a   b---c"), "a-b-c")

    def test_strips_leading_trailing_dashes(self):
        self.assertEqual(_slugify("---hello---"), "hello")

    def test_empty_string(self):
        self.assertEqual(_slugify(""), "")

    def test_unicode_stripped(self):
        self.assertEqual(_slugify("deep learning"), "deep-learning")


class TestEnrichS2AuthorAffiliations(unittest.TestCase):
    """Tests for _enrich_s2_author_affiliations(authors)."""

    def test_dict_affiliations(self):
        authors = [
            {"affiliations": [{"name": "MIT"}, {"name": "Stanford"}]},
        ]
        result = _enrich_s2_author_affiliations(authors)
        self.assertIn("MIT", result)
        self.assertIn("Stanford", result)
        self.assertEqual(len(result), 2)

    def test_string_affiliations(self):
        authors = [
            {"affiliations": ["MIT", "Stanford"]},
        ]
        result = _enrich_s2_author_affiliations(authors)
        self.assertIn("MIT", result)
        self.assertIn("Stanford", result)

    def test_no_affiliations_key(self):
        authors = [{"name": "Alice"}]
        result = _enrich_s2_author_affiliations(authors)
        self.assertEqual(result, [])

    def test_empty_affiliations_list(self):
        authors = [{"affiliations": []}]
        result = _enrich_s2_author_affiliations(authors)
        self.assertEqual(result, [])

    def test_deduplicates(self):
        authors = [
            {"affiliations": [{"name": "MIT"}]},
            {"affiliations": [{"name": "MIT"}]},
        ]
        result = _enrich_s2_author_affiliations(authors)
        self.assertEqual(len(result), 1)

    def test_strips_whitespace(self):
        authors = [{"affiliations": ["  MIT  "]}]
        result = _enrich_s2_author_affiliations(authors)
        self.assertEqual(result, ["MIT"])

    def test_skips_empty_labels(self):
        authors = [{"affiliations": ["", "  "]}]
        result = _enrich_s2_author_affiliations(authors)
        self.assertEqual(result, [])


class TestS2PaperToDict(unittest.TestCase):
    """Tests for _s2_paper_to_dict(p)."""

    def test_sets_source(self):
        p = {"title": "Test"}
        result = _s2_paper_to_dict(p)
        self.assertEqual(result["source"], "s2_graph")

    def test_defaults_counts_to_zero(self):
        p = {"title": "Test"}
        result = _s2_paper_to_dict(p)
        self.assertEqual(result["influentialCitationCount"], 0)
        self.assertEqual(result["citationCount"], 0)

    def test_extracts_arxiv_id(self):
        p = {"title": "Test", "externalIds": {"ArXiv": "2501.12345"}}
        result = _s2_paper_to_dict(p)
        self.assertEqual(result["arxiv_id"], "2501.12345")

    def test_no_external_ids(self):
        p = {"title": "Test"}
        result = _s2_paper_to_dict(p)
        self.assertIsNone(result["arxiv_id"])

    def test_sets_impact_signal(self):
        p = {"title": "Test", "influentialCitationCount": 42}
        result = _s2_paper_to_dict(p)
        self.assertEqual(result["impact_signal"], 42)

    def test_preserves_existing_counts(self):
        p = {"title": "Test", "influentialCitationCount": 10, "citationCount": 50}
        result = _s2_paper_to_dict(p)
        self.assertEqual(result["influentialCitationCount"], 10)
        self.assertEqual(result["citationCount"], 50)

    def test_extracts_affiliations_from_authors(self):
        p = {
            "title": "Test",
            "authors": [{"affiliations": [{"name": "MIT"}]}],
        }
        result = _s2_paper_to_dict(p)
        self.assertIn("affiliations", result)
        self.assertIn("MIT", result["affiliations"])


class TestNormalizeS2Results(unittest.TestCase):
    """Tests for _normalize_s2_results(payload, top_k)."""

    def test_filters_papers_without_title(self):
        payload = {
            "data": [
                {"abstract": "Has abstract"},
                {"title": "Real Paper", "abstract": "Has both"},
            ]
        }
        result = _normalize_s2_results(payload, 10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Real Paper")

    def test_filters_papers_without_abstract(self):
        payload = {
            "data": [
                {"title": "No Abstract Paper"},
            ]
        }
        result = _normalize_s2_results(payload, 10)
        self.assertEqual(len(result), 0)

    def test_sorted_by_influential_citations(self):
        payload = {
            "data": [
                {"title": "Low", "abstract": "abs", "influentialCitationCount": 5},
                {"title": "High", "abstract": "abs", "influentialCitationCount": 50},
                {"title": "Mid", "abstract": "abs", "influentialCitationCount": 25},
            ]
        }
        result = _normalize_s2_results(payload, 10)
        titles = [p["title"] for p in result]
        self.assertEqual(titles, ["High", "Mid", "Low"])

    def test_respects_top_k_limit(self):
        payload = {
            "data": [{"title": f"Paper {i}", "abstract": "abs", "influentialCitationCount": i} for i in range(20)]
        }
        result = _normalize_s2_results(payload, 5)
        self.assertEqual(len(result), 5)

    def test_empty_data(self):
        result = _normalize_s2_results({}, 10)
        self.assertEqual(result, [])

    def test_transforms_via_s2_paper_to_dict(self):
        payload = {
            "data": [
                {
                    "title": "Test",
                    "abstract": "abs",
                    "influentialCitationCount": 10,
                    "externalIds": {"ArXiv": "2501.12345"},
                },
            ]
        }
        result = _normalize_s2_results(payload, 10)
        self.assertEqual(result[0]["source"], "s2_graph")
        self.assertEqual(result[0]["arxiv_id"], "2501.12345")


if __name__ == "__main__":
    unittest.main()
