"""Community detection: group symbols into logical modules/clusters.

Uses directory structure as primary clustering + graph connectivity refinement.
"""
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .db import GraphDB


def build_communities(db: GraphDB, root: Path) -> int:
    """Build communities from directory structure and import edges."""
    db.delete_all_communities()
    
    # Get all nodes with their file paths
    cur = db.conn.execute(
        "SELECT n.id, n.type, n.name, f.language, f.path as file_path "
        "FROM nodes n JOIN files f ON n.file_id = f.id"
    )
    nodes = [dict(r) for r in cur.fetchall()]
    
    if not nodes:
        return 0
    
    # Phase 1: Directory-based clustering
    dir_clusters: Dict[str, List[int]] = defaultdict(list)
    for n in nodes:
        rel_path = Path(n["file_path"]).relative_to(root)
        # Use parent directory as primary cluster key
        dir_key = str(rel_path.parent) if rel_path.parent != Path(".") else "root"
        dir_clusters[dir_key].append(n["id"])
    
    # Phase 2: Merge small clusters using import/call edges
    # Build adjacency (undirected for clustering)
    adj: Dict[int, Set[int]] = defaultdict(set)
    cur = db.conn.execute(
        "SELECT source_id, target_id FROM edges WHERE target_id IS NOT NULL"
    )
    for row in cur.fetchall():
        adj[row["source_id"]].add(row["target_id"])
        adj[row["target_id"]].add(row["source_id"])
    
    # Union-Find for community merging
    parent = {n["id"]: n["id"] for n in nodes}
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    
    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py
    
    # Union all nodes in same directory
    for dir_key, node_ids in dir_clusters.items():
        first = node_ids[0]
        for nid in node_ids[1:]:
            union(first, nid)
    
    # Union nodes connected by edges across directories (strong coupling)
    for src, targets in adj.items():
        for tgt in targets:
            union(src, tgt)
    
    # Group by final parent
    communities: Dict[int, Set[int]] = defaultdict(set)
    for n in nodes:
        communities[find(n["id"])].add(n["id"])
    
    # Create community records
    communities_created = 0
    for root_node, members in communities.items():
        if len(members) < 2:
            continue  # Skip single-node communities
        
        member_nodes = [n for n in nodes if n["id"] in members]
        
        # Determine dominant language
        lang_counts: Dict[str, int] = defaultdict(int)
        for n in member_nodes:
            lang = n.get("language", "unknown")
            if lang:
                lang_counts[lang] += 1
        dominant_lang = max(lang_counts, key=lang_counts.get) if lang_counts else None
        
        # Determine directory name for community label
        dirs = set()
        for n in member_nodes:
            rel = Path(n["file_path"]).relative_to(root)
            dirs.add(str(rel.parent) if rel.parent != Path(".") else "root")
        
        name = "/".join(sorted(dirs)[:3])
        if len(dirs) > 3:
            name += f" (+{len(dirs)-3} more)"
        
        # Calculate cohesion = internal edges / total edges for members
        member_set = set(members)
        internal_edges = 0
        total_edges = 0
        for n in member_nodes:
            nid = n["id"]
            for tgt in adj.get(nid, set()):
                total_edges += 1
                if tgt in member_set:
                    internal_edges += 1
        
        cohesion = internal_edges / total_edges if total_edges > 0 else 0.0
        
        # Summary: top symbols by type
        summary_parts = []
        funcs = [n["name"] for n in member_nodes if n["type"] in ("function", "method")][:5]
        classes = [n["name"] for n in member_nodes if n["type"] == "class"][:5]
        if classes:
            summary_parts.append(f"Classes: {', '.join(classes)}")
        if funcs:
            summary_parts.append(f"Functions: {', '.join(funcs)}")
        summary = "; ".join(summary_parts)
        
        comm_id = db.insert_community(
            name=name,
            dominant_language=dominant_lang,
            size=len(members),
            cohesion=round(cohesion, 2),
            summary=summary
        )
        
        for nid in members:
            db.add_community_member(nid, comm_id)
        
        communities_created += 1
    
    return communities_created
