# AI-Memory

Stop burning API tokens on file-by-file exploration. **AI-Memory** builds a self-updating knowledge graph of your entire codebase so your AI assistant answers instantly — with full context — instead of asking "can you show me that file?" repeatedly.

```
Before: You ask AI a question → AI opens 5 files → 8,000 tokens → still confused
After:  AI-Memory knows your code → AI queries the graph  → 500 tokens  → precise answer
```

## The Problem (You Know This Pain)

You ask your AI assistant: "How do I add pagination to the user list?"

| Step | What AI Does | Tokens |
|------|-------------|--------|
| 1 | Opens `routes.py`, reads 200 lines | 1,500 |
| 2 | Opens `models.py`, reads 150 lines | 1,200 |
| 3 | Opens `controllers.py`, reads 300 lines | 2,400 |
| 4 | Asks "Can you show me the User model?" | — |
| 5 | You paste it | 500 |
| 6 | Re-reads everything again | 2,500 |
| **Total** | | **~8,000 tokens** |

**With AI-Memory:** AI runs one internal query and gets `list_users(self, db, skip=0, limit=100)` with full body, types, and callers. **500 tokens. One shot. Correct answer.**

## How It Works

| Engine | What It Does |
|--------|-------------|
| **Scan** | Tree-sitter parses Python, JS/TS, Ruby, Go, Rust, Java, C#, C/C++, SQL |
| **Graph** | Functions, classes, imports, calls, inheritance in SQLite |
| **Import Resolution** | Cross-file imports resolved to real symbol definitions |
| **Execution Flows** | Pre-computed call chains from every entry point |
| **Communities** | Auto-detected code modules by directory + graph coupling |
| **Semantic Search** | `sentence-transformers` embeddings: find `login_user` from "auth" |
| **Type & Body Storage** | Full function bodies and type annotations cached |
| **Watch** | Incremental updates on every file save |

---

## Supported Languages

| Backend | Frontend | Systems | Data & Config | Manifests |
|---------|----------|---------|---------------|-----------|
| Python | JavaScript | C | SQL | `requirements.txt` |
| Go | TypeScript | C++ | YAML | `package.json` |
| Rust | JSX | C# | JSON | `Cargo.toml` |
| Java | TSX | | TOML | `pyproject.toml` |
| Ruby | | | Protobuf | `go.mod` |
| | | | GraphQL | |

**DB Schemas:** Table, index, column extraction from SQL and migration files.

---

## Supported IDEs

| IDE | Integration | Setup Required |
|-----|------------|--------------|
| **Windsurf** | `.windsurfrules` auto-generated | **None** — AI reads instructions automatically |
| **Cursor** | `.cursorrules` auto-generated | **None** — AI reads instructions automatically |
| **Claude Desktop** | MCP server `ai-memory-mcp` | One JSON config |
| **VS Code** | MCP server or CLI | Terminal or extension |

After `ai-memory init`, your AI **already knows** about the graph. Zero IDE configuration.

---

## Get Started (3 Commands)

```bash
# 1. Install
cd your-project
pip install ai-memory

# 2. Initialize — config, DB, gitignore, IDE rule files
ai-memory init

# 3. Scan your codebase — one time
ai-memory scan
```

**Optional:**
```bash
# Enable semantic search (~2 min one-time)
ai-memory embed

# Auto-update on file changes (background daemon)
ai-memory watch
```

---

## What Happens After Init

```
your-project/
├── .ai-memory/           # Graph database (gitignored automatically)
│   └── graph.db          # SQLite: ~380 symbols, ~1850 relations, 34 deps
├── .ai-memory.toml       # Your project config
├── .windsurfrules        # Windsurf: "Use ai-memory for context"
├── .cursorrules          # Cursor: "Use ai-memory for context"
└── .gitignore            # Auto-added: .ai-memory/
```

---

## CLI Commands

### Core Workflow
| Command | Description |
|---------|-------------|
| `init` | Create config, DB, gitignore entry, IDE rule files |
| `scan` | Full codebase scan + post-processing |
| `watch` | Auto-incremental update on file changes |
| `embed` | Build semantic embeddings for all symbols |
| `embed --incremental` | Only new/changed symbols |

### Symbol Context
| Command | Description |
|---------|-------------|
| `context <symbol>` | Symbol + body + types + neighbors |
| `callers <symbol>` | Reverse call graph — who calls this |
| `inherits <class>` | Full inheritance chain |

### Search & Discovery
| Command | Description |
|---------|-------------|
| `ask "<question>"` | Natural language → compact context |
| `semantic "<query>"` | Embedding-based semantic search |
| `search "<query>"` | Full-text search over names, signatures, docstrings |
| `find <name>` | Search symbols by name |

### Analysis
| Command | Description |
|---------|-------------|
| `stats` | Project overview (files, nodes, edges, top hubs) |
| `flows` | Pre-computed execution flows from entry points |
| `communities` | Detected code modules/clusters |
| `cycles` | Circular dependencies |
| `dead-code` | Unused symbols (zero incoming references) |
| `api` | Public API surface from `__init__.py`, `index.js`, `lib.rs` |
| `todos` | TODO, FIXME, HACK, XXX markers |
| `test-map` | Map tests to implementation |

### Dependencies & Coverage
| Command | Description |
|---------|-------------|
| `deps` | List dependencies from manifests |
| `coverage` | Load coverage data and show summary |
| `coverage-detail` | Per-symbol coverage status |

### Export
| Command | Description |
|---------|-------------|
| `graph [symbol]` | Mermaid or DOT call graph |
| `file <path>` | Summary of a single file |
| `schemas` | All DB schemas / migrations |
| `review` | Git diff impact analysis |

---

## MCP Server (Native IDE Integration)

For Claude Desktop, Windsurf, Cursor:

```bash
ai-memory-mcp --root /path/to/project
```

**20 exposed tools:** `ai_memory_scan`, `ai_memory_stats`, `ai_memory_context`, `ai_memory_ask`, `ai_memory_semantic`, `ai_memory_flows`, `ai_memory_communities`, `ai_memory_schemas`, `ai_memory_find`, `ai_memory_dead_code`, `ai_memory_callers`, `ai_memory_todos`, `ai_memory_test_map`, `ai_memory_graph`, `ai_memory_cycles`, `ai_memory_inherits`, `ai_memory_api`, `ai_memory_search`, `ai_memory_coverage`, `ai_memory_deps`.

---

## Configuration

Edit `.ai-memory.toml` to customize:

```toml
scan_dirs = ["src", "app", "lib"]
extensions = [".py", ".js", ".ts", ".go", ".rs"]
ignore_patterns = ["node_modules", "venv", "__pycache__"]
output_format = "markdown"
max_context_tokens = 4000
```

---

## Architecture

```
Source Code
    │
    ▼
Tree-sitter Parsers (Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby)
    │
    ▼
Symbol Extractor ──→ Symbols (functions, classes, imports)
│                     Body Extractor ──→ Full function bodies
│                     Type Extractor ──→ Type annotations
│
Relation Extractor ──→ Calls, Inherits, Imports
    │
    ▼
Import Resolver ──→ Cross-file links resolved
    │
    ▼
SQLite Graph DB ──→ nodes, edges, files, schemas, flows, communities
    │
    ▼
┌─────────────────┬─────────────────┬─────────────────┐
│  Semantic       │  Execution      │  Community      │
│  Embeddings     │  Flows          │  Detection      │
│  (MiniLM)       │  (BFS from      │  (Leiden        │
│                 │   entry points) │   algorithm)    │
└─────────────────┴─────────────────┴─────────────────┘
    │
    ▼
CLI / MCP Server / Watch Daemon
    │
    ▼
AI Assistant (Windsurf, Cursor, Claude Desktop)
```
