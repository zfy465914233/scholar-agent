"""Paper import service — shared logic for CLI, MCP, and HTTP entry points."""

import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _parse_content_disposition_filename(content_disposition: str, default: str) -> str:
    """Extract filename from Content-Disposition header."""
    match = re.search(r'filename="?([^";]+)"?', content_disposition)
    return match.group(1) if match else default


def import_from_url(
    paper_id: str,
    token: str | None,
    base_url: str,
    knowledge_dir: Path,
    index_path: Path,
) -> tuple[str, str | None]:
    """Fetch a distilled paper note from a remote source and save to knowledge base.

    Args:
        paper_id: The UUID or identifier of the paper to import.
        token: Optional Bearer token for authentication.
        base_url: Base URL of the remote source (e.g. "https://pulse.mindpulse.ai").
        knowledge_dir: Local directory to save the markdown file.
        index_path: Path to the search index file.

    Returns:
        Tuple of (status_message, filename). filename is None on error.
    """
    url = f"{base_url.rstrip('/')}/api/v1/papers/{paper_id}/export-scholar-agent"

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            content_disposition = response.info().get("Content-Disposition", "")
            filename = _parse_content_disposition_filename(
                content_disposition, f"distilled-{paper_id}.md"
            )

            markdown_content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return "Error: Unauthorized. Please configure your API token.", None
        if e.code == 404:
            return f"Error: Paper note {paper_id} not found.", None
        return f"Error: Failed to fetch paper note (HTTP {e.code}): {e.reason}", None
    except Exception as e:
        return f"Error: Request failed: {e}", None

    # Save to knowledge_dir
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    dest_path = knowledge_dir / filename
    dest_path.write_text(markdown_content, encoding="utf-8")

    # Reindex
    try:
        from scholar_agent.engine.close_knowledge_loop import reindex
        reindex(index_path)
    except Exception:
        pass

    return f"Successfully imported paper note: {filename}", filename


def import_markdown(
    filename: str,
    markdown_content: str,
    knowledge_dir: Path,
    index_path: Path,
) -> tuple[str, str | None]:
    """Save raw markdown content to knowledge base and reindex.

    Args:
        filename: Desired filename (will be sanitized).
        markdown_content: The markdown content to save.
        knowledge_dir: Local directory to save the markdown file.
        index_path: Path to the search index file.

    Returns:
        Tuple of (status_message, filename). filename is None on error.
    """
    # Sanitize filename to prevent directory traversal
    safe_filename = Path(filename).name
    if not safe_filename.endswith(".md"):
        safe_filename += ".md"

    knowledge_dir.mkdir(parents=True, exist_ok=True)
    dest_path = knowledge_dir / safe_filename
    dest_path.write_text(markdown_content, encoding="utf-8")

    # Reindex
    try:
        from scholar_agent.engine.close_knowledge_loop import reindex
        reindex(index_path)
    except Exception:
        pass

    return f"Successfully saved: {safe_filename}", safe_filename
