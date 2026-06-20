"""Tests for fetch_url / _fetch_url_impl (G5 一手抓取 + G2 网页快照)."""

from pathlib import Path
from unittest import mock


def _stub_fetch_content(content_md="", title="", status="succeeded", failure=""):
    return {
        "title": title,
        "content_md": content_md,
        "retrieval_status": status,
        "failure_reason": failure,
        "images": [],
    }


def test_rejects_empty_url():
    from scholar_agent.server import _fetch_url_impl

    out = _fetch_url_impl("")
    assert "error" in out


def test_rejects_non_http_url():
    from scholar_agent.server import _fetch_url_impl

    out = _fetch_url_impl("ftp://example.com/x")
    assert "error" in out


def test_stores_snapshot_with_captured_at(tmp_path, monkeypatch):
    from scholar_agent import server

    monkeypatch.setattr(server, "get_knowledge_dir", lambda: tmp_path)
    with mock.patch(
        "scholar_agent.engine.research_harness.fetch_content",
        return_value=_stub_fetch_content(content_md="# Title\n\n正文一手内容 here", title="Title"),
    ):
        out = server._fetch_url_impl("https://example.com/article")

    assert out["retrieval_status"] == "succeeded"
    assert out["captured_at"]  # YYYY-MM-DD present
    assert out["snapshot_path"]
    assert out["content_chars"] > 0

    snap = Path(out["snapshot_path"])
    assert snap.exists()
    text = snap.read_text(encoding="utf-8")
    assert "https://example.com/article" in text
    assert "正文一手内容 here" in text
    assert out["captured_at"] in text  # captured_at archived in snapshot


def test_no_snapshot_when_fetch_empty(tmp_path, monkeypatch):
    from scholar_agent import server

    monkeypatch.setattr(server, "get_knowledge_dir", lambda: tmp_path)
    with mock.patch(
        "scholar_agent.engine.research_harness.fetch_content",
        return_value=_stub_fetch_content(content_md="", status="failed", failure="boom"),
    ):
        out = server._fetch_url_impl("https://example.com/x")

    assert out["snapshot_path"] == ""
    assert out["captured_at"] == ""
    assert out["retrieval_status"] == "failed"
    assert out["failure_reason"] == "boom"


def test_snapshot_filename_is_stable_sha1_of_url(tmp_path, monkeypatch):
    """Same URL → same snapshot filename (so re-fetch refreshes, doesn't duplicate)."""
    import hashlib

    from scholar_agent import server

    monkeypatch.setattr(server, "get_knowledge_dir", lambda: tmp_path)
    stub = _stub_fetch_content(content_md="body", title="t")
    with mock.patch("scholar_agent.engine.research_harness.fetch_content", return_value=stub):
        out = server._fetch_url_impl("https://example.com/stable")

    expected_digest = hashlib.sha1(b"https://example.com/stable").hexdigest()[:16]
    assert out["snapshot_path"].endswith(f"{expected_digest}.md")


def test_snapshot_sources_archives_each_http_url(tmp_path, monkeypatch):
    """save_research auto-snapshot helper (G2): fetch + archive each http(s) source."""
    import hashlib

    from scholar_agent import server

    monkeypatch.setattr(server, "get_knowledge_dir", lambda: tmp_path)
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return _stub_fetch_content(content_md=f"body of {url}", title="t")

    with mock.patch("scholar_agent.engine.research_harness.fetch_content", side_effect=fake_fetch):
        server._snapshot_sources(["https://a.com/x", "https://b.com/y", "ftp://skip", "", "not-a-url"])

    # only http(s) urls are fetched
    assert "https://a.com/x" in fetched and "https://b.com/y" in fetched
    assert "ftp://skip" not in fetched
    # each archived under sha1(url)[:16].md with its content
    for u in ["https://a.com/x", "https://b.com/y"]:
        digest = hashlib.sha1(u.encode("utf-8")).hexdigest()[:16]
        snap = tmp_path / "_snapshots" / f"{digest}.md"
        assert snap.exists(), f"missing snapshot for {u}"
        assert f"body of {u}" in snap.read_text(encoding="utf-8")
