"""Auto-generate .windsurfrules and similar IDE integration files."""
from pathlib import Path
from typing import Dict, Optional

WINDSURF_RULES = """# AI-Memory Integration Rules

This project uses `ai-memory` for codebase context management.

## Quick Commands

```bash
# Initialize (one-time per project)
ai-memory init

# Full scan (run after major changes)
ai-memory scan

# Watch mode (auto-update on file changes)
ai-memory watch

# Ask about the codebase (low-token context)
ai-memory ask "<your question>"

# Semantic search (run `ai-memory embed` first)
ai-memory semantic "<query>"

# Symbol context with call graph
ai-memory context <symbol_name>

# Reverse call graph — who calls this symbol
ai-memory callers <symbol>

# Full-text search over names/signatures/docstrings
ai-memory search "<query>"

# Detect circular dependencies
ai-memory cycles

# Full inheritance chain for a class
ai-memory inherits <class_name>

# Public API surface
ai-memory api

# See execution flows
ai-memory flows

# See code communities/modules
ai-memory communities

# Find dead/unused code
ai-memory dead-code

# Review changed files and impacted flows
ai-memory review

# Extract TODO/FIXME/HACK markers
ai-memory todos

# Map tests to implementation
ai-memory test-map

# Dependency manifests
ai-memory deps

# Load coverage data
ai-memory coverage

# Build semantic embeddings
ai-memory embed

# Incremental embeddings (only new/changed symbols)
ai-memory embed --incremental
```

## Guidelines for AI Assistants

1. **Before answering questions**, use `ai-memory ask` or `ai-memory semantic` to get pre-computed context.
2. **When modifying code**, check `ai-memory review` to see which flows and communities are impacted.
3. **For new features**, consult `ai-memory communities` to find the right module to extend.
4. **For debugging**, use `ai-memory context <symbol>` to trace call chains from entry points.
5. **To find where code is tested**, use `ai-memory test-map`.
6. **To find public APIs**, use `ai-memory api`.
7. **To search by keyword**, use `ai-memory search "auth middleware"`.

## Project Structure (from ai-memory communities)

Check `ai-memory communities` for the latest module boundaries.

## Database Schemas

Check `ai-memory schemas` for SQL/migration definitions.
"""

CURSOR_RULES = """# AI-Memory: Codebase Knowledge Graph

This project uses `ai-memory` — a self-updating knowledge graph that scans the entire codebase into SQLite.

## Setup (run once per project)

```bash
ai-memory init    # creates config, .ai-memory/, adds to .gitignore
ai-memory scan    # full codebase scan (builds the graph)
ai-memory embed   # semantic embeddings for AI search
```

## MCP Server (if configured)

The MCP server exposes these tools:
- `ai_memory_scan` — refresh the graph
- `ai_memory_context` — symbol context with call graph
- `ai_memory_ask` — compact query context
- `ai_memory_semantic` — embedding-based search
- `ai_memory_flows` — execution flows from entry points
- `ai_memory_communities` — code modules/clusters
- `ai_memory_review` — impact analysis of recent changes
- `ai_memory_cycles` — circular dependency detection
- `ai_memory_inherits` — full inheritance chains
- `ai_memory_api` — public API surface
- `ai_memory_search` — full-text search
- `ai_memory_coverage` — code coverage overlay
- `ai_memory_deps` — dependency manifests

## CLI Commands

```bash
# Core
ai-memory init              # one-time project setup
ai-memory scan              # full codebase scan
ai-memory watch             # auto-update on file changes
ai-memory embed             # build semantic embeddings
ai-memory embed --incremental  # only new/changed symbols

# Symbol context
ai-memory context <symbol>  # symbol + call graph
ai-memory callers <symbol>  # reverse call graph
ai-memory inherits <class>  # full inheritance chain

# Search & discovery
ai-memory ask "<question>"  # natural language query
ai-memory semantic "<query>"  # embedding-based search
ai-memory search "<query>"  # full-text search

# Analysis
ai-memory cycles            # circular dependencies
ai-memory api               # public API surface
ai-memory dead-code         # unused symbols
ai-memory todos             # TODO/FIXME/HACK markers
ai-memory test-map          # test → implementation mapping

# Dependencies & coverage
ai-memory deps              # dependency manifests
ai-memory coverage          # load coverage data
ai-memory coverage-detail   # per-symbol coverage

# Structure
ai-memory flows             # execution flows
ai-memory communities       # code modules
ai-memory schemas           # database schemas
ai-memory review            # impact of recent changes
ai-memory graph [symbol]    # Mermaid/DOT export
```

## Best Practices

- Always consult the graph before large refactors.
- Check `ai-memory review` before committing to understand blast radius.
- Run `ai-memory scan` after adding new dependencies or major file moves.
- Use `ai-memory watch` during active development for incremental updates.
"""


def generate_windsurf_rules(root: Path) -> Path:
    """Write .windsurfrules to project root."""
    path = root / ".windsurfrules"
    path.write_text(WINDSURF_RULES)
    return path


def generate_cursor_rules(root: Path) -> Path:
    """Write .cursorrules to project root."""
    path = root / ".cursorrules"
    path.write_text(CURSOR_RULES)
    return path


def generate_all(root: Path) -> Dict[str, Path]:
    """Generate all IDE rule files."""
    return {
        "windsurf": generate_windsurf_rules(root),
        "cursor": generate_cursor_rules(root),
    }
