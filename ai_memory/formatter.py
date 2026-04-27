"""Format graph data into AI-optimized, low-token context summaries."""
import json
from typing import Dict, List, Optional
from .db import GraphDB


def _truncate(s: str, max_len: int = 200) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ")
    if len(s) > max_len:
        return s[:max_len - 3] + "..."
    return s


def file_summary(db: GraphDB, file_path: str) -> str:
    """Return a markdown summary of a single file."""
    file_row = db.get_file_by_path(file_path)
    if not file_row:
        return f"# File not found: `{file_path}`\n"

    lines = [f"# {file_path}", f"- **Language:** {file_row['language']}", f"- **Lines:** {file_row['line_count']}", ""]

    nodes = db.get_nodes_by_file(file_row["id"])
    if nodes:
        lines.append("## Symbols")
        for n in nodes:
            sig = _truncate(n.get("signature"), 100)
            kind = n["type"]
            name = n["name"]
            qname = n["qualified_name"]
            line = n["start_line"]
            lines.append(f"- `{kind}` **{name}** (L{line}) `{sig}`")

            # Show edges
            edges = db.get_edges_from(n["id"])
            if edges:
                calls = [f"`{e['target_name']}`" for e in edges if e["type"] == "calls"][:8]
                imports = [f"`{e['target_name']}`" for e in edges if e["type"] == "imports"][:5]
                inherits = [f"`{e['target_name']}`" for e in edges if e["type"] == "inherits"][:3]
                if calls:
                    lines.append(f"  - calls: {', '.join(calls)}")
                if imports:
                    lines.append(f"  - imports: {', '.join(imports)}")
                if inherits:
                    lines.append(f"  - inherits: {', '.join(inherits)}")

    return "\n".join(lines)


def symbol_context(db: GraphDB, name: str, max_depth: int = 2) -> str:
    """Return a focused context around a symbol and its neighbors."""
    nodes = db.search_nodes(name, limit=5)
    if not nodes:
        return f"# No symbol found for: `{name}`\n"

    lines = [f"# Symbol Context: `{name}`", ""]
    visited: set = set()

    def describe(node: Dict, depth: int = 0):
        if node["id"] in visited:
            return
        visited.add(node["id"])
        indent = "  " * depth
        sig = _truncate(node.get("signature"), 120)
        lines.append(f"{indent}- `{node['type']}` **{node['name']}** `{sig}` ({node['file_path']}:L{node['start_line']})")
        if node.get("type_annotations"):
            lines.append(f"{indent}  - types: `{_truncate(node['type_annotations'], 100)}`")
        if node.get("body"):
            body_preview = _truncate(node["body"].replace("\n", " "), 120)
            lines.append(f"{indent}  - body: `{body_preview}`")

        if depth < max_depth:
            for e in db.get_edges_from(node["id"]):
                if e["target_id"]:
                    # Resolve target
                    cur = db.conn.execute("SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id WHERE n.id = ?", (e["target_id"],))
                    row = cur.fetchone()
                    if row:
                        describe(dict(row), depth + 1)
                else:
                    lines.append(f"{indent}  - {e['type']} -> `{e['target_name']}` (unresolved)")

            for e in db.get_edges_to(node["id"]):
                cur = db.conn.execute("SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id WHERE n.id = ?", (e["source_id"],))
                row = cur.fetchone()
                if row:
                    src = dict(row)
                    if src["id"] not in visited:
                        sig = _truncate(src.get("signature"), 120)
                        lines.append(f"{indent}  - called by `{src['type']}` **{src['name']}** `{sig}` ({src['file_path']}:L{src['start_line']})")

    for node in nodes:
        describe(node)

    return "\n".join(lines)


def project_overview(db: GraphDB) -> str:
    """Return a high-level project overview."""
    stats = db.get_stats()
    summary = db.get_graph_summary()

    lines = [
        "# Project Overview",
        f"- **Files:** {stats['files']}",
        f"- **Symbols:** {stats['nodes']}",
        f"- **Relations:** {stats['edges']}",
        f"- **Schemas:** {stats['schemas']}",
        "",
        "## Symbol Types",
    ]
    for t, c in summary.get("node_types", {}).items():
        lines.append(f"- {t}: {c}")

    lines.append("")
    lines.append("## Relation Types")
    for t, c in summary.get("edge_types", {}).items():
        lines.append(f"- {t}: {c}")

    # Dependencies
    deps = db.get_dependencies()
    if deps:
        lines.append("")
        lines.append("## Dependencies")
        by_type: Dict[str, List] = {}
        for d in deps:
            by_type.setdefault(d.get("dep_type", "unknown"), []).append(d)
        for dep_type, items in by_type.items():
            lines.append(f"### {dep_type} ({len(items)})")
            for d in items[:10]:
                ver = d.get("version") or ""
                dev = " [dev]" if d.get("is_dev") else ""
                lines.append(f"- {d['name']}{ver and ' ' + ver}{dev}")
            if len(items) > 10:
                lines.append(f"- ... and {len(items) - 10} more")

    # Top hubs (most connected nodes)
    cur = db.conn.execute(
        """
        SELECT n.*, f.path as file_path,
               (SELECT COUNT(*) FROM edges WHERE source_id = n.id OR target_id = n.id) as degree
        FROM nodes n JOIN files f ON n.file_id = f.id
        ORDER BY degree DESC LIMIT 10
        """
    )
    lines.append("")
    lines.append("## Top Connected Symbols")
    for row in cur.fetchall():
        lines.append(f"- `{row['type']}` **{row['name']}** ({row['file_path']}:L{row['start_line']}) — {row['degree']} connections")

    return "\n".join(lines)


def schema_overview(db: GraphDB) -> str:
    """Return all database schemas."""
    cur = db.conn.execute("SELECT * FROM schemas ORDER BY table_name")
    rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        return "# No schemas found\n"

    lines = ["# Database Schemas", ""]
    for r in rows:
        kind = r["kind"].upper()
        name = r["table_name"]
        db_type = r["db_type"]
        defn = _truncate(r["definition"], 200)
        lines.append(f"## {kind}: `{name}` ({db_type})")
        lines.append(f"```sql\n{defn}\n```")
        lines.append("")

    return "\n".join(lines)


def query_context(db: GraphDB, query: str, max_tokens: int = 4000) -> str:
    """Generate a compact context summary for an AI query."""
    nodes = db.search_nodes(query, limit=15)
    lines: List[str] = []
    token_estimate = 0

    lines.append(f"# Query: `{query}`")
    lines.append("")
    lines.append("## Relevant Symbols")

    for n in nodes:
        chunk = f"- `{n['type']}` **{n['name']}** `{_truncate(n.get('signature'), 100)}` ({n['file_path']}:L{n['start_line']})\n"
        token_estimate += len(chunk) // 4
        if token_estimate > max_tokens:
            break
        lines.append(chunk)

        # Add 1-hop edges
        edges = db.get_edges_from(n["id"])
        for e in edges[:5]:
            edge_chunk = f"  - {e['type']} `{e['target_name']}`\n"
            token_estimate += len(edge_chunk) // 4
            if token_estimate > max_tokens:
                break
            lines.append(edge_chunk)

    if token_estimate > max_tokens:
        lines.append("\n... (truncated for token limit)\n")

    return "".join(lines)


def flows_overview(db: GraphDB) -> str:
    """Return pre-computed execution flows."""
    flows = db.get_flows(limit=50)
    if not flows:
        return "# No execution flows found\nRun `ai-memory scan` to build flows.\n"

    lines = ["# Execution Flows", ""]
    for f in flows:
        steps = json.loads(f["steps"])
        lines.append(f"## {f['name']}")
        lines.append(f"- **Nodes:** {f['node_count']} | **Files:** {f['file_count']} | **Criticality:** {f['criticality']:.2f}")
        lines.append("### Path")
        for step in steps[:15]:
            sig = _truncate(step.get("signature", ""), 60)
            lines.append(f"  → `{step['type']}` **{step['name']}** `{sig}` ({step['file']}:L{step['line']})")
        if len(steps) > 15:
            lines.append(f"  ... ({len(steps) - 15} more steps)")
        lines.append("")

    return "\n".join(lines)


def communities_overview(db: GraphDB) -> str:
    """Return detected code communities/modules."""
    communities = db.get_communities()
    if not communities:
        return "# No communities found\nRun `ai-memory scan` to detect communities.\n"

    lines = ["# Code Communities", ""]
    for c in communities:
        lines.append(f"## {c['name']}")
        lines.append(f"- **Size:** {c['size']} symbols | **Language:** {c['dominant_language'] or 'mixed'} | **Cohesion:** {c['cohesion']}")
        if c["summary"]:
            lines.append(f"- **Summary:** {c['summary']}")

        members = db.get_community_members(c["id"])
        if members:
            lines.append("### Key Symbols")
            for m in members[:10]:
                sig = _truncate(m.get("signature", ""), 50)
                lines.append(f"- `{m['type']}` **{m['name']}** `{sig}` ({m['file_path']}:L{m['start_line']})")
            if len(members) > 10:
                lines.append(f"- ... ({len(members) - 10} more)")
        lines.append("")

    return "\n".join(lines)
