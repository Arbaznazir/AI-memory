"""Language detection and tree-sitter parser loading."""
from pathlib import Path
from typing import Optional, Dict, Any
from tree_sitter import Language, Parser

LANG_MAP: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rb": "ruby",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "c_sharp",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".proto": "proto",
    ".graphql": "graphql",
}

_PARSERS: Dict[str, Any] = {}


def detect_language(file_path: Path) -> Optional[str]:
    return LANG_MAP.get(file_path.suffix.lower())


def get_parser(lang: str):
    if lang in _PARSERS:
        return _PARSERS[lang]

    from tree_sitter import Language, Parser

    # Lazy load language libraries
    lib_map = {
        "python": ("tree_sitter_python", "language"),
        "javascript": ("tree_sitter_javascript", "language"),
        "typescript": ("tree_sitter_typescript", "language_typescript"),
        "ruby": ("tree_sitter_ruby", "language"),
        "go": ("tree_sitter_go", "language"),
        "rust": ("tree_sitter_rust", "language"),
        "java": ("tree_sitter_java", "language"),
        "c_sharp": ("tree_sitter_c_sharp", "language"),
        "c": ("tree_sitter_c", "language"),
        "cpp": ("tree_sitter_cpp", "language"),
    }

    if lang not in lib_map:
        return None

    mod_name, attr = lib_map[lang]
    try:
        mod = __import__(mod_name, fromlist=[attr])
        capsule = getattr(mod, attr)()
        lang_obj = Language(capsule)
        parser = Parser(lang_obj)
        _PARSERS[lang] = parser
        return parser
    except Exception:
        return None
