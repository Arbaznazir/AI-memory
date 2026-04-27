"""Detect public API surface: symbols exported from package entry points.

For Python: __init__.py re-exports, __all__ lists
For JS/TS: index.js exports, module.exports
For Rust: pub use re-exports in lib.rs
"""
import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .db import GraphDB


def _parse_python_all(code: str) -> List[str]:
    """Parse __all__ list from Python source."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    
    exports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                exports.append(elt.value)
                            elif isinstance(elt, ast.Str):
                                exports.append(elt.s)
    return exports


def _parse_js_exports(code: str) -> List[str]:
    """Parse JS/TS export statements."""
    exports = []
    
    # export { foo, bar } from './module'
    # export { foo, bar }
    pattern = r'export\s*\{([^}]+)\}'
    for match in re.finditer(pattern, code):
        names = match.group(1)
        for name in names.split(','):
            name = name.strip().split(' as ')[0].split(':')[0].strip()
            if name:
                exports.append(name)
    
    # export default Foo
    default_pattern = r'export\s+default\s+(\w+)'
    for match in re.finditer(default_pattern, code):
        exports.append(match.group(1))
    
    # export const foo = ...
    # export function foo() ...
    # export class Foo ...
    decl_pattern = r'export\s+(?:const|let|var|function|class|interface|type)\s+(\w+)'
    for match in re.finditer(decl_pattern, code):
        exports.append(match.group(1))
    
    # module.exports = { foo, bar }
    mod_pattern = r'module\.exports\s*=\s*\{([^}]+)\}'
    for match in re.finditer(mod_pattern, code):
        names = match.group(1)
        for name in names.split(','):
            name = name.strip().split(':')[0].strip()
            if name:
                exports.append(name)
    
    return list(set(exports))


def _parse_rust_pub_use(code: str) -> List[str]:
    """Parse Rust pub use re-exports."""
    exports = []
    # pub use crate::foo::bar;
    # pub use self::foo::Bar;
    pattern = r'pub\s+use\s+([\w::]+)(?:\s+as\s+(\w+))?\s*;'
    for match in re.finditer(pattern, code):
        full_path = match.group(1)
        alias = match.group(2)
        if alias:
            exports.append(alias)
        else:
            # Last segment is the exported name
            parts = full_path.split('::')
            if parts:
                exports.append(parts[-1])
    return exports


def detect_api_surface(db: GraphDB, root: Path) -> Dict[str, List[Dict]]:
    """Detect public API surface by language."""
    result: Dict[str, List[Dict]] = {"python": [], "javascript": [], "rust": []}
    
    # Python: __init__.py files
    for init_file in root.rglob("__init__.py"):
        rel_path = init_file.relative_to(root)
        try:
            code = init_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        
        exports = _parse_python_all(code)
        if not exports:
            # No __all__, look for imports that might be re-exports
            continue
        
        # Find these symbols in the graph
        for name in exports:
            cur = db.conn.execute(
                "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
                "WHERE n.name = ? AND f.path LIKE ?",
                (name, f"%{rel_path.parent}%")
            )
            for row in cur.fetchall():
                node = dict(row)
                node["package"] = str(rel_path.parent)
                node["export_type"] = "__all__"
                result["python"].append(node)
    
    # JavaScript/TypeScript: index.js, index.ts
    for index_file in list(root.rglob("index.js")) + list(root.rglob("index.ts")):
        rel_path = index_file.relative_to(root)
        try:
            code = index_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        
        exports = _parse_js_exports(code)
        for name in exports:
            cur = db.conn.execute(
                "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
                "WHERE n.name = ? AND f.path LIKE ?",
                (name, f"%{rel_path.parent}%")
            )
            for row in cur.fetchall():
                node = dict(row)
                node["package"] = str(rel_path.parent)
                node["export_type"] = "export"
                result["javascript"].append(node)
    
    # Rust: lib.rs
    for lib_file in root.rglob("lib.rs"):
        rel_path = lib_file.relative_to(root)
        try:
            code = lib_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        
        exports = _parse_rust_pub_use(code)
        for name in exports:
            cur = db.conn.execute(
                "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
                "WHERE n.name = ? AND f.path LIKE ?",
                (name, f"%{rel_path.parent}%")
            )
            for row in cur.fetchall():
                node = dict(row)
                node["package"] = str(rel_path.parent)
                node["export_type"] = "pub use"
                result["rust"].append(node)
    
    return result


def format_api_surface(surface: Dict[str, List[Dict]]) -> str:
    """Format API surface as markdown."""
    lines = ["# Public API Surface", ""]
    
    total = sum(len(v) for v in surface.values())
    if total == 0:
        lines.append("No public exports detected. Ensure the codebase has `__init__.py`, `index.js`, or `lib.rs` with explicit exports.\n")
        return "\n".join(lines)
    
    lines.append(f"**Total public symbols:** {total}\n")
    
    for lang, symbols in surface.items():
        if not symbols:
            continue
        
        lines.append(f"## {lang.title()} ({len(symbols)})")
        
        # Group by package
        by_package: Dict[str, List[Dict]] = {}
        for sym in symbols:
            pkg = sym.get("package", "unknown")
            by_package.setdefault(pkg, []).append(sym)
        
        for pkg, syms in sorted(by_package.items()):
            lines.append(f"### {pkg}")
            for sym in syms:
                sig = str(sym.get("signature", ""))[:60]
                lines.append(f"- `{sym['type']}` **{sym['name']}** `{sym.get('export_type', '')}` ({sym['file_path']}:L{sym['start_line']})")
                if sym.get("doc"):
                    doc = str(sym["doc"])[:80].replace("\n", " ")
                    lines.append(f"  - {doc}")
            lines.append("")
    
    return "\n".join(lines)
