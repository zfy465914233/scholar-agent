"""Local HTTP sync server adapter.

A lightweight HTTP server (separate from the stdio MCP transport) exposing a
write endpoint (``/import-markdown``) for external tools such as the
PaperPulse SaaS to push markdown into the knowledge base, plus a ``/health``
probe. MCP tools live in :mod:`scholar_agent.server`; this module owns only the
HTTP layer.

Authentication: when ``paperpulse_token`` is configured it is strictly
enforced; otherwise writes are restricted to loopback peers/origins.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from scholar_agent.engine.index_lifecycle import async_reindex as _async_reindex
from scholar_agent.engine.scholar_config import _configured_index_path, load_config

logger = logging.getLogger(__name__)


def _is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return False
    from urllib.parse import urlparse

    try:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if parsed.scheme == "https" and hostname == "mindpulse.top":
            return True
        if parsed.scheme == "http" and hostname in ("localhost", "127.0.0.1"):
            return True
    except Exception:
        pass
    return False


def _is_loopback_host(value: str) -> bool:
    """Return True when a Host/Origin hostname represents this machine."""
    host = value.strip().strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_loopback_peer(peer: str) -> bool:
    """Return True only for actual loopback peer addresses."""
    try:
        return ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return False


def _host_header_is_loopback(host_header: str) -> bool:
    """Validate Host header hostname without trusting substring matches."""
    if not host_header:
        return False
    if host_header.startswith("["):
        host = host_header[1:].split("]", 1)[0]
    elif host_header.count(":") > 1:
        host = host_header
    else:
        host = host_header.rsplit(":", 1)[0] if ":" in host_header else host_header
    return _is_loopback_host(host)


class ScholarAgentLocalServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Prevent printing to stdout to avoid corrupting MCP JSON-RPC protocol
        logger.info(format % args)

    def _origin_is_forbidden(self) -> bool:
        """True when an explicit Origin header is present but not allow-listed."""
        origin = self.headers.get("Origin")
        return origin is not None and not _is_allowed_origin(origin)

    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        if _is_allowed_origin(origin):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", origin or "")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS, GET")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")
            # Required for Chrome Private Network Access (public HTTPS → localhost HTTP)
            if self.headers.get("Access-Control-Request-Private-Network"):
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
        else:
            self.send_response(403)
            self.end_headers()

    def do_GET(self):
        if self._origin_is_forbidden():
            self.send_response(403)
            self.end_headers()
            return
        origin = self.headers.get("Origin")

        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "version": "1.0.0"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self._origin_is_forbidden():
            self.send_response(403)
            self.end_headers()
            return
        origin = self.headers.get("Origin")

        if self.path == "/import-markdown":
            # Cap body size at 10 MB to prevent OOM
            _MAX_BODY = 10 * 1024 * 1024
            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                self.send_error_response(400, "Invalid Content-Length", origin)
                return
            if content_length < 0:
                self.send_error_response(400, "Invalid Content-Length", origin)
                return
            if content_length > _MAX_BODY:
                self.send_error_response(413, "Payload too large (max 10 MB)", origin)
                return
            body = self.rfile.read(content_length) if content_length > 0 else b""
            try:
                data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as e:
                self.send_error_response(400, f"Invalid JSON body: {e!s}", origin)
                return

            if not isinstance(data, dict):
                self.send_error_response(400, "Invalid JSON payload: expected a dictionary object", origin)
                return

            # Check Authentication Token
            config = load_config()
            configured_token = config.get("paperpulse_token", "").strip()

            # Extract token from header or body
            auth_header = self.headers.get("Authorization", "")
            req_token = ""
            if auth_header.lower().startswith("bearer "):
                req_token = auth_header[7:].strip()
            else:
                req_token = data.get("token") or data.get("api_token") or ""
            req_token = str(req_token).strip()

            # If token is configured, enforce strict match.
            # If token is NOT configured, allow ONLY if request comes from local origin or no origin (direct curl/test).
            is_authenticated = False
            if configured_token:
                is_authenticated = req_token == configured_token
            else:
                host_header = self.headers.get("Host", "")
                is_local_host = _host_header_is_loopback(host_header)
                is_local_origin = False
                if origin is None:
                    is_local_origin = _is_loopback_peer(str(self.client_address[0]))
                else:
                    from urllib.parse import urlparse

                    try:
                        parsed = urlparse(origin)
                        is_local_origin = bool(parsed.hostname and _is_loopback_host(parsed.hostname))
                    except Exception:
                        is_local_origin = False
                is_authenticated = is_local_host and is_local_origin

            if not is_authenticated:
                self.send_error_response(
                    401, "Unauthorized: Invalid or missing token, or write rejected for security reasons.", origin
                )
                return

            filename = data.get("filename")
            markdown_content = data.get("markdown")

            if not filename or not markdown_content:
                self.send_error_response(400, "Missing filename or markdown content", origin)
                return

            try:
                from scholar_agent.engine.import_service import import_markdown

                msg, saved_filename = import_markdown(filename, markdown_content)

                if saved_filename is None:
                    self.send_error_response(400, msg, origin)
                    return

                index_path = _configured_index_path(config)
                _async_reindex(index_path)

                self.send_success_response(
                    origin,
                    {
                        "status": "success",
                        "filename": saved_filename,
                        "message": msg,
                    },
                )
            except Exception:
                logger.warning("HTTP /import-markdown failed", exc_info=True)
                self.send_error_response(500, "Internal server error", origin)
        else:
            self.send_error_response(404, "Not Found", origin)

    def _respond(self, code: int, payload: dict, origin: str | None = None) -> None:
        """Write a JSON response with an optional CORS header (shared by success/error)."""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def send_success_response(self, origin, data):
        self._respond(200, data, origin)

    def send_error_response(self, code, message, origin=None):
        self._respond(code, {"error": message}, origin)


def start_local_server() -> int:
    """Start the HTTP sync server. Returns 0 on success, 1 on failure."""
    port = int(os.environ.get("SCHOLAR_PORT", "8374"))
    try:
        server = HTTPServer(("127.0.0.1", port), ScholarAgentLocalServer)
        logger.info("Scholar Agent Local Sync Server listening on http://127.0.0.1:%d", port)
        server.serve_forever()
    except Exception:
        logger.error("Failed to start Scholar Agent Local Sync Server", exc_info=True)
        return 1
    return 0
