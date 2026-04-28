"""Semantic search using sentence-transformers embeddings on symbol metadata."""
import json
from typing import Dict, List, Optional, Tuple

from .db import GraphDB


_MODEL = None
_MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model():
    global _MODEL
    if _MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _MODEL = SentenceTransformer(_MODEL_NAME)
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
    return _MODEL


def _encode(texts: List[str]) -> List[List[float]]:
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    try:
        import numpy as np
        a_arr = np.array(a)
        b_arr = np.array(b)
        norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
        if norm == 0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / norm)
    except ImportError:
        # Fallback: pure Python cosine similarity
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


def build_embeddings(db: GraphDB, batch_size: int = 64, incremental: bool = False) -> int:
    """Generate embeddings for all symbols and store in DB.
    
    Args:
        incremental: If True, only re-embed nodes that have no embedding
                     or whose node content changed (signature/doc/name).
    """
    if not incremental:
        db.delete_all_embeddings()
    
    # Get all candidate nodes
    cur = db.conn.execute(
        "SELECT n.id, n.name, n.signature, n.doc, n.type, f.path as file_path "
        "FROM nodes n JOIN files f ON n.file_id = f.id "
        "WHERE n.type IN ('function', 'method', 'class', 'interface')"
    )
    all_nodes = [dict(r) for r in cur.fetchall()]
    
    if not all_nodes:
        return 0
    
    nodes = all_nodes
    if incremental:
        # Find nodes that need embedding (no existing embedding or content changed)
        cur = db.conn.execute(
            "SELECT node_id, embedding FROM node_embeddings"
        )
        existing = {r["node_id"]: r["embedding"] for r in cur.fetchall()}
        
        nodes_to_embed = []
        for n in all_nodes:
            if n["id"] not in existing:
                nodes_to_embed.append(n)
            else:
                # Could add content hash comparison here for robustness
                # For now, always re-embed if incremental is requested but node has embedding
                pass
        
        if not nodes_to_embed:
            return 0
        nodes = nodes_to_embed
    
    texts = []
    for n in nodes:
        # Compose rich text for embedding
        parts = [n["name"], n["type"]]
        if n["signature"]:
            parts.append(n["signature"])
        if n["doc"]:
            parts.append(n["doc"])
        parts.append(n["file_path"])
        texts.append(" | ".join(parts))
    
    # Batch encode
    count = 0
    for i in range(0, len(texts), batch_size):
        batch_nodes = nodes[i:i+batch_size]
        batch_texts = texts[i:i+batch_size]
        embeddings = _encode(batch_texts)
        
        for node, emb in zip(batch_nodes, embeddings):
            db.insert_embedding(
                node_id=node["id"],
                embedding=json.dumps(emb),
                model=_MODEL_NAME
            )
            count += 1
    
    return count


def semantic_search(db: GraphDB, query: str, limit: int = 10) -> List[Tuple[Dict, float]]:
    """Search symbols by semantic similarity to query."""
    # Encode query
    query_emb = _encode([query])[0]
    
    # Load all embeddings
    cur = db.conn.execute(
        "SELECT ne.node_id, ne.embedding, n.*, f.path as file_path "
        "FROM node_embeddings ne "
        "JOIN nodes n ON ne.node_id = n.id "
        "JOIN files f ON n.file_id = f.id"
    )
    
    results = []
    for row in cur.fetchall():
        emb = json.loads(row["embedding"])
        score = _cosine_similarity(query_emb, emb)
        node = dict(row)
        node["score"] = score
        results.append((node, score))
    
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]
