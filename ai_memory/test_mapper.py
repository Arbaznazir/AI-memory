"""Map test functions to their corresponding implementation functions/classes.

Heuristics:
- test_foo -> foo
- TestFoo -> Foo (class)
- test_get_user -> get_user
- test_module_foo -> foo in module (less reliable)
"""
import re
from typing import Dict, List, Optional

from .db import GraphDB


def _normalize_test_name(test_name: str) -> str:
    """Convert test name to likely implementation name."""
    name = test_name
    if name.startswith("test_"):
        name = name[5:]
    elif name.startswith("Test"):
        name = name[4:]
    return name


def find_test_targets(db: GraphDB, test_node: Dict) -> List[Dict]:
    """Find likely implementation functions/classes for a given test."""
    test_name = test_node["name"]
    target_name = _normalize_test_name(test_name)
    
    # Search for exact name match in non-test files
    cur = db.conn.execute(
        """
        SELECT n.*, f.path as file_path
        FROM nodes n
        JOIN files f ON n.file_id = f.id
        WHERE n.name = ?
          AND n.type IN ('function', 'method', 'class')
          AND f.path NOT LIKE '%test%'
          AND f.path NOT LIKE '%spec%'
        """,
        (target_name,)
    )
    results = [dict(r) for r in cur.fetchall()]
    
    # If no exact match, try partial
    if not results and len(target_name) > 3:
        cur = db.conn.execute(
            """
            SELECT n.*, f.path as file_path
            FROM nodes n
            JOIN files f ON n.file_id = f.id
            WHERE n.name LIKE ?
              AND n.type IN ('function', 'method', 'class')
              AND f.path NOT LIKE '%test%'
              AND f.path NOT LIKE '%spec%'
            LIMIT 5
            """,
            (f"%{target_name}%",)
        )
        results = [dict(r) for r in cur.fetchall()]
    
    return results


def map_all_tests(db: GraphDB) -> List[Dict]:
    """Map all test functions to their implementation targets."""
    # Find all test-like nodes
    cur = db.conn.execute(
        """
        SELECT n.*, f.path as file_path
        FROM nodes n
        JOIN files f ON n.file_id = f.id
        WHERE (n.name LIKE 'test_%' OR n.name LIKE 'Test%' OR f.path LIKE '%test%')
          AND n.type IN ('function', 'method', 'class')
        """
    )
    tests = [dict(r) for r in cur.fetchall()]
    
    mappings = []
    for test in tests:
        targets = find_test_targets(db, test)
        if targets:
            mappings.append({
                "test": test,
                "targets": targets
            })
    
    return mappings


def format_test_map(mappings: List[Dict]) -> str:
    """Format test mappings as markdown."""
    if not mappings:
        return "# Test-to-Code Mapping\n\nNo test functions found or no targets mapped.\n"
    
    lines = ["# Test-to-Code Mapping", f"\n**Tests mapped:** {len(mappings)}\n"]
    
    for m in mappings:
        test = m["test"]
        targets = m["targets"]
        lines.append(f"## {test['name']}")
        lines.append(f"- **Test:** `{test['file_path']}`:L{test['start_line']} ({test['type']})")
        lines.append("- **Implements:**")
        for t in targets:
            lines.append(f"  - `{t['type']}` **{t['name']}** ({t['file_path']}:L{t['start_line']})")
        lines.append("")
    
    return "\n".join(lines)
