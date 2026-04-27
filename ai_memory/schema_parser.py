"""Parse SQL and migration files for schema definitions."""
import re
from typing import List, Dict


def parse_schema_file(content: str, file_path: str) -> List[Dict]:
    results: List[Dict] = []
    lines = content.splitlines()
    in_table = False
    table_name = ""
    definition_lines: List[str] = []
    start_line = 0

    # Regex patterns
    create_table_re = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`?([^`\s]+)`?\.)?`?([^`(\s]+)`?",
        re.IGNORECASE
    )
    create_index_re = re.compile(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`?([^`\s]+)`?\.)?`?([^`(\s]+)`?",
        re.IGNORECASE
    )
    alter_table_re = re.compile(
        r"ALTER\s+TABLE\s+(?:`?([^`\s]+)`?\.)?`?([^`(\s]+)`?",
        re.IGNORECASE
    )

    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("--") or stripped.startswith("/*"):
            continue

        # CREATE TABLE
        m = create_table_re.search(stripped)
        if m:
            schema = m.group(1) or "public"
            table = m.group(2)
            in_table = True
            table_name = table
            definition_lines = [stripped]
            start_line = idx
            continue

        if in_table:
            definition_lines.append(stripped)
            if stripped.rstrip().endswith(";"):
                results.append({
                    "db_type": "sql",
                    "schema_name": schema,
                    "table_name": table_name,
                    "definition": "\n".join(definition_lines),
                    "kind": "table",
                    "line_start": start_line,
                    "line_end": idx
                })
                in_table = False
                table_name = ""
                definition_lines = []
            continue

        # CREATE INDEX
        m = create_index_re.search(stripped)
        if m:
            schema = m.group(1) or "public"
            index_name = m.group(2)
            results.append({
                "db_type": "sql",
                "schema_name": schema,
                "table_name": index_name,
                "definition": stripped,
                "kind": "index",
                "line_start": idx,
                "line_end": idx
            })
            continue

        # ALTER TABLE
        m = alter_table_re.search(stripped)
        if m:
            schema = m.group(1) or "public"
            table = m.group(2)
            results.append({
                "db_type": "sql",
                "schema_name": schema,
                "table_name": table,
                "definition": stripped,
                "kind": "alter",
                "line_start": idx,
                "line_end": idx
            })
            continue

    return results
