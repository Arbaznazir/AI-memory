"""Dead code detection: find symbols with zero incoming references."""
from typing import Dict, List

from .db import GraphDB


def find_dead_code(db: GraphDB, min_lines: int = 0) -> List[Dict]:
    """Find functions/classes/methods with no incoming call/inherit/implements edges.
    
    Filters out:
    - Test functions (test_*)
    - Main/entry points
    - Symbols in __init__.py (often re-exports)
    - Very short symbols (< 3 lines)
    """
    cur = db.conn.execute(
        """
        SELECT n.*, f.path as file_path, f.language,
               (n.end_line - n.start_line + 1) as symbol_lines
        FROM nodes n
        JOIN files f ON n.file_id = f.id
        WHERE n.type IN ('function', 'method', 'class')
          AND (SELECT COUNT(*) FROM edges WHERE target_id = n.id) = 0
        ORDER BY symbol_lines DESC
        """
    )
    
    results = []
    for row in cur.fetchall():
        node = dict(row)
        name = node["name"]
        
        # Skip test functions
        if name.startswith("test_") or name.startswith("Test"):
            continue
        
        # Skip entry point names
        entry_names = {"main", "__main__", "run", "serve", "start", "init", "cli", "handler"}
        if name.lower() in entry_names:
            continue
        
        # Skip __init__ and __str__ etc (dunder methods are called implicitly)
        if name.startswith("__") and name.endswith("__"):
            continue
        
        # Skip re-exports in __init__.py
        if "__init__.py" in node.get("file_path", ""):
            continue
        
        # Skip very short functions
        if node.get("symbol_lines", 0) < min_lines:
            continue
        
        results.append(node)
    
    return results
