"""Git diff scanner: analyze impact of recent changes on flows and communities."""
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .db import GraphDB


def get_changed_files(root: Path, base: str = "HEAD~1") -> List[str]:
    """Get list of changed files from git diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}..HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True
        )
        return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    except subprocess.CalledProcessError:
        return []
    except FileNotFoundError:
        return []


def get_diff_stats(root: Path, base: str = "HEAD~1") -> Dict[str, Tuple[int, int]]:
    """Get diff stats per file: (insertions, deletions)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--numstat", f"{base}..HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True
        )
        stats = {}
        for line in result.stdout.strip().split("\n"):
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                insertions = int(parts[0]) if parts[0].isdigit() else 0
                deletions = int(parts[1]) if parts[1].isdigit() else 0
                path = parts[2]
                stats[path] = (insertions, deletions)
        return stats
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return {}


def analyze_impact(db: GraphDB, changed_files: List[str], root: Path) -> Dict:
    """Analyze which nodes, flows, and communities are impacted by changed files."""
    
    # Find nodes in changed files
    impacted_nodes: List[Dict] = []
    for file_path in changed_files:
        # Try relative path
        file_row = db.get_file_by_path(file_path)
        if not file_row:
            # Try absolute-ish
            abs_path = str(root / file_path)
            file_row = db.get_file_by_path(abs_path)
        
        if file_row:
            nodes = db.get_nodes_by_file(file_row["id"])
            impacted_nodes.extend(nodes)
    
    # Find flows that pass through impacted nodes
    impacted_flows: List[Dict] = []
    if impacted_nodes:
        node_ids = {n["id"] for n in impacted_nodes}
        
        # Check all flows for overlap
        flows = db.get_flows(limit=200)
        for flow in flows:
            steps = json.loads(flow["steps"])
            for step in steps:
                if step["id"] in node_ids:
                    impacted_flows.append(flow)
                    break
    
    # Find impacted communities
    impacted_communities: Set[int] = set()
    for node in impacted_nodes:
        comm = db.get_node_community(node["id"])
        if comm:
            impacted_communities.add(comm["id"])
    
    return {
        "changed_files": changed_files,
        "impacted_nodes": impacted_nodes,
        "impacted_flows": impacted_flows,
        "impacted_communities": list(impacted_communities),
        "node_count": len(impacted_nodes),
        "flow_count": len(impacted_flows),
        "community_count": len(impacted_communities),
    }


def format_review(report: Dict, diff_stats: Dict[str, Tuple[int, int]]) -> str:
    """Format impact report as markdown."""
    lines = [
        "# Code Review Impact Analysis",
        "",
        f"- **Changed files:** {len(report['changed_files'])}",
        f"- **Impacted symbols:** {report['node_count']}",
        f"- **Impacted execution flows:** {report['flow_count']}",
        f"- **Impacted communities:** {report['community_count']}",
        "",
    ]
    
    # Changed files with stats
    lines.append("## Changed Files")
    for f in report["changed_files"]:
        ins, dels = diff_stats.get(f, (0, 0))
        lines.append(f"- `{f}` (+{ins}/-{dels})")
    lines.append("")
    
    # Impacted symbols
    if report["impacted_nodes"]:
        lines.append("## Impacted Symbols")
        for n in report["impacted_nodes"][:30]:
            lines.append(f"- `{n['type']}` **{n['name']}** ({n.get('file_path', '')}:L{n['start_line']})")
        if len(report["impacted_nodes"]) > 30:
            lines.append(f"- ... ({len(report['impacted_nodes']) - 30} more)")
        lines.append("")
    
    # Impacted flows
    if report["impacted_flows"]:
        lines.append("## Impacted Execution Flows")
        for flow in report["impacted_flows"][:15]:
            lines.append(f"- **{flow['name']}** — {flow['node_count']} nodes, {flow['file_count']} files")
        if len(report["impacted_flows"]) > 15:
            lines.append(f"- ... ({len(report['impacted_flows']) - 15} more)")
        lines.append("")
    
    # Recommendations
    lines.append("## Recommendations")
    if report["flow_count"] > 0:
        lines.append("- **Run tests** for the impacted execution flows above.")
    if report["community_count"] > 1:
        lines.append("- **Cross-community coupling detected** — changes span multiple modules. Consider if this coupling is intentional.")
    if not report["impacted_flows"]:
        lines.append("- No execution flows impacted — changes may be isolated or in dead code.")
    
    return "\n".join(lines)


def review(root: Path, db: GraphDB, base: str = "HEAD~1") -> str:
    """Run full review: git diff + impact analysis."""
    changed = get_changed_files(root, base)
    if not changed:
        return "# No changes detected\n\nNo files changed in the specified range.\n"
    
    stats = get_diff_stats(root, base)
    report = analyze_impact(db, changed, root)
    return format_review(report, stats)
