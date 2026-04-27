"""CLI entrypoints for ai-memory."""
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .db import GraphDB
from .config import load_config, DEFAULT_CONFIG
from .scanner import full_scan, scan_file
from .watcher import watch_project
from .formatter import (
    file_summary, symbol_context, project_overview, schema_overview,
    query_context, flows_overview, communities_overview
)
from .embeddings import build_embeddings, semantic_search
from .git_review import review as review_diff
from .dead_code import find_dead_code
from .rules_generator import generate_all
from .callers import find_callers, build_reverse_call_graph
from .todo_extractor import extract_all_todos, format_todos
from .test_mapper import map_all_tests, format_test_map
from .graph_export import export_mermaid_flow, export_mermaid_call_graph, export_dot_communities, export_mermaid_project
from .cycles import find_all_cycles, format_cycles
from .inheritance import get_inheritance_chain, format_inheritance_chain
from .api_surface import detect_api_surface, format_api_surface
from .fts_search import init_fts, search_fts, format_search_results, rebuild_fts
from .coverage_overlay import load_coverage, get_coverage_summary, format_coverage_summary

console = Console()


def _ensure_db(root: Path) -> GraphDB:
    config = load_config(root)
    db_dir = config["db_path"].parent
    db_dir.mkdir(parents=True, exist_ok=True)
    return GraphDB(config["db_path"])


def _add_to_gitignore(root: Path, pattern: str = ".ai-memory/"):
    gitignore = root / ".gitignore"
    content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if pattern not in content:
        with open(gitignore, "a", encoding="utf-8") as f:
            f.write(f"\n{pattern}\n")


@click.group()
@click.option("--root", "-r", type=click.Path(), default=".", help="Project root directory")
@click.pass_context
def cli(ctx, root):
    ctx.ensure_object(dict)
    ctx.obj["root"] = Path(root).resolve()


@cli.command()
@click.pass_context
def scan(ctx):
    """Full scan of the codebase."""
    root = ctx.obj["root"]
    config = load_config(root)
    with _ensure_db(root) as db:
        console.print(f"[blue]Scanning {root}...[/blue]")
        scanned, changed = full_scan(root, db, config)
        stats = db.get_stats()
        console.print(Panel.fit(
            f"[green]Scanned {scanned} files ({changed} changed)[/green]\n"
            f"Files: {stats['files']}, Nodes: {stats['nodes']}, Edges: {stats['edges']}, Schemas: {stats['schemas']}",
            title="Scan Complete"
        ))


@cli.command()
@click.argument("path")
@click.pass_context
def update(ctx, path):
    """Update a single file in the graph."""
    root = ctx.obj["root"]
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    with _ensure_db(root) as db:
        if scan_file(target, db):
            console.print(f"[green]Updated {path}[/green]")
        else:
            console.print(f"[dim]{path} unchanged or unsupported[/dim]")


@cli.command()
@click.pass_context
def init(ctx):
    """Initialize ai-memory for this project: create config, .ai-memory/, add to .gitignore."""
    root = ctx.obj["root"]
    config_path = root / ".ai-memory.toml"
    ai_dir = root / ".ai-memory"
    ai_dir.mkdir(exist_ok=True)

    if not config_path.exists():
        import toml
        cfg = dict(DEFAULT_CONFIG)
        cfg.pop("db_path", None)
        with open(config_path, "w") as f:
            toml.dump(cfg, f)
        console.print(f"[green]Created {config_path}[/green]")
    else:
        console.print(f"[dim]{config_path} already exists[/dim]")

    _add_to_gitignore(root)
    console.print(f"[green]Added .ai-memory/ to .gitignore[/green]")

    # Generate IDE rules so AI knows to use ai-memory
    paths = generate_all(root)
    for name, path in paths.items():
        console.print(f"[green]Generated {name} rules: {path}[/green]")

    console.print("[blue]Next: run `ai-memory scan` to build the graph.[/blue]")


@cli.command()
@click.pass_context
def stats(ctx):
    """Show project graph statistics."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        console.print(project_overview(db))


@cli.command()
@click.argument("query")
@click.option("--depth", "-d", default=2, help="Context depth")
@click.pass_context
def context(ctx, query, depth):
    """Show AI-optimized context for a symbol."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        console.print(symbol_context(db, query, max_depth=depth))


@cli.command()
@click.argument("file_path")
@click.pass_context
def file(ctx, file_path):
    """Show summary for a file."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        console.print(file_summary(db, file_path))


@cli.command()
@click.pass_context
def schemas(ctx):
    """Show all database schemas."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        console.print(schema_overview(db))


@cli.command()
@click.argument("query")
@click.option("--tokens", "-t", default=4000, help="Max token estimate")
@click.pass_context
def ask(ctx, query, tokens):
    """Generate compact context for an AI query."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        result = query_context(db, query, max_tokens=tokens)
        console.print(result)


@cli.command()
@click.argument("name")
@click.pass_context
def find(ctx, name):
    """Find symbols by name."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        nodes = db.search_nodes(name, limit=20)
        table = Table(title=f"Symbols matching '{name}'")
        table.add_column("Type", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("File", style="dim")
        table.add_column("Line", style="magenta")
        for n in nodes:
            table.add_row(n["type"], n["name"], n.get("file_path", ""), str(n["start_line"]))
        console.print(table)


@cli.command()
@click.pass_context
def flows(ctx):
    """Show pre-computed execution flows."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        console.print(flows_overview(db))


@cli.command()
@click.pass_context
def communities(ctx):
    """Show detected code communities/modules."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        console.print(communities_overview(db))


@cli.command()
@click.pass_context
def watch(ctx):
    """Watch files for changes and auto-update the graph (daemon mode)."""
    root = ctx.obj["root"]
    config = load_config(root)
    db_path = config["db_path"]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with GraphDB(db_path) as db:
        watch_project(root, db, config)


@cli.command()
@click.option("--incremental", "-i", is_flag=True, help="Only embed new/changed symbols")
@click.pass_context
def embed(ctx, incremental):
    """Build semantic embeddings for all symbols."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        if incremental:
            console.print("[blue]Running incremental embedding...[/blue]")
        else:
            console.print("[blue]Building embeddings...[/blue]")
        try:
            count = build_embeddings(db, incremental=incremental)
            console.print(f"[green]Embedded {count} symbols[/green]")
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=10, help="Max results")
@click.pass_context
def semantic(ctx, query, limit):
    """Semantic search for symbols."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        try:
            results = semantic_search(db, query, limit=limit)
            if not results:
                console.print("[yellow]No embeddings found. Run `ai-memory embed` first.[/yellow]")
                return
            table = Table(title=f"Semantic search: '{query}'")
            table.add_column("Score", style="cyan", justify="right")
            table.add_column("Type", style="blue")
            table.add_column("Name", style="green")
            table.add_column("File", style="dim")
            for node, score in results:
                table.add_row(f"{score:.3f}", node["type"], node["name"], node.get("file_path", ""))
            console.print(table)
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")


@cli.command()
@click.option("--base", "-b", default="HEAD~1", help="Git base ref for diff")
@click.pass_context
def review(ctx, base):
    """Review git diff impact on flows and communities."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        console.print(f"[blue]Analyzing changes since {base}...[/blue]")
        result = review_diff(root, db, base)
        console.print(result)


@cli.command()
@click.pass_context
def dead_code(ctx):
    """Find potentially unused symbols (zero incoming references)."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        dead = find_dead_code(db)
        if not dead:
            console.print("[green]No dead code detected![/green]")
            return
        table = Table(title=f"Potentially Unused Symbols ({len(dead)} found)")
        table.add_column("Type", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("File", style="dim")
        table.add_column("Line", style="magenta")
        for n in dead[:50]:
            table.add_row(n["type"], n["name"], n.get("file_path", ""), str(n["start_line"]))
        console.print(table)
        if len(dead) > 50:
            console.print(f"[dim]... and {len(dead) - 50} more[/dim]")


@cli.command()
@click.pass_context
def rules(ctx):
    """Generate .windsurfrules and .cursorrules for IDE integration."""
    root = ctx.obj["root"]
    paths = generate_all(root)
    console.print(Panel.fit(
        f"[green]Generated IDE integration files:[/green]\n"
        f"  - {paths['windsurf']}\n"
        f"  - {paths['cursor']}",
        title="ai-memory rules"
    ))


@cli.command()
@click.pass_context
def mcp(ctx):
    """Run MCP server over stdio for native IDE integration."""
    root = ctx.obj["root"]
    from .mcp_server import serve
    serve(root)


@cli.command()
@click.argument("symbol")
@click.option("--depth", "-d", default=2, help="Reverse depth")
@click.pass_context
def callers(ctx, symbol, depth):
    """Show reverse call graph — who calls this symbol."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        callers_list = find_callers(db, symbol)
        if not callers_list:
            console.print(f"[yellow]No callers found for '{symbol}'[/yellow]")
            return
        table = Table(title=f"Callers of '{symbol}'")
        table.add_column("Caller", style="green")
        table.add_column("Type", style="cyan")
        table.add_column("File", style="dim")
        table.add_column("Line", style="magenta")
        for c in callers_list:
            table.add_row(
                c.get("caller_name", c.get("source_name", "?")),
                c.get("caller_type", "?"),
                c.get("caller_file", "?"),
                str(c.get("caller_line", "?"))
            )
        console.print(table)


@cli.command()
@click.pass_context
def todos(ctx):
    """Extract TODO, FIXME, HACK, XXX markers from the codebase."""
    root = ctx.obj["root"]
    config = load_config(root)
    items = extract_all_todos(root, config)
    console.print(format_todos(items))


@cli.command()
@click.pass_context
def test_map(ctx):
    """Map test functions to their implementation targets."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        mappings = map_all_tests(db)
        console.print(format_test_map(mappings))


@cli.command()
@click.argument("symbol", required=False)
@click.option("--format", "-f", type=click.Choice(["mermaid", "dot"]), default="mermaid", help="Output format")
@click.option("--flow-id", "-i", type=int, default=None, help="Export specific flow ID")
@click.pass_context
def graph(ctx, symbol, format, flow_id):
    """Export call graph or community graph as Mermaid or DOT."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        if flow_id:
            text = export_mermaid_flow(flow_id, db)
        elif symbol:
            if format == "mermaid":
                text = export_mermaid_call_graph(symbol, db)
            else:
                console.print("[red]DOT format for single symbol not yet supported. Use --format mermaid.[/red]")
                return
        else:
            if format == "mermaid":
                text = export_mermaid_project(db)
            else:
                text = export_dot_communities(db)
        console.print(text)


@cli.command()
@click.pass_context
def cycles(ctx):
    """Find circular dependencies in import and call graphs."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        cycles = find_all_cycles(db)
        console.print(format_cycles(cycles))


@cli.command()
@click.argument("class_name")
@click.pass_context
def inherits(ctx, class_name):
    """Show full inheritance chain for a class (ancestors, descendants, siblings)."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        chain = get_inheritance_chain(db, class_name)
        console.print(format_inheritance_chain(chain))


@cli.command()
@click.pass_context
def api(ctx):
    """Detect public API surface from __init__.py, index.js, lib.rs exports."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        surface = detect_api_surface(db, root)
        console.print(format_api_surface(surface))


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=20, help="Max results")
@click.pass_context
def search(ctx, query, limit):
    """Full-text search over symbol names, signatures, and docstrings."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        init_fts(db)
        results = search_fts(db, query, limit=limit)
        console.print(format_search_results(results, query))


@cli.command()
@click.option("--file", "-f", type=click.Path(), default=None, help="Coverage file path (auto-detected if omitted)")
@click.option("--source", "-s", default="pytest", help="Coverage source: pytest, jest, go")
@click.pass_context
def coverage(ctx, file, source):
    """Load code coverage data and show summary."""
    root = ctx.obj["root"]
    coverage_path = Path(file) if file else None
    with _ensure_db(root) as db:
        count = load_coverage(db, root, coverage_path, source)
        if count > 0:
            console.print(f"[green]Loaded coverage for {count} files[/green]")
        else:
            console.print("[yellow]No coverage data found.[/yellow]")
            console.print("Run: pytest --cov=. --cov-report=json:coverage.json")
        summary = get_coverage_summary(db)
        console.print(format_coverage_summary(summary))


@cli.command()
@click.pass_context
def coverage_detail(ctx):
    """Show per-symbol coverage status."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        from .coverage_overlay import get_symbol_coverage
        cur = db.conn.execute(
            "SELECT n.id, n.name, n.type, n.start_line, n.end_line, f.path as file_path, "
            "cs.covered_lines, cs.uncovered_lines, cs.coverage_pct "
            "FROM nodes n JOIN files f ON n.file_id = f.id "
            "LEFT JOIN coverage_status cs ON cs.file_path = f.path "
            "WHERE n.type IN ('function', 'method', 'class') AND cs.file_path IS NOT NULL "
            "ORDER BY cs.coverage_pct ASC LIMIT 50"
        )
        rows = [dict(r) for r in cur.fetchall()]
        if not rows:
            console.print("[yellow]No coverage data. Run `ai-memory coverage` first.[/yellow]")
            return
        table = Table(title="Symbol Coverage (Least Covered First)")
        table.add_column("Symbol", style="green")
        table.add_column("Type", style="cyan")
        table.add_column("File", style="dim")
        table.add_column("Coverage", style="magenta")
        for r in rows:
            cov = r.get("coverage_pct", 0) or 0
            table.add_row(r["name"], r["type"], r["file_path"].split("/")[-1], f"{cov:.1f}%")
        console.print(table)


@cli.command()
@click.option("--type", "-t", default=None, help="Filter by dependency type (python, npm, cargo, go)")
@click.pass_context
def deps(ctx, type):
    """List project dependencies from manifest files."""
    root = ctx.obj["root"]
    with _ensure_db(root) as db:
        dependencies = db.get_dependencies(dep_type=type)
        if not dependencies:
            console.print("[yellow]No dependencies found.[/yellow]")
            return
        table = Table(title="Project Dependencies")
        table.add_column("Name", style="green")
        table.add_column("Version", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Manifest", style="dim")
        table.add_column("Dev", style="yellow")
        for d in dependencies:
            table.add_row(
                d["name"],
                d.get("version") or "-",
                d.get("dep_type") or "-",
                d.get("manifest_file", "").split("/")[-1],
                "yes" if d.get("is_dev") else "no"
            )
        console.print(table)


if __name__ == "__main__":
    cli()
