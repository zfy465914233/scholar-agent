"""Build a minimal hybrid evidence pack from local retrieval and optional web evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from local_retrieve import retrieve


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a hybrid evidence pack from local and web sources.")
    parser.add_argument("query", help="User query")
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("indexes/local/index.json"),
        help="Path to the local retrieval index.",
    )
    parser.add_argument(
        "--web-evidence",
        type=Path,
        help="Optional path to a web evidence JSON bundle produced by the research harness.",
    )
    parser.add_argument("--local-limit", type=int, default=5, help="Maximum number of local results to include.")
    return parser.parse_args()


def normalize_local_items(query: str, local_payload: dict[str, object]) -> list[dict[str, object]]:
    items = []
    for result in local_payload.get("results", []):
        items.append(
            {
                "origin": "local",
                "query": query,
                "evidence_id": result["doc_id"],
                "source_type": result["type"],
                "title": result["title"],
                "path": result["path"],
                "url": None,
                "score": result["score"],
                "matched_terms": result["matched_terms"],
                "summary": None,
            }
        )
    return items


def normalize_web_items(web_payload: dict[str, object]) -> list[dict[str, object]]:
    items = []
    for result in web_payload.get("evidence", []):
        url = result.get("url") or ""
        digest = hashlib.md5(str(url).encode("utf-8")).hexdigest()[:8]
        items.append(
            {
                "origin": "web",
                "query": result.get("query") or web_payload.get("query"),
                "evidence_id": f"web-{digest}",
                "source_type": result.get("source_type", "other"),
                "title": result.get("title", ""),
                "path": None,
                "url": url,
                "score": None,
                "matched_terms": [],
                "summary": result.get("summary"),
            }
        )
    return items


def build_evidence_pack(query: str, index_path: Path, web_evidence_path: Path | None, local_limit: int) -> dict[str, object]:
    local_payload = retrieve(query, index_path, local_limit)
    items = normalize_local_items(query, local_payload)

    if web_evidence_path is not None:
        web_payload = json.loads(web_evidence_path.read_text(encoding="utf-8"))
        items.extend(normalize_web_items(web_payload))

    return {
        "query": query,
        "local_count": sum(1 for item in items if item["origin"] == "local"),
        "web_count": sum(1 for item in items if item["origin"] == "web"),
        "items": items,
    }


def main() -> int:
    args = parse_args()
    payload = build_evidence_pack(args.query, args.index, args.web_evidence, args.local_limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
