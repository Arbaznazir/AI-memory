"""Full inheritance chain tracing for classes."""
from typing import Dict, List, Optional, Set

from .db import GraphDB


def find_class(db: GraphDB, class_name: str) -> Optional[Dict]:
    """Find a class node by name or qualified name."""
    cur = db.conn.execute(
        "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
        "WHERE n.type = 'class' AND (n.name = ? OR n.qualified_name = ?)",
        (class_name, class_name)
    )
    row = cur.fetchone()
    return dict(row) if row else None


def get_direct_parents(db: GraphDB, node_id: int) -> List[Dict]:
    """Get direct parent classes via inherits edges."""
    cur = db.conn.execute(
        """
        SELECT n.*, f.path as file_path
        FROM edges e
        JOIN nodes n ON e.target_id = n.id
        JOIN files f ON n.file_id = f.id
        WHERE e.source_id = ? AND e.type = 'inherits'
        """,
        (node_id,)
    )
    return [dict(r) for r in cur.fetchall()]


def get_direct_children(db: GraphDB, node_id: int) -> List[Dict]:
    """Get direct child classes (classes that inherit from this one)."""
    cur = db.conn.execute(
        """
        SELECT n.*, f.path as file_path
        FROM edges e
        JOIN nodes n ON e.source_id = n.id
        JOIN files f ON n.file_id = f.id
        WHERE e.target_id = ? AND e.type = 'inherits'
        """,
        (node_id,)
    )
    return [dict(r) for r in cur.fetchall()]


def get_ancestors(db: GraphDB, node_id: int, visited: Optional[Set[int]] = None) -> List[Dict]:
    """Get all ancestor classes (recursive)."""
    if visited is None:
        visited = set()
    
    if node_id in visited:
        return []
    visited.add(node_id)
    
    parents = get_direct_parents(db, node_id)
    result = []
    for p in parents:
        result.append(p)
        result.extend(get_ancestors(db, p["id"], visited))
    return result


def get_descendants(db: GraphDB, node_id: int, visited: Optional[Set[int]] = None) -> List[Dict]:
    """Get all descendant classes (recursive)."""
    if visited is None:
        visited = set()
    
    if node_id in visited:
        return []
    visited.add(node_id)
    
    children = get_direct_children(db, node_id)
    result = []
    for c in children:
        result.append(c)
        result.extend(get_descendants(db, c["id"], visited))
    return result


def get_inheritance_chain(db: GraphDB, class_name: str) -> Dict:
    """Get full inheritance chain for a class: ancestors, descendants, siblings."""
    node = find_class(db, class_name)
    if not node:
        return {"error": f"Class '{class_name}' not found"}
    
    node_id = node["id"]
    
    # Ancestors (parents, grandparents, etc.)
    ancestors = get_ancestors(db, node_id)
    
    # Descendants (children, grandchildren, etc.)
    descendants = get_descendants(db, node_id)
    
    # Direct parents
    parents = get_direct_parents(db, node_id)
    
    # Siblings (share at least one parent)
    siblings = []
    if parents:
        parent_ids = [p["id"] for p in parents]
        placeholders = ",".join(["?"] * len(parent_ids))
        cur = db.conn.execute(
            f"""
            SELECT DISTINCT n.*, f.path as file_path
            FROM edges e
            JOIN nodes n ON e.source_id = n.id
            JOIN files f ON n.file_id = f.id
            WHERE e.target_id IN ({placeholders}) AND e.type = 'inherits'
              AND n.id != ?
            """,
            tuple(parent_ids + [node_id])
        )
        siblings = [dict(r) for r in cur.fetchall()]
    
    # Build chain visualization
    chain = []
    if ancestors:
        # Reverse to show top-down
        for a in reversed(ancestors):
            chain.append({"direction": "↑", "node": a})
    chain.append({"direction": "●", "node": node})
    for d in descendants:
        chain.append({"direction": "↓", "node": d})
    
    return {
        "class": node,
        "parents": parents,
        "ancestors": ancestors,
        "children": get_direct_children(db, node_id),
        "descendants": descendants,
        "siblings": siblings,
        "chain": chain,
    }


def format_inheritance_chain(result: Dict) -> str:
    """Format inheritance chain as markdown."""
    if "error" in result:
        return f"# Error\n\n{result['error']}\n"
    
    node = result["class"]
    lines = [f"# Inheritance Chain: {node['name']}", ""]
    lines.append(f"**Defined in:** `{node['file_path']}`:L{node['start_line']}\n")
    
    # Chain visualization
    if result["chain"]:
        lines.append("## Hierarchy")
        for item in result["chain"]:
            n = item["node"]
            indent = "  " * (result["chain"].index(item))
            lines.append(f"{indent}{item['direction']} `{n['type']}` **{n['name']}** ({n.get('file_path', '').split('/')[-1]})")
        lines.append("")
    
    # Summary stats
    lines.append("## Summary")
    lines.append(f"- **Parents:** {len(result['parents'])}")
    lines.append(f"- **Ancestors:** {len(result['ancestors'])}")
    lines.append(f"- **Children:** {len(result['children'])}")
    lines.append(f"- **Descendants:** {len(result['descendants'])}")
    lines.append(f"- **Siblings:** {len(result['siblings'])}")
    lines.append("")
    
    # Details sections
    if result["parents"]:
        lines.append("### Direct Parents")
        for p in result["parents"]:
            lines.append(f"- `{p['name']}` ({p['file_path']}:L{p['start_line']})")
        lines.append("")
    
    if result["children"]:
        lines.append("### Direct Children")
        for c in result["children"]:
            lines.append(f"- `{c['name']}` ({c['file_path']}:L{c['start_line']})")
        lines.append("")
    
    if result["siblings"]:
        lines.append("### Siblings (Same Parents)")
        for s in result["siblings"]:
            lines.append(f"- `{s['name']}` ({s['file_path']}:L{s['start_line']})")
        lines.append("")
    
    return "\n".join(lines)
