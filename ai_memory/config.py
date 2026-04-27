import os
import toml
from pathlib import Path
from typing import Dict, List, Set

DEFAULT_CONFIG = {
    "project_name": "",
    "scan_dirs": ["src", "lib", "app", "models", "controllers", "services", "db", "migrations", "schema"],
    "extensions": [
        ".py", ".js", ".ts", ".tsx", ".jsx", ".rb", ".go", ".rs",
        ".java", ".cs", ".c", ".cpp", ".h", ".hpp", ".sql",
        ".yaml", ".yml", ".json", ".toml", ".proto", ".graphql"
    ],
    "ignore_patterns": [
        "node_modules", "venv", ".git", "__pycache__", ".idea",
        "dist", "build", "target", "vendor", ".pytest_cache",
        "*.min.js", "*.min.css", "*.map"
    ],
    "output_format": "markdown",
    "max_context_tokens": 4000,
    "db_path": ".ai-memory/graph.db"
}


def load_config(root: Path) -> Dict:
    config_path = root / ".ai-memory.toml"
    if config_path.exists():
        user_config = toml.load(config_path)
        config = {**DEFAULT_CONFIG, **user_config}
    else:
        config = dict(DEFAULT_CONFIG)
    config["root"] = root
    config["db_path"] = root / config["db_path"]
    return config
