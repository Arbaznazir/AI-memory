"""Cross-file import resolution.

Parses import statements per-language, resolves relative paths,
and links edges to actual symbol definitions across files.
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
import json

from .db import GraphDB


def _resolve_relative_path(from_file: str, import_path: str, root: Path) -> Optional[Path]:
    """Resolve a relative import path to an actual file."""
    from_dir = Path(from_file).parent
    target = from_dir / import_path
    
    # Try exact file
    if target.exists() and target.is_file():
        return target
    
    # Try with extensions
    for ext in [".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".java", ".cs"]:
        candidate = Path(str(target) + ext)
        if candidate.exists() and candidate.is_file():
            return candidate
    
    # Try __init__.py / index.js
    if target.is_dir():
        for init in ["__init__.py", "index.js", "index.ts", "mod.rs", "lib.rs"]:
            candidate = target / init
            if candidate.exists():
                return candidate
    
    return None


def _parse_python_import(node_text: str, from_file: str, root: Path) -> List[Tuple[str, Optional[str], Optional[Path]]]:
    """Parse Python import, return list of (name, alias, resolved_path)."""
    results = []
    text = node_text.strip()
    
    if text.startswith("from "):
        # from x.y import a, b
        parts = text.split(" import ")
        if len(parts) == 2:
            module_path = parts[0].replace("from ", "").strip().replace(".", "/")
            names_part = parts[1].strip()
            # Strip parentheses for multi-line imports
            names_part = names_part.replace("(", "").replace(")", "").strip()
            
            resolved = None
            if not module_path.startswith("/"):  # not stdlib absolute
                # Try relative
                if parts[0].replace("from ", "").strip().startswith("."):
                    resolved = _resolve_relative_path(from_file, module_path, root)
                else:
                    # Try from root (simplified - real projects need PYTHONPATH)
                    root_target = root / module_path
                    if root_target.exists() or (root_target.parent / (root_target.name + ".py")).exists():
                        resolved = _resolve_relative_path(str(root), module_path, root)
            
            for name in names_part.split(","):
                name = name.strip().split(" as ")[0].strip()
                if name:
                    results.append((name, None, resolved))
    
    elif text.startswith("import "):
        # import x.y or import x as y
        rest = text.replace("import ", "").strip()
        for part in rest.split(","):
            part = part.strip()
            name = part.split(" as ")[0].strip().split(".")[0]
            if name:
                results.append((name, None, None))
    
    return results


def _parse_js_import(node_text: str, from_file: str, root: Path) -> List[Tuple[str, Optional[str], Optional[Path]]]:
    """Parse JS/TS import, return list of (name, alias, resolved_path)."""
    results = []
    text = node_text.strip()
    
    # Extract from path
    from_path = None
    if "from" in text:
        parts = text.split("from")
        if len(parts) >= 2:
            path_part = parts[-1].strip().strip(";'\"`")
            if path_part.startswith("."):
                from_path = _resolve_relative_path(from_file, path_part, root)
    
    # Extract imported names
    if "{" in text and "}" in text:
        # Named imports: import { foo, bar } from './x'
        brace_start = text.find("{")
        brace_end = text.find("}")
        if brace_start != -1 and brace_end != -1:
            names_text = text[brace_start + 1:brace_end]
            for name_str in names_text.split(","):
                name_str = name_str.strip()
                if name_str:
                    # Handle "foo as bar" or "foo: bar"
                    name = name_str
                    if " as " in name_str:
                        name = name_str.split(" as ")[0].strip()
                    elif ":" in name_str:
                        name = name_str.split(":")[0].strip()
                    results.append((name, None, from_path))
    elif "import * as" in text:
        # import * as foo from './x'
        parts = text.split("import * as")
        if len(parts) == 2:
            name = parts[1].split("from")[0].strip()
            results.append((name, None, from_path))
    elif "import" in text:
        # import foo from './x' or import './x'
        # Simple default import
        after_import = text.replace("import", "", 1).strip()
        # Check if there's a name before 'from'
        if "from" in after_import:
            name_part = after_import.split("from")[0].strip()
            if name_part and not name_part.startswith("{") and not name_part.startswith("*"):
                results.append((name_part, None, from_path))
    
    return results


def resolve_imports(db: GraphDB, root: Path):
    """Post-process all import edges to resolve cross-file targets."""
    
    # Build lookup: (file_path, name) -> node_id
    file_symbols: Dict[Tuple[str, str], int] = {}
    cur = db.conn.execute(
        "SELECT n.id, n.name, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id"
    )
    for row in cur.fetchall():
        file_symbols[(row["file_path"], row["name"])] = row["id"]
    
    # Get all import edges with unresolved target_id
    cur = db.conn.execute(
        "SELECT e.id, e.source_id, e.target_name, n.file_id, f.path as source_file_path, f.language "
        "FROM edges e JOIN nodes n ON e.source_id = n.id JOIN files f ON n.file_id = f.id "
        "WHERE e.type = 'imports' AND e.target_id IS NULL"
    )
    
    unresolved = [dict(r) for r in cur.fetchall()]
    
    resolved_count = 0
    for imp in unresolved:
        source_file = imp["source_file_path"]
        lang = imp["language"]
        target_name = imp["target_name"]
        
        resolved_path = None
        imported_names = []
        
        if lang == "python":
            imported_names = _parse_python_import(target_name, source_file, root)
        elif lang in ("javascript", "typescript"):
            imported_names = _parse_js_import(target_name, source_file, root)
        else:
            # For other languages, just store the raw import
            continue
        
        # Try to resolve each imported name
        for name, alias, path in imported_names:
            if path:
                resolved_path = str(path)
                # Look up the symbol in the target file
                key = (resolved_path, name)
                if key in file_symbols:
                    node_id = file_symbols[key]
                    db.conn.execute(
                        "UPDATE edges SET target_id = ?, target_file = ? WHERE id = ?",
                        (node_id, resolved_path, imp["id"])
                    )
                    resolved_count += 1
                else:
                    # Update with at least the file
                    db.conn.execute(
                        "UPDATE edges SET target_file = ? WHERE id = ?",
                        (resolved_path, imp["id"])
                    )
    
    db.conn.commit()
    return resolved_count


def resolve_calls(db: GraphDB, root: Path):
    """Post-process call edges to resolve method calls on imported objects."""
    # Build lookup by qualified name and simple name
    qname_to_id: Dict[str, int] = {}
    name_to_ids: Dict[str, List[int]] = {}
    
    cur = db.conn.execute(
        "SELECT n.id, n.name, n.qualified_name, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id"
    )
    for row in cur.fetchall():
        if row["qualified_name"]:
            qname_to_id[row["qualified_name"]] = row["id"]
        name_to_ids.setdefault(row["name"], []).append(row["id"])
    
    # Get unresolved call edges
    cur = db.conn.execute(
        "SELECT e.id, e.source_id, e.target_name, n.file_id, f.path as source_file_path "
        "FROM edges e JOIN nodes n ON e.source_id = n.id JOIN files f ON n.file_id = f.id "
        "WHERE e.type = 'calls' AND e.target_id IS NULL"
    )
    
    unresolved = [dict(r) for r in cur.fetchall()]
    resolved_count = 0
    
    for call in unresolved:
        target_name = call["target_name"]
        
        # Try qualified name first
        if target_name in qname_to_id:
            db.conn.execute(
                "UPDATE edges SET target_id = ? WHERE id = ?",
                (qname_to_id[target_name], call["id"])
            )
            resolved_count += 1
            continue
        
        # Try simple name - prefer same file, then others
        simple_name = target_name.split(".")[-1]
        if simple_name in name_to_ids:
            candidates = name_to_ids[simple_name]
            if len(candidates) == 1:
                db.conn.execute(
                    "UPDATE edges SET target_id = ? WHERE id = ?",
                    (candidates[0], call["id"])
                )
                resolved_count += 1
    
    db.conn.commit()
    return resolved_count
