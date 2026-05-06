"""PDF and arXiv source figure extraction for academic papers.

Two-stage pipeline:
  1. Download the arXiv source tarball and harvest images from known
     figure directories (figures/, pics/, fig/, images/, img/).
  2. If too few figures were found, fall back to extracting embedded
     images from the PDF via PyMuPDF.

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
# Directory / extension conventions
# ---------------------------------------------------------------------------

_FIGURE_SUBDIRS = ("pics", "figures", "fig", "images", "img")
_SOURCE_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}
_RASTER_EXTS = {".png", ".jpg", ".jpeg"}
_NOISE_NAMES = {"logo", "icon"}


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
# arXiv source download + extraction
# ---------------------------------------------------------------------------

def _pull_source_tarball(paper_id: str, dest: str) -> bool:
    """Download the arXiv e-print tarball and extract into *dest*."""
    url = f"https://arxiv.org/e-print/{paper_id}"
    logger.info("Fetching source tarball: %s", url)
    try:
        status, blob = _fetch_bytes(url, timeout=60)
        if status != 200 or not blob:
            return False
        tar_path = os.path.join(dest, f"{paper_id}.tar")
        with open(tar_path, "wb") as fh:
            fh.write(blob)
        with tarfile.open(tar_path, "r:*") as tf:
            safe = [
                m for m in tf.getmembers()
                if not m.name.startswith("/") and ".." not in m.name
                and not m.issym() and not m.islnk()
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
# Source-level figure harvesting
# ---------------------------------------------------------------------------

def _find_source_figures(tmp_dir: str) -> list[dict[str, Any]]:
    """Walk known figure sub-directories inside the extracted source."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    for subdir in _FIGURE_SUBDIRS:
        dpath = os.path.join(tmp_dir, subdir)
        if not os.path.isdir(dpath):
            continue
        for fn in os.listdir(dpath):
            if fn in seen:
                continue
            if os.path.splitext(fn)[1].lower() in _SOURCE_EXTS:
                seen.add(fn)
                found.append({
                    "type": "source",
                    "source": "arxiv-source",
                    "path": os.path.join(dpath, fn),
                    "filename": fn,
                })

    # fallback: raster images in root (skip noise)
    if not found:
        for fn in os.listdir(tmp_dir):
            full = os.path.join(tmp_dir, fn)
            if not os.path.isfile(full):
                continue
            if os.path.splitext(fn)[1].lower() not in _RASTER_EXTS:
                continue
            if any(n in fn.lower() for n in _NOISE_NAMES):
                continue
            found.append({
                "type": "source",
                "source": "arxiv-source",
                "path": full,
                "filename": fn,
            })

    return found


# ---------------------------------------------------------------------------
# PDF-embedded image extraction
# ---------------------------------------------------------------------------

def _extract_pdf_images(
    pdf_path: str,
    output_dir: str,
    min_w: int = 200,
    min_h: int = 200,
    min_bytes: int = 5000,
) -> list[dict[str, Any]]:
    if not _FITZ_OK:
        return []
    result: list[dict[str, Any]] = []
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
                if w < min_w or h < min_h or len(blob) < min_bytes:
                    continue

                fname = f"page{pg_idx + 1}_fig{img_seq + 1}.{payload['ext']}"
                dest = os.path.join(output_dir, fname)
                with open(dest, "wb") as fh:
                    fh.write(blob)
                result.append({
                    "filename": fname,
                    "path": f"images/{fname}",
                    "size": len(blob),
                    "width": w,
                    "height": h,
                    "ext": payload["ext"],
                    "source": "pdf-extraction",
                })
        doc.close()
    except Exception as exc:
        logger.error("PDF image extraction error: %s", exc)
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
        # Stage 1: source tarball
        if paper_id and _pull_source_tarball(paper_id, scratch):
            for entry in _find_source_figures(scratch):
                dest = os.path.join(output_dir, entry["filename"])
                shutil.copy2(entry["path"], dest)
                collected.append({
                    "filename": entry["filename"],
                    "path": f"images/{entry['filename']}",
                    "size": os.path.getsize(dest),
                    "ext": os.path.splitext(entry["filename"])[1][1:].lower(),
                    "source": entry["source"],
                })

        # Stage 2: PDF fallback when source yields too few
        if len(collected) < 3 and pdf_path and _FITZ_OK:
            collected.extend(_extract_pdf_images(pdf_path, output_dir))

    return collected
