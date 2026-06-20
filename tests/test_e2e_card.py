"""E2E 集成: fetch_url + save_research 协同产达标卡 (G5/G4/F3)."""

import json
from unittest import mock


def _stub_fetch(content_md="body", title="t"):
    return {
        "title": title,
        "content_md": content_md,
        "retrieval_status": "succeeded",
        "failure_reason": "",
        "images": [],
    }


def test_save_research_grounded_card_has_freshness_and_source_links(tmp_path, monkeypatch):
    """save_research with sources + evidence_ids=url → card carries G4 freshness
    fields and F3 source links (evidence_ids resolved to [host](url))."""
    from scholar_agent import server

    monkeypatch.setattr(server, "get_knowledge_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "get_index_path", lambda: tmp_path / "index.json")

    url = "https://example.com/agent-article"
    with mock.patch(
        "scholar_agent.engine.research_harness.fetch_content",
        return_value=_stub_fetch("# Title\n\n一手正文", "Title"),
    ):
        answer = {
            "answer": "基于一手抓取正文的深度回答，包含具体机制与数字，确保超过200字符的实质性内容阈值。" * 6,
            "supporting_claims": [
                {
                    "claim": "引用一手来源具体内容的论断，长度超过二十个字符",
                    "evidence_ids": [url],
                    "confidence": "high",
                }
            ],
            "sources": [url],
            "inferences": ["由证据推出的推论"],
        }
        out = json.loads(
            server.save_research(
                "e2e grounded card",
                json.dumps(answer, ensure_ascii=False),
                domain="e2e",
            )
        )

    assert out["status"] == "ok", out
    cards = [c for c in tmp_path.rglob("*.md") if "_snapshots" not in str(c)]
    assert cards, "card not written"
    text = cards[0].read_text(encoding="utf-8")

    # G4: 时效字段
    assert "source_years" in text
    assert "info_freshness" in text
    assert "version" in text
    # F3: evidence_ids=url → rendered as source link
    assert url in text
    assert "example.com" in text
