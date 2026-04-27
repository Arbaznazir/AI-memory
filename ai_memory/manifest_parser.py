"""Parse dependency manifests (requirements.txt, package.json, Cargo.toml, etc.)."""
import json
import re
from pathlib import Path
from typing import Dict, List

from .db import GraphDB


def parse_manifests(root: Path, db: GraphDB):
    """Discover and parse all dependency manifest files in the project."""
    # Clear old dependency entries before reparsing
    db.conn.execute("DELETE FROM dependencies")
    db.conn.commit()

    for f in root.rglob("*"):
        if not f.is_file():
            continue
        name = f.name.lower()
        if name == "requirements.txt":
            _parse_requirements_txt(f, db)
        elif name == "package.json":
            _parse_package_json(f, db)
        elif name == "cargo.toml":
            _parse_cargo_toml(f, db)
        elif name == "pyproject.toml":
            _parse_pyproject_toml(f, db)
        elif name == "go.mod":
            _parse_go_mod(f, db)


def _parse_requirements_txt(path: Path, db: GraphDB):
    """Parse requirements.txt format (pkg==1.0, pkg>=1.0, -r, comments)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # Match package name and optional version specifier
                m = re.match(r'^([a-zA-Z0-9_\-\.]+)(.*)', line)
                if m:
                    pkg = m.group(1)
                    spec = m.group(2).strip()
                    db.insert_dependency(pkg, spec or None, "python", str(path))
    except Exception:
        pass


def _parse_package_json(path: Path, db: GraphDB):
    """Parse package.json dependencies and devDependencies."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for dep_type in ("dependencies", "devDependencies"):
            deps = data.get(dep_type, {})
            is_dev = dep_type == "devDependencies"
            for name, version in deps.items():
                db.insert_dependency(name, version, "npm", str(path), is_dev)
    except Exception:
        pass


def _parse_cargo_toml(path: Path, db: GraphDB):
    """Parse Cargo.toml [dependencies] and [dev-dependencies]."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # Simple regex-based parsing for dependencies table
        for section in re.finditer(r'\[(dependencies|dev-dependencies)\](.*?)(?=\[|$)', content, re.DOTALL):
            is_dev = section.group(1) == "dev-dependencies"
            block = section.group(2)
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'^([a-zA-Z0-9_\-]+)\s*=\s*(.*)', line)
                if m:
                    name = m.group(1)
                    spec = m.group(2).strip().strip('"')
                    db.insert_dependency(name, spec or None, "cargo", str(path), is_dev)
    except Exception:
        pass


def _parse_pyproject_toml(path: Path, db: GraphDB):
    """Parse pyproject.toml [project.dependencies] and [tool.poetry.dependencies]."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # [project] dependencies
        m = re.search(r'\[project\].*?dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if m:
            for dep in re.findall(r'"([^"]+)"', m.group(1)):
                parts = dep.split(">=")
                name = parts[0].strip()
                version = parts[1].strip() if len(parts) > 1 else None
                db.insert_dependency(name, version, "python", str(path))
        # [tool.poetry.dependencies]
        m = re.search(r'\[tool\.poetry\.dependencies\](.*?)(?=\[|$)', content, re.DOTALL)
        if m:
            block = m.group(1)
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("python"):
                    continue
                name, _, spec = line.partition("=")
                name = name.strip()
                spec = spec.strip().strip('"')
                db.insert_dependency(name, spec or None, "python", str(path))
        # [tool.poetry.dev-dependencies] or [tool.poetry.group.dev.dependencies]
        m = re.search(r'\[tool\.poetry\.(dev-dependencies|group\.dev\.dependencies)\](.*?)(?=\[|$)', content, re.DOTALL)
        if m:
            block = m.group(2)
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, spec = line.partition("=")
                db.insert_dependency(name.strip(), spec.strip().strip('"') or None, "python", str(path), is_dev=True)
    except Exception:
        pass


def _parse_go_mod(path: Path, db: GraphDB):
    """Parse go.mod require statements."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for m in re.finditer(r'require\s*\((.*?)\)', content, re.DOTALL):
            block = m.group(1)
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    db.insert_dependency(parts[0], parts[1], "go", str(path))
    except Exception:
        pass
