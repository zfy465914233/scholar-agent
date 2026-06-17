"""
Comprehensive tests for the unified LLM client and paper_analyzer fill pipeline.

Covers:
  1. resolve_providers() — 6 user scenarios
  2. _parse_anthropic / _parse_openai — response parsing + error handling
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

from scholar_agent.engine.llm_client import (
    ProviderConfig,
    _parse_anthropic,
    _parse_openai,
    _send_anthropic,
    _send_openai,
    resolve_providers,
)


def _reload_paper_analyzer():
    """Reload paper_analyzer to pick up env var changes."""
    import scholar_agent.engine.academic.paper_analyzer as pa

    importlib.reload(pa)
    return pa


def _clean_env():
    """Remove all LLM-related env vars and clear provider cache."""
    for key in list(os.environ):
        if any(
            key.startswith(p)
            for p in (
                "SCHOLAR_FILLER_",
                "ANTHROPIC_",
                "OPENAI_",
                "SCHOLAR_ROUTER_",
                "LLM_",
                "GITHUB_TOKEN",
            )
        ):
            del os.environ[key]
    # Clear the provider resolution cache
    from scholar_agent.engine import llm_client

    llm_client._resolved_cache = None
    llm_client._cache_ts = 0.0


# ============================================================================
# 1. resolve_providers — 6 user scenarios
# ============================================================================
class TestResolveProviders(unittest.TestCase):
    """Test provider resolution for different user configurations."""

    def setUp(self):
        _clean_env()

    def test_scenario1_explicit_filler(self):
        """User with SCHOLAR_FILLER_* explicit override."""
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "openai"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://proxy.example.com/v1"
        os.environ["SCHOLAR_FILLER_MODEL"] = "my-model"
        os.environ["SCHOLAR_FILLER_API_KEY"] = "key-explicit"
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "key-anth"
        os.environ["OPENAI_API_KEY"] = "key-oai"

        providers = resolve_providers(force=True)

        # Priority 1: explicit filler
        self.assertEqual(providers[0].format, "openai")
        self.assertEqual(providers[0].url, "https://proxy.example.com/v1")
        self.assertEqual(providers[0].key, "key-explicit")
        self.assertEqual(providers[0].model, "my-model")

        # Priority 2: Anthropic (different URL)
        self.assertEqual(providers[1].format, "anthropic")

        # Priority 3: OpenAI (different URL from filler -> not deduped)
        self.assertEqual(providers[2].format, "openai")
        self.assertIn("api.openai.com", providers[2].url)

    def test_scenario2_pure_anthropic(self):
        """User with only Anthropic official credentials."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-xxx"
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"

        providers = resolve_providers(force=True)

        anthro = [p for p in providers if p.format == "anthropic"]
        self.assertGreaterEqual(len(anthro), 1)
        self.assertIn("api.anthropic.com", anthro[0].url)
        self.assertEqual(anthro[0].model, "claude-sonnet-4-20250514")

    def test_scenario3_pure_openai(self):
        """User with only OpenAI credentials."""
        os.environ["OPENAI_API_KEY"] = "sk-xxx"

        providers = resolve_providers(force=True)

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].format, "openai")
        self.assertIn("api.openai.com", providers[0].url)

    def test_scenario4_zhipu_proxy(self):
        """User with ANTHROPIC_* pointing to Zhipu proxy (not real Anthropic)."""
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "zhipu-token"
        os.environ["ANTHROPIC_BASE_URL"] = "https://open.bigmodel.cn/api/anthropic"

        providers = resolve_providers(force=True)

        anthro = [p for p in providers if p.format == "anthropic"]
        self.assertGreaterEqual(len(anthro), 1)
        self.assertIn("bigmodel.cn", anthro[0].url)

    def test_scenario5_no_credentials(self):
        """User with no LLM credentials at all."""
        providers = resolve_providers(force=True)
        self.assertEqual(len(providers), 0)

    def test_deduplication(self):
        """Same (format, url) should only appear once."""
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "anthropic"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://api.anthropic.com"
        os.environ["SCHOLAR_FILLER_API_KEY"] = "key1"
        os.environ["ANTHROPIC_API_KEY"] = "key2"
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"

        providers = resolve_providers(force=True)

        anthro_providers = [p for p in providers if p.format == "anthropic"]
        urls = [p.url.rstrip("/") for p in anthro_providers]
        self.assertEqual(len([u for u in urls if "api.anthropic.com" in u]), 1)


# ============================================================================
# 2. Response parsing — _parse_anthropic / _parse_openai
# ============================================================================
class TestParseAnthropic(unittest.TestCase):
    def test_normal_response(self):
        data = {"content": [{"type": "text", "text": "Hello from Claude"}], "model": "claude-3"}
        resp = _parse_anthropic(data)
        self.assertEqual(resp.content, "Hello from Claude")
        self.assertEqual(resp.provider_format, "anthropic")

    def test_error_response(self):
        with self.assertRaises(RuntimeError) as ctx:
            _parse_anthropic({"error": {"message": "Invalid API key", "type": "auth_error"}})
        self.assertIn("Invalid API key", str(ctx.exception))

    def test_thinking_blocks_skipped(self):
        data = {
            "content": [
                {"type": "thinking", "thinking": "internal thought"},
                {"type": "text", "text": "The actual answer"},
            ]
        }
        resp = _parse_anthropic(data)
        self.assertEqual(resp.content, "The actual answer")

    def test_proxy_nonstandard_response(self):
        """Proxy returns non-standard format with no content key."""
        with self.assertRaises(KeyError) as ctx:
            _parse_anthropic({"code": 500, "msg": "404 NOT_FOUND", "success": False})
        self.assertIn("content", str(ctx.exception))

    def test_usage_parsing(self):
        data = {
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        resp = _parse_anthropic(data)
        self.assertEqual(resp.usage["prompt_tokens"], 100)
        self.assertEqual(resp.usage["completion_tokens"], 50)
        self.assertEqual(resp.usage["total_tokens"], 150)


class TestParseOpenai(unittest.TestCase):
    def test_normal_response(self):
        data = {"choices": [{"message": {"content": "Hello from GPT"}}], "model": "gpt-4o-mini"}
        resp = _parse_openai(data)
        self.assertEqual(resp.content, "Hello from GPT")
        self.assertEqual(resp.provider_format, "openai")

    def test_error_response(self):
        with self.assertRaises(RuntimeError) as ctx:
            _parse_openai({"error": {"message": "Rate limit exceeded", "type": "rate_limit"}})
        self.assertIn("Rate limit", str(ctx.exception))

    def test_empty_choices(self):
        resp = _parse_openai({"choices": []})
        self.assertEqual(resp.content, "")

    def test_missing_choices(self):
        resp = _parse_openai({"status": "error", "detail": "something went wrong"})
        self.assertEqual(resp.content, "")

    def test_usage_parsing(self):
        data = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        resp = _parse_openai(data)
        self.assertEqual(resp.usage["total_tokens"], 30)


# ============================================================================
# 3. URL construction — no double-append
# ============================================================================
class TestUrlConstruction(unittest.TestCase):
    def _mock_response(self, data):
        mock = MagicMock()
        mock.read.return_value = json.dumps(data).encode()
        mock.__enter__ = lambda s: s
        mock.__exit__ = lambda s, *a: None
        return mock

    def test_anthropic_url_no_double_messages(self):
        provider = ProviderConfig(format="anthropic", url="https://api.anthropic.com/v1/messages", key="k", model="m")
        with patch(
            "scholar_agent.engine.llm_client.urlopen",
            return_value=self._mock_response({"content": [{"type": "text", "text": "ok"}]}),
        ) as mock_open:
            _send_anthropic(provider, [{"role": "user", "content": "hi"}])
            req = mock_open.call_args[0][0]
            self.assertNotIn("/messages/messages", req.full_url)
            self.assertTrue(req.full_url.endswith("/messages"))

    def test_openai_url_no_double_chat_completions(self):
        provider = ProviderConfig(
            format="openai", url="https://api.example.com/v1/chat/completions", key="k", model="m"
        )
        with patch(
            "scholar_agent.engine.llm_client.urlopen",
            return_value=self._mock_response({"choices": [{"message": {"content": "ok"}}]}),
        ) as mock_open:
            _send_openai(provider, [{"role": "user", "content": "hi"}])
            req = mock_open.call_args[0][0]
            self.assertNotIn("/chat/completions/chat/completions", req.full_url)
            self.assertTrue(req.full_url.endswith("/chat/completions"))


# ============================================================================
# 4. fill_note_from_pdf — branching logic
# ============================================================================
class TestFillNoteFromPdf(unittest.TestCase):
    def setUp(self):
        _clean_env()

    def test_no_providers_skips(self):
        """No API keys -> returns skipped."""
        _reload_paper_analyzer()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nstatus: skeleton\n---\n\n## Test\n<!-- LLM: fill this -->\n")
            f.flush()
            tmp_name = f.name

        pa = _reload_paper_analyzer()
        result = pa.fill_note_from_pdf(tmp_name, "some pdf text")

        self.assertEqual(result["status"], "skipped")
        self.assertIn("No API key", result["reason"])
        os.unlink(tmp_name)

    def test_no_placeholders_skips(self):
        """Note with no placeholders -> returns skipped."""
        os.environ["SCHOLAR_FILLER_API_KEY"] = "test-key"
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "openai"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://example.com/v1"
        os.environ["SCHOLAR_FILLER_MODEL"] = "test"

        pa = _reload_paper_analyzer()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nstatus: filled\n---\n\n## Already filled\nContent here.\n")
            f.flush()
            tmp_name = f.name

        result = pa.fill_note_from_pdf(tmp_name, "some pdf text")

        self.assertEqual(result["status"], "skipped")
        self.assertIn("No placeholders", result["reason"])
        os.unlink(tmp_name)

    def test_fallback_on_primary_failure(self):
        """Primary provider fails -> fallback provider succeeds."""
        os.environ["SCHOLAR_FILLER_API_KEY"] = "filler-key"
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "anthropic"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://broken-proxy.com/api"
        os.environ["SCHOLAR_FILLER_MODEL"] = "test-model"
        os.environ["OPENAI_API_KEY"] = "openai-key"

        _reload_paper_analyzer()

        call_count = {"n": 0}

        def mock_urlopen(req, timeout=120):
            call_count["n"] += 1
            if "messages" in req.full_url:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps({"code": 500, "msg": "NOT_FOUND", "success": False}).encode()
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = lambda s, *a: None
                return mock_resp
            else:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(
                    {"choices": [{"message": {"content": "## Filled\nContent."}}]}
                ).encode()
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = lambda s, *a: None
                return mock_resp

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nstatus: skeleton\n---\n\n## Test\n<!-- LLM: fill this -->\n")
            f.flush()
            tmp_name = f.name

        with patch("scholar_agent.engine.llm_client.urlopen", side_effect=mock_urlopen):
            pa = _reload_paper_analyzer()
            result = pa.fill_note_from_pdf(tmp_name, "pdf text")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["api_format"], "openai")
        self.assertGreater(call_count["n"], 1)
        os.unlink(tmp_name)


# ============================================================================
# 4b. fill_note_from_pdf — per-section filling (改动 B)
# ============================================================================
class TestFillPerSection(unittest.TestCase):
    """Per-section filling: each ## section is its own LLM call so no single
    call's output is truncated. Regression for the 8192-token truncation bug."""

    def setUp(self):
        _clean_env()

    def _setup_single_provider(self):
        os.environ["SCHOLAR_FILLER_API_KEY"] = "test-key"
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "openai"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://example.com/v1"
        os.environ["SCHOLAR_FILLER_MODEL"] = "test-model"

    def _mock_openai(self, content="## Section\n\nFilled content."):
        def _urlopen(req, timeout=120):
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(
                {"choices": [{"message": {"content": content}}], "model": "test-model"}
            ).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            return mock_resp

        return _urlopen

    def test_each_section_filled_in_own_call(self):
        """A two-section note triggers >=2 LLM calls and fills all placeholders."""
        self._setup_single_provider()

        note = (
            "---\nstatus: skeleton\n---\n\n# Title\n\n"
            "## Section One\n\n<!-- LLM: fill A -->\n\n"
            "## Section Two\n\n<!-- LLM: fill B -->\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(note)
            tmp_name = f.name

        call_count = {"n": 0}
        _orig = self._mock_openai()

        def _count(req, timeout=120):
            call_count["n"] += 1
            return _orig(req, timeout)

        with patch("scholar_agent.engine.llm_client.urlopen", side_effect=_count):
            pa2 = _reload_paper_analyzer()
            result = pa2.fill_note_from_pdf(tmp_name, "pdf text")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["placeholders_remaining"], 0)
        self.assertEqual(result["placeholders_filled"], 2)
        self.assertGreaterEqual(result["sections_filled"], 2)
        self.assertGreater(call_count["n"], 1)  # one call per section, not a single call
        os.unlink(tmp_name)

    def test_section_failure_does_not_block_others(self):
        """If one section's LLM call fails, other sections still get filled."""
        self._setup_single_provider()

        note = (
            "---\nstatus: skeleton\n---\n\n# Title\n\n"
            "## Section One\n\n<!-- LLM: fill A -->\n\n"
            "## Section Two\n\n<!-- LLM: fill B -->\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(note)
            tmp_name = f.name

        _ok = self._mock_openai()
        state = {"n": 0}

        def _flaky(req, timeout=120):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("boom on first section")
            return _ok(req, timeout)

        with patch("scholar_agent.engine.llm_client.urlopen", side_effect=_flaky):
            pa2 = _reload_paper_analyzer()
            result = pa2.fill_note_from_pdf(tmp_name, "pdf text")

        # At least one section failed but the run completed (did not raise).
        self.assertGreaterEqual(result["sections_failed"], 1)
        self.assertIn(result["status"], ("partial", "ok"))
        os.unlink(tmp_name)

    def test_split_into_sections_keeps_headings(self):
        """Helper splits by ## headings and keeps the preamble."""
        pa = _reload_paper_analyzer()
        content = "---\nfm: 1\n---\n\n# Title\n\n## A\n\nbody-a\n\n## B\n\nbody-b\n"
        chunks = pa._split_into_sections(content)
        # preamble + 2 sections
        self.assertEqual(len(chunks), 3)
        self.assertIn("fm: 1", chunks[0])
        self.assertTrue(chunks[1].startswith("## A"))
        self.assertIn("body-a", chunks[1])
        self.assertTrue(chunks[2].startswith("## B"))


# ============================================================================
# 5. generate_note — path consistency with download_paper
# ============================================================================
class TestGenerateNotePath(unittest.TestCase):
    def test_note_in_title_subfolder(self):
        """generate_note should create {domain}/{title}/{title}.md structure."""
        _clean_env()
        pa = _reload_paper_analyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            paper = {
                "title": "Test Paper Title Here",
                "arxiv_id": "2401.12345",
                "authors": ["Author One"],
                "best_domain": "test-domain",
            }
            note_path = pa.generate_note(paper, tmpdir, language="en")

            self.assertIn("test-domain", note_path)
            parent = Path(note_path).parent.name
            self.assertIn("Test", parent)

            self.assertTrue(Path(note_path).exists())

            flat_path = os.path.join(tmpdir, "test-domain", Path(note_path).name)
            if note_path != flat_path:
                self.assertFalse(os.path.exists(flat_path), f"Note should not exist at flat path: {flat_path}")


# ============================================================================
# 6. Integration — full flow check
# ============================================================================
class TestIntegration(unittest.TestCase):
    def setUp(self):
        _clean_env()

    def test_full_flow_with_mock(self):
        """Simulate full analyze + fill flow with mocked LLM."""
        os.environ["SCHOLAR_FILLER_API_KEY"] = "test-key"
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "openai"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://api.example.com/v1"
        os.environ["SCHOLAR_FILLER_MODEL"] = "test-model"

        pa = _reload_paper_analyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            paper = {
                "title": "Integration Test Paper",
                "arxiv_id": "9999.99999",
                "authors": ["Test Author"],
                "best_domain": "test-domain",
            }
            note_path = pa.generate_note(paper, tmpdir, language="zh")

            content = Path(note_path).read_text(encoding="utf-8")
            self.assertIn("<!-- LLM:", content)
            self.assertIn("status: skeleton", content)

            mock_llm_output = content.replace("status: skeleton", "status: filled")
            mock_llm_output = mock_llm_output.replace("<!-- LLM:", "RESOLVED<!-- ")
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(
                {"choices": [{"message": {"content": mock_llm_output}}], "model": "test-model"}
            ).encode()
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = lambda s, *a: None

            with patch("scholar_agent.engine.llm_client.urlopen", return_value=mock_response):
                result = pa.fill_note_from_pdf(note_path, "fake pdf text for testing")

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["api_format"], "openai")
            self.assertEqual(result["model_used"], "test-model")


# ============================================================================
# 7. Regression tests
# ============================================================================
class TestBugFixes(unittest.TestCase):
    def test_slugification_matches_download_paper(self):
        """title_to_filename must produce the same slug as _sanitize_title."""
        _clean_env()
        pa = _reload_paper_analyzer()

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
                self.assertEqual(pa.title_to_filename(title), _sanitize_title(title), f"Slug mismatch for: {title}")

    def test_openai_empty_choices_returns_empty(self):
        """Empty choices list returns empty content (not crash)."""
        resp = _parse_openai({"choices": []})
        self.assertEqual(resp.content, "")

    def test_anthropic_url_no_double_append(self):
        """URL ending in /messages should not be doubled."""
        provider = ProviderConfig(format="anthropic", url="https://api.anthropic.com/v1/messages", key="k", model="m")
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: None

        with patch("scholar_agent.engine.llm_client.urlopen", return_value=mock_response) as mock_urlopen:
            _send_anthropic(provider, [{"role": "user", "content": "hi"}])
            request_obj = mock_urlopen.call_args[0][0]
            self.assertNotIn("/messages/messages", request_obj.full_url)
            self.assertTrue(request_obj.full_url.endswith("/messages"))


# ============================================================================
# 8. fill_note_from_pdf — continuation loop (A1b) + orphan marker cleanup (A2b)
# ============================================================================
class TestFillContinuation(unittest.TestCase):
    """A1b: re-fill sections that still have placeholders after round 1;
    stop on completion or no-progress."""

    def setUp(self):
        _clean_env()

    def _setup_single_provider(self):
        os.environ["SCHOLAR_FILLER_API_KEY"] = "test-key"
        os.environ["SCHOLAR_FILLER_API_FORMAT"] = "openai"
        os.environ["SCHOLAR_FILLER_API_URL"] = "https://example.com/v1"
        os.environ["SCHOLAR_FILLER_MODEL"] = "test-model"

    def test_continuation_fills_leftover_placeholder(self):
        """Round 1 leaves the placeholder; round 2 fills it -> status ok."""
        self._setup_single_provider()
        note = "---\nstatus: skeleton\n---\n\n# T\n\n## S\n\n<!-- LLM: fill -->\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(note)
            tmp = f.name

        state = {"n": 0}

        def _urlopen(req, timeout=120):
            state["n"] += 1
            mock = MagicMock()
            content = "## S\n\n<!-- LLM: fill -->\n" if state["n"] == 1 else "## S\n\nFilled now.\n"
            mock.read.return_value = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            mock.__enter__ = lambda s: s
            mock.__exit__ = lambda s, *a: None
            return mock

        with patch("scholar_agent.engine.llm_client.urlopen", side_effect=_urlopen):
            pa = _reload_paper_analyzer()
            result = pa.fill_note_from_pdf(tmp, "pdf text")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["placeholders_remaining"], 0)
        self.assertGreaterEqual(result["rounds_used"], 2)
        os.unlink(tmp)

    def test_no_progress_stops_loop(self):
        """A round that makes no progress stops the loop (capped, no spin)."""
        self._setup_single_provider()
        note = "---\nstatus: skeleton\n---\n\n# T\n\n## S\n\n<!-- LLM: fill -->\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(note)
            tmp = f.name

        def _urlopen(req, timeout=120):
            mock = MagicMock()
            # Always echo the placeholder back — never fills.
            mock.read.return_value = json.dumps(
                {"choices": [{"message": {"content": "## S\n\n<!-- LLM: fill -->\n"}}]}
            ).encode()
            mock.__enter__ = lambda s: s
            mock.__exit__ = lambda s, *a: None
            return mock

        with patch("scholar_agent.engine.llm_client.urlopen", side_effect=_urlopen):
            pa = _reload_paper_analyzer()
            result = pa.fill_note_from_pdf(tmp, "pdf text")

        self.assertIn(result["status"], ("partial", "error"))
        self.assertLessEqual(result["rounds_used"], 3)  # capped at max_rounds
        os.unlink(tmp)


class TestOrphanedCommentMarkers(unittest.TestCase):
    """A2b: orphaned --> (filled content but kept closing marker) is stripped."""

    def test_orphaned_marker_dropped_placeholder_kept(self):
        from scholar_agent.engine.academic.paper_analyzer import _strip_orphaned_comment_markers

        text = "## S\n\nSome content. -->\n\n## T\n\n<!-- LLM: keep -->\n"
        cleaned = _strip_orphaned_comment_markers(text)
        self.assertNotIn("content. -->", cleaned)  # orphaned --> removed
        self.assertIn("<!-- LLM: keep -->", cleaned)  # balanced placeholder kept

    def test_balanced_comment_preserved(self):
        from scholar_agent.engine.academic.paper_analyzer import _strip_orphaned_comment_markers

        text = "<!-- ordinary comment --> and text"
        self.assertEqual(_strip_orphaned_comment_markers(text), text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
