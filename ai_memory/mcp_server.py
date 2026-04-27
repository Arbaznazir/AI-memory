"""MCP (Model Context Protocol) server for AI IDE integration.

Exposes ai-memory tools natively to Windsurf, Cursor, Claude Desktop, etc.
Uses stdio JSON-RPC for communication.
"""
import json
import sys
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import GraphDB
from .config import load_config
from .scanner import full_scan, scan_file
from .formatter import (
    file_summary, symbol_context, project_overview, schema_overview,
    query_context, flows_overview, communities_overview
)
from .embeddings import build_embeddings, semantic_search


class MCPServer:
    def __init__(self, root: Path):
        self.root = root
        self.config = load_config(root)
        self.db = GraphDB(self.config["db_path"])

    def _send(self, msg: Dict):
        data = json.dumps(msg, separators=(",", ":"))
        sys.stdout.write(f"Content-Length: {len(data.encode('utf-8'))}\r\n\r\n{data}")
        sys.stdout.flush()

    def _read(self) -> Optional[Dict]:
        line = sys.stdin.readline()
        if not line:
            return None
        if not line.startswith("Content-Length: "):
            return None
        length = int(line.strip().split(": ")[1])
        sys.stdin.readline()  # empty line
        data = sys.stdin.read(length)
        return json.loads(data)

    def handle(self, request: Dict) -> Dict:
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        result = None
        error = None

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {
                            "listChanged": False
                        }
                    },
                    "serverInfo": {
                        "name": "ai-memory",
                        "version": "0.1.0"
                    }
                }

            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "ai_memory_scan",
                            "description": "Scan the entire codebase and update the knowledge graph.",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_stats",
                            "description": "Get project overview: files, symbols, edges, schemas, top connected nodes.",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_context",
                            "description": "Get AI-optimized context for a symbol including its call graph neighbors.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "symbol": {"type": "string", "description": "Symbol name to look up"},
                                    "depth": {"type": "integer", "default": 2, "description": "How many hops to include"}
                                },
                                "required": ["symbol"]
                            }
                        },
                        {
                            "name": "ai_memory_file",
                            "description": "Get summary of a single file with all symbols and their edges.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string", "description": "File path relative to project root"}
                                },
                                "required": ["path"]
                            }
                        },
                        {
                            "name": "ai_memory_ask",
                            "description": "Generate compact context for an AI query using keyword search.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "Natural language query"},
                                    "max_tokens": {"type": "integer", "default": 4000}
                                },
                                "required": ["query"]
                            }
                        },
                        {
                            "name": "ai_memory_semantic",
                            "description": "Semantic search for symbols using embeddings. Run embed first if no results.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "Natural language query"},
                                    "limit": {"type": "integer", "default": 10}
                                },
                                "required": ["query"]
                            }
                        },
                        {
                            "name": "ai_memory_flows",
                            "description": "List pre-computed execution flows (call chains from entry points).",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_communities",
                            "description": "List detected code communities/modules with their key symbols.",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_schemas",
                            "description": "List all database schemas and migrations.",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_find",
                            "description": "Find symbols by exact or partial name match.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"}
                                },
                                "required": ["name"]
                            }
                        },
                        {
                            "name": "ai_memory_dead_code",
                            "description": "Find symbols with zero incoming references (potentially unused).",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_callers",
                            "description": "Reverse call graph — who calls a given symbol.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "symbol": {"type": "string", "description": "Symbol name to look up callers for"},
                                    "depth": {"type": "integer", "default": 2}
                                },
                                "required": ["symbol"]
                            }
                        },
                        {
                            "name": "ai_memory_todos",
                            "description": "List TODO, FIXME, HACK, XXX markers in the codebase.",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_test_map",
                            "description": "Map test functions to their implementation targets.",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_graph",
                            "description": "Export call graph as Mermaid or DOT format.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "symbol": {"type": "string", "description": "Symbol to center graph on"},
                                    "format": {"type": "string", "default": "mermaid"},
                                    "flow_id": {"type": "integer"}
                                }
                            }
                        },
                        {
                            "name": "ai_memory_cycles",
                            "description": "Find circular dependencies in import and call graphs.",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_inherits",
                            "description": "Show full inheritance chain for a class.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "class_name": {"type": "string", "description": "Class name to trace inheritance for"}
                                },
                                "required": ["class_name"]
                            }
                        },
                        {
                            "name": "ai_memory_api",
                            "description": "Detect public API surface from package entry points.",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "ai_memory_search",
                            "description": "Full-text search over symbol names, signatures, and docstrings.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "Search query"},
                                    "limit": {"type": "integer", "default": 20}
                                },
                                "required": ["query"]
                            }
                        },
                        {
                            "name": "ai_memory_coverage",
                            "description": "Load and summarize code coverage data.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "coverage_file": {"type": "string", "description": "Path to coverage file (auto-detected if omitted)"}
                                }
                            }
                        },
                        {
                            "name": "ai_memory_deps",
                            "description": "List project dependencies from manifest files.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "dep_type": {"type": "string", "description": "Filter by dependency type (python, npm, cargo, go)"}
                                }
                            }
                        },
                    ]
                }

            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_input = params.get("arguments", {})
                result = self._call_tool(tool_name, tool_input)

            elif method == "notifications/initialized":
                result = {}

            else:
                error = {"code": -32601, "message": f"Method not found: {method}"}

        except Exception as e:
            error = {"code": -32000, "message": str(e)}

        response = {"jsonrpc": "2.0"}
        if req_id is not None:
            response["id"] = req_id
        if error:
            response["error"] = error
        else:
            response["result"] = result
        return response

    def _call_tool(self, name: str, args: Dict) -> Dict:
        if name == "ai_memory_scan":
            from .scanner import full_scan
            scanned, changed = full_scan(self.root, self.db, self.config)
            stats = self.db.get_stats()
            return {
                "content": [{"type": "text", "text": f"Scanned {scanned} files ({changed} changed). Stats: {stats}"}]
            }

        elif name == "ai_memory_stats":
            text = project_overview(self.db)
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_context":
            symbol = args.get("symbol", "")
            depth = args.get("depth", 2)
            text = symbol_context(self.db, symbol, max_depth=depth)
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_file":
            path = args.get("path", "")
            text = file_summary(self.db, path)
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_ask":
            query = args.get("query", "")
            max_tokens = args.get("max_tokens", 4000)
            text = query_context(self.db, query, max_tokens=max_tokens)
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_semantic":
            query = args.get("query", "")
            limit = args.get("limit", 10)
            try:
                results = semantic_search(self.db, query, limit=limit)
                lines = [f"Semantic search results for '{query}':"]
                for node, score in results:
                    lines.append(f"- [{score:.3f}] {node['type']} {node['name']} ({node.get('file_path', '')})")
                text = "\n".join(lines)
            except RuntimeError as e:
                text = f"Error: {e}. Run `ai-memory embed` first to build embeddings."
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_flows":
            text = flows_overview(self.db)
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_communities":
            text = communities_overview(self.db)
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_schemas":
            text = schema_overview(self.db)
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_find":
            name_query = args.get("name", "")
            nodes = self.db.search_nodes(name_query, limit=20)
            lines = [f"Symbols matching '{name_query}':"]
            for n in nodes:
                lines.append(f"- {n['type']} {n['name']} ({n.get('file_path', '')}:L{n['start_line']})")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        elif name == "ai_memory_dead_code":
            from .dead_code import find_dead_code
            dead = find_dead_code(self.db)
            lines = [f"Potentially unused symbols ({len(dead)} found):"]
            for n in dead[:50]:
                lines.append(f"- {n['type']} {n['name']} ({n.get('file_path', '')}:L{n['start_line']})")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        elif name == "ai_memory_callers":
            from .callers import find_callers
            symbol = args.get("symbol", "")
            callers = find_callers(self.db, symbol)
            lines = [f"Callers of '{symbol}':"]
            for c in callers[:30]:
                lines.append(f"- {c.get('caller_type', '?')} {c.get('caller_name', c.get('source_name', '?'))} ({c.get('caller_file', '?')})")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        elif name == "ai_memory_todos":
            from .todo_extractor import extract_all_todos, format_todos
            from .config import load_config
            todos = extract_all_todos(self.root, load_config(self.root))
            return {"content": [{"type": "text", "text": format_todos(todos)}]}

        elif name == "ai_memory_test_map":
            from .test_mapper import map_all_tests, format_test_map
            mappings = map_all_tests(self.db)
            return {"content": [{"type": "text", "text": format_test_map(mappings)}]}

        elif name == "ai_memory_graph":
            from .graph_export import (
                export_mermaid_flow, export_mermaid_call_graph,
                export_dot_communities, export_mermaid_project
            )
            symbol = args.get("symbol", "")
            fmt = args.get("format", "mermaid")
            flow_id = args.get("flow_id")
            if flow_id:
                text = export_mermaid_flow(flow_id, self.db)
            elif symbol:
                text = export_mermaid_call_graph(symbol, self.db)
            else:
                if fmt == "mermaid":
                    text = export_mermaid_project(self.db)
                else:
                    text = export_dot_communities(self.db)
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_cycles":
            from .cycles import find_all_cycles, format_cycles
            cycles = find_all_cycles(self.db)
            return {"content": [{"type": "text", "text": format_cycles(cycles)}]}

        elif name == "ai_memory_inherits":
            from .inheritance import get_inheritance_chain, format_inheritance_chain
            class_name = args.get("class_name", "")
            chain = get_inheritance_chain(self.db, class_name)
            return {"content": [{"type": "text", "text": format_inheritance_chain(chain)}]}

        elif name == "ai_memory_api":
            from .api_surface import detect_api_surface, format_api_surface
            surface = detect_api_surface(self.db, self.root)
            return {"content": [{"type": "text", "text": format_api_surface(surface)}]}

        elif name == "ai_memory_search":
            from .fts_search import init_fts, search_fts, format_search_results
            init_fts(self.db)
            query = args.get("query", "")
            limit = args.get("limit", 20)
            results = search_fts(self.db, query, limit=limit)
            return {"content": [{"type": "text", "text": format_search_results(results, query)}]}

        elif name == "ai_memory_coverage":
            from .coverage_overlay import load_coverage, get_coverage_summary, format_coverage_summary
            from pathlib import Path
            coverage_file = args.get("coverage_file")
            coverage_path = Path(coverage_file) if coverage_file else None
            count = load_coverage(self.db, self.root, coverage_path)
            summary = get_coverage_summary(self.db)
            text = format_coverage_summary(summary)
            if count > 0:
                text = f"Loaded coverage for {count} files.\n\n" + text
            return {"content": [{"type": "text", "text": text}]}

        elif name == "ai_memory_deps":
            dep_type = args.get("dep_type")
            deps = self.db.get_dependencies(dep_type=dep_type)
            lines = [f"Dependencies ({len(deps)} found):"]
            for d in deps:
                ver = d.get("version") or ""
                dev = " [dev]" if d.get("is_dev") else ""
                lines.append(f"- {d['name']}{ver and ' ' + ver} ({d.get('dep_type', '?')}){dev}")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        else:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}]}

    def run(self):
        while True:
            try:
                request = self._read()
                if request is None:
                    break
                response = self.handle(request)
                self._send(response)
            except Exception as e:
                self._send({"jsonrpc": "2.0", "error": {"code": -32000, "message": str(e)}})


def serve(root: Path):
    """Run MCP server over stdio."""
    server = MCPServer(root)
    server.run()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", "-r", default=".", help="Project root")
    args = parser.parse_args()
    serve(Path(args.root).resolve())
