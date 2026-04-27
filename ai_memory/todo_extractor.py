"""Extract TODO, FIXME, HACK, XXX, and other technical debt markers from source code."""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from .db import GraphDB
from .languages import detect_language

# Patterns per language for comment syntax
COMMENT_PATTERNS = {
    "python": [
        r'#\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'""".*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)"""',
        r"'''.*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)'''",
    ],
    "javascript": [
        r'//\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'/\*.*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)\*/',
    ],
    "typescript": [
        r'//\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'/\*.*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)\*/',
    ],
    "ruby": [
        r'#\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'=begin.*?\n\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)\n=end',
    ],
    "go": [
        r'//\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'/\*.*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)\*/',
    ],
    "rust": [
        r'//\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'/\*.*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)\*/',
    ],
    "java": [
        r'//\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'/\*.*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)\*/',
    ],
    "c_sharp": [
        r'//\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'/\*.*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)\*/',
    ],
    "c": [
        r'//\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'/\*.*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)\*/',
    ],
    "cpp": [
        r'//\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*)',
        r'/\*.*?(TODO|FIXME|HACK|XXX|BUG|NOTE|WARN|WARNING)\s*:?\s*(.*?)\*/',
    ],
}


@dataclass
class TodoItem:
    kind: str  # TODO, FIXME, etc.
    text: str
    file_path: str
    line: int
    column: int
    assignee: Optional[str] = None  # e.g. "TODO(john): fix this"


def extract_todos_from_file(path: Path, language: Optional[str] = None) -> List[TodoItem]:
    """Scan a single file for TODO/FIXME markers."""
    lang = language or detect_language(path)
    patterns = COMMENT_PATTERNS.get(lang, COMMENT_PATTERNS.get("python", []))
    
    if not patterns:
        return []
    
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    
    todos = []
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    
    for line_no, line in enumerate(content.splitlines(), 1):
        for pattern in compiled:
            for match in pattern.finditer(line):
                kind = match.group(1).upper()
                text = match.group(2).strip() if len(match.groups()) >= 2 else ""
                
                # Try to extract assignee: TODO(john): ...
                assignee = None
                assignee_match = re.match(r'\(([^)]+)\)\s*[:\-]?\s*(.*)', text)
                if assignee_match:
                    assignee = assignee_match.group(1)
                    text = assignee_match.group(2)
                
                todos.append(TodoItem(
                    kind=kind,
                    text=text,
                    file_path=str(path),
                    line=line_no,
                    column=match.start(),
                    assignee=assignee
                ))
    
    return todos


def extract_all_todos(root: Path, config: Optional[Dict] = None) -> List[TodoItem]:
    """Scan entire project for TODO/FIXME markers."""
    from .config import DEFAULT_CONFIG
    
    cfg = config or DEFAULT_CONFIG
    todos = []
    
    for ext in cfg.get("extensions", []):
        for path in root.rglob(f"*.{ext}"):
            if any(ign in str(path) for ign in cfg.get("ignore_patterns", [])):
                continue
            lang = detect_language(path)
            if lang:
                todos.extend(extract_todos_from_file(path, lang))
    
    return todos


def format_todos(todos: List[TodoItem]) -> str:
    """Format todo list as markdown."""
    if not todos:
        return "# Technical Debt\n\nNo TODOs, FIXMEs, or other markers found.\n"
    
    # Group by kind
    by_kind: Dict[str, List[TodoItem]] = {}
    for t in todos:
        by_kind.setdefault(t.kind, []).append(t)
    
    lines = ["# Technical Debt Summary", f"\n**Total markers:** {len(todos)}\n"]
    
    for kind, items in sorted(by_kind.items(), key=lambda x: -len(x[1])):
        lines.append(f"## {kind} ({len(items)})")
        for t in items:
            assignee_str = f" *@{t.assignee}*" if t.assignee else ""
            lines.append(f"- `{t.file_path}`:L{t.line}{assignee_str} — {t.text}")
        lines.append("")
    
    return "\n".join(lines)
