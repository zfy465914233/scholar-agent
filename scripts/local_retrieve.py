"""Run minimal lexical retrieval over the local knowledge index."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TOKEN_RE = re.compile(r"[a-z0-9_-]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retrieve local knowledge documents from the JSON index.")
    parser.add_argument("query", help="Query text for lexical retrieval")
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("indexes/local/index.json"),
        help="Path to the local JSON index file.",
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of results to return.")
    return parser.parse_args()


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def score_document(query_terms: list[str], document: dict[str, object]) -> tuple[int, list[str]]:
    title_terms = set(tokenize(str(document.get("title", ""))))
    topic_terms = set(tokenize(str(document.get("topic", ""))))
    tag_terms = set(tokenize(" ".join(str(tag) for tag in document.get("tags", []))))
    body_terms = set(tokenize(str(document.get("search_text", ""))))

    matched_terms: list[str] = []
    score = 0
    for term in query_terms:
        if term in title_terms:
            score += 4
            matched_terms.append(term)
        elif term in tag_terms:
            score += 3
            matched_terms.append(term)
        elif term in topic_terms:
            score += 2
            matched_terms.append(term)
        elif term in body_terms:
            score += 1
            matched_terms.append(term)

    doc_type = str(document.get("type", ""))
    if doc_type == "definition" and any(term in {"what", "define", "definition"} for term in query_terms):
        score += 5

    deduped_terms = []
    seen = set()
    for term in matched_terms:
        if term not in seen:
            deduped_terms.append(term)
            seen.add(term)
    return score, deduped_terms


def retrieve(query: str, index_path: Path, limit: int) -> dict[str, object]:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    query_terms = tokenize(query)
    results = []

    for document in payload.get("documents", []):
        score, matched_terms = score_document(query_terms, document)
        if score <= 0:
            continue
        results.append(
            {
                "doc_id": document["doc_id"],
                "path": document["path"],
                "title": document["title"],
                "type": document["type"],
                "topic": document["topic"],
                "score": score,
                "matched_terms": matched_terms,
            }
        )

    results.sort(key=lambda item: (-item["score"], item["doc_id"]))
    return {"query": query, "results": results[:limit]}


def main() -> int:
    args = parse_args()
    payload = retrieve(args.query, args.index, args.limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
