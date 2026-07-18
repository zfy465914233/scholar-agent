import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from unittest.mock import patch

from scholar_agent.adapters.http_server import ScholarAgentLocalServer
from scholar_agent.engine import scholar_config

GRAPH_FIXTURE = {
    "schema_version": 1,
    "nodes": [
        {
            "id": "paper-note__mock",
            "title": "Mock Paper",
            "node_type": "paper-note",
            "topic": "",
            "domain": "test",
            "tags": ["论文笔记"],
            "year": 2024,
            "arxiv_id": "2401.00001",
            "venue": "NeurIPS 2024",
            "domains": ["test"],
            "is_local": True,
        }
    ],
    "edges": [],
    "stats": {"local_nodes": 1, "local_edges": 0, "cloud_edges": 0},
}


class TestGraphHttpEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.orig_cache = getattr(scholar_config, "_config_cache", None)
        self.server = HTTPServer(("127.0.0.1", 0), ScholarAgentLocalServer)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        scholar_config.clear_cache()
        if self.orig_cache:
            scholar_config._config_cache = self.orig_cache

    def _set_config(self, **overrides) -> None:
        config = {
            "knowledge_dir": "/tmp/nonexistent-knowledge",
            "index_path": "/tmp/nonexistent-index.json",
            "paperpulse_url": "https://mindpulse.top",
        }
        config.update(overrides)
        scholar_config._config_cache = config

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path: str, headers: dict) -> tuple[int, dict, object]:
        """Return (status, json_body, response_headers); tolerates HTTP errors."""
        req = urllib.request.Request(self._url(path), headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8")), e.headers

    def test_graph_success_with_bearer_and_cors(self) -> None:
        self._set_config(paperpulse_token="mock-token")
        with patch(
            "scholar_agent.engine.graph_export.build_graph_export", return_value=GRAPH_FIXTURE
        ) as mock_export:
            status, body, headers = self._get(
                "/graph",
                {"Origin": "https://mindpulse.top", "Authorization": "Bearer mock-token"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(body, GRAPH_FIXTURE)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://mindpulse.top")
        mock_export.assert_called_once_with(include_cloud=True)

    def test_graph_unauthorized_without_bearer(self) -> None:
        self._set_config(paperpulse_token="mock-token")
        with patch("scholar_agent.engine.graph_export.build_graph_export", return_value=GRAPH_FIXTURE):
            status, body, _ = self._get("/graph", {"Origin": "https://mindpulse.top"})
        self.assertEqual(status, 401)
        self.assertIn("error", body)

    def test_graph_unauthorized_with_wrong_bearer(self) -> None:
        self._set_config(paperpulse_token="mock-token")
        with patch("scholar_agent.engine.graph_export.build_graph_export", return_value=GRAPH_FIXTURE):
            status, body, _ = self._get(
                "/graph",
                {"Origin": "https://mindpulse.top", "Authorization": "Bearer wrong-token"},
            )
        self.assertEqual(status, 401)
        self.assertIn("error", body)

    def test_graph_loopback_allowed_when_no_token_configured(self) -> None:
        self._set_config()  # no paperpulse_token
        with patch("scholar_agent.engine.graph_export.build_graph_export", return_value=GRAPH_FIXTURE):
            status, body, _ = self._get("/graph", {"Origin": "http://localhost:3000"})
        self.assertEqual(status, 200)
        self.assertEqual(body, GRAPH_FIXTURE)

    def test_graph_non_loopback_origin_forbidden(self) -> None:
        self._set_config()  # no paperpulse_token
        req = urllib.request.Request(self._url("/graph"), headers={"Origin": "https://malicious.com"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)

    def test_options_preflight_allows_authorization_header(self) -> None:
        self._set_config()
        req = urllib.request.Request(
            self._url("/graph"),
            headers={
                "Origin": "https://mindpulse.top",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
            method="OPTIONS",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            allow_headers = resp.headers.get("Access-Control-Allow-Headers", "")
        self.assertIn("Authorization", allow_headers)
        self.assertIn("Content-Type", allow_headers)

    def test_graph_local_only_query_param(self) -> None:
        self._set_config(paperpulse_token="mock-token")
        headers = {"Origin": "https://mindpulse.top", "Authorization": "Bearer mock-token"}
        with patch(
            "scholar_agent.engine.graph_export.build_graph_export", return_value=GRAPH_FIXTURE
        ) as mock_export:
            status, _, _ = self._get("/graph?local_only=1", headers)
            self.assertEqual(status, 200)
            mock_export.assert_called_once_with(include_cloud=False)

        with patch(
            "scholar_agent.engine.graph_export.build_graph_export", return_value=GRAPH_FIXTURE
        ) as mock_export:
            status, _, _ = self._get("/graph", headers)
            self.assertEqual(status, 200)
            mock_export.assert_called_once_with(include_cloud=True)


if __name__ == "__main__":
    unittest.main()
