import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scholar_agent.cli import _run_import_paper
from scholar_agent.engine import scholar_config
from scholar_agent.server import import_paperpulse_note


class TestImportPaperPulse(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = Path(__file__).resolve().parent / "fixtures_temp"
        self.test_dir.mkdir(parents=True, exist_ok=True)

        self.index_path = self.test_dir / "index.json"

        self.orig_cache = getattr(scholar_config, "_config_cache", None)
        scholar_config._config_cache = {
            "knowledge_dir": str(self.test_dir),
            "index_path": str(self.index_path),
            "paperpulse_url": "https://pulse.mindpulse.ai",
            "paperpulse_token": "mock-token",
        }

    def tearDown(self) -> None:
        scholar_config.clear_cache()
        if self.orig_cache:
            scholar_config._config_cache = self.orig_cache

        # Cleanup files
        for f in self.test_dir.rglob("*"):
            if f.is_file():
                f.unlink()
        if self.test_dir.exists():
            self.test_dir.rmdir()

    @patch("urllib.request.urlopen")
    def test_import_mcp_tool_success(self, mock_urlopen) -> None:
        # Mock HTTP Response
        mock_response = MagicMock()
        mock_response.info.return_value = {"Content-Disposition": 'attachment; filename="distilled-test-paper.md"'}
        mock_response.read.return_value = b"---\ntitle: Mocked Paper\n---\nBody content"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = import_paperpulse_note("test-paper-123")
        self.assertIn("Successfully imported paper note", res)

        # Check file was written
        card_file = self.test_dir / "distilled-test-paper.md"
        self.assertTrue(card_file.exists())
        self.assertIn("Mocked Paper", card_file.read_text(encoding="utf-8"))

    @patch("urllib.request.urlopen")
    def test_import_cli_command_success(self, mock_urlopen) -> None:
        # Mock HTTP Response
        mock_response = MagicMock()
        mock_response.info.return_value = {}
        mock_response.read.return_value = b"---\ntitle: CLI Mocked Paper\n---\nCLI Body content"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Call CLI helper directly
        status = _run_import_paper(paper_id="test-paper-456", token="cli-token", url="http://localhost:8000")
        self.assertEqual(0, status)

        # Check file was written to default fallback filename
        card_file = self.test_dir / "distilled-test-paper-456.md"
        self.assertTrue(card_file.exists())
        self.assertIn("CLI Mocked Paper", card_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
