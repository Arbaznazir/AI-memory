"""Code coverage overlay: read coverage reports and mark symbols as tested/untested."""
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .db import GraphDB


COVERAGE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS coverage_status (
    file_path TEXT PRIMARY KEY,
    covered_lines TEXT,  -- JSON array of covered line numbers
    uncovered_lines TEXT,  -- JSON array of uncovered line numbers
    coverage_pct REAL DEFAULT 0.0,
    source TEXT  -- e.g. 'pytest', 'jest', 'go test'
);
"""


def init_coverage_table(db: GraphDB):
    """Create coverage tracking table."""
    db.conn.execute(COVERAGE_TABLE_SQL)
    db.conn.commit()


def read_coverage_json(path: Path) -> Optional[Dict]:
    """Read coverage.json (pytest-cov format)."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def parse_pytest_coverage(data: Dict, root: Path) -> Dict[str, Tuple[Set[int], Set[int]]]:
    """Parse pytest-cov coverage.json.
    
    Returns: {file_path: (covered_lines, uncovered_lines)}
    """
    result = {}
    files = data.get("files", {})
    
    for file_path, file_data in files.items():
        # file_data has "executed_lines" and "missing_lines"
        executed = set(file_data.get("executed_lines", []))
        missing = set(file_data.get("missing_lines", []))
        
        # Resolve path relative to root
        abs_path = Path(file_path)
        if not abs_path.is_absolute():
            abs_path = root / file_path
        
        result[str(abs_path)] = (executed, missing)
    
    return result


def parse_lcov(lcov_path: Path) -> Dict[str, Tuple[Set[int], Set[int]]]:
    """Parse lcov.info format (used by jest, nyc, etc.)."""
    result = {}
    current_file = None
    current_executed = set()
    current_missing = set()
    
    try:
        with open(lcov_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SF:"):
                    if current_file and current_executed:
                        all_lines = current_executed | current_missing
                        result[current_file] = (current_executed, current_missing)
                    current_file = line[3:]
                    current_executed = set()
                    current_missing = set()
                elif line.startswith("DA:"):
                    parts = line[3:].split(",")
                    line_no = int(parts[0])
                    hit_count = int(parts[1])
                    if hit_count > 0:
                        current_executed.add(line_no)
                    else:
                        current_missing.add(line_no)
            
            if current_file and current_executed:
                result[current_file] = (current_executed, current_missing)
    except FileNotFoundError:
        pass
    
    return result


def load_coverage(db: GraphDB, root: Path, coverage_file: Optional[Path] = None, source: str = "pytest") -> int:
    """Load coverage data into the database.
    
    Auto-detects coverage.json, lcov.info, or uses provided path.
    Returns number of files processed.
    """
    init_coverage_table(db)
    
    # Auto-detect coverage files
    if coverage_file is None:
        candidates = [
            root / "coverage.json",
            root / ".coverage" / "coverage.json",
            root / "coverage" / "coverage.json",
            root / "lcov.info",
            root / "coverage" / "lcov.info",
            root / "coverage" / "lcov-report" / "lcov.info",
        ]
        for c in candidates:
            if c.exists():
                coverage_file = c
                break
    
    if not coverage_file or not coverage_file.exists():
        return 0
    
    # Parse based on file type
    if coverage_file.name.endswith(".json"):
        data = read_coverage_json(coverage_file)
        if data:
            coverage_data = parse_pytest_coverage(data, root)
        else:
            return 0
    elif coverage_file.name == "lcov.info":
        coverage_data = parse_lcov(coverage_file)
    else:
        return 0
    
    # Store in DB
    count = 0
    for file_path, (executed, missing) in coverage_data.items():
        all_lines = executed | missing
        pct = len(executed) / len(all_lines) * 100 if all_lines else 0.0
        
        db.conn.execute(
            """
            INSERT OR REPLACE INTO coverage_status
            (file_path, covered_lines, uncovered_lines, coverage_pct, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                file_path,
                json.dumps(sorted(executed)),
                json.dumps(sorted(missing)),
                pct,
                source
            )
        )
        count += 1
    
    db.conn.commit()
    return count


def get_symbol_coverage(db: GraphDB, symbol_id: int) -> Optional[Dict]:
    """Get coverage status for a specific symbol."""
    cur = db.conn.execute(
        """
        SELECT n.*, f.path as file_path,
               cs.covered_lines, cs.uncovered_lines, cs.coverage_pct
        FROM nodes n
        JOIN files f ON n.file_id = f.id
        LEFT JOIN coverage_status cs ON cs.file_path = f.path
        WHERE n.id = ?
        """,
        (symbol_id,)
    )
    row = cur.fetchone()
    if not row:
        return None
    
    result = dict(row)
    
    # Calculate symbol-level coverage
    if result.get("covered_lines"):
        covered = set(json.loads(result["covered_lines"]))
        uncovered = set(json.loads(result.get("uncovered_lines", "[]")))
        symbol_lines = set(range(result["start_line"], result["end_line"] + 1))
        
        symbol_covered = symbol_lines & covered
        symbol_uncovered = symbol_lines & uncovered
        symbol_unknown = symbol_lines - covered - uncovered
        
        if symbol_lines:
            result["symbol_coverage_pct"] = len(symbol_covered) / len(symbol_lines) * 100
        else:
            result["symbol_coverage_pct"] = 0.0
        
        result["symbol_covered_lines"] = sorted(symbol_covered)
        result["symbol_uncovered_lines"] = sorted(symbol_uncovered)
        result["symbol_unknown_lines"] = sorted(symbol_unknown)
    else:
        result["symbol_coverage_pct"] = None
    
    return result


def get_coverage_summary(db: GraphDB) -> Dict:
    """Get overall coverage summary."""
    cur = db.conn.execute(
        """
        SELECT COUNT(*) as total_files,
               AVG(coverage_pct) as avg_coverage,
               SUM(CASE WHEN coverage_pct > 0 THEN 1 ELSE 0 END) as covered_files,
               SUM(CASE WHEN coverage_pct = 0 THEN 1 ELSE 0 END) as uncovered_files
        FROM coverage_status
        """
    )
    row = dict(cur.fetchone())
    
    # Count symbols with coverage data
    cur = db.conn.execute(
        """
        SELECT COUNT(*) as total_symbols,
               SUM(CASE WHEN cs.file_path IS NOT NULL THEN 1 ELSE 0 END) as symbols_with_coverage
        FROM nodes n
        JOIN files f ON n.file_id = f.id
        LEFT JOIN coverage_status cs ON cs.file_path = f.path
        WHERE n.type IN ('function', 'method', 'class')
        """
    )
    sym_row = dict(cur.fetchone())
    row.update(sym_row)
    
    return row


def format_coverage_summary(summary: Dict) -> str:
    """Format coverage summary as markdown."""
    lines = ["# Code Coverage Summary", ""]
    
    if not summary.get("total_files"):
        lines.append("No coverage data loaded.\n")
        lines.append("Run tests with coverage, then:\n")
        lines.append("```bash")
        lines.append("pytest --cov=. --cov-report=json:coverage.json")
        lines.append("ai-memory coverage")
        lines.append("```\n")
        return "\n".join(lines)
    
    lines.append(f"**Coverage files:** {summary['total_files']}")
    lines.append(f"**Avg file coverage:** {summary.get('avg_coverage', 0):.1f}%")
    lines.append(f"**Covered files:** {summary.get('covered_files', 0)}")
    lines.append(f"**Uncovered files:** {summary.get('uncovered_files', 0)}")
    lines.append(f"**Symbols with coverage:** {summary.get('symbols_with_coverage', 0)} / {summary.get('total_symbols', 0)}")
    lines.append("")
    
    return "\n".join(lines)
