"""Build structured LLM prompts with automatic token budgeting and relevance ranking.

Produces compact, well-formatted prompts that fit within typical LLM context windows.
"""
from typing import Dict, List, Optional, Any


def estimate_tokens(text: str) -> int:
    """Rough token count: ~4 chars per token (good enough for planning)."""
    return len(text) // 4


def _header(title: str) -> str:
    return f"# {title}\n\n"


def build_symbol_prompt(
    symbol_name: str,
    symbol_info: Dict[str, Any],
    callers: List[Dict],
    callees: List[Dict],
    file_context: str,
    docs: Optional[str] = None,
    max_tokens: int = 4000
) -> str:
    """Build a focused prompt about a single symbol with its call graph."""
    parts = []
    
    parts.append(_header(f"Context: {symbol_name}"))
    parts.append(f"**Type:** {symbol_info.get('type', 'unknown')}\n")
    parts.append(f"**Location:** {symbol_info.get('file_path', 'unknown')}:L{symbol_info.get('start_line', 0)}\n")
    
    if docs:
        parts.append(f"**Documentation:** {docs}\n\n")
    
    if file_context:
        parts.append(_header("File Context"))
        parts.append(file_context[:2000] + "\n\n")
    
    if callees:
        parts.append(_header("Calls (outgoing)"))
        for c in callees[:10]:
            parts.append(f"- `{c['target_name']}` ({c.get('target_file', 'unknown')})\n")
        if len(callees) > 10:
            parts.append(f"- ... ({len(callees) - 10} more)\n")
        parts.append("\n")
    
    if callers:
        parts.append(_header("Called by (incoming)"))
        for c in callers[:10]:
            parts.append(f"- `{c.get('caller_name', c.get('source_name', 'unknown'))}` ({c.get('caller_file', 'unknown')}:L{c.get('caller_line', 0)})\n")
        if len(callers) > 10:
            parts.append(f"- ... ({len(callers) - 10} more)\n")
        parts.append("\n")
    
    prompt = "".join(parts)
    
    # Trim if over budget
    if estimate_tokens(prompt) > max_tokens:
        cutoff = max_tokens * 4
        prompt = prompt[:cutoff] + "\n\n... (truncated for token limit)\n"
    
    return prompt


def build_query_prompt(
    query: str,
    relevant_symbols: List[Dict],
    relevant_files: List[str],
    schemas: List[Dict],
    flows: List[Dict],
    max_tokens: int = 4000
) -> str:
    """Build a prompt answering a natural language query about the codebase."""
    parts = []
    
    parts.append(_header(f"Query: {query}"))
    parts.append("You are an expert software engineer. Use the provided codebase context to answer the query accurately and concisely.\n\n")
    
    if schemas:
        parts.append(_header("Relevant Schemas"))
        for s in schemas[:5]:
            parts.append(f"- `{s.get('table_name', 'unknown')}` ({s.get('kind', 'unknown')}): {str(s.get('definition', ''))[:100]}\n")
        parts.append("\n")
    
    if flows:
        parts.append(_header("Relevant Execution Flows"))
        for f in flows[:3]:
            parts.append(f"- **{f.get('name', 'unknown')}**: {f.get('node_count', 0)} nodes, {f.get('file_count', 0)} files\n")
        parts.append("\n")
    
    if relevant_symbols:
        parts.append(_header("Relevant Symbols"))
        for sym in relevant_symbols[:15]:
            sig = str(sym.get('signature', ''))[:60]
            parts.append(f"- `{sym.get('type', 'unknown')}` **{sym.get('name', 'unknown')}** `{sig}` ({sym.get('file_path', 'unknown')}:L{sym.get('start_line', 0)})\n")
            if sym.get('doc'):
                doc = str(sym['doc'])[:80].replace('\n', ' ')
                parts.append(f"  - {doc}\n")
        if len(relevant_symbols) > 15:
            parts.append(f"- ... ({len(relevant_symbols) - 15} more)\n")
        parts.append("\n")
    
    if relevant_files:
        parts.append(_header("Relevant Files"))
        for f in relevant_files[:5]:
            parts.append(f"- `{f}`\n")
        parts.append("\n")
    
    parts.append("---\n\n")
    parts.append("Please answer the query based on the context above. Be specific with file names, function names, and line numbers when possible.\n")
    
    prompt = "".join(parts)
    
    if estimate_tokens(prompt) > max_tokens:
        cutoff = max_tokens * 4
        prompt = prompt[:cutoff] + "\n\n... (truncated for token limit)\n"
    
    return prompt


def build_impact_prompt(
    changed_files: List[str],
    impacted_flows: List[Dict],
    impacted_communities: List[Dict],
    impacted_symbols: List[Dict],
    max_tokens: int = 4000
) -> str:
    """Build a prompt for reviewing code changes and their impact."""
    parts = []
    
    parts.append(_header("Code Change Impact Review"))
    parts.append("You are reviewing a code change. Below are the files changed and their impact on the codebase.\n\n")
    
    parts.append(_header("Changed Files"))
    for f in changed_files[:20]:
        parts.append(f"- `{f}`\n")
    if len(changed_files) > 20:
        parts.append(f"- ... ({len(changed_files) - 20} more)\n")
    parts.append("\n")
    
    if impacted_communities:
        parts.append(_header("Impacted Modules"))
        for c in impacted_communities[:5]:
            parts.append(f"- **{c.get('name', 'unknown')}** ({c.get('size', 0)} symbols, cohesion: {c.get('cohesion', 0)})\n")
        parts.append("\n")
    
    if impacted_flows:
        parts.append(_header("Impacted Execution Flows"))
        for f in impacted_flows[:5]:
            parts.append(f"- **{f.get('name', 'unknown')}**: {f.get('node_count', 0)} nodes, {f.get('file_count', 0)} files\n")
        parts.append("\n")
    
    if impacted_symbols:
        parts.append(_header("Impacted Symbols"))
        for sym in impacted_symbols[:15]:
            parts.append(f"- `{sym.get('type', 'unknown')}` **{sym.get('name', 'unknown')}** ({sym.get('file_path', 'unknown')})\n")
        if len(impacted_symbols) > 15:
            parts.append(f"- ... ({len(impacted_symbols) - 15} more)\n")
        parts.append("\n")
    
    parts.append("---\n\n")
    parts.append("Please review the impact of these changes. Identify potential risks, suggest tests to run, and note if cross-module coupling seems unexpected.\n")
    
    prompt = "".join(parts)
    
    if estimate_tokens(prompt) > max_tokens:
        cutoff = max_tokens * 4
        prompt = prompt[:cutoff] + "\n\n... (truncated for token limit)\n"
    
    return prompt
