"""Pre-compute execution flows by tracing call graphs from entry points."""
import json
from typing import Dict, List, Optional, Set, Tuple
from collections import deque

from .db import GraphDB


# Entry point heuristics
ENTRY_PATTERNS = {
    "function": [
        "main", "__main__", "run", "serve", "start", "init",
        "handler", "process_request", "handle_event",
    ],
    "method": [
        "get", "post", "put", "delete", "patch", "handle",
        "on_request", "dispatch", "invoke",
    ]
}

# Framework route decorators / patterns
ROUTE_DECORATORS = {
    "python": {
        "flask": ["@app.route", "@app.get", "@app.post", "@app.put", "@app.delete", "@app.patch"],
        "fastapi": ["@app.get", "@app.post", "@app.put", "@app.delete", "@app.patch", "@router.get", "@router.post"],
        "django": ["@login_required", "@require_http_methods", "@require_GET", "@require_POST"],
        "tornado": ["@tornado.web.authenticated"],
        "falcon": ["@falcon.before", "@falcon.after"],
    },
    "javascript": {
        "express": ["app.get", "app.post", "app.put", "app.delete", "app.use", "router.get", "router.post"],
        "fastify": ["fastify.get", "fastify.post", "fastify.put", "fastify.delete"],
        "koa": ["router.get", "router.post", "router.put", "router.delete"],
    }
}


def _has_route_decorator(node: Dict) -> bool:
    """Check if node's metadata indicates a framework route."""
    meta = node.get("meta", "{}")
    if isinstance(meta, str):
        try:
            import json
            meta = json.loads(meta)
        except:
            meta = {}
    
    if not meta:
        return False
    
    decorators = meta.get("decorators", [])
    if not decorators:
        return False
    
    for dec in decorators:
        dec_str = str(dec).lower()
        for framework, patterns in ROUTE_DECORATORS.get("python", {}).items():
            for pat in patterns:
                if pat.lower() in dec_str:
                    return True
        for framework, patterns in ROUTE_DECORATORS.get("javascript", {}).items():
            for pat in patterns:
                if pat.lower() in dec_str:
                    return True
    
    return False


def is_entry_point(node: Dict) -> bool:
    """Heuristic: is this node an entry point?"""
    name = node["name"].lower()
    ntype = node["type"]
    
    if ntype in ("function", "method"):
        if name in ENTRY_PATTERNS["function"]:
            return True
        if ntype == "method" and name in ENTRY_PATTERNS["method"]:
            return True
        # Test functions
        if name.startswith("test_"):
            return True
        # CLI commands / click decorators
        meta = node.get("meta", "{}")
        if isinstance(meta, str):
            try:
                import json
                meta = json.loads(meta)
            except:
                meta = {}
        if meta and meta.get("is_cli_command"):
            return True
        # Framework routes
        if _has_route_decorator(node):
            return True
        # Common framework handler patterns by name
        if any(pat in name for pat in ["handler", "controller", "endpoint", "route_", "view_"]):
            return True
    
    return False


def build_flows(db: GraphDB, max_depth: int = 6) -> int:
    """Build execution flows from all entry points. Returns count of flows created."""
    db.delete_all_flows()
    
    # Get all nodes
    cur = db.conn.execute(
        "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id"
    )
    all_nodes = {r["id"]: dict(r) for r in cur.fetchall()}
    
    # Find entry points
    entry_points = [n for n in all_nodes.values() if is_entry_point(n)]
    
    # If no obvious entry points, use top connected nodes as proxies
    if not entry_points:
        # Find nodes with no incoming 'calls' edges but with outgoing calls
        cur = db.conn.execute(
            """
            SELECT n.*, f.path as file_path,
                   (SELECT COUNT(*) FROM edges WHERE target_id = n.id AND type = 'calls') as in_degree,
                   (SELECT COUNT(*) FROM edges WHERE source_id = n.id AND type = 'calls') as out_degree
            FROM nodes n JOIN files f ON n.file_id = f.id
            HAVING out_degree > 0
            ORDER BY out_degree DESC LIMIT 20
            """
        )
        entry_points = [dict(r) for r in cur.fetchall()]
    
    # Build adjacency list for call edges (with resolved targets)
    adj: Dict[int, List[Dict]] = {}
    cur = db.conn.execute(
        "SELECT * FROM edges WHERE type = 'calls' AND target_id IS NOT NULL"
    )
    for row in cur.fetchall():
        adj.setdefault(row["source_id"], []).append(dict(row))
    
    flows_created = 0
    
    for entry in entry_points:
        entry_id = entry["id"]
        flow_nodes: List[int] = []
        flow_edges: List[Tuple[int, int]] = []
        visited: Set[int] = set()
        files_in_flow: Set[str] = set()
        queue = deque([(entry_id, 0)])
        
        while queue:
            node_id, depth = queue.popleft()
            if node_id in visited or depth > max_depth:
                continue
            visited.add(node_id)
            
            node = all_nodes.get(node_id)
            if not node:
                continue
            
            flow_nodes.append(node_id)
            files_in_flow.add(node["file_path"])
            
            for edge in adj.get(node_id, []):
                target_id = edge["target_id"]
                flow_edges.append((node_id, target_id))
                if target_id not in visited:
                    queue.append((target_id, depth + 1))
        
        if len(flow_nodes) < 2:
            continue  # Skip trivial flows
        
        # Build step descriptions
        steps = []
        for nid in flow_nodes:
            n = all_nodes[nid]
            steps.append({
                "id": nid,
                "name": n["name"],
                "type": n["type"],
                "file": n["file_path"],
                "line": n["start_line"],
                "signature": n.get("signature", "")[:100]
            })
        
        # Criticality = number of unique files + node count / 100
        criticality = len(files_in_flow) + len(flow_nodes) / 100.0
        
        flow_name = f"{entry['type']}:{entry['name']} ({entry['file_path']})"
        
        # Calculate depth from BFS traversal
        max_depth = 0
        visited_depths = {}
        queue_depth = deque([(entry_id, 0)])
        visited_d = set()
        while queue_depth:
            nid, d = queue_depth.popleft()
            if nid in visited_d:
                continue
            visited_d.add(nid)
            max_depth = max(max_depth, d)
            for edge in adj.get(nid, []):
                tgt = edge["target_id"]
                if tgt not in visited_d:
                    queue_depth.append((tgt, d + 1))

        db.insert_flow(
            name=flow_name,
            entry_point_id=entry_id,
            steps=json.dumps(steps),
            depth=max_depth,
            node_count=len(flow_nodes),
            file_count=len(files_in_flow),
            criticality=criticality
        )
        flows_created += 1
    
    return flows_created
