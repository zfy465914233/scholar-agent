import contextlib
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
        self.paper_notes_dir = self.test_dir.parent / "paper-notes"
        scholar_config._config_cache = {
            "knowledge_dir": str(self.test_dir),
            "index_path": str(self.index_path),
            "paperpulse_url": "https://mindpulse.top",
            "paperpulse_token": "mock-token",
            "academic": {
                "paper_notes_dir": str(self.paper_notes_dir),
                "daily_notes_dir": str(self.test_dir.parent / "daily-notes"),
            },
        }

    def _cleanup_dir(self, directory: Path) -> None:
        if not directory.exists():
            return
        # Retry cleanup: background reindex threads may still be writing
        for _ in range(3):
            for f in sorted(directory.rglob("*"), reverse=True):
                if f.is_file():
                    f.unlink(missing_ok=True)
                elif f.is_dir():
                    with contextlib.suppress(OSError):
                        f.rmdir()
            if not directory.exists():
                return
            with contextlib.suppress(OSError):
                directory.rmdir()
                return
            import time

            time.sleep(0.1)

    def tearDown(self) -> None:
        scholar_config.clear_cache()
        if self.orig_cache:
            scholar_config._config_cache = self.orig_cache

        # Cleanup test directories
        self._cleanup_dir(self.test_dir)
        self._cleanup_dir(self.paper_notes_dir)

    @patch("urllib.request.urlopen")
    def test_import_mcp_tool_success(self, mock_urlopen) -> None:
        # Mock HTTP Response
        mock_response = MagicMock()
        mock_response.info.return_value = {"Content-Disposition": 'attachment; filename="distilled-test-paper.md"'}
        mock_response.read.return_value = b"---\ntitle: Mocked Paper\n---\nBody content"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = import_paperpulse_note("test-paper-123")
        self.assertIn("Successfully imported paper note", res)

        # Check file was written to paper-notes under title folder
        card_file = self.paper_notes_dir / "Mocked_Paper" / "Mocked_Paper.md"
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

        # Check file was written to paper-notes under title folder
        card_file = self.paper_notes_dir / "CLI_Mocked_Paper" / "CLI_Mocked_Paper.md"
        self.assertTrue(card_file.exists())
        self.assertIn("CLI Mocked Paper", card_file.read_text(encoding="utf-8"))

    def test_allowed_origin_matching(self) -> None:
        from scholar_agent.server import _host_header_is_loopback, _is_allowed_origin, _is_loopback_peer

        self.assertTrue(_is_allowed_origin("https://mindpulse.top"))
        self.assertTrue(_is_allowed_origin("http://localhost:3000"))
        self.assertTrue(_is_allowed_origin("http://127.0.0.1:8080"))
        self.assertTrue(_is_allowed_origin("http://localhost"))
        self.assertTrue(_is_allowed_origin("https://mindpulse.top:8443"))
        self.assertFalse(_is_allowed_origin("https://mindpulse.top.attacker.com"))
        self.assertFalse(_is_allowed_origin("http://localhost.attacker.com:3000"))
        self.assertFalse(_is_allowed_origin("http://localhost.attacker.com"))
        self.assertFalse(_is_allowed_origin("https://attacker.com/mindpulse.top"))
        self.assertFalse(_is_allowed_origin("https://malicious.com"))
        self.assertFalse(_is_allowed_origin(None))
        self.assertTrue(_is_loopback_peer("127.0.0.1"))
        self.assertTrue(_is_loopback_peer("::1"))
        self.assertFalse(_is_loopback_peer("192.168.1.10"))
        self.assertTrue(_host_header_is_loopback("localhost:8765"))
        self.assertTrue(_host_header_is_loopback("127.0.0.1:8765"))
        self.assertTrue(_host_header_is_loopback("[::1]:8765"))
        self.assertFalse(_host_header_is_loopback("localhost.attacker.com"))
        self.assertFalse(_host_header_is_loopback("127.0.0.1.attacker.com"))

    def test_configured_index_path_falls_back_when_empty(self) -> None:
        from scholar_agent.server import _configured_index_path

        self.assertEqual(self.index_path, _configured_index_path({}))
        self.assertEqual(self.index_path, _configured_index_path({"index_path": ""}))
        custom = self.test_dir / "custom-index.json"
        self.assertEqual(custom, _configured_index_path({"index_path": str(custom)}))

    def test_local_http_sync_server(self) -> None:
        import json
        import threading
        import urllib.error
        import urllib.request
        from http.server import HTTPServer

        from scholar_agent.server import ScholarAgentLocalServer

        # Start server on free port
        server = HTTPServer(("127.0.0.1", 0), ScholarAgentLocalServer)
        port = server.server_port

        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        # HTTP handler writes to paper-notes/ (sibling of knowledge_dir)
        paper_notes_dir = self.test_dir.parent / "paper-notes"

        try:
            # 1. Health check
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health", headers={"Origin": "https://mindpulse.top"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["status"], "ok")

            # 2. Import markdown (with correct token in header)
            post_data = {
                "filename": "test-via-http.md",
                "markdown": "---\ntitle: Test HTTP Sync\ndomain: Test\n---\n# Success Title\nContent here",
            }
            body = json.dumps(post_data).encode("utf-8")

            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/import-markdown",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://mindpulse.top",
                    "Authorization": "Bearer mock-token",
                },
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["status"], "success")

            # 2b. Import markdown with missing token (expect 401)
            req_no_token = urllib.request.Request(
                f"http://127.0.0.1:{port}/import-markdown",
                data=body,
                headers={"Content-Type": "application/json", "Origin": "https://mindpulse.top"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req_no_token)
            self.assertEqual(cm.exception.code, 401)

            # 2c. Import markdown with bad token (expect 401)
            req_bad_token = urllib.request.Request(
                f"http://127.0.0.1:{port}/import-markdown",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://mindpulse.top",
                    "Authorization": "Bearer wrong-token",
                },
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req_bad_token)
            self.assertEqual(cm.exception.code, 401)

            # Verify file was written to paper-notes/Test/Test_HTTP_Sync/Test_HTTP_Sync.md
            written_file = paper_notes_dir / "Test" / "Test_HTTP_Sync" / "Test_HTTP_Sync.md"
            self.assertTrue(written_file.exists())
            self.assertIn("Success Title", written_file.read_text(encoding="utf-8"))

            # 3. Disallowed origin health check
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health", headers={"Origin": "https://malicious.com"})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code, 403)

            # 4. Invalid JSON
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/import-markdown",
                data=b"{invalid-json}",
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://mindpulse.top",
                    "Authorization": "Bearer mock-token",
                },
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code, 400)
            err_data = json.loads(cm.exception.read().decode("utf-8"))
            self.assertIn("Invalid JSON body", err_data["error"])

            # 4a. Malformed Content-Length should return 400 instead of crashing the handler
            import socket

            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                sock.sendall(
                    (
                        "POST /import-markdown HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{port}\r\n"
                        "Origin: https://mindpulse.top\r\n"
                        "Content-Type: application/json\r\n"
                        "Authorization: Bearer mock-token\r\n"
                        "Content-Length: nope\r\n"
                        "\r\n"
                    ).encode("ascii")
                )
                response = sock.recv(1024).decode("utf-8", errors="replace")
            self.assertIn("400", response)

            # 4b. Invalid JSON type (list instead of dict)
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/import-markdown",
                data=b"[1, 2, 3]",
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://mindpulse.top",
                    "Authorization": "Bearer mock-token",
                },
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code, 400)
            err_data = json.loads(cm.exception.read().decode("utf-8"))
            self.assertIn("expected a dictionary object", err_data["error"])

            # 5. Missing fields
            post_missing = {"filename": "missing.md"}
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/import-markdown",
                data=json.dumps(post_missing).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://mindpulse.top",
                    "Authorization": "Bearer mock-token",
                },
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code, 400)
            err_data = json.loads(cm.exception.read().decode("utf-8"))
            self.assertIn("Missing filename or markdown content", err_data["error"])

        finally:
            server.shutdown()
            server.server_close()
            self._cleanup_dir(paper_notes_dir)


if __name__ == "__main__":
    unittest.main()
