"""Circular dependency detection in import and call graphs."""
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict

from .db import GraphDB


def find_cycles(db: GraphDB, edge_type: str = "imports", max_length: int = 10) -> List[List[Dict]]:
    """Find all cycles in the graph up to max_length.
    
    Returns list of cycles, each cycle is a list of node dicts.
    """
    # Build adjacency list
    cur = db.conn.execute(
        "SELECT source_id, target_id FROM edges WHERE type = ? AND target_id IS NOT NULL",
        (edge_type,)
    )
    adj: Dict[int, List[int]] = defaultdict(list)
    for row in cur.fetchall():
        adj[row["source_id"]].append(row["target_id"])
    
    cycles: List[List[int]] = []
    
    def dfs(node: int, path: List[int], visited: Set[int]):
        if len(path) > max_length:
            return
        for neighbor in adj.get(node, []):
            if neighbor == path[0] and len(path) >= 2:
                # Found cycle
                cycles.append(path.copy())
            elif neighbor not in visited and neighbor not in path:
                visited.add(neighbor)
                path.append(neighbor)
                dfs(neighbor, path, visited)
                path.pop()
                visited.discard(neighbor)
    
    all_nodes = set(adj.keys())
    for start in all_nodes:
        dfs(start, [start], {start})
    
    # Deduplicate cycles (same cycle, different rotation)
    unique_cycles: List[Tuple[int, ...]] = []
    seen: Set[frozenset] = set()
    for cycle in cycles:
        # Normalize: start from smallest node_id
        min_idx = cycle.index(min(cycle))
        normalized = tuple(cycle[min_idx:] + cycle[:min_idx])
        cycle_set = frozenset(normalized)
        if cycle_set not in seen:
            seen.add(cycle_set)
            unique_cycles.append(normalized)
    
    # Resolve node details
    result = []
    for cycle_ids in unique_cycles:
        cycle_nodes = []
        for nid in cycle_ids:
            cur = db.conn.execute(
                "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id WHERE n.id = ?",
                (nid,)
            )
            row = cur.fetchone()
            if row:
                cycle_nodes.append(dict(row))
        if cycle_nodes:
            result.append(cycle_nodes)
    
    return result


def find_all_cycles(db: GraphDB, max_length: int = 10) -> Dict[str, List[List[Dict]]]:
    """Find cycles for both imports and calls."""
    return {
        "imports": find_cycles(db, "imports", max_length),
        "calls": find_cycles(db, "calls", max_length),
        "inherits": find_cycles(db, "inherits", max_length),
    }


def format_cycles(cycles: Dict[str, List[List[Dict]]]) -> str:
    """Format cycles as markdown."""
    lines = ["# Circular Dependencies", ""]
    
    total = sum(len(c) for c in cycles.values())
    if total == 0:
        lines.append("**No circular dependencies found.**")
        return "\n".join(lines)
    
    lines.append(f"**Total cycles found:** {total}\n")
    
    for edge_type, cycle_list in cycles.items():
        if not cycle_list:
            continue
        lines.append(f"## {edge_type.title()} Cycles ({len(cycle_list)})")
        for i, cycle in enumerate(cycle_list, 1):
            cycle_str = " → ".join(
                f"**{n['name']}** ({n.get('file_path', 'unknown').split('/')[-1]})"
                for n in cycle
            )
            lines.append(f"{i}. {cycle_str} → **{cycle[0]['name']}**")
        lines.append("")
    
    return "\n".join(lines)
