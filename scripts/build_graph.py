"""Build an interactive knowledge graph visualization from the local index.

Reads the JSON index, extracts nodes (cards) and edges (wiki-links/backlinks),
and generates a self-contained HTML file using vis.js for visualization.

Usage:
  python scripts/build_graph.py
  python scripts/build_graph.py --index indexes/local/index.json --output graph.html
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a knowledge graph HTML visualization.")
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("indexes/local/index.json"),
        help="Path to the local JSON index file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("graph.html"),
        help="Output HTML file path.",
    )
    return parser.parse_args()


_TOPIC_COLORS = {
    "qpe": "#4CAF50",
    "markov_chain": "#2196F3",
    "quantum_phase_estimation": "#9C27B0",
    "linear_programming": "#FF9800",
    "model_quantization": "#F44336",
    "general": "#607D8B",
}


def build_graph_data(index_path: Path) -> dict:
    """Build nodes and edges from the index."""
    if not index_path.exists():
        return {"nodes": [], "edges": []}

    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    documents = index_data.get("documents", [])

    nodes = []
    edges = []
    seen_edges: set[tuple[str, str]] = set()

    for doc in documents:
        doc_id = doc.get("doc_id", "")
        if not doc_id:
            continue
        topic = doc.get("topic", "general")
        color = _TOPIC_COLORS.get(topic, _TOPIC_COLORS["general"])
        nodes.append({
            "id": doc_id,
            "label": doc.get("title", doc_id)[:40],
            "title": f"<b>{doc.get('title', doc_id)}</b><br>Topic: {topic}<br>Type: {doc.get('type', '?')}",
            "color": color,
            "group": topic,
        })

        for link in doc.get("links", []):
            edge_key = (doc_id, link)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append({"from": doc_id, "to": link})

    return {"nodes": nodes, "edges": edges}


_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Lore Agent — Knowledge Graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; }
  #graph { width: 100vw; height: 100vh; }
  #info { position: absolute; top: 10px; left: 10px; background: rgba(26,26,46,0.9); padding: 12px 16px; border-radius: 8px; font-size: 14px; z-index: 10; }
  #info h3 { margin: 0 0 6px; color: #64ffda; }
  #info span { color: #aaa; }
</style>
</head>
<body>
<div id="info">
  <h3>Lore Knowledge Graph</h3>
  <span>NODES_COUNT nodes · EDGES_COUNT edges</span>
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
