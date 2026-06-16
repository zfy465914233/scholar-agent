"""Tests for analyze_paper PDF resolution (改动 A): fail-loud + auto-download.

`_resolve_analysis_pdf` is the extracted helper that implements the precedence
explicit path > local detection > arXiv auto-download > None. analyze_paper calls
it and fail-louds (returns status="error", no empty skeleton) on None — that
end-to-end contract is verified via the real MCP tool in the integration check.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]

from scholar_agent.engine import scholar_config
from scholar_agent.server import _resolve_analysis_pdf


class ResolveAnalysisPdfTest(unittest.TestCase):
    """_resolve_analysis_pdf precedence: explicit path > local detect > download > None."""

    def setUp(self) -> None:
        # Pin config to scholar-agent's own dirs PER-TEST so PDF resolution
        # never leaks into parent projects. Done in setUp (not at module import)
        # so we don't mutate the global scholar_config cache during collection —
        # that module-level side effect previously polluted other suites
        # (e.g. test_incremental_index, whose iter_cards reads this cache).
        self._orig_cache = scholar_config._config_cache
        scholar_config._config_cache = {
            "knowledge_dir": str(_ROOT / "tests" / "fixtures"),
            "index_path": str(_ROOT / "indexes" / "local" / "index.json"),
            "scholar_dir": str(_ROOT),
        }

    def tearDown(self) -> None:
        scholar_config._config_cache = self._orig_cache

    def test_explicit_path_returned_directly(self):
        paper = {"title": "Explicit"}
        expected = Path("/scholar/x.pdf")
        with patch("scholar_agent.server._validate_path_within", return_value=expected):
            # _resolve_analysis_pdf returns str(Path); compare platform-natively
            # so the assertion holds on both POSIX (/) and Windows (\).
            self.assertEqual(_resolve_analysis_pdf(paper, "/scholar/x.pdf"), str(expected))

    def test_local_detection_skips_download(self):
        paper = {"title": "Local", "arxiv_id": "1234.5678"}
        with (
            patch("scholar_agent.server._find_local_pdf", return_value="/scholar/local.pdf"),
            patch("scholar_agent.engine.academic.image_extractor.download_arxiv_pdf") as dl,
        ):
            self.assertEqual(_resolve_analysis_pdf(paper, ""), "/scholar/local.pdf")
            dl.assert_not_called()  # found locally -> no download attempt

    def test_autodownload_when_no_local_pdf(self):
        paper = {"title": "Auto", "arxiv_id": "1234.5678"}
        with tempfile.TemporaryDirectory() as tmp:
            fake_pdf = Path(tmp) / "1234.5678.pdf"
            fake_pdf.write_bytes(b"%PDF-1.4 fake")
            with (
                patch("scholar_agent.server._find_local_pdf", return_value=None),
                patch("scholar_agent.server.get_paper_notes_dir", return_value=Path(tmp)),
                patch(
                    "scholar_agent.engine.academic.image_extractor.download_arxiv_pdf",
                    return_value=str(fake_pdf),
                ) as dl,
            ):
                result = _resolve_analysis_pdf(paper, "")
            self.assertEqual(result, str(fake_pdf))
            dl.assert_called_once_with("1234.5678", str(Path(tmp) / "1234.5678"))

    def test_none_when_no_arxiv_and_no_path(self):
        paper = {"title": "No Source"}  # no arxiv_id, no pdf_path
        with (
            patch("scholar_agent.server._find_local_pdf", return_value=None),
            patch("scholar_agent.engine.academic.image_extractor.download_arxiv_pdf") as dl,
        ):
            # This None is exactly what makes analyze_paper fail-loud.
            self.assertIsNone(_resolve_analysis_pdf(paper, ""))
            dl.assert_not_called()

    def test_download_failure_returns_none_not_raise(self):
        """A failed download must not raise — analyze_paper then fail-louds on None."""

        def _boom(_aid, _dir):
            raise RuntimeError("network down")

        paper = {"title": "Broken", "arxiv_id": "1234.5678"}
        with (
            patch("scholar_agent.server._find_local_pdf", return_value=None),
            patch("scholar_agent.server.get_paper_notes_dir", return_value=Path(tempfile.mkdtemp())),
            patch(
                "scholar_agent.engine.academic.image_extractor.download_arxiv_pdf",
                side_effect=_boom,
            ),
        ):
            self.assertIsNone(_resolve_analysis_pdf(paper, ""))

    def test_invalid_pdf_path_raises_value_error(self):
        paper = {"title": "Bad Path"}
        with patch("scholar_agent.server._validate_path_within", return_value=None), self.assertRaises(ValueError):
            _resolve_analysis_pdf(paper, "/etc/passwd")


if __name__ == "__main__":
    unittest.main(verbosity=2)
