"""PDF and arXiv source figure extraction for academic papers.

Two-stage pipeline:
  1. Selectively extract image files from the arXiv source tarball
     (only image extensions, skip .tex/.bib etc).
  2. If too few figures were found, fall back to extracting embedded
     images from the PDF via PyMuPDF — with global area-based ranking.

Also provides ``download_arxiv_pdf`` for caching PDFs locally and
``extract_pdf_text`` for plain-text extraction (BM25 indexing).
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from urllib import request as _url_lib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency guards
# ---------------------------------------------------------------------------

try:
    import fitz  # PyMuPDF
    _FITZ_OK = True
except ImportError:
    _FITZ_OK = False

try:
    import requests as _http
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# Expose module-level flags expected by callers / tests
HAS_FITZ = _FITZ_OK
HAS_REQUESTS = _REQUESTS_OK

# ---------------------------------------------------------------------------
# Image conventions
# ---------------------------------------------------------------------------

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}
_RASTER_EXTS = {".png", ".jpg", ".jpeg"}
_NOISE_NAMES = {"logo", "icon", "badge", "banner", "watermark"}


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _fetch_bytes(url: str, *, timeout: int = 60, ua: str = "scholar-agent/1.0 (research)"):
    """Return (status, bytes) using requests or urllib fallback."""
    headers = {"User-Agent": ua}
    if _REQUESTS_OK:
        r = _http.get(url, timeout=timeout, headers=headers)
        return r.status_code, r.content
    req = _url_lib.Request(url, headers=headers)
    resp = _url_lib.urlopen(req, timeout=timeout)
    return getattr(resp, "status", 200), resp.read()


# ---------------------------------------------------------------------------
# Selective source tarball extraction (only image files)
# ---------------------------------------------------------------------------

def _pull_source_tarball(paper_id: str, dest: str) -> bool:
    """Download arXiv e-print and selectively extract only image files."""
    url = f"https://arxiv.org/e-print/{paper_id}"
    logger.info("Fetching source tarball: %s", url)
    try:
        status, blob = _fetch_bytes(url, timeout=60)
        if status != 200 or not blob:
            return False
        tar_path = os.path.join(dest, f"{paper_id}.tar")
        with open(tar_path, "wb") as fh:
            fh.write(blob)

        # Selective extraction: only image files, skip everything else
        with tarfile.open(tar_path, "r:*") as tf:
            image_members = [
                m for m in tf.getmembers()
                if not m.name.startswith("/")
                and ".." not in m.name
                and not m.issym()
                and not m.islnk()
                and os.path.splitext(m.name)[1].lower() in _IMAGE_EXTS
            ]
            if image_members:
                tf.extractall(path=dest, members=image_members)
            else:
                # Fallback: try full extraction if no image members found
                safe = [
                    m for m in tf.getmembers()
                    if not m.name.startswith("/")
                    and ".." not in m.name
                    and not m.issym()
                    and not m.islnk()
                ]
                tf.extractall(path=dest, members=safe)
        return True
    except Exception as exc:
        logger.error("Source tarball failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# PDF download
# ---------------------------------------------------------------------------

def download_arxiv_pdf(arxiv_id: str, output_dir: str) -> str:
    """Download arXiv PDF to *output_dir*/*arxiv_id*.pdf (with caching)."""
    os.makedirs(output_dir, exist_ok=True)
    target = os.path.join(output_dir, f"{arxiv_id}.pdf")

    if os.path.exists(target) and os.path.getsize(target) > 0:
        logger.info("PDF cache hit: %s", target)
        return os.path.abspath(target)

    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    logger.info("Downloading PDF: %s", url)
    try:
        status, blob = _fetch_bytes(url, timeout=120)
        if status != 200:
            raise RuntimeError(f"arXiv returned HTTP {status}")
        with open(target, "wb") as fh:
            fh.write(blob)
        return os.path.abspath(target)
    except Exception as exc:
        if os.path.exists(target):
            os.remove(target)
        raise RuntimeError(f"PDF download failed for {arxiv_id}: {exc}") from exc


# ---------------------------------------------------------------------------
# Text extraction (for BM25 indexing)
# ---------------------------------------------------------------------------

def extract_pdf_text(pdf_path: str, max_chars: int = 80000) -> str:
    """Extract plain text from a PDF via PyMuPDF.

    LLMs read PDFs directly for analysis; this function exists for
    programmatic indexing (BM25).
    """
    if not _FITZ_OK:
        logger.warning("PyMuPDF unavailable — cannot extract text")
        return ""
    try:
        doc = fitz.open(pdf_path)
        chunks = [page.get_text() for page in doc]
        doc.close()
        full = "\n\n".join(chunks)
        return full[:max_chars]
    except Exception as exc:
        logger.error("Text extraction error: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Glob-based source image discovery
# ---------------------------------------------------------------------------

def _discover_source_images(scratch_dir: str) -> list[dict[str, Any]]:
    """Use pathlib glob to find images, dynamically choosing the best directory.

    Instead of iterating a fixed list of directory names, this scans all
    subdirectories and picks the one with the most image files.
    """
    root = Path(scratch_dir)
    # Collect all image files across all subdirectories
    all_images: list[Path] = []
    for ext in _RASTER_EXTS:
        all_images.extend(root.rglob(f"*{ext}"))

    if not all_images:
        # Also check source extensions for non-raster image formats
        for ext in (".pdf", ".eps", ".svg"):
            all_images.extend(root.rglob(f"*{ext}"))

    if not all_images:
        return []

    # Filter out noise files
    filtered = [
        p for p in all_images
        if not any(n in p.name.lower() for n in _NOISE_NAMES)
    ]
    if not filtered:
        filtered = all_images

    # Group by parent directory, pick the richest directory
    dir_counts: dict[Path, list[Path]] = {}
    for p in filtered:
        parent = p.parent
        dir_counts.setdefault(parent, []).append(p)

    # Use the directory with the most images as the primary source
    best_dir = max(dir_counts, key=lambda d: len(dir_counts[d]))

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for img_path in dir_counts[best_dir]:
        fn = img_path.name
        if fn in seen:
            continue
        seen.add(fn)
        found.append({
            "kind": "source_archive",
            "origin": "arxiv-tarball",
            "path": str(img_path),
            "filename": fn,
        })

    return found


# ---------------------------------------------------------------------------
# PDF image extraction with global area ranking
# ---------------------------------------------------------------------------

def _pull_embedded_images(
    pdf_path: str,
    output_dir: str,
    max_images: int = 20,
    min_bytes: int = 4000,
) -> list[dict[str, Any]]:
    """Extract PDF images via global metadata sweep + area ranking.

    Instead of processing page-by-page and keeping everything above threshold,
    this collects ALL image metadata first, ranks by area, takes the top-N,
    then saves only those.
    """
    if not _FITZ_OK:
        return []

    # Phase 1: collect all image metadata across all pages
    candidates: list[dict[str, Any]] = []
    try:
        doc = fitz.open(pdf_path)
        for pg_idx in range(len(doc)):
            page = doc[pg_idx]
            for img_seq, info in enumerate(page.get_images(full=True)):
                xref = info[0]
                try:
                    payload = doc.extract_image(xref)
                except Exception:
                    continue
                if not payload:
                    continue
                w = payload.get("width", 0)
                h = payload.get("height", 0)
                blob = payload["image"]
                area = w * h
                candidates.append({
                    "page": pg_idx + 1,
                    "seq": img_seq + 1,
                    "width": w,
                    "height": h,
                    "area": area,
                    "blob": blob,
                    "ext": payload["ext"],
                    "size": len(blob),
                })
        doc.close()
    except Exception as exc:
        logger.error("PDF image extraction error: %s", exc)
        return []

    # Phase 2: global ranking by area, filter by minimum size
    candidates.sort(key=lambda c: c["area"], reverse=True)
    top = [
        c for c in candidates
        if c["size"] >= min_bytes
    ][:max_images]

    # Phase 3: save only the selected images
    result: list[dict[str, Any]] = []
    for c in top:
        fname = f"p{c['page']}_img{c['seq']}.{c['ext']}"
        dest = os.path.join(output_dir, fname)
        with open(dest, "wb") as fh:
            fh.write(c["blob"])
        result.append({
            "filename": fname,
            "rel_path": f"images/{fname}",
            "byte_size": c["size"],
            "width": c["width"],
            "height": c["height"],
            "format": c["ext"],
            "origin": "pdf-extraction",
        })

    return result


# ---------------------------------------------------------------------------
# Top-level API
# ---------------------------------------------------------------------------

def extract_paper_images(
    paper_id: str,
    output_dir: str,
    pdf_path: str | None = None,
) -> list[dict[str, Any]]:
    """Harvest images from arXiv source + PDF fallback."""
    os.makedirs(output_dir, exist_ok=True)
    collected: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as scratch:
        # Stage 1: selective source extraction + glob discovery
        if paper_id and _pull_source_tarball(paper_id, scratch):
            for entry in _discover_source_images(scratch):
                dest = os.path.join(output_dir, entry["filename"])
                shutil.copy2(entry["path"], dest)
                collected.append({
                    "filename": entry["filename"],
                    "rel_path": f"images/{entry['filename']}",
                    "byte_size": os.path.getsize(dest),
                    "format": os.path.splitext(entry["filename"])[1][1:].lower(),
                    "origin": entry.get("origin", "arxiv-tarball"),
                })

        # Stage 2: PDF fallback when source yields too few
        if len(collected) < 2 and pdf_path and _FITZ_OK:
            collected.extend(_pull_embedded_images(pdf_path, output_dir))

    return collected
