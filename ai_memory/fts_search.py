"""Full-text search using SQLite FTS5 on symbol names, signatures, and docstrings."""
import json
from typing import Dict, List, Optional, Tuple

from .db import GraphDB


def init_fts(db: GraphDB):
    """Initialize FTS5 virtual table if supported."""
    # Check if FTS5 is available
    cur = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='fts_nodes'")
    if cur.fetchone():
        return  # Already exists
    
    try:
        db.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_nodes USING fts5(
                name, signature, doc, qualified_name,
                content='nodes',
                content_rowid='id'
            )
        """)
        db.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS fts_nodes_insert AFTER INSERT ON nodes BEGIN
                INSERT INTO fts_nodes(rowid, name, signature, doc, qualified_name)
                VALUES (new.id, new.name, new.signature, new.doc, new.qualified_name);
            END
        """)
        db.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS fts_nodes_delete AFTER DELETE ON nodes BEGIN
                INSERT INTO fts_nodes(fts_nodes, rowid, name, signature, doc, qualified_name)
                VALUES ('delete', old.id, old.name, old.signature, old.doc, old.qualified_name);
            END
        """)
        db.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS fts_nodes_update AFTER UPDATE ON nodes BEGIN
                INSERT INTO fts_nodes(fts_nodes, rowid, name, signature, doc, qualified_name)
                VALUES ('delete', old.id, old.name, old.signature, old.doc, old.qualified_name);
                INSERT INTO fts_nodes(rowid, name, signature, doc, qualified_name)
                VALUES (new.id, new.name, new.signature, new.doc, new.qualified_name);
            END
        """)
        db.conn.commit()
        
        # Populate initial data
        db.conn.execute("""
            INSERT INTO fts_nodes(rowid, name, signature, doc, qualified_name)
            SELECT id, name, signature, doc, qualified_name FROM nodes
        """)
        db.conn.commit()
    except Exception:
        # FTS5 might not be available
        pass


def rebuild_fts(db: GraphDB):
    """Rebuild FTS index from scratch."""
    try:
        db.conn.execute("DELETE FROM fts_nodes")
        db.conn.execute("""
            INSERT INTO fts_nodes(rowid, name, signature, doc, qualified_name)
            SELECT id, name, signature, doc, qualified_name FROM nodes
        """)
        db.conn.commit()
    except Exception:
        pass


def search_fts(db: GraphDB, query: str, limit: int = 20) -> List[Dict]:
    """Full-text search for symbols.
    
    Supports SQLite FTS5 query syntax:
    - Simple words: auth middleware
    - Phrase: "auth middleware"
    - Prefix: auth*
    - NEAR: auth NEAR middleware
    """
    try:
        cur = db.conn.execute(
            """
            SELECT n.*, f.path as file_path, rank
            FROM fts_nodes
            JOIN nodes n ON fts_nodes.rowid = n.id
            JOIN files f ON n.file_id = f.id
            WHERE fts_nodes MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit)
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        # FTS5 not available or query error, fall back to LIKE
        return _fallback_search(db, query, limit)


def _fallback_search(db: GraphDB, query: str, limit: int) -> List[Dict]:
    """Fallback search using LIKE when FTS5 is unavailable."""
    words = query.replace('"', '').replace('*', '%').split()
    if not words:
        return []
    
    # Build OR conditions
    conditions = []
    params = []
    for word in words:
        conditions.append("(n.name LIKE ? OR n.signature LIKE ? OR n.doc LIKE ? OR n.qualified_name LIKE ?)")
        params.extend([f"%{word}%"] * 4)
    
    where_clause = " OR ".join(conditions)
    
    cur = db.conn.execute(
        f"""
        SELECT n.*, f.path as file_path
        FROM nodes n
        JOIN files f ON n.file_id = f.id
        WHERE {where_clause}
        LIMIT ?
        """,
        tuple(params + [limit])
    )
    return [dict(r) for r in cur.fetchall()]


def format_search_results(results: List[Dict], query: str) -> str:
    """Format search results as markdown."""
    lines = [f"# Search Results: '{query}'", ""]
    
    if not results:
        lines.append("No matching symbols found.\n")
        return "\n".join(lines)
    
    lines.append(f"**Found {len(results)} symbols**\n")
    
    for r in results:
        sig = str(r.get("signature", ""))[:80].replace("\n", " ")
        doc = str(r.get("doc", ""))[:100].replace("\n", " ") if r.get("doc") else ""
        lines.append(f"## `{r['type']}` {r['name']}")
        lines.append(f"- **File:** `{r['file_path']}`:L{r['start_line']}")
        if sig:
            lines.append(f"- **Signature:** `{sig}`")
        if doc:
            lines.append(f"- **Doc:** {doc}")
        lines.append("")
    
    return "\n".join(lines)
