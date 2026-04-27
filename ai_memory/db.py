import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    language TEXT,
    mtime REAL,
    hash TEXT,
    line_count INTEGER,
    last_scan REAL
);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT,
    signature TEXT,
    start_line INTEGER,
    end_line INTEGER,
    start_col INTEGER,
    end_col INTEGER,
    doc TEXT,
    body TEXT,
    type_annotations TEXT,
    meta TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    target_id INTEGER,
    target_name TEXT,
    target_file TEXT,
    type TEXT NOT NULL,
    line INTEGER,
    meta TEXT,
    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_id);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_qname ON nodes(qualified_name);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
CREATE INDEX IF NOT EXISTS idx_edges_target_name ON edges(target_name);

CREATE TABLE IF NOT EXISTS schemas (
    id INTEGER PRIMARY KEY,
    file_id INTEGER,
    db_type TEXT,
    schema_name TEXT,
    table_name TEXT,
    definition TEXT,
    kind TEXT,
    line_start INTEGER,
    line_end INTEGER,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_schema_table ON schemas(table_name);
CREATE INDEX IF NOT EXISTS idx_schema_kind ON schemas(kind);

CREATE TABLE IF NOT EXISTS flows (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    entry_point_id INTEGER NOT NULL,
    steps TEXT NOT NULL,
    depth INTEGER DEFAULT 0,
    node_count INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    criticality REAL DEFAULT 0.0,
    FOREIGN KEY (entry_point_id) REFERENCES nodes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_flows_entry ON flows(entry_point_id);

CREATE TABLE IF NOT EXISTS communities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    dominant_language TEXT,
    size INTEGER DEFAULT 0,
    cohesion REAL DEFAULT 0.0,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS community_members (
    node_id INTEGER NOT NULL,
    community_id INTEGER NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (community_id) REFERENCES communities(id) ON DELETE CASCADE,
    UNIQUE(node_id, community_id)
);
CREATE INDEX IF NOT EXISTS idx_cm_node ON community_members(node_id);
CREATE INDEX IF NOT EXISTS idx_cm_comm ON community_members(community_id);

CREATE TABLE IF NOT EXISTS node_embeddings (
    node_id INTEGER PRIMARY KEY,
    embedding TEXT NOT NULL,
    model TEXT,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coverage_status (
    file_path TEXT PRIMARY KEY,
    covered_lines TEXT,
    uncovered_lines TEXT,
    coverage_pct REAL DEFAULT 0.0,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_coverage_path ON coverage_status(file_path);

CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT,
    dep_type TEXT,  -- python, npm, cargo, go, etc.
    manifest_file TEXT,
    is_dev INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_deps_type ON dependencies(dep_type);
"""


@dataclass
class Node:
    id: Optional[int]
    file_id: int
    type: str  # function, class, method, variable, import, interface, enum
    name: str
    qualified_name: Optional[str]
    signature: Optional[str]
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    doc: Optional[str]
    body: Optional[str]
    type_annotations: Optional[str]
    meta: Optional[Dict]


@dataclass
class Edge:
    id: Optional[int]
    source_id: int
    target_id: Optional[int]
    target_name: Optional[str]
    target_file: Optional[str]
    type: str  # calls, imports, inherits, contains, references, implements
    line: int
    meta: Optional[Dict]


class GraphDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()
        # Migrate existing databases: add columns if missing
        self._migrate_add_column("nodes", "body", "TEXT")
        self._migrate_add_column("nodes", "type_annotations", "TEXT")

    def _migrate_add_column(self, table: str, column: str, col_type: str):
        cur = self.conn.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        if column not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # --- Files ---

    def upsert_file(self, path: str, language: str, mtime: float, hash: str, line_count: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO files(path, language, mtime, hash, line_count, last_scan) "
            "VALUES (?, ?, ?, ?, ?, strftime('%s','now')) "
            "ON CONFLICT(path) DO UPDATE SET language=excluded.language, mtime=excluded.mtime, "
            "hash=excluded.hash, line_count=excluded.line_count, last_scan=excluded.last_scan "
            "RETURNING id",
            (path, language, mtime, hash, line_count)
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def get_file_by_path(self, path: str) -> Optional[Dict]:
        cur = self.conn.execute("SELECT * FROM files WHERE path = ?", (path,))
        row = cur.fetchone()
        return dict(row) if row else None

    def delete_file(self, path: str):
        self.conn.execute("DELETE FROM files WHERE path = ?", (path,))
        self.conn.commit()

    def get_all_files(self) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM files")
        return [dict(r) for r in cur.fetchall()]

    # --- Nodes ---

    def insert_node(self, node: Node) -> int:
        cur = self.conn.execute(
            "INSERT INTO nodes(file_id, type, name, qualified_name, signature, start_line, end_line, start_col, end_col, doc, body, type_annotations, meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (node.file_id, node.type, node.name, node.qualified_name, node.signature,
             node.start_line, node.end_line, node.start_col, node.end_col,
             node.doc, node.body, node.type_annotations,
             json.dumps(node.meta) if node.meta else None)
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def delete_nodes_by_file(self, file_id: int):
        self.conn.execute("DELETE FROM nodes WHERE file_id = ?", (file_id,))
        self.conn.commit()

    def get_nodes_by_file(self, file_id: int) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM nodes WHERE file_id = ?", (file_id,))
        return [dict(r) for r in cur.fetchall()]

    def find_node_by_name(self, name: str, node_type: Optional[str] = None) -> List[Dict]:
        if node_type:
            cur = self.conn.execute(
                "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
                "WHERE n.name = ? AND n.type = ?", (name, node_type))
        else:
            cur = self.conn.execute(
                "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
                "WHERE n.name = ?", (name,))
        return [dict(r) for r in cur.fetchall()]

    def find_node_by_qualified_name(self, qname: str) -> Optional[Dict]:
        cur = self.conn.execute(
            "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
            "WHERE n.qualified_name = ? LIMIT 1", (qname,))
        row = cur.fetchone()
        return dict(row) if row else None

    def search_nodes(self, query: str, limit: int = 20) -> List[Dict]:
        # Simple FTS-like wildcard search
        pattern = f"%{query}%"
        cur = self.conn.execute(
            "SELECT n.*, f.path as file_path FROM nodes n JOIN files f ON n.file_id = f.id "
            "WHERE n.name LIKE ? OR n.qualified_name LIKE ? OR n.signature LIKE ? "
            "ORDER BY n.type LIMIT ?",
            (pattern, pattern, pattern, limit)
        )
        return [dict(r) for r in cur.fetchall()]

    # --- Edges ---

    def insert_edge(self, edge: Edge) -> int:
        cur = self.conn.execute(
            "INSERT INTO edges(source_id, target_id, target_name, target_file, type, line, meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (edge.source_id, edge.target_id, edge.target_name, edge.target_file,
             edge.type, edge.line, json.dumps(edge.meta) if edge.meta else None)
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def delete_edges_by_source_file(self, file_id: int):
        self.conn.execute(
            "DELETE FROM edges WHERE source_id IN (SELECT id FROM nodes WHERE file_id = ?)",
            (file_id,)
        )
        self.conn.commit()

    def get_edges_from(self, node_id: int) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM edges WHERE source_id = ?", (node_id,))
        return [dict(r) for r in cur.fetchall()]

    def get_edges_to(self, node_id: int) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM edges WHERE target_id = ?", (node_id,))
        return [dict(r) for r in cur.fetchall()]

    def get_all_edges(self) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM edges")
        return [dict(r) for r in cur.fetchall()]

    # --- Schemas ---

    def insert_schema(self, file_id: Optional[int], db_type: str, schema_name: Optional[str],
                      table_name: str, definition: str, kind: str, line_start: int, line_end: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO schemas(file_id, db_type, schema_name, table_name, definition, kind, line_start, line_end) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (file_id, db_type, schema_name, table_name, definition, kind, line_start, line_end)
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def delete_schemas_by_file(self, file_id: int):
        self.conn.execute("DELETE FROM schemas WHERE file_id = ?", (file_id,))
        self.conn.commit()

    def find_schema(self, table_name: str) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM schemas WHERE table_name = ?", (table_name,))
        return [dict(r) for r in cur.fetchall()]

    # --- Flows ---

    def insert_flow(self, name: str, entry_point_id: int, steps: str, depth: int, node_count: int, file_count: int, criticality: float) -> int:
        cur = self.conn.execute(
            "INSERT INTO flows(name, entry_point_id, steps, depth, node_count, file_count, criticality) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (name, entry_point_id, steps, depth, node_count, file_count, criticality)
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def delete_flow(self, flow_id: int):
        self.conn.execute("DELETE FROM flows WHERE id = ?", (flow_id,))
        self.conn.commit()

    def delete_all_flows(self):
        self.conn.execute("DELETE FROM flows")
        self.conn.commit()

    def get_flows(self, limit: int = 50) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM flows ORDER BY criticality DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    def get_flow(self, flow_id: int) -> Optional[Dict]:
        cur = self.conn.execute("SELECT * FROM flows WHERE id = ?", (flow_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_flows_for_node(self, node_id: int) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM flows WHERE entry_point_id = ?", (node_id,))
        return [dict(r) for r in cur.fetchall()]

    # --- Communities ---

    def insert_community(self, name: str, dominant_language: Optional[str], size: int, cohesion: float, summary: Optional[str]) -> int:
        cur = self.conn.execute(
            "INSERT INTO communities(name, dominant_language, size, cohesion, summary) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            (name, dominant_language, size, cohesion, summary)
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def delete_all_communities(self):
        self.conn.execute("DELETE FROM communities")
        self.conn.execute("DELETE FROM community_members")
        self.conn.commit()

    def add_community_member(self, node_id: int, community_id: int):
        self.conn.execute(
            "INSERT OR IGNORE INTO community_members(node_id, community_id) VALUES (?, ?)",
            (node_id, community_id)
        )
        self.conn.commit()

    def get_communities(self) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM communities ORDER BY size DESC")
        return [dict(r) for r in cur.fetchall()]

    def get_community_members(self, community_id: int) -> List[Dict]:
        cur = self.conn.execute(
            "SELECT n.*, f.path as file_path FROM nodes n "
            "JOIN community_members cm ON n.id = cm.node_id "
            "JOIN files f ON n.file_id = f.id "
            "WHERE cm.community_id = ?", (community_id,)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_node_community(self, node_id: int) -> Optional[Dict]:
        cur = self.conn.execute(
            "SELECT c.* FROM communities c "
            "JOIN community_members cm ON c.id = cm.community_id "
            "WHERE cm.node_id = ? LIMIT 1", (node_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    # --- Dependencies ---

    def insert_dependency(self, name: str, version: Optional[str], dep_type: str, manifest_file: str, is_dev: bool = False) -> int:
        cur = self.conn.execute(
            "INSERT INTO dependencies(name, version, dep_type, manifest_file, is_dev) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (name, version, dep_type, manifest_file, 1 if is_dev else 0)
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def delete_dependencies_by_type(self, dep_type: str):
        self.conn.execute("DELETE FROM dependencies WHERE dep_type = ?", (dep_type,))
        self.conn.commit()

    def get_dependencies(self, dep_type: Optional[str] = None) -> List[Dict]:
        if dep_type:
            cur = self.conn.execute("SELECT * FROM dependencies WHERE dep_type = ?", (dep_type,))
        else:
            cur = self.conn.execute("SELECT * FROM dependencies")
        return [dict(r) for r in cur.fetchall()]

    # --- Embeddings ---

    def insert_embedding(self, node_id: int, embedding: str, model: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO node_embeddings(node_id, embedding, model) VALUES (?, ?, ?)",
            (node_id, embedding, model)
        )
        self.conn.commit()

    def delete_all_embeddings(self):
        self.conn.execute("DELETE FROM node_embeddings")
        self.conn.commit()

    def get_embedding(self, node_id: int) -> Optional[Dict]:
        cur = self.conn.execute("SELECT * FROM node_embeddings WHERE node_id = ?", (node_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_all_embeddings(self) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM node_embeddings")
        return [dict(r) for r in cur.fetchall()]

    # --- Stats ---

    def get_stats(self) -> Dict:
        cur = self.conn.execute("SELECT COUNT(*) as files FROM files")
        files = cur.fetchone()["files"]
        cur = self.conn.execute("SELECT COUNT(*) as nodes FROM nodes")
        nodes = cur.fetchone()["nodes"]
        cur = self.conn.execute("SELECT COUNT(*) as edges FROM edges")
        edges = cur.fetchone()["edges"]
        cur = self.conn.execute("SELECT COUNT(*) as schemas FROM schemas")
        schemas = cur.fetchone()["schemas"]
        return {"files": files, "nodes": nodes, "edges": edges, "schemas": schemas}

    def get_graph_summary(self) -> Dict:
        cur = self.conn.execute(
            "SELECT type, COUNT(*) as count FROM nodes GROUP BY type ORDER BY count DESC"
        )
        node_types = {r["type"]: r["count"] for r in cur.fetchall()}
        cur = self.conn.execute(
            "SELECT type, COUNT(*) as count FROM edges GROUP BY type ORDER BY count DESC"
        )
        edge_types = {r["type"]: r["count"] for r in cur.fetchall()}
        return {"node_types": node_types, "edge_types": edge_types}
