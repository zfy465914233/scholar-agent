"""Build an interactive knowledge graph visualization from the local index.

The data layer is :func:`scholar_agent.engine.graph_export.build_graph_export`
(the machine-readable schema_version-1 contract); this module adapts it to
vis.js nodes/edges and renders a self-contained HTML file.

Color scheme (deterministic):
- Nodes take a stable palette color derived from ``md5(topic) % len(_PALETTE)``,
  so every topic gets a reproducible color without a hardcoded topic map.
- ``paper-note`` and ``daily-note`` nodes use fixed per-type colors so they
  stand out from topic-colored knowledge cards.
- Local wiki-link edges (``origin: local``) keep the default gray; cloud
  PaperPulse edges (``origin: paperpulse``) are dashed and colored per
  ``rel_type`` via ``_CLOUD_EDGE_COLORS``. The HTML legend documents both.

Usage:
  python -m scholar_agent.engine.build_graph
  python -m scholar_agent.engine.build_graph --index indexes/local/index.json --output graph.html
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any

from scholar_agent.engine.graph_export import build_graph_export
from scholar_agent.engine.scholar_config import get_index_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a knowledge graph HTML visualization.")
    parser.add_argument(
        "--index",
        type=Path,
        default=get_index_path(),
        help="Path to the local JSON index file. Defaults to the configured index_path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("graph.html"),
        help="Output HTML file path.",
    )
    return parser.parse_args()


# Topic palette — a topic is assigned a color by hashing (md5 → palette
# index), which stays stable across runs and needs no per-topic config.
_PALETTE = [
    "#4CAF50",
    "#2196F3",
    "#9C27B0",
    "#FF9800",
    "#F44336",
    "#00BCD4",
    "#FFC107",
    "#8BC34A",
    "#3F51B5",
    "#FF5722",
    "#009688",
    "#795548",
]

# Fixed node-type overrides so paper/daily notes are recognizable at a glance.
_NODE_TYPE_COLORS = {
    "paper-note": "#E91E63",
    "daily-note": "#B0BEC5",
}
_DEFAULT_NODE_COLOR = "#607D8B"

# Cloud (PaperPulse) edge colors per rel_type; local "references" edges stay gray.
_CLOUD_EDGE_COLORS = {
    "cites": "#90A4AE",
    "extends": "#64B5F6",
    "improves_upon": "#81C784",
    "baseline_for": "#FFB74D",
    "variant_of": "#CE93D8",
}


def _topic_color(topic: str) -> str:
    """Deterministic palette color for a topic: md5(topic) → palette index."""
    if not topic:
        return _DEFAULT_NODE_COLOR
    digest = hashlib.md5(topic.encode("utf-8")).hexdigest()
    return _PALETTE[int(digest, 16) % len(_PALETTE)]


def _node_color(node: dict[str, Any]) -> str:
    return _NODE_TYPE_COLORS.get(node.get("node_type", "")) or _topic_color(str(node.get("topic") or ""))


def build_graph_data(index_path: Path) -> dict:
    """Build vis.js nodes/edges from the graph export contract.

    Returns ``{"nodes": [...], "edges": [...]}`` with the id/label/title/
    color/group + from/to shape the HTML template (and the MCP ``build_graph``
    tool) consume. Never raises on missing data — an unreadable index yields
    empty lists.
    """
    export = build_graph_export(index_path)

    nodes = []
    for node in export["nodes"]:
        safe_title = html.escape(str(node["title"]))
        safe_topic = html.escape(str(node.get("topic") or ""))
        safe_type = html.escape(str(node.get("node_type") or "?"))
        tooltip = f"<b>{safe_title}</b><br>Topic: {safe_topic}<br>Type: {safe_type}"
        if node.get("arxiv_id"):
            tooltip += f"<br>arXiv: {html.escape(str(node['arxiv_id']))}"
        if node.get("venue"):
            tooltip += f"<br>Venue: {html.escape(str(node['venue']))}"
        nodes.append(
            {
                "id": node["id"],
                "label": safe_title[:40],
                "title": tooltip,
                "color": _node_color(node),
                "group": str(node.get("topic") or ""),
            }
        )

    edges = []
    for edge in export["edges"]:
        item: dict[str, Any] = {"from": edge["source"], "to": edge["target"]}
        if edge.get("origin") == "paperpulse":
            rel_type = str(edge.get("rel_type") or "cites")
            item["color"] = {"color": _CLOUD_EDGE_COLORS.get(rel_type, "#90A4AE")}
            item["dashes"] = True
            reason = str(edge.get("reason") or "").strip()
            tooltip = f"{rel_type} · PaperPulse · confidence {edge.get('confidence', 0)}"
            if reason:
                tooltip += f"<br>{html.escape(reason)}"
            item["title"] = tooltip
        edges.append(item)

    return {"nodes": nodes, "edges": edges}


_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Scholar Agent — Knowledge Graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; }
  #graph { width: 100vw; height: 100vh; }
  #info { position: absolute; top: 10px; left: 10px; background: rgba(26,26,46,0.9); padding: 12px 16px; border-radius: 8px; font-size: 14px; z-index: 10; }
  #info h3 { margin: 0 0 6px; color: #64ffda; }
  #info span { color: #aaa; }
  #legend { position: absolute; bottom: 10px; left: 10px; background: rgba(26,26,46,0.9); padding: 10px 14px; border-radius: 8px; font-size: 12px; color: #aaa; z-index: 10; line-height: 1.7; }
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
  .ln { display: inline-block; width: 18px; height: 2px; margin: 0 6px 3px 6px; }
</style>
</head>
<body>
<div id="info">
  <h3>Scholar Knowledge Graph</h3>
  <span>NODES_COUNT nodes · EDGES_COUNT edges</span>
</div>
<div id="legend">
  <span class="sw" style="background:#E91E63"></span>paper-note
  <span class="sw" style="background:#B0BEC5"></span>daily-note
  <span class="sw" style="background:#4CAF50"></span>knowledge card / other (topic-hashed)<br>
  <span class="ln" style="background:#555"></span>local references
  <span class="ln" style="background:#64B5F6"></span>PaperPulse relation (dashed, colored per rel_type)
</div>
<div id="graph"></div>
<script>
var data = {
  nodes: new vis.DataSet(NODES_JSON),
  edges: new vis.DataSet(EDGES_JSON)
};
var options = {
  nodes: { shape: "dot", size: 16, font: { size: 12, color: "#e0e0e0" }, borderWidth: 2 },
  edges: { arrows: "to", color: { color: "#555", highlight: "#64ffda" }, smooth: { type: "continuous" } },
  physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -30, centralGravity: 0.005, springLength: 120 } },
  interaction: { hover: true, tooltipDelay: 100 },
  layout: { improvedLayout: true }
};
new vis.Network(document.getElementById("graph"), data, options);
</script>
</body>
</html>"""


def generate_html(graph_data: dict, output_path: Path) -> Path:
    """Generate self-contained HTML visualization."""
    nodes_json = json.dumps(graph_data["nodes"], ensure_ascii=False)
    edges_json = json.dumps(graph_data["edges"], ensure_ascii=False)

    html = _HTML_TEMPLATE
    html = html.replace("NODES_JSON", nodes_json)
    html = html.replace("EDGES_JSON", edges_json)
    html = html.replace("NODES_COUNT", str(len(graph_data["nodes"])))
    html = html.replace("EDGES_COUNT", str(len(graph_data["edges"])))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main() -> int:
    args = parse_args()
    graph_data = build_graph_data(args.index)
    output = generate_html(graph_data, args.output)
    print(f"Graph written to {output} ({len(graph_data['nodes'])} nodes, {len(graph_data['edges'])} edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
