"""SQLite-backed paper store for the precision daily recommendation system.

Provides persistent storage, dedup, and funnel progress tracking via SQLite.
Uses WAL mode for safe concurrent access from the MCP server process.

Tables: schema_version, papers, funnel_runs, fetch_checkpoints.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT
);

CREATE TABLE IF NOT EXISTS funnel_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT NOT NULL,
    config_snapshot TEXT,
    stage1_input    INTEGER DEFAULT 0,
    stage2_output   INTEGER DEFAULT 0,
    stage3_output   INTEGER DEFAULT 0,
    stage4_output   INTEGER DEFAULT 0,
    recommended     INTEGER DEFAULT 0,
    llm_calls       INTEGER DEFAULT 0,
    llm_tokens      INTEGER DEFAULT 0,
    duration_seconds REAL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running',
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS papers (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id                    TEXT UNIQUE,
    s2_id                       TEXT,
    doi                         TEXT,
    title                       TEXT NOT NULL,
    abstract                    TEXT,
    authors                     TEXT,
    affiliations                TEXT,
    categories                  TEXT,
    published_date              TEXT,
    venue                       TEXT,
    source                      TEXT NOT NULL DEFAULT 'arxiv',
    citation_count              INTEGER DEFAULT 0,
    influential_citation_count  INTEGER DEFAULT 0,
    pdf_url                     TEXT,
    url                         TEXT,

    status          TEXT NOT NULL DEFAULT 'fetched',
    is_historical   INTEGER NOT NULL DEFAULT 0,
    funnel_run_id   INTEGER REFERENCES funnel_runs(id),

    relevance_score REAL DEFAULT 0,
    best_domain     TEXT,
    domain_keywords TEXT,

    skip_reason        TEXT,

    llm_review_passed   INTEGER DEFAULT 0,
    llm_review_detail   TEXT,
    llm_novelty         REAL,
    llm_credibility     REAL,
    llm_depth           REAL,
    llm_rigor           REAL,
    llm_model           TEXT,

    recommendation_score  REAL DEFAULT 0,
    recommendation_reason TEXT,
    recommended_at        TEXT,

    fetched_at   TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_status_relevance ON papers(status, relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published_date);
CREATE INDEX IF NOT EXISTS idx_papers_recommended ON papers(recommended_at)
    WHERE recommended_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS fetch_checkpoints (
    source            TEXT NOT NULL,
    category          TEXT NOT NULL DEFAULT '',
    last_fetched_date TEXT NOT NULL,
    papers_fetched    INTEGER DEFAULT 0,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, category)
);
"""


def _normalize_paper(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize heterogeneous paper dicts into a canonical shape for storage."""
    p: dict[str, Any] = {}

    p["arxiv_id"] = raw.get("arxiv_id") or raw.get("arxivId") or None
    p["s2_id"] = raw.get("s2_id") or raw.get("paperId") or None
    p["doi"] = raw.get("doi") or None
    p["title"] = (raw.get("title") or "").strip()
    p["abstract"] = raw.get("abstract") or raw.get("summary") or None
    p["venue"] = raw.get("venue") or raw.get("journal") or None
    p["source"] = raw.get("source", "arxiv")
    p["pdf_url"] = raw.get("pdf_url") or raw.get("pdfUrl") or None
    p["url"] = raw.get("url") or None

    # Citation counts
    p["citation_count"] = raw.get("citation_count") or raw.get("citationCount") or 0
    p["influential_citation_count"] = raw.get("influential_citation_count") or raw.get("influentialCitationCount") or 0

    # Published date
    pd = raw.get("published_date") or raw.get("publicationDate") or raw.get("published") or None
    if isinstance(pd, datetime):
        pd = pd.isoformat()
    p["published_date"] = pd

    # JSON-array fields
    authors = raw.get("authors", [])
    if isinstance(authors, list):
        authors = [a if isinstance(a, str) else a.get("name", "") for a in authors if a]
    p["authors"] = json.dumps(authors, ensure_ascii=False) if authors else None

    affiliations = raw.get("affiliations", [])
    if isinstance(affiliations, list):
        affiliations = [a if isinstance(a, str) else a.get("name", "") for a in affiliations if a]
    p["affiliations"] = json.dumps(affiliations, ensure_ascii=False) if affiliations else None

    categories = raw.get("categories", [])
    if isinstance(categories, list):
        categories = [str(c) for c in categories]
    p["categories"] = json.dumps(categories, ensure_ascii=False) if categories else None

    return p


class PaperStore:
    """SQLite-backed paper store with WAL mode for concurrent MCP access."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PaperStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Yield a cursor with commit/rollback semantics.

        Thread-safe: serializes concurrent database operations via an
        internal lock so that only one thread can execute a transaction
        at a time.
        """
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # -- Schema management ---------------------------------------------------

    def initialize(self) -> None:
        """Create tables and register schema version."""
        with self._cursor() as cur:
            cur.executescript(_CREATE_TABLES)
            cur.execute(
                "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
                (_SCHEMA_VERSION, "initial"),
            )

    # -- Upsert --------------------------------------------------------------

    def upsert_paper(self, raw: dict[str, Any]) -> int:
        """Normalize and insert/update a paper. Returns row id."""
        p = _normalize_paper(raw)
        is_historical = 1 if raw.get("is_historical") else 0
        fetched_at = raw.get("fetched_at") or datetime.now(timezone.utc).isoformat()

        with self._cursor() as cur:
            # If no arxiv_id, look up by title as fallback dedup
            existing_id: int | None = None
            if not p["arxiv_id"]:
                cur.execute("SELECT id FROM papers WHERE title = ?", (p["title"],))
                row = cur.fetchone()
                if row:
                    existing_id = row["id"]

            if existing_id is not None:
                cur.execute(
                    """UPDATE papers SET
                        arxiv_id = COALESCE(?, arxiv_id),
                        s2_id = COALESCE(?, s2_id),
                        doi = COALESCE(?, doi),
                        abstract = COALESCE(?, abstract),
                        authors = COALESCE(?, authors),
                        affiliations = COALESCE(?, affiliations),
                        categories = COALESCE(?, categories),
                        published_date = COALESCE(?, published_date),
                        venue = COALESCE(?, venue),
                        citation_count = MAX(?, citation_count),
                        influential_citation_count = MAX(?, influential_citation_count),
                        pdf_url = COALESCE(?, pdf_url),
                        url = COALESCE(?, url)
                    WHERE id = ?""",
                    (
                        p["arxiv_id"],
                        p["s2_id"],
                        p["doi"],
                        p["abstract"],
                        p["authors"],
                        p["affiliations"],
                        p["categories"],
                        p["published_date"],
                        p["venue"],
                        p["citation_count"],
                        p["influential_citation_count"],
                        p["pdf_url"],
                        p["url"],
                        existing_id,
                    ),
                )
                return existing_id

            cur.execute(
                """INSERT INTO papers (
                    arxiv_id, s2_id, doi, title, abstract, authors, affiliations,
                    categories, published_date, venue, source, citation_count,
                    influential_citation_count, pdf_url, url, is_historical, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(arxiv_id) DO UPDATE SET
                    title = COALESCE(excluded.title, papers.title),
                    abstract = COALESCE(excluded.abstract, papers.abstract),
                    authors = COALESCE(excluded.authors, papers.authors),
                    affiliations = COALESCE(excluded.affiliations, papers.affiliations),
                    categories = COALESCE(excluded.categories, papers.categories),
                    published_date = COALESCE(excluded.published_date, papers.published_date),
                    venue = COALESCE(excluded.venue, papers.venue),
                    citation_count = MAX(excluded.citation_count, papers.citation_count),
                    influential_citation_count = MAX(excluded.influential_citation_count, papers.influential_citation_count),
                    pdf_url = COALESCE(excluded.pdf_url, papers.pdf_url),
                    url = COALESCE(excluded.url, papers.url)
                """,
                (
                    p["arxiv_id"],
                    p["s2_id"],
                    p["doi"],
                    p["title"],
                    p["abstract"],
                    p["authors"],
                    p["affiliations"],
                    p["categories"],
                    p["published_date"],
                    p["venue"],
                    p["source"],
                    p["citation_count"],
                    p["influential_citation_count"],
                    p["pdf_url"],
                    p["url"],
                    is_historical,
                    fetched_at,
                ),
            )
            row_id = cur.lastrowid
            if row_id is None:
                raise RuntimeError("INSERT did not produce a rowid")
            return row_id

    def upsert_papers(self, papers: list[dict[str, Any]]) -> int:
        """Batch upsert in a single transaction. Returns count of papers processed (inserts + updates)."""
        count = 0
        for raw in papers:
            self.upsert_paper(raw)
            count += 1
        return count

    # -- Query ---------------------------------------------------------------

    def paper_exists(self, arxiv_id: str | None = None, title: str | None = None) -> bool:
        """Check if a paper exists by arxiv_id or title."""
        with self._cursor() as cur:
            if arxiv_id:
                cur.execute("SELECT 1 FROM papers WHERE arxiv_id = ?", (arxiv_id,))
                if cur.fetchone():
                    return True
            if title:
                cur.execute("SELECT 1 FROM papers WHERE title = ?", (title.strip(),))
                if cur.fetchone():
                    return True
        return False

    def get_papers_by_status(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get papers filtered by status."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM papers WHERE status = ? ORDER BY fetched_at DESC LIMIT ?",
                (status, limit),
            )
            rows = [dict(row) for row in cur.fetchall()]
            for r in rows:
                r["_db_id"] = r["id"]
            return rows

    def update_status(self, paper_id: int, status: str, **fields: Any) -> None:
        """Update a paper's status and optional fields."""
        sets: list[str] = ["status = ?"]
        vals: list[Any] = [status]
        for k, v in fields.items():
            if k in (
                "relevance_score",
                "best_domain",
                "domain_keywords",
                "skip_reason",
                "llm_review_passed",
                "llm_review_detail",
                "llm_novelty",
                "llm_credibility",
                "llm_depth",
                "llm_rigor",
                "llm_model",
                "recommendation_score",
                "recommendation_reason",
                "recommended_at",
                "processed_at",
                "funnel_run_id",
            ):
                sets.append(f"{k} = ?")
                vals.append(v)
        if status == "recommended" and "recommended_at" not in fields:
            sets.append("recommended_at = ?")
            vals.append(datetime.now(timezone.utc).isoformat())
        if status in ("recommended", "skipped") and "processed_at" not in fields:
            sets.append("processed_at = ?")
            vals.append(datetime.now(timezone.utc).isoformat())

        vals.append(paper_id)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE papers SET {', '.join(sets)} WHERE id = ?",
                vals,
            )

    # -- Checkpoints ---------------------------------------------------------

    def get_checkpoint(self, source: str, category: str = "") -> str | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT last_fetched_date FROM fetch_checkpoints WHERE source = ? AND category = ?",
                (source, category),
            )
            row = cur.fetchone()
            return row["last_fetched_date"] if row else None

    def set_checkpoint(self, source: str, category: str, date: str, papers_fetched: int = 0) -> None:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO fetch_checkpoints (source, category, last_fetched_date, papers_fetched, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(source, category) DO UPDATE SET
                    last_fetched_date = excluded.last_fetched_date,
                    papers_fetched = excluded.papers_fetched,
                    updated_at = datetime('now')
                """,
                (source, category, date, papers_fetched),
            )

    # -- Funnel runs ---------------------------------------------------------

    def start_funnel_run(self, date: str, config_snapshot: dict[str, Any] | None = None) -> int:
        snap_json = json.dumps(config_snapshot, ensure_ascii=False) if config_snapshot else None
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO funnel_runs (run_date, config_snapshot) VALUES (?, ?)",
                (date, snap_json),
            )
            row_id = cur.lastrowid
            if row_id is None:
                raise RuntimeError("INSERT did not produce a rowid")
            return row_id

    def update_funnel_run(self, run_id: int, **fields: Any) -> None:
        sets: list[str] = []
        vals: list[Any] = []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        if not sets:
            return
        vals.append(run_id)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE funnel_runs SET {', '.join(sets)} WHERE id = ?",
                vals,
            )

    # -- Stats ---------------------------------------------------------------

    def count_by_status(self) -> dict[str, int]:
        with self._cursor() as cur:
            cur.execute("SELECT status, COUNT(*) as cnt FROM papers GROUP BY status")
            return {row["status"]: row["cnt"] for row in cur.fetchall()}
