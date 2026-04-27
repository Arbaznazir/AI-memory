"""Export knowledge graph to Mermaid or DOT format for visualization."""
import json
from typing import Dict, List, Optional

from .db import GraphDB


def export_mermaid_flow(flow_id: int, db: GraphDB) -> str:
    """Export a single execution flow as Mermaid flowchart."""
    flow = db.get_flow(flow_id)
    if not flow:
        return "%% Flow not found"
    
    steps = json.loads(flow["steps"])
    if not steps:
        return "%% No steps in flow"
    
    lines = ["```mermaid", "flowchart TD"]
    
    # Create nodes
    for i, step in enumerate(steps):
        node_id = f"n{i}"
        label = step["name"][:20]
        lines.append(f"    {node_id}[{label}]")
    
    # Create edges from flow structure
    for i in range(len(steps) - 1):
        lines.append(f"    n{i} --> n{i+1}")
    
    lines.append("```")
    return "\n".join(lines)


def export_mermaid_call_graph(symbol_name: str, db: GraphDB, max_depth: int = 3) -> str:
    """Export call graph centered on a symbol as Mermaid flowchart."""
    from .callers import build_reverse_call_graph
    
    graph = build_reverse_call_graph(db, symbol_name, max_depth=max_depth)
    if "error" in graph:
        return f"%% {graph['error']}"
    
    nodes = graph["nodes"]
    edges = graph["edges"]
    
    if not nodes:
        return "%% No call graph found"
    
    lines = ["```mermaid", "flowchart TD"]
    
    # Create node map
    node_map: Dict[int, str] = {}
    for i, n in enumerate(nodes):
        node_id = f"n{n['id']}"
        node_map[n['id']] = node_id
        label = f"{n['type']}:{n['name']}"[:25]
        lines.append(f"    {node_id}[{label}]")
    
    # Reverse edges for call graph (callers pointing to callees)
    for e in edges:
        from_id = node_map.get(e["from_id"])
        to_id = node_map.get(e["to_id"])
        if from_id and to_id:
            lines.append(f"    {from_id} --> {to_id}")
    
    # Also add forward edges (calls from target)
    target_id = graph["target"]["id"]
    cur = db.conn.execute(
        """
        SELECT e.*, tgt.name as tgt_name, tgt.id as tgt_id
        FROM edges e
        JOIN nodes tgt ON e.target_id = tgt.id
        WHERE e.source_id = ? AND e.type = 'calls' AND e.target_id IS NOT NULL
        LIMIT 10
        """,
        (target_id,)
    )
    for row in cur.fetchall():
        from_id = node_map.get(target_id)
        to_id = node_map.get(row["tgt_id"])
        if from_id and to_id:
            lines.append(f"    {from_id} --> {to_id}")
        elif from_id:
            # External node
            ext_id = f"ext{row['tgt_id']}"
            lines.append(f"    {ext_id}[{row['tgt_name'][:20]}]")
            lines.append(f"    {from_id} --> {ext_id}")
    
    lines.append("```")
    return "\n".join(lines)


def export_dot_communities(db: GraphDB) -> str:
    """Export community graph as DOT format."""
    communities = db.get_communities()
    if not communities:
        return "// No communities found"
    
    lines = ["digraph Communities {"]
    
    for c in communities:
        c_id = f"c{c['id']}"
        label = f"{c['name']}\\n({c['size']} symbols)"
        lines.append(f'    {c_id} [label="{label}"];')
    
    # Find cross-community edges
    for c in communities:
        members = db.get_community_members(c["id"])
        member_ids = {m["id"] for m in members}
        
        # Check outgoing edges from this community to others
        cur = db.conn.execute(
            """
            SELECT DISTINCT cm2.community_id
            FROM edges e
            JOIN community_members cm1 ON e.source_id = cm1.node_id
            JOIN community_members cm2 ON e.target_id = cm2.node_id
            WHERE cm1.community_id = ? AND cm2.community_id != ?
            """,
            (c["id"], c["id"])
        )
        for row in cur.fetchall():
            other_id = row["community_id"]
            lines.append(f"    c{c['id']} -> c{other_id};")
    
    lines.append("}")
    return "\n".join(lines)


def export_mermaid_project(db: GraphDB, max_nodes: int = 50) -> str:
    """Export simplified project overview as Mermaid."""
    cur = db.conn.execute(
        """
        SELECT n.*, f.path as file_path
        FROM nodes n
        JOIN files f ON n.file_id = f.id
        WHERE n.type IN ('function', 'method', 'class')
        ORDER BY (SELECT COUNT(*) FROM edges WHERE source_id = n.id OR target_id = n.id) DESC
        LIMIT ?
        """,
        (max_nodes,)
    )
    nodes = [dict(r) for r in cur.fetchall()]
    
    if not nodes:
        return "%% No nodes found"
    
    node_ids = {n["id"] for n in nodes}
    
    # Get edges between these nodes
    placeholders = ",".join(["?"] * len(node_ids))
    cur = db.conn.execute(
        f"""
        SELECT e.*, src.name as src_name, tgt.name as tgt_name
        FROM edges e
        JOIN nodes src ON e.source_id = src.id
        JOIN nodes tgt ON e.target_id = tgt.id
        WHERE e.source_id IN ({placeholders}) AND e.target_id IN ({placeholders})
          AND e.type = 'calls'
        LIMIT 100
        """,
        tuple(list(node_ids) + list(node_ids))
    )
    edges = [dict(r) for r in cur.fetchall()]
    
    lines = ["```mermaid", "flowchart TD"]
    
    for n in nodes:
        label = f"{n['type']}:{n['name']}"[:20]
        lines.append(f"    n{n['id']}[{label}]")
    
    seen = set()
    for e in edges:
        key = f"n{e['source_id']} --> n{e['target_id']}"
        if key not in seen:
            seen.add(key)
            lines.append(f"    {key}")
    
    lines.append("```")
    return "\n".join(lines)
