"""Paper import service — shared logic for CLI, MCP, and HTTP entry points."""

import logging
import re
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# Validate paper_id: only alphanumeric, dashes, underscores, dots
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _sanitize_filename(filename: str, default: str) -> str:
    """Sanitize a filename to prevent path traversal.

    Strips directory components and ensures the result is a valid .md filename.
    """
    safe = Path(filename).name
    if not safe or safe.startswith("."):
        safe = default
    if not safe.endswith(".md"):
        safe += ".md"
    return safe


def _parse_content_disposition_filename(content_disposition: str, default: str) -> str:
    """Extract filename from Content-Disposition header, sanitized."""
    match = re.search(r'filename="?([^";]+)"?', content_disposition)
    raw = match.group(1) if match else default
    return _sanitize_filename(raw, default)


def _parse_frontmatter_domain_title(markdown: str) -> tuple[str, str]:
    """Extract domain and title from YAML frontmatter in a markdown string."""
    domain = ""
    title = ""
    match = re.match(r"^---\s*\n(.*?)\n---", markdown, re.DOTALL)
    if match:
        fm = match.group(1)
        for line in fm.split("\n"):
            if line.startswith("domain:"):
                domain = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip('"').strip("'")
    return domain, title


def _resolve_paper_notes_dir(knowledge_dir: Path) -> Path:
    """Resolve paper-notes directory from config, falling back to knowledge_dir sibling."""
    try:
        from scholar_agent.engine.scholar_config import load_config

        config = load_config()
        configured = config.get("academic", {}).get("paper_notes_dir")
        if configured:
            return Path(configured)
    except Exception:
        pass
    # Fallback: sibling of knowledge_dir
    return knowledge_dir.parent / "paper-notes"


def save_markdown_to_papernotes(
    filename: str,
    markdown_content: str,
    knowledge_dir: Path,
) -> tuple[Path, str]:
    """Core logic to save a markdown note to the paper-notes/ directory under a domain/title layout.

    Returns a tuple of (resolved_dest_path, safe_filename).
    Raises ValueError on path safety check failures.
    """
    from scholar_agent.engine.common import sanitize_title

    # 1. Parse frontmatter to extract domain and title
    domain, title = _parse_frontmatter_domain_title(markdown_content)

    # 2. Resolve paper-notes/ directory from config
    paper_notes_dir = _resolve_paper_notes_dir(knowledge_dir)

    # 3. Derive safe title and domain paths
    safe_title = sanitize_title(title) if title else Path(filename).stem
    if domain:
        domain = sanitize_title(domain)

    # 4. Construct destination paths
    dest_dir = paper_notes_dir / domain / safe_title if domain else paper_notes_dir / safe_title
    resolved_dest = dest_dir.resolve()

    # 5. Prevent path traversal attacks
    if not str(resolved_dest).startswith(str(paper_notes_dir.resolve())):
        raise ValueError("Invalid domain or title in frontmatter causing path traversal")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{safe_title}.md"
    dest_path.write_text(markdown_content, encoding="utf-8")

    return dest_path, f"{safe_title}.md"


def import_from_url(
    paper_id: str,
    token: str | None,
    base_url: str,
    knowledge_dir: Path,
    index_path: Path,
) -> tuple[str, str | None]:
    """Fetch a distilled paper note from a remote source and save to paper-notes/."""
    if not _SAFE_ID_RE.match(paper_id):
        return f"Error: Invalid paper_id '{paper_id}': must contain only alphanumeric, dash, underscore, or dot.", None

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

    try:
        _, saved_filename = save_markdown_to_papernotes(filename, markdown_content, knowledge_dir)
    except ValueError as e:
        return f"Error: {e}", None

    return f"Successfully imported paper note: {saved_filename}", saved_filename


def import_markdown(
    filename: str,
    markdown_content: str,
    knowledge_dir: Path,
    index_path: Path,
) -> tuple[str, str | None]:
    """Save raw markdown content to paper-notes/ directory under correct domain/title subfolders."""
    try:
        _, saved_filename = save_markdown_to_papernotes(filename, markdown_content, knowledge_dir)
    except ValueError as e:
        return f"Error: {e}", None

    return f"Successfully saved: {saved_filename}", saved_filename
