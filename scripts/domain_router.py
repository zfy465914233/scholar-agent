"""Dynamic routing for knowledge folders.

Routes cards into a hierarchical structure:
    knowledge/<major_domain>/<card>.md
    knowledge/<major_domain>/<subdomain>/<card>.md

AI is the primary router. It sees existing folder content summaries and makes
informed decisions. Falls back to folder-name token matching and heuristic
slug generation when AI is unavailable.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "schemas" / "routing_skill.md"
POLICY_PATH = ROOT / "schemas" / "domain_routing_policy.json"
GUIDE_PATH = ROOT / "schemas" / "domain_routing_guide.md"

# ── Limits ──────────────────────────────────────────────────────────

MAX_TITLES_PER_FOLDER = 10
MAX_TAGS_PER_FOLDER = 20
MAX_CARD_SUMMARY_LEN = 500

# ── Folder cache ────────────────────────────────────────────────────

_domain_tree_cache: dict[str, dict[str, Path]] | None = None
_folder_summaries_cache: dict[str, dict[str, FolderSummary]] | None = None
_cache_root: Path | None = None
ROOT_SUBDOMAIN = ""


# ── Types ───────────────────────────────────────────────────────────


class FolderSummary(TypedDict):
    card_count: int
    titles: list[str]
    tags: list[str]


# ── Config loaders ──────────────────────────────────────────────────


def load_routing_policy() -> dict[str, object] | None:
    """Load the optional user-override routing policy.

    Returns None if the file does not exist (routing does not depend on it).
    """
    if not POLICY_PATH.exists():
        return None
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def load_routing_skill() -> str:
    """Load the routing skill instruction for AI."""
    if not SKILL_PATH.exists():
        return (
            "You are a knowledge base routing assistant. "
            "Decide where a new card should be filed. "
            "Return JSON: {\"major_domain\":\"...\",\"subdomain\":\"\",\"reason\":\"...\"}"
        )
    return SKILL_PATH.read_text(encoding="utf-8")


def load_routing_guide() -> str:
    """Load the legacy routing guide (kept for backward compatibility)."""
    if not GUIDE_PATH.exists():
        return ""
    return GUIDE_PATH.read_text(encoding="utf-8")


# ── Domain tree discovery ──────────────────────────────────────────


def discover_domain_tree(knowledge_root: Path) -> dict[str, dict[str, Path]]:
    """Scan knowledge_root for major-domain folders and optional subdomains."""
    domain_tree: dict[str, dict[str, Path]] = {}
    if not knowledge_root.exists():
        return domain_tree
    for child in sorted(knowledge_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name == "templates":
            continue
        subdomains: dict[str, Path] = {}
        has_root_cards = False
        for grandchild in sorted(child.iterdir()):
            if grandchild.is_dir() and not grandchild.name.startswith("."):
                subdomains[grandchild.name] = grandchild
            elif grandchild.is_file() and grandchild.suffix.lower() == ".md":
                has_root_cards = True
        if has_root_cards or not subdomains:
            subdomains[ROOT_SUBDOMAIN] = child
        if subdomains:
            domain_tree[child.name] = subdomains
    return domain_tree


def get_domain_tree(knowledge_root: Path) -> dict[str, dict[str, Path]]:
    """Return cached domain tree, rebuilding if necessary."""
    global _domain_tree_cache, _cache_root
    if _domain_tree_cache is None or _cache_root != knowledge_root:
        _domain_tree_cache = discover_domain_tree(knowledge_root)
        _cache_root = knowledge_root
    return _domain_tree_cache


def clear_folder_cache() -> None:
    """Invalidate the folder cache so next call re-discovers the tree."""
    global _domain_tree_cache, _folder_summaries_cache, _cache_root
    _domain_tree_cache = None
    _folder_summaries_cache = None
    _cache_root = None


# ── Folder summaries ───────────────────────────────────────────────


def _parse_frontmatter_title_tags(text: str) -> tuple[str, list[str]]:
    """Extract title and tags from markdown frontmatter.

    Handles multiple YAML formats:
    - title: Single Line
    - title: >
      Multi-line folded
    - tags: [tag1, tag2]        (inline list)
    - tags:                     (block list)
        - tag1
        - tag2
    """
    title = ""
    tags: list[str] = []
    if not text.startswith("---"):
        return title, tags
    end = text.find("---", 3)
    if end < 0:
        return title, tags
    fm = text[3:end]

    # Extract title: handle quoted, multi-line folded (>) and literal (|)
    title_match = re.search(
        r"^title:\s*(?:'([^']*)'|\"([^\"]*)\"|>(.*?)$|\|(.*)$|(.*))$",
        fm, re.MULTILINE,
    )
    if title_match:
        # Groups: 1=single-quoted, 2=double-quoted, 3=folded, 4=literal, 5=plain
        for group_val in title_match.groups():
            if group_val is not None:
                title = group_val.strip()
                break

    # Extract tags: handle both inline [a, b] and block - item formats
    tags_match = re.search(r"^tags:\s*\[(.+?)\]", fm, re.MULTILINE)
    if tags_match:
        # Inline list: tags: [tag1, tag2, tag3]
        tags = [t.strip().strip("'\"") for t in tags_match.group(1).split(",") if t.strip()]
    else:
        # Block list: tags:\n  - tag1\n  - tag2
        tags_section = re.search(r"^tags:\s*$((?:\n\s+-\s+.+$)*)", fm, re.MULTILINE)
        if tags_section:
            tags = [
                line.strip().lstrip("-").strip().strip("'\"")
                for line in tags_section.group(1).strip().splitlines()
                if line.strip()
            ]

    return title, tags


def collect_folder_summaries(knowledge_root: Path) -> dict[str, dict[str, FolderSummary]]:
    """Collect lightweight content summaries for each folder.

    Returns {major_domain: {subdomain: FolderSummary}}.
    Reads only card frontmatter (title + tags), not full body.
    """
    global _folder_summaries_cache, _cache_root
    if _folder_summaries_cache is not None and _cache_root == knowledge_root:
        return _folder_summaries_cache

    domain_tree = get_domain_tree(knowledge_root)
    summaries: dict[str, dict[str, FolderSummary]] = {}

    for major_slug, subdomain_map in domain_tree.items():
        summaries[major_slug] = {}
        for sub_slug, folder_path in subdomain_map.items():
            titles: list[str] = []
            tags: list[str] = []
            card_count = 0
            if folder_path.is_dir():
                for md_file in sorted(folder_path.glob("*.md")):
                    if md_file.name.startswith("_"):
                        continue
                    card_count += 1
                    if len(titles) < MAX_TITLES_PER_FOLDER:
                        try:
                            text = md_file.read_text(encoding="utf-8")
                            t, tg = _parse_frontmatter_title_tags(text)
                            if t:
                                titles.append(t[:80])
                            for tag in tg:
                                if tag not in tags and len(tags) < MAX_TAGS_PER_FOLDER:
                                    tags.append(tag)
                        except (OSError, UnicodeDecodeError):
                            pass
            summaries[major_slug][sub_slug] = FolderSummary(
                card_count=card_count,
                titles=titles,
                tags=tags,
            )

    _folder_summaries_cache = summaries
    return summaries


# ── Routing context ────────────────────────────────────────────────


def build_routing_context(
    query: str,
    knowledge_root: Path,
    card_title: str = "",
    card_summary: str = "",
) -> dict:
    """Build the full context object for routing decisions."""
    domain_tree = get_domain_tree(knowledge_root)
    folder_summaries = collect_folder_summaries(knowledge_root)

    existing_folders: dict[str, list[str]] = {}
    for major, subs in domain_tree.items():
        existing_folders[major] = sorted(subs.keys())

    folder_contents: dict[str, dict[str, dict]] = {}
    for major, sub_map in folder_summaries.items():
        folder_contents[major] = {}
        for sub, summary in sub_map.items():
            if summary["card_count"] == 0 and sub == ROOT_SUBDOMAIN:
                continue
            folder_contents[major][sub] = {
                "card_count": summary["card_count"],
                "titles": summary["titles"],
            }

    return {
        "query": query,
        "card_title": card_title,
        "card_summary": card_summary[:MAX_CARD_SUMMARY_LEN],
        "existing_folders": existing_folders,
        "folder_contents": folder_contents,
    }


# ── Token extraction (for folder-name matching) ────────────────────


def _tokens_from_slug(slug: str) -> list[str]:
    """Split a kebab-case slug into searchable tokens."""
    parts = slug.lower().split("-")
    return [slug.lower()] + [p for p in parts if len(p) > 1]


def _score_tokens(query: str, tokens: list[str]) -> int:
    """Return a lightweight lexical score for a token list."""
    q = query.lower()
    score = 0
    for token in tokens:
        if not token:
            continue
        if re.fullmatch(r"[a-z0-9-]+", token):
            pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
            if re.search(pattern, q):
                score = max(score, len(token.split("-")))
        elif token in q:
            score = max(score, len(token))
    return score


# ── Folder-name matching (Tier 2, no API needed) ──────────────────


def match_existing_folders(
    query: str,
    domain_tree: dict[str, dict[str, Path]],
) -> tuple[str, str | None] | None:
    """Match a query against existing folder names using token scoring.

    This is the zero-cost fallback when AI is unavailable.
    It does not depend on any predefined policy — only on actual folder names.
    """
    best_route: tuple[str, str | None] | None = None
    best_score = 0

    for major_slug, subdomain_map in domain_tree.items():
        major_tokens = _tokens_from_slug(major_slug)
        major_score = _score_tokens(query, major_tokens)

        for sub_slug in subdomain_map:
            if sub_slug in {ROOT_SUBDOMAIN, "general"}:
                continue
            sub_tokens = _tokens_from_slug(sub_slug)
            sub_score = _score_tokens(query, sub_tokens)
            if sub_score == 0:
                continue
            pair_score = (sub_score * 10) + major_score
            if pair_score > best_score:
                best_score = pair_score
                best_route = (major_slug, sub_slug)

        if major_score > best_score:
            best_score = major_score
            best_route = (major_slug, None)

    if best_route is None or best_score == 0:
        return None

    return best_route


# ── Legacy policy matching (kept for optional user overrides) ──────


def _major_tokens(major_slug: str, major_policy: dict[str, object]) -> list[str]:
    tokens = _tokens_from_slug(major_slug)
    label = str(major_policy.get("label", "")).lower()
    if label:
        tokens.append(label)
    for alias in major_policy.get("aliases", []):
        tokens.append(str(alias).lower())
    return list(dict.fromkeys(tokens))


def _subdomain_tokens(sub_slug: str, sub_policy: dict[str, object]) -> list[str]:
    if not sub_slug:
        return []
    tokens = _tokens_from_slug(sub_slug)
    label = str(sub_policy.get("label", "")).lower()
    if label:
        tokens.append(label)
    for alias in sub_policy.get("aliases", []):
        tokens.append(str(alias).lower())
    return list(dict.fromkeys(tokens))


def match_route(
    query: str,
    policy: dict[str, object],
    domain_tree: dict[str, dict[str, Path]],
) -> tuple[str, str | None] | None:
    """Match a query against policy-defined domains and subdomains.

    This is the legacy policy-based matcher, kept for backward compatibility
    and optional user overrides. Prefer match_existing_folders() for the
    zero-config path.
    """
    majors = policy.get("major_domains", {})
    best_route: tuple[str, str | None] | None = None
    best_score = 0

    for major_slug, major_policy in majors.items():
        major_score = _score_tokens(query, _major_tokens(major_slug, major_policy))
        available_subdomains = set(domain_tree.get(major_slug, {}).keys())
        available_subdomains.update(major_policy.get("subdomains", {}).keys())

        for subdomain_slug in available_subdomains:
            if subdomain_slug in {ROOT_SUBDOMAIN, "general"}:
                continue
            sub_policy = major_policy.get("subdomains", {}).get(subdomain_slug, {})
            sub_score = _score_tokens(query, _subdomain_tokens(subdomain_slug, sub_policy))
            if sub_score == 0:
                continue
            pair_score = (sub_score * 10) + major_score
            if pair_score > best_score:
                best_score = pair_score
                best_route = (major_slug, subdomain_slug)

        if major_score > best_score:
            best_score = major_score
            best_route = (major_slug, None)

    if best_route is None or best_score == 0:
        return None

    return best_route


# ── AI routing ─────────────────────────────────────────────────────


def _router_api_url() -> str:
    return os.getenv("LORE_ROUTER_API_URL") or os.getenv("LLM_API_URL") or "https://api.openai.com/v1"


def _router_api_key() -> str:
    return os.getenv("LORE_ROUTER_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("GITHUB_TOKEN") or ""


def _router_model() -> str:
    return os.getenv("LORE_ROUTER_MODEL") or os.getenv("LLM_MODEL") or "gpt-4o-mini"


def _call_router_llm(system_prompt: str, user_message: str) -> str | None:
    """Call an OpenAI-compatible endpoint for folder classification."""
    api_key = _router_api_key()
    if not api_key:
        return None

    payload = {
        "model": _router_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
        "max_tokens": 128,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    req = Request(
        _router_api_url().rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError):
        return None

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return None


def _build_routing_prompt(context: dict) -> tuple[str, str]:
    """Build the system prompt and user message for AI routing.

    Returns (system_prompt, user_message).
    """
    skill_text = load_routing_skill()
    user_json = json.dumps(
        {
            "query": context["query"],
            "card_title": context.get("card_title", ""),
            "card_summary": context.get("card_summary", ""),
            "existing_folders": context.get("existing_folders", {}),
            "folder_contents": context.get("folder_contents", {}),
        },
        ensure_ascii=False,
        indent=2,
    )
    return skill_text, user_json


def infer_domain_with_ai(context: dict) -> dict[str, str] | None:
    """Ask an LLM to decide a major domain and optional subdomain.

    Uses the routing skill as the system prompt and the routing context
    (query + card info + folder summaries) as the user message.
    """
    system_prompt, user_message = _build_routing_prompt(context)
    text = _call_router_llm(system_prompt, user_message)
    if text is None:
        return None

    text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start:end])
        except json.JSONDecodeError:
            return None

    major_domain = str(payload.get("major_domain", "")).strip()
    raw_subdomain = payload.get("subdomain", "")
    subdomain = "" if raw_subdomain is None else str(raw_subdomain).strip()
    reason = str(payload.get("reason", "")).strip()
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", major_domain):
        return None
    if subdomain and not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", subdomain):
        return None
    if subdomain == "general" and major_domain != "general":
        subdomain = ""
    return {
        "major_domain": major_domain,
        "subdomain": subdomain,
        "reason": reason,
    }


# ── Fallback ───────────────────────────────────────────────────────


def _propose_new_major_domain(query: str) -> str:
    """Build a conservative fallback major-domain slug from the query text."""
    normalized = query.strip().lower()
    tokens = re.findall(r"[a-z0-9]+", normalized)
    if tokens:
        return "-".join(tokens[:3])

    compact = re.sub(r"\s+", "", query.strip())
    if compact:
        return compact[:16]

    return "general"


def _ensure_dir(path: Path) -> bool:
    """Create directory if it doesn't exist. Returns True if a new dir was created."""
    if path.is_dir():
        return False
    path.mkdir(parents=True, exist_ok=True)
    return True


def _build_route(knowledge_root: Path, major_domain: str, subdomain: str | None) -> tuple[str, Path, str]:
    """Return the route slug, output path, and normalized subdomain string."""
    normalized_subdomain = (subdomain or "").strip()
    if normalized_subdomain == "general" and major_domain != "general":
        normalized_subdomain = ""

    output_path = knowledge_root / major_domain
    route_slug = major_domain
    if normalized_subdomain:
        output_path = output_path / normalized_subdomain
        route_slug = f"{major_domain}/{normalized_subdomain}"
    return route_slug, output_path, normalized_subdomain


# ── Main entry points ──────────────────────────────────────────────


def infer_domain_decision(
    query: str,
    knowledge_root: Path,
    use_ai_fallback: bool = True,
    *,
    card_title: str = "",
    card_summary: str = "",
) -> dict[str, object]:
    """Infer the full domain routing decision for a query.

    Priority: AI primary → folder-name matching → heuristic fallback.
    """
    context = build_routing_context(query, knowledge_root, card_title, card_summary)
    domain_tree = context.get("existing_folders", {})

    # Reconstruct the actual domain_tree with Paths for routing
    actual_tree = get_domain_tree(knowledge_root)

    # Tier 1: AI primary routing
    if use_ai_fallback:
        ai_result = infer_domain_with_ai(context)
        if ai_result is not None:
            major_domain = str(ai_result["major_domain"])
            subdomain = str(ai_result["subdomain"])
            route_slug, output_path, normalized_subdomain = _build_route(
                knowledge_root, major_domain, subdomain,
            )
            if _ensure_dir(output_path):
                clear_folder_cache()
            return {
                "major_domain": major_domain,
                "subdomain": normalized_subdomain,
                "route_slug": route_slug,
                "output_path": output_path,
                "decision_mode": "ai_primary",
                "reason": ai_result.get("reason", "AI selected the best matching route."),
            }

    # Tier 2: Folder-name token matching (zero-config, no API)
    matched = match_existing_folders(query, actual_tree)
    if matched is not None:
        major_domain, subdomain = matched
        route_slug, output_path, normalized_subdomain = _build_route(
            knowledge_root, major_domain, subdomain,
        )
        if _ensure_dir(output_path):
            clear_folder_cache()
        return {
            "major_domain": major_domain,
            "subdomain": normalized_subdomain,
            "route_slug": route_slug,
            "output_path": output_path,
            "decision_mode": "folder_match",
            "reason": "Matched against existing folder names.",
        }

    # Tier 3: Heuristic fallback
    new_major_domain = _propose_new_major_domain(query)
    if new_major_domain != "general":
        route_slug, output_path, normalized_subdomain = _build_route(
            knowledge_root, new_major_domain, None,
        )
        if _ensure_dir(output_path):
            clear_folder_cache()
        return {
            "major_domain": new_major_domain,
            "subdomain": normalized_subdomain,
            "route_slug": route_slug,
            "output_path": output_path,
            "decision_mode": "fallback_new_major",
            "reason": "No AI or folder match available, created a new domain from the query.",
        }

    route_slug, output_path, normalized_subdomain = _build_route(
        knowledge_root, "general", None,
    )
    if _ensure_dir(output_path):
        clear_folder_cache()
    return {
        "major_domain": "general",
        "subdomain": normalized_subdomain,
        "route_slug": route_slug,
        "output_path": output_path,
        "decision_mode": "fallback_general",
        "reason": "No AI, folder match, or heuristic domain available.",
    }


def infer_domain(
    query: str,
    knowledge_root: Path,
    use_ai_fallback: bool = True,
    *,
    card_title: str = "",
    card_summary: str = "",
) -> tuple[str, Path]:
    """Infer the route slug and output path for a query.

    Returns (route_slug, output_path).
    """
    decision = infer_domain_decision(
        query, knowledge_root, use_ai_fallback=use_ai_fallback,
        card_title=card_title, card_summary=card_summary,
    )
    return str(decision["route_slug"]), Path(str(decision["output_path"]))
