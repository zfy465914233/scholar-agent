"""Paper image extractor — arXiv source + PDF fallback.

Priority:
  1. arXiv source archive (pics/, figures/, etc.)
  2. PDF-embedded figure files
  3. Direct PDF image extraction (PyMuPDF)

Adapted from evil-read-arxiv/extract-paper-images/scripts/extract_images.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def _download_arxiv_source(arxiv_id: str, temp_dir: str) -> bool:
    """Download and extract arXiv source archive."""
    source_url = f"https://arxiv.org/e-print/{arxiv_id}"
    logger.info("Downloading arXiv source: %s", source_url)

    try:
        if HAS_REQUESTS:
            resp = _requests.get(source_url, timeout=60)
            content = resp.content if resp.status_code == 200 else None
            status = resp.status_code
        else:
            req = urllib_request.urlopen(source_url, timeout=60)
            content = req.read()
            status = req.status

        if status == 200 and content:
            tar_path = os.path.join(temp_dir, f"{arxiv_id}.tar.gz")
            with open(tar_path, "wb") as f:
                f.write(content)

            with tarfile.open(tar_path, "r:*") as tar:
                safe = [
                    m for m in tar.getmembers()
                    if not m.name.startswith("/") and ".." not in m.name
                    and not m.issym() and not m.islnk()
                ]
                tar.extractall(path=temp_dir, members=safe)
            return True
        return False
    except Exception as e:
        logger.error("Failed to download source: %s", e)
        return False


def _find_source_figures(temp_dir: str) -> list[dict[str, Any]]:
    """Find images in arXiv source directories."""
    figures: list[dict[str, Any]] = []
    seen: set[str] = set()
    image_dirs = ["pics", "figures", "fig", "images", "img"]
    image_exts = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}

    for d in image_dirs:
        dpath = os.path.join(temp_dir, d)
        if os.path.exists(dpath):
            for fn in os.listdir(dpath):
                if fn in seen:
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext in image_exts:
                    seen.add(fn)
                    figures.append({
                        "type": "source",
                        "source": "arxiv-source",
                        "path": os.path.join(dpath, fn),
                        "filename": fn,
                    })

    # Fallback: root directory images
    if not figures:
        for fn in os.listdir(temp_dir):
            ext = os.path.splitext(fn)[1].lower()
            fpath = os.path.join(temp_dir, fn)
            if os.path.isfile(fpath) and ext in {".png", ".jpg", ".jpeg"}:
                if "logo" not in fn.lower() and "icon" not in fn.lower():
                    figures.append({
                        "type": "source",
                        "source": "arxiv-source",
                        "path": fpath,
                        "filename": fn,
                    })

    return figures


def _extract_pdf_images(
    pdf_path: str,
    output_dir: str,
    min_width: int = 200,
    min_height: int = 200,
    min_bytes: int = 5000,
) -> list[dict[str, Any]]:
    """Extract images from PDF using PyMuPDF."""
    if not HAS_FITZ:
        logger.warning("PyMuPDF not installed, cannot extract from PDF")
        return []

    images: list[dict[str, Any]] = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            for img_idx, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                try:
                    base = doc.extract_image(xref)
                except Exception:
                    continue
                if not base:
                    continue
                if base.get("width", 0) < min_width or base.get("height", 0) < min_height:
                    continue
                if len(base["image"]) < min_bytes:
                    continue

                fn = f"page{page_num + 1}_fig{img_idx + 1}.{base['ext']}"
                fpath = os.path.join(output_dir, fn)
                with open(fpath, "wb") as f:
                    f.write(base["image"])

                images.append({
                    "filename": fn,
                    "path": f"images/{fn}",
                    "size": len(base["image"]),
                    "width": base.get("width", 0),
                    "height": base.get("height", 0),
                    "ext": base["ext"],
                    "source": "pdf-extraction",
                })
        doc.close()
    except Exception as e:
        logger.error("PDF extraction error: %s", e)

    return images


def extract_paper_images(
    paper_id: str,
    output_dir: str,
    pdf_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract images from a paper.

    Args:
        paper_id: arXiv ID (e.g. "2510.24701").
        output_dir: Directory to save extracted images.
        pdf_path: Optional local PDF file path.

    Returns:
        List of image metadata dicts.
    """
    os.makedirs(output_dir, exist_ok=True)
    arxiv_id = paper_id
    all_figures: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp:
        # Step 1: arXiv source
        if arxiv_id and _download_arxiv_source(arxiv_id, tmp):
            source_figs = _find_source_figures(tmp)
            for fig in source_figs:
                dest = os.path.join(output_dir, fig["filename"])
                shutil.copy2(fig["path"], dest)
                all_figures.append({
                    "filename": fig["filename"],
                    "path": f"images/{fig['filename']}",
                    "size": os.path.getsize(dest),
                    "ext": os.path.splitext(fig["filename"])[1][1:].lower(),
                    "source": fig["source"],
                })

        # Step 2: PDF extraction fallback
        if len(all_figures) < 3 and pdf_path and HAS_FITZ:
            pdf_figs = _extract_pdf_images(pdf_path, output_dir)
            all_figures.extend(pdf_figs)

    return all_figures
