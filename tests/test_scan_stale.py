"""Tests for the `scholar-agent scan-stale` CLI subcommand (ISSUES G3 / F4).

Covers the pure scanner ``_scan_stale_cards`` and the end-to-end runner
``_run_scan_stale`` against synthetic cards written under ``tmp_path``.
"""

from __future__ import annotations

import io
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from scholar_agent.cli import _mark_card_stale, _run_scan_stale, _scan_stale_cards, _extract_card_urls


def _write_card(path: Path, *, domain: str | None, source_date: str | None, updated_at: str | None = None) -> None:
    """Write a minimal valid-frontmatter card with the requested fields."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {path.stem}",
        "title: Test Card",
        "type: knowledge",
        "topic: test",
        "confidence: confirmed",
        f"updated_at: {updated_at or '2026-06-01'}",
    ]
    if domain is not None:
        lines.append(f"domain: {domain}")
    if source_date is not None:
        lines.append(f"source_date: {source_date}")
    lines.append("---")
    lines.append("")
    # body > 300 chars so the card is not "thin" (not relevant to stale logic,
    # but keeps the cards realistic).
    lines.append("x " * 200)
    path.write_text("\n".join(lines), encoding="utf-8")


class TestScanStaleClassification(unittest.TestCase):
    """The scanner classifies cards against the domain-specific threshold."""

    def setUp(self) -> None:
        # Pin "now" so the test is deterministic regardless of run date.
        self.now = datetime(2026, 6, 18)

    def test_ai_domain_old_source_is_stale(self):
        # AI threshold = 0.5 years; 2020 → 6 years elapsed >> 0.5 → stale.
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "ai_old.md", domain="ai", source_date="2020-01-01")
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["source_year"], 2020)
        self.assertAlmostEqual(stale[0]["threshold_years"], 0.5)
        self.assertIn("ai_old.md", stale[0]["path"])

    def test_ai_domain_recent_source_not_stale(self):
        # AI threshold = 0.5 years; this year → 0 years elapsed → not stale.
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "ai_new.md", domain="ai", source_date="2026-03-01")
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(stale, [])

    def test_history_domain_three_years_ago_not_stale(self):
        # History threshold = 5 years; 2023 → 3 years elapsed < 5 → not stale.
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "hist.md", domain="history", source_date="2023-06-01")
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(stale, [])

    def test_history_domain_six_years_ago_is_stale(self):
        # History threshold = 5 years; 2020 → 6 years elapsed > 5 → stale.
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "hist_old.md", domain="history", source_date="2020-06-01")
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(len(stale), 1)
        self.assertAlmostEqual(stale[0]["threshold_years"], 5.0)

    def test_default_domain_three_years_ago_borderline_not_stale(self):
        # Unknown domain → default 3 years; 2023 → 3 years elapsed, NOT > 3.
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "misc.md", domain="geology", source_date="2023-01-01")
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(stale, [])

    def test_default_domain_four_years_ago_is_stale(self):
        # Unknown domain → default 3 years; 2022 → 4 years elapsed > 3 → stale.
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "misc_old.md", domain="geology", source_date="2022-01-01")
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(len(stale), 1)

    def test_mixed_dir_only_flags_stale_ones(self):
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "stale1.md", domain="ai", source_date="2019-01-01")  # stale
        _write_card(tmp / "fresh1.md", domain="ai", source_date="2026-01-01")  # fresh
        _write_card(tmp / "stale2.md", domain="history", source_date="2010-01-01")  # stale
        _write_card(tmp / "fresh2.md", domain="history", source_date="2024-01-01")  # fresh
        stale = _scan_stale_cards(tmp, now=self.now)
        names = sorted(Path(s["path"]).name for s in stale)
        self.assertEqual(names, ["stale1.md", "stale2.md"])

    def test_nested_subdirectories_are_scanned(self):
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "sub" / "deep" / "old.md", domain="ai", source_date="2018-01-01")
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(len(stale), 1)
        self.assertIn("deep", stale[0]["path"])

    def test_falls_back_to_updated_at_when_source_date_absent(self):
        # No source_date → scanner uses updated_at.
        tmp = Path(self.mkdtemp_safe())
        _write_card(
            tmp / "no_source.md",
            domain="ai",
            source_date=None,
            updated_at="2019-05-01",
        )
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(len(stale), 1)

    def test_card_without_any_date_is_skipped(self):
        tmp = Path(self.mkdtemp_safe())
        card = tmp / "nodate.md"
        card.parent.mkdir(parents=True, exist_ok=True)
        card.write_text(
            "---\nid: nodate\ntitle: T\ntype: knowledge\ntopic: t\nconfidence: confirmed\n---\nbody",
            encoding="utf-8",
        )
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(stale, [])

    def test_templates_and_readme_are_skipped(self):
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "templates" / "tpl.md", domain="ai", source_date="2000-01-01")
        _write_card(tmp / "README.md", domain="ai", source_date="2000-01-01")
        stale = _scan_stale_cards(tmp, now=self.now)
        self.assertEqual(stale, [])

    def test_days_stale_is_positive_and_reasonable(self):
        tmp = Path(self.mkdtemp_safe())
        _write_card(tmp / "ai_old.md", domain="ai", source_date="2020-01-01")
        stale = _scan_stale_cards(tmp, now=self.now)
        # 6 years elapsed - 0.5 threshold = 5.5 years ≈ 2008 days.
        self.assertGreater(stale[0]["days_stale"], 1900)
        self.assertLess(stale[0]["days_stale"], 2100)

    def mkdtemp_safe(self) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="scan_stale_")


class TestMarkCardStale(unittest.TestCase):
    """`_mark_card_stale` edits frontmatter in place, idempotently."""

    def test_inserts_stale_true(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="mark_stale_")) / "card.md"
        tmp.write_text(
            "---\nid: c\ntitle: T\ntype: knowledge\n---\nbody",
            encoding="utf-8",
        )
        changed = _mark_card_stale(tmp)
        self.assertTrue(changed)
        content = tmp.read_text(encoding="utf-8")
        self.assertIn("stale: true", content.split("---")[1])

    def test_idempotent_when_already_stale(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="mark_stale_")) / "card.md"
        tmp.write_text(
            "---\nid: c\nstale: true\ntitle: T\ntype: knowledge\n---\nbody",
            encoding="utf-8",
        )
        changed = _mark_card_stale(tmp)
        self.assertFalse(changed)


class TestRunScanStaleText(unittest.TestCase):
    """End-to-end runner (text + json output, --write)."""

    def setUp(self) -> None:
        self.now = datetime(2026, 6, 18)
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="run_scan_"))
        _write_card(self.tmp / "ai_old.md", domain="ai", source_date="2020-01-01")
        _write_card(self.tmp / "ai_new.md", domain="ai", source_date="2026-01-01")

    def test_text_reports_stale_and_total(self):
        # _run_scan_stale resolves the knowledge dir from the argument, so no
        # mock of scholar_config is needed — just point it at tmp_path.
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = _run_scan_stale(knowledge_dir=str(self.tmp), write=False, output_format="text")
        text = out.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("ai_old.md", text)
        self.assertIn("ai_new.md"[-3:], text)  # fresh card name substring ok
        self.assertIn("1 stale card", text)
        # Fresh card must NOT appear as a stale entry line.
        self.assertNotIn("ai_new.md  domain=", text)

    def test_json_payload_shape(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = _run_scan_stale(knowledge_dir=str(self.tmp), write=False, output_format="json")
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["stale_count"], 1)
        self.assertIsNone(payload["marked"])
        self.assertEqual(len(payload["stale"]), 1)
        self.assertEqual(payload["stale"][0]["source_year"], 2020)

    def test_write_marks_card_on_disk(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            rc = _run_scan_stale(knowledge_dir=str(self.tmp), write=True, output_format="json")
        self.assertEqual(rc, 0)
        marked_content = (self.tmp / "ai_old.md").read_text(encoding="utf-8")
        fresh_content = (self.tmp / "ai_new.md").read_text(encoding="utf-8")
        self.assertIn("stale: true", marked_content.split("---")[1])
        self.assertNotIn("stale: true", fresh_content)

    def test_no_stale_prints_no_stale_cards(self):
        import tempfile

        empty = Path(tempfile.mkdtemp(prefix="empty_"))
        _write_card(empty / "fresh.md", domain="ai", source_date="2026-01-01")
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = _run_scan_stale(knowledge_dir=str(empty), write=False, output_format="text")
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), "no stale cards")


def _write_card_with_sources(
    path: Path,
    *,
    domain: str,
    source_date: str,
    source_refs: list[str] | None,
) -> None:
    """Write a card carrying a source_refs YAML list."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {path.stem}",
        "title: Test Card",
        "type: knowledge",
        "topic: test",
        "confidence: confirmed",
        f"updated_at: {source_date}",
        f"domain: {domain}",
        f"source_date: {source_date}",
    ]
    if source_refs is not None:
        lines.append("source_refs:")
        for url in source_refs:
            lines.append(f"  - {url}")
    lines.append("---")
    lines.append("")
    lines.append("x " * 200)
    path.write_text("\n".join(lines), encoding="utf-8")


class TestScanStaleRefresh(unittest.TestCase):
    """--refresh re-fetches source URLs, writes snapshots, stamps captured_at."""

    def setUp(self) -> None:
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="refresh_scan_"))
        # A stale card with two source URLs.
        _write_card_with_sources(
            self.tmp / "ai_old.md",
            domain="ai",
            source_date="2020-01-01",
            source_refs=[
                "https://example.com/alpha",
                "https://example.com/beta",
            ],
        )
        # A stale card with no sources at all.
        _write_card_with_sources(
            self.tmp / "ai_old_no_sources.md",
            domain="ai",
            source_date="2019-01-01",
            source_refs=None,
        )

    def test_extract_card_urls_reads_source_refs(self):
        urls = _extract_card_urls(self.tmp / "ai_old.md")
        self.assertEqual(
            urls, ["https://example.com/alpha", "https://example.com/beta"]
        )

    def test_extract_card_urls_empty_when_no_sources(self):
        self.assertEqual(_extract_card_urls(self.tmp / "ai_old_no_sources.md"), [])

    def test_refresh_writes_snapshots_and_stamps_captured_at(self):
        import hashlib

        def _fake_fetch(url: str) -> dict:
            return {
                "title": f"Title for {url}",
                "content_md": f"# Snapshot\n\nbody of {url}",
                "retrieval_status": "succeeded",
                "failure_reason": "",
                "images": [],
            }

        with mock.patch(
            "scholar_agent.engine.research_harness.fetch_content",
            side_effect=_fake_fetch,
        ) as fc, mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = _run_scan_stale(
                knowledge_dir=str(self.tmp),
                write=False,
                output_format="text",
                refresh=True,
            )

        text = out.getvalue()
        self.assertEqual(rc, 0)
        # Both source URLs were fetched.
        self.assertEqual(fc.call_count, 2)
        # The card-with-sources reports 2/2 refreshed.
        self.assertIn("refreshed 2/2 sources", text)
        # The no-sources card reports accordingly.
        self.assertIn("no sources to refresh", text)

        # Snapshots exist under _snapshots/.
        snapshots_dir = self.tmp / "_snapshots"
        self.assertTrue(snapshots_dir.is_dir())
        files = sorted(p.name for p in snapshots_dir.glob("*.md"))
        self.assertEqual(len(files), 2)
        slug_alpha = hashlib.sha1(b"https://example.com/alpha").hexdigest()[:16]
        self.assertIn(f"{slug_alpha}.md", files)

        # captured_at stamped on the refreshed card, not on the no-sources one.
        refreshed_fm = (self.tmp / "ai_old.md").read_text(encoding="utf-8").split("---")[1]
        self.assertIn("captured_at:", refreshed_fm)
        no_src_fm = (
            (self.tmp / "ai_old_no_sources.md").read_text(encoding="utf-8").split("---")[1]
        )
        self.assertNotIn("captured_at:", no_src_fm)

        # Answer body untouched (no snapshot content leaked into the card body).
        body = (self.tmp / "ai_old.md").read_text(encoding="utf-8").split("---", 2)[2]
        self.assertNotIn("body of https", body)

    def test_refresh_json_payload_includes_refreshed(self):
        with mock.patch(
            "scholar_agent.engine.research_harness.fetch_content",
            return_value={
                "title": "t",
                "content_md": "c",
                "retrieval_status": "succeeded",
                "failure_reason": "",
                "images": [],
            },
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = _run_scan_stale(
                knowledge_dir=str(self.tmp),
                write=False,
                output_format="json",
                refresh=True,
            )
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertIn("refreshed", payload)
        self.assertEqual(len(payload["refreshed"]), 2)  # two stale cards
        by_refreshed = {r["refreshed"] for r in payload["refreshed"]}
        self.assertEqual(by_refreshed, {0, 2})

    def test_refresh_best_effort_skips_failed_fetch(self):
        # First URL fails (returns failed status, empty content); second succeeds.
        def _fake_fetch(url: str) -> dict:
            if url.endswith("/alpha"):
                return {
                    "title": "",
                    "content_md": "",
                    "retrieval_status": "failed",
                    "failure_reason": "boom",
                    "images": [],
                }
            return {
                "title": "beta",
                "content_md": "ok",
                "retrieval_status": "succeeded",
                "failure_reason": "",
                "images": [],
            }

        with mock.patch(
            "scholar_agent.engine.research_harness.fetch_content",
            side_effect=_fake_fetch,
        ), mock.patch("sys.stderr", new_callable=io.StringIO), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = _run_scan_stale(
                knowledge_dir=str(self.tmp),
                write=False,
                output_format="text",
                refresh=True,
            )
        self.assertEqual(rc, 0)
        self.assertIn("refreshed 1/2 sources", out.getvalue())
        # Only one snapshot written.
        self.assertEqual(len(list((self.tmp / "_snapshots").glob("*.md"))), 1)
        # captured_at still stamped because at least one source succeeded.
        fm = (self.tmp / "ai_old.md").read_text(encoding="utf-8").split("---")[1]
        self.assertIn("captured_at:", fm)

    def test_refresh_does_not_abort_on_fetch_exception(self):
        def _fake_fetch(url: str) -> dict:
            raise RuntimeError("network down")

        with mock.patch(
            "scholar_agent.engine.research_harness.fetch_content",
            side_effect=_fake_fetch,
        ), mock.patch("sys.stderr", new_callable=io.StringIO), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = _run_scan_stale(
                knowledge_dir=str(self.tmp),
                write=False,
                output_format="text",
                refresh=True,
            )
        self.assertEqual(rc, 0)
        self.assertIn("refreshed 0/2 sources", out.getvalue())
        # No snapshot written, no captured_at stamped (zero successes).
        self.assertFalse((self.tmp / "_snapshots").exists())
        fm = (self.tmp / "ai_old.md").read_text(encoding="utf-8").split("---")[1]
        self.assertNotIn("captured_at:", fm)

    def test_refresh_combinable_with_write(self):
        with mock.patch(
            "scholar_agent.engine.research_harness.fetch_content",
            return_value={
                "title": "t",
                "content_md": "c",
                "retrieval_status": "succeeded",
                "failure_reason": "",
                "images": [],
            },
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = _run_scan_stale(
                knowledge_dir=str(self.tmp),
                write=True,
                output_format="text",
                refresh=True,
            )
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("refreshed 2/2 sources", text)
        self.assertIn("marked 2 card(s) with stale: true", text)
        # stale: true written to both stale cards.
        for name in ("ai_old.md", "ai_old_no_sources.md"):
            fm = (self.tmp / name).read_text(encoding="utf-8").split("---")[1]
            self.assertIn("stale: true", fm)


if __name__ == "__main__":
    unittest.main()
