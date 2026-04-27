"""File discovery, parsing, and graph population."""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import asdict

from .db import GraphDB, Node, Edge
from .languages import detect_language, get_parser
from .extractors import extract as extract_ast
from .schema_parser import parse_schema_file
from .import_resolver import resolve_imports, resolve_calls
from .flows import build_flows
from .communities import build_communities
from .manifest_parser import parse_manifests


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_files(root: Path, config: Dict) -> List[Path]:
    scan_dirs = config.get("scan_dirs", ["."])
    extensions = config.get("extensions", [])
    ignore_patterns = config.get("ignore_patterns", [])
    files: List[Path] = []

    def should_ignore(p: Path) -> bool:
        rel = str(p.relative_to(root))
        for pat in ignore_patterns:
            if pat.startswith("*"):
                if p.name.endswith(pat[1:]) or p.match(pat):
                    return True
            elif pat in rel or p.match(pat):
                return True
        return False

    search_roots = [root / d for d in scan_dirs if (root / d).exists()]
    if not search_roots:
        search_roots = [root]

    for sr in search_roots:
        for p in sr.rglob("*"):
            if p.is_file():
                if should_ignore(p):
                    continue
                if p.suffix.lower() in extensions:
                    files.append(p)
    return files


def scan_file(file_path: Path, db: GraphDB) -> bool:
    """Scan a single file and populate the graph. Returns True if changed."""
    rel_path = str(file_path)
    lang = detect_language(file_path)
    if not lang:
        return False

    mtime = os.path.getmtime(file_path)
    line_count = 0
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        line_count = content.count("\n") + 1

    file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    existing = db.get_file_by_path(rel_path)
    if existing and existing["hash"] == file_hash:
        return False

    file_id = db.upsert_file(rel_path, lang, mtime, file_hash, line_count)
    db.delete_nodes_by_file(file_id)
    db.delete_edges_by_source_file(file_id)
    db.delete_schemas_by_file(file_id)

    # Parse AST
    parser = get_parser(lang)
    if parser:
        tree = parser.parse(bytes(content, "utf8"))
        symbols, relations = extract_ast(tree, bytes(content, "utf8"), lang, rel_path)

        # Insert nodes
        name_to_id: Dict[str, int] = {}
        for sym in symbols:
            node = Node(
                id=None,
                file_id=file_id,
                type=sym.type,
                name=sym.name,
                qualified_name=sym.qualified_name,
                signature=sym.signature,
                start_line=sym.start_line,
                end_line=sym.end_line,
                start_col=sym.start_col,
                end_col=sym.end_col,
                doc=sym.doc,
                body=sym.body,
                type_annotations=sym.type_annotations,
                meta=sym.meta
            )
            nid = db.insert_node(node)
            key = sym.qualified_name or sym.name
            name_to_id[key] = nid

        # Insert edges
        for rel in relations:
            src_key = rel.source_name
            tgt_key = rel.target_name
            source_id = name_to_id.get(src_key)
            target_id = name_to_id.get(tgt_key)

            if source_id:
                edge = Edge(
                    id=None,
                    source_id=source_id,
                    target_id=target_id,
                    target_name=tgt_key,
                    target_file=rel.target_file,
                    type=rel.type,
                    line=rel.line,
                    meta=rel.meta
                )
                db.insert_edge(edge)

    # Schema parsing for SQL / migration files
    if lang == "sql" or file_path.name.endswith((".migration", ".migrate")):
        schemas = parse_schema_file(content, str(file_path))
        for s in schemas:
            db.insert_schema(
                file_id=file_id,
                db_type=s.get("db_type", "sql"),
                schema_name=s.get("schema_name"),
                table_name=s.get("table_name", ""),
                definition=s.get("definition", ""),
                kind=s.get("kind", ""),
                line_start=s.get("line_start", 0),
                line_end=s.get("line_end", 0)
            )

    return True


def full_scan(root: Path, db: GraphDB, config: Dict) -> Tuple[int, int]:
    """Perform a full scan. Returns (files_scanned, files_changed)."""
    files = discover_files(root, config)
    changed = 0
    scanned = 0

    # Remove files that no longer exist
    existing_paths = {str(p) for p in files}
    for f in db.get_all_files():
        if f["path"] not in existing_paths:
            db.delete_file(f["path"])

    for f in files:
        scanned += 1
        if scan_file(f, db):
            changed += 1

    # Parse dependency manifests
    parse_manifests(root, db)

    # Post-processing: cross-file resolution
    if changed > 0:
        resolved_imports = resolve_imports(db, root)
        resolved_calls = resolve_calls(db, root)
        flows = build_flows(db)
        communities = build_communities(db, root)
        # (embeddings built separately via CLI since they need sentence-transformers)

    return scanned, changed


def incremental_scan(root: Path, db: GraphDB, config: Dict, changed_paths: List[Path]) -> Tuple[int, int]:
    """Scan only changed files, rebuild affected flows and communities."""
    changed = 0
    scanned = 0
    changed_file_ids = set()
    for p in changed_paths:
        if p.is_file() and detect_language(p):
            scanned += 1
            rel_path = str(p)
            # Track file ID before re-scan to delete affected flows/communities
            existing = db.get_file_by_path(rel_path)
            if existing:
                changed_file_ids.add(existing["id"])
            if scan_file(p, db):
                changed += 1
                # Re-fetch file_id after upsert
                updated = db.get_file_by_path(rel_path)
                if updated:
                    changed_file_ids.add(updated["id"])

    if changed > 0:
        # Resolve cross-file edges for changed files only (faster than full)
        resolve_imports(db, root)
        resolve_calls(db, root)

        # Rebuild affected flows: delete flows whose entry points are in changed files
        for fid in changed_file_ids:
            nodes = db.get_nodes_by_file(fid)
            node_ids = {n["id"] for n in nodes}
            for flow in db.get_flows(limit=9999):
                steps = json.loads(flow["steps"])
                # Check if any step in the flow touches a changed node
                if any(s.get("node_id") in node_ids for s in steps):
                    db.delete_flow(flow["id"])
        # Rebuild all flows (could be optimized further)
        build_flows(db)

        # Communities: full rebuild is fast enough for now
        build_communities(db, root)

    return scanned, changed
