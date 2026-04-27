"""Reverse call graph: find all symbols that call/reference a given symbol."""
from typing import Dict, List, Optional

from .db import GraphDB


def find_callers(db: GraphDB, symbol_name: str, max_depth: int = 3) -> List[Dict]:
    """Find all symbols that directly call or reference the given symbol.
    
    Searches by qualified_name first, then falls back to simple name match.
    Returns list of caller nodes with edge metadata.
    """
    # Find target node(s)
    cur = db.conn.execute(
        "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
        "WHERE n.qualified_name = ? OR n.name = ?",
        (symbol_name, symbol_name)
    )
    targets = [dict(r) for r in cur.fetchall()]
    
    if not targets:
        return []
    
    target_ids = [t["id"] for t in targets]
    
    # Find all edges where target is the callee
    placeholders = ",".join(["?"] * len(target_ids))
    query = f"""
        SELECT e.*, src.name as caller_name, src.qualified_name as caller_qname,
               src.type as caller_type, f.path as caller_file,
               src.start_line as caller_line
        FROM edges e
        JOIN nodes src ON e.source_id = src.id
        JOIN files f ON src.file_id = f.id
        WHERE e.target_id IN ({placeholders}) AND e.type = 'calls'
        ORDER BY f.path, src.start_line
    """
    cur = db.conn.execute(query, tuple(target_ids))
    callers = [dict(r) for r in cur.fetchall()]
    
    # Also include references via imports
    query_imports = f"""
        SELECT e.*, src.name as caller_name, src.qualified_name as caller_qname,
               src.type as caller_type, f.path as caller_file,
               src.start_line as caller_line
        FROM edges e
        JOIN nodes src ON e.source_id = src.id
        JOIN files f ON src.file_id = f.id
        WHERE e.target_id IN ({placeholders}) AND e.type = 'imports'
        ORDER BY f.path, src.start_line
    """
    cur = db.conn.execute(query_imports, tuple(target_ids))
    callers.extend([dict(r) for r in cur.fetchall()])
    
    return callers


def build_reverse_call_graph(db: GraphDB, symbol_name: str, max_depth: int = 3) -> Dict:
    """Build reverse call graph up to max_depth hops.
    
    Returns tree: {node_id, name, type, file, callers: [recursive]}
    """
    from collections import deque
    
    # Resolve initial target
    cur = db.conn.execute(
        "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
        "WHERE n.qualified_name = ? OR n.name = ? LIMIT 1",
        (symbol_name, symbol_name)
    )
    target_row = cur.fetchone()
    if not target_row:
        return {"error": f"Symbol '{symbol_name}' not found"}
    
    target = dict(target_row)
    visited = set()
    queue = deque([(target["id"], 0, None)])
    
    nodes_by_id: Dict[int, Dict] = {}
    edges: List[Dict] = []
    
    while queue:
        node_id, depth, via = queue.popleft()
        if node_id in visited or depth > max_depth:
            continue
        visited.add(node_id)
        
        # Get node info
        cur = db.conn.execute(
            "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id WHERE n.id = ?",
            (node_id,)
        )
        row = cur.fetchone()
        if row:
            nodes_by_id[node_id] = dict(row)
        
        # Find callers (reverse direction)
        cur = db.conn.execute(
            """
            SELECT e.*, src.id as caller_id, src.name as caller_name,
                   src.type as caller_type, f.path as caller_file
            FROM edges e
            JOIN nodes src ON e.source_id = src.id
            JOIN files f ON src.file_id = f.id
            WHERE e.target_id = ? AND e.type = 'calls'
            """,
            (node_id,)
        )
        for r in cur.fetchall():
            caller_id = r["caller_id"]
            edges.append({
                "from_id": caller_id,
                "to_id": node_id,
                "from_name": r["caller_name"],
                "to_name": nodes_by_id.get(node_id, {}).get("name", ""),
                "line": r["line"]
            })
            if caller_id not in visited:
                queue.append((caller_id, depth + 1, node_id))
    
    return {
        "target": target,
        "nodes": list(nodes_by_id.values()),
        "edges": edges,
        "depth": max_depth,
    }
