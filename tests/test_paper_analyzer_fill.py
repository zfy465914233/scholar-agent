"""
Comprehensive tests for paper_analyzer fill pipeline.

Covers:
  1. _resolve_providers() — 6 user scenarios
  2. _call_llm_anthropic / _call_llm_openai — response parsing + error handling
  3. URL construction — no double-append
  4. fill_note_from_pdf — branching logic
  5. generate_note — path consistency with download_paper
  6. Integration — full end-to-end flow
"""

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure scripts/ is on path


def _reload_module():
    """Reload paper_analyzer to pick up env var changes."""
    import scholar_agent.engine.academic.paper_analyzer as pa
    importlib.reload(pa)
    return pa


# ============================================================================
# 1. _resolve_providers — 6 user scenarios
# ============================================================================
class TestResolveProviders(unittest.TestCase):
    """Test provider resolution for different user configurations."""

    def _clean_env(self):
        """Remove all LLM-related env vars."""
        for key in list(os.environ):
            if any(key.startswith(p) for p in (
                "SCHOLAR_FILLER_", "ANTHROPIC_", "OPENAI_",
                "SCHOLAR_ROUTER_", "LLM_", "GITHUB_TOKEN",
            )):
                del os.environ[key]

    def test_scenario1_explicit_filler(self):
        """User with SCHOLAR_FILLER_* explicit override."""
        self._clean_env()
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "openai"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://proxy.example.com/v1"
        os.environ["SCHOLAR_FILLER_MODEL"] = "my-model"
        os.environ["SCHOLAR_FILLER_API_KEY"] = "key-explicit"
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "key-anth"
        os.environ["OPENAI_API_KEY"] = "key-oai"

        pa = _reload_module()
        providers = pa._resolve_providers()

        # Priority 1: explicit filler
        self.assertEqual(providers[0][0], "openai")
        self.assertEqual(providers[0][1], "https://proxy.example.com/v1")
        self.assertEqual(providers[0][2], "key-explicit")
        self.assertEqual(providers[0][3], "my-model")

        # Priority 2: Anthropic (different URL)
        self.assertEqual(providers[1][0], "anthropic")

        # Priority 3: OpenAI (different URL from filler → not deduped)
        self.assertEqual(providers[2][0], "openai")
        self.assertIn("api.openai.com", providers[2][1])

    def test_scenario2_pure_anthropic(self):
        """User with only Anthropic official credentials."""
        self._clean_env()
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-xxx"
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"

        pa = _reload_module()
        providers = pa._resolve_providers()

        # Should have at least the Anthropic provider
        anthro = [p for p in providers if p[0] == "anthropic"]
        self.assertGreaterEqual(len(anthro), 1)
        self.assertIn("api.anthropic.com", anthro[0][1])
        self.assertEqual(anthro[0][3], "claude-sonnet-4-20250514")

    def test_scenario3_pure_openai(self):
        """User with only OpenAI credentials."""
        self._clean_env()
        os.environ["OPENAI_API_KEY"] = "sk-xxx"

        pa = _reload_module()
        providers = pa._resolve_providers()

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0][0], "openai")
        self.assertIn("api.openai.com", providers[0][1])

    def test_scenario4_zhipu_proxy(self):
        """User with ANTHROPIC_* pointing to Zhipu proxy (not real Anthropic)."""
        self._clean_env()
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "zhipu-token"
        os.environ["ANTHROPIC_BASE_URL"] = "https://open.bigmodel.cn/api/anthropic"

        pa = _reload_module()
        providers = pa._resolve_providers()

        # Should resolve as Anthropic provider (Priority 2)
        anthro = [p for p in providers if p[0] == "anthropic"]
        self.assertGreaterEqual(len(anthro), 1)
        self.assertIn("bigmodel.cn", anthro[0][1])

    def test_scenario5_no_credentials(self):
        """User with no LLM credentials at all."""
        self._clean_env()

        pa = _reload_module()
        providers = pa._resolve_providers()

        self.assertEqual(len(providers), 0)

    def test_deduplication(self):
        """Same (format, url) should only appear once."""
        self._clean_env()
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "anthropic"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://api.anthropic.com"
        os.environ["SCHOLAR_FILLER_API_KEY"] = "key1"
        os.environ["ANTHROPIC_API_KEY"] = "key2"
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"

        pa = _reload_module()
        providers = pa._resolve_providers()

        # Anthropic @ api.anthropic.com should appear only once
        anthro_providers = [p for p in providers if p[0] == "anthropic"]
        urls = [p[1].rstrip("/") for p in anthro_providers]
        self.assertEqual(len([u for u in urls if "api.anthropic.com" in u]), 1)


# ============================================================================
# 2. LLM call functions — response parsing + error handling
# ============================================================================
class TestCallLlmAnthropic(unittest.TestCase):

    def test_normal_response(self):
        """Standard Anthropic response with content blocks."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "content": [{"type": "text", "text": "Hello from Claude"}]
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response):
            result = pa._call_llm_anthropic(
                "https://api.anthropic.com", "key", "model", "sys", "user"
            )
            self.assertEqual(result, "Hello from Claude")

    def test_error_response(self):
        """API returns error object instead of content."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "error": {"message": "Invalid API key", "type": "auth_error"}
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response):
            with self.assertRaises(RuntimeError) as ctx:
                pa._call_llm_anthropic(
                    "https://api.anthropic.com", "key", "model", "sys", "user"
                )
            self.assertIn("Invalid API key", str(ctx.exception))

    def test_proxy_nonstandard_response(self):
        """Proxy returns non-standard format (e.g. Zhipu's {code, msg, success})."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "code": 500, "msg": "404 NOT_FOUND", "success": False
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response):
            with self.assertRaises(KeyError) as ctx:
                pa._call_llm_anthropic(
                    "https://proxy.example.com", "key", "model", "sys", "user"
                )
            self.assertIn("content", str(ctx.exception))

    def test_thinking_blocks_skipped(self):
        """Response with thinking blocks should find the text block."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "content": [
                {"type": "thinking", "thinking": "internal thought"},
                {"type": "text", "text": "The actual answer"},
            ]
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response):
            result = pa._call_llm_anthropic(
                "https://api.anthropic.com", "key", "model", "sys", "user"
            )
            self.assertEqual(result, "The actual answer")


class TestCallLlmOpenai(unittest.TestCase):

    def test_normal_response(self):
        """Standard OpenAI response."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Hello from GPT"}}]
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response):
            result = pa._call_llm_openai(
                "https://api.openai.com/v1", "key", "model", "sys", "user"
            )
            self.assertEqual(result, "Hello from GPT")

    def test_error_response(self):
        """OpenAI-compatible API returns error."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "error": {"message": "Rate limit exceeded", "type": "rate_limit"}
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response):
            with self.assertRaises(RuntimeError) as ctx:
                pa._call_llm_openai(
                    "https://api.openai.com/v1", "key", "model", "sys", "user"
                )
            self.assertIn("Rate limit", str(ctx.exception))

    def test_missing_choices_key(self):
        """Response missing 'choices' key."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "error", "detail": "something went wrong"
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response):
            with self.assertRaises(KeyError) as ctx:
                pa._call_llm_openai(
                    "https://proxy.example.com/v1", "key", "model", "sys", "user"
                )
            self.assertIn("choices", str(ctx.exception))

    def test_url_no_double_append(self):
        """URL already ending in /chat/completions should not be doubled."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "ok"}}]
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response) as mock_urlopen:
            pa._call_llm_openai(
                "https://api.example.com/v1/chat/completions", "key", "model", "sys", "user"
            )
            # Check the actual URL used in the request
            call_args = mock_urlopen.call_args
            request_obj = call_args[0][0]
            self.assertNotIn("/chat/completions/chat/completions", request_obj.full_url)
            self.assertTrue(request_obj.full_url.endswith("/chat/completions"))


# ============================================================================
# 3. fill_note_from_pdf — branching logic
# ============================================================================
class TestFillNoteFromPdf(unittest.TestCase):

    def test_no_providers_skips(self):
        """No API keys → returns skipped."""
        for key in list(os.environ):
            if any(key.startswith(p) for p in (
                "SCHOLAR_FILLER_", "ANTHROPIC_", "OPENAI_",
                "SCHOLAR_ROUTER_", "LLM_", "GITHUB_TOKEN",
            )):
                del os.environ[key]

        pa = _reload_module()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nstatus: skeleton\n---\n\n## Test\n<!-- LLM: fill this -->\n")
            f.flush()
            result = pa.fill_note_from_pdf(f.name, "some pdf text")

        self.assertEqual(result["status"], "skipped")
        self.assertIn("No API key", result["reason"])
        os.unlink(f.name)

    def test_no_placeholders_skips(self):
        """Note with no placeholders → returns skipped."""
        os.environ["SCHOLAR_FILLER_API_KEY"] = "test-key"
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "openai"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://example.com/v1"
        os.environ["SCHOLAR_FILLER_MODEL"] = "test"

        pa = _reload_module()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nstatus: filled\n---\n\n## Already filled\nContent here.\n")
            f.flush()
            result = pa.fill_note_from_pdf(f.name, "some pdf text")

        self.assertEqual(result["status"], "skipped")
        self.assertIn("No placeholders", result["reason"])
        os.unlink(f.name)

    def test_fallback_on_primary_failure(self):
        """Primary provider fails → fallback provider succeeds."""
        for key in list(os.environ):
            if any(key.startswith(p) for p in (
                "SCHOLAR_FILLER_", "ANTHROPIC_", "OPENAI_",
                "SCHOLAR_ROUTER_", "LLM_", "GITHUB_TOKEN",
            )):
                del os.environ[key]

        os.environ["SCHOLAR_FILLER_API_KEY"] = "filler-key"
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "anthropic"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://broken-proxy.com/api"
        os.environ["SCHOLAR_FILLER_MODEL"] = "test-model"
        os.environ["OPENAI_API_KEY"] = "openai-key"

        pa = _reload_module()

        # Mock: Anthropic (primary) fails, OpenAI (fallback) succeeds
        call_count = {"n": 0}

        def mock_urlopen(req, timeout=120):
            call_count["n"] += 1
            if "messages" in req.full_url:
                # Anthropic format → error
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps({
                    "code": 500, "msg": "NOT_FOUND", "success": False
                }).encode()
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = lambda s, *a: None
                return mock_resp
            else:
                # OpenAI format → success
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps({
                    "choices": [{"message": {"content": "## Filled\nContent."}}]
                }).encode()
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = lambda s, *a: None
                return mock_resp

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nstatus: skeleton\n---\n\n## Test\n<!-- LLM: fill this -->\n")
            f.flush()

            with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", side_effect=mock_urlopen):
                result = pa.fill_note_from_pdf(f.name, "pdf text")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["api_format"], "openai")
        self.assertGreater(call_count["n"], 1)  # Tried more than one provider
        os.unlink(f.name)


# ============================================================================
# 4. generate_note — path consistency with download_paper
# ============================================================================
class TestGenerateNotePath(unittest.TestCase):

    def test_note_in_title_subfolder(self):
        """generate_note should create {domain}/{title}/{title}.md structure."""
        for key in list(os.environ):
            if any(key.startswith(p) for p in ("SCHOLAR_FILLER_",)):
                del os.environ[key]

        pa = _reload_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            paper = {
                "title": "Test Paper Title Here",
                "arxiv_id": "2401.12345",
                "authors": ["Author One"],
                "best_domain": "test-domain",
            }
            note_path = pa.generate_note(paper, tmpdir, language="en")

            # Should be at: tmpdir/test-domain/Test-Paper-Title-Here/Test-Paper-Title-Here.md
            self.assertIn("test-domain", note_path)
            parent = Path(note_path).parent.name
            self.assertIn("Test", parent)

            # File should exist
            self.assertTrue(Path(note_path).exists())

            # Should NOT be at tmpdir/test-domain/Test-Paper-Title-Here.md (old structure)
            flat_path = os.path.join(tmpdir, "test-domain", Path(note_path).name)
            if note_path != flat_path:
                self.assertFalse(
                    os.path.exists(flat_path),
                    f"Note should not exist at flat path: {flat_path}"
                )


# ============================================================================
# 5. Integration — full flow check
# ============================================================================
class TestIntegration(unittest.TestCase):

    def test_full_flow_with_mock(self):
        """Simulate full analyze + fill flow with mocked LLM."""
        for key in list(os.environ):
            if any(key.startswith(p) for p in (
                "SCHOLAR_FILLER_", "ANTHROPIC_", "OPENAI_",
                "SCHOLAR_ROUTER_", "LLM_", "GITHUB_TOKEN",
            )):
                del os.environ[key]

        os.environ["SCHOLAR_FILLER_API_KEY"] = "test-key"
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "openai"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://api.example.com/v1"
        os.environ["SCHOLAR_FILLER_MODEL"] = "test-model"

        pa = _reload_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Step 1: Generate note (skeleton)
            paper = {
                "title": "Integration Test Paper",
                "arxiv_id": "9999.99999",
                "authors": ["Test Author"],
                "best_domain": "test-domain",
            }
            note_path = pa.generate_note(paper, tmpdir, language="zh")

            # Verify skeleton has placeholders
            content = Path(note_path).read_text(encoding="utf-8")
            self.assertIn("<!-- LLM:", content)
            self.assertIn("status: skeleton", content)

            # Step 2: Fill with mocked LLM
            mock_response = MagicMock()
            filled_content = content.replace("<!-- LLM: fill -->", "Filled content")
            # Simulate LLM returning the content with placeholders filled
            mock_llm_output = content.replace("status: skeleton", "status: filled")
            mock_llm_output = mock_llm_output.replace("<!-- LLM:", "RESOLVED<!-- ")
            mock_response.read.return_value = json.dumps({
                "choices": [{"message": {"content": mock_llm_output}}]
            }).encode()
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = lambda s, *a: None

            with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response):
                result = pa.fill_note_from_pdf(note_path, "fake pdf text for testing")

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["api_format"], "openai")
            self.assertEqual(result["model_used"], "test-model")


# ============================================================================
# 6. Regression tests for newly fixed bugs
# ============================================================================
class TestBugFixes(unittest.TestCase):

    def test_bugA_slugification_matches_download_paper(self):
        """title_to_filename must produce the same slug as _sanitize_title."""
        pa = _reload_module()

        from scholar_agent.server import _sanitize_title

        test_titles = [
            "Survey of Data-driven Newsvendor: Unified Analysis and Spectrum",
            "The Data-Driven Censored Newsvendor Problem",
            "Deep Generative Demand Learning for Newsvendor and Pricing",
            "A/B Testing: Why & How!",
            "Normal Title Without Special Characters",
        ]
        for title in test_titles:
            with self.subTest(title=title):
                self.assertEqual(
                    pa.title_to_filename(title),
                    _sanitize_title(title),
                    f"Slug mismatch for: {title}"
                )

    def test_bugB_openai_empty_choices(self):
        """Empty choices list should raise KeyError, not IndexError."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": []
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response):
            with self.assertRaises(KeyError) as ctx:
                pa._call_llm_openai(
                    "https://api.openai.com/v1", "key", "model", "sys", "user"
                )
            self.assertIn("no choices", str(ctx.exception).lower())

    def test_bugC_anthropic_url_no_double_append(self):
        """URL ending in /messages should not be doubled."""
        pa = _reload_module()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "content": [{"type": "text", "text": "ok"}]
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.academic.paper_analyzer.urlopen", return_value=mock_response) as mock_urlopen:
            pa._call_llm_anthropic(
                "https://api.anthropic.com/v1/messages", "key", "model", "sys", "user"
            )
            request_obj = mock_urlopen.call_args[0][0]
            self.assertNotIn("/messages/messages", request_obj.full_url)
            self.assertTrue(request_obj.full_url.endswith("/messages"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
