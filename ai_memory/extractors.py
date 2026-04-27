"""AST extractors: pull symbols, calls, imports from tree-sitter trees."""
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class Symbol:
    type: str  # function, class, method, interface, enum, variable, import
    name: str
    qualified_name: Optional[str]
    signature: Optional[str]
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    doc: Optional[str]
    body: Optional[str] = None
    type_annotations: Optional[str] = None
    meta: Optional[Dict] = None


@dataclass
class Relation:
    source_name: str  # which symbol this relation originates from
    target_name: str
    target_file: Optional[str]
    type: str  # calls, imports, inherits, implements, references
    line: int
    meta: Optional[Dict]


def _node_text(node, code: bytes) -> str:
    return code[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _extract_body(node, code: bytes) -> Optional[str]:
    """Extract full text of a node (function/class body)."""
    return code[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _extract_python_type_annotations(node, code: bytes) -> Optional[str]:
    """Extract Python type hints from function parameters and return type."""
    parts = []
    params_node = node.child_by_field_name("parameters")
    if params_node:
        for child in params_node.children:
            if child.type == "typed_parameter":
                parts.append(_node_text(child, code))
            elif child.type == "typed_default_parameter":
                parts.append(_node_text(child, code))
            elif child.type in ("identifier", "list_splat_pattern", "dictionary_splat_pattern"):
                parts.append(_node_text(child, code))
    return_type = node.child_by_field_name("return_type")
    if return_type:
        parts.append("-> " + _node_text(return_type, code))
    return " | ".join(parts) if parts else None


def _extract_js_type_annotations(node, code: bytes) -> Optional[str]:
    """Extract TypeScript/JSDoc type annotations."""
    parts = []
    params_node = node.child_by_field_name("parameters")
    if params_node:
        for child in params_node.children:
            if child.type in ("identifier", "required_parameter", "optional_parameter"):
                parts.append(_node_text(child, code))
    return_type = node.child_by_field_name("return_type")
    if return_type:
        parts.append(": " + _node_text(return_type, code))
    return " | ".join(parts) if parts else None


def _extract_doc(node, code: bytes) -> Optional[str]:
    """Try to find docstring inside a function/class body."""
    body = node.child_by_field_name("body")
    if not body:
        return None
    for child in body.children:
        if child.type == "expression_statement":
            for inner in child.children:
                if inner.type in ("string", "string_literal", "concatenated_string"):
                    return _node_text(inner, code).strip("'\"\"")
        # Stop at first non-docstring statement
        if child.type not in ("pass_statement", "expression_statement", "string"):
            break
    return None


def _extract_preceding_comment(node, code: bytes) -> Optional[str]:
    """Extract JSDoc / block comment preceding a node."""
    # Walk siblings before this node in the parent's children
    parent = node.parent
    if not parent:
        return None
    idx = -1
    for i, child in enumerate(parent.children):
        if child == node or (child.start_byte == node.start_byte and child.end_byte == node.end_byte):
            idx = i
            break
    if idx < 0:
        return None
    # Look backwards for comment nodes
    comments = []
    for i in range(idx - 1, -1, -1):
        sibling = parent.children[i]
        if sibling.type in ("comment", "line_comment", "block_comment"):
            text = _node_text(sibling, code).strip()
            comments.insert(0, text)
        elif sibling.type == "decorator":
            continue
        else:
            break
    if comments:
        return "\n".join(comments)
    return None


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


class PythonExtractor:
    @staticmethod
    def extract(tree, code: bytes, file_path: str) -> Tuple[List[Symbol], List[Relation]]:
        symbols: List[Symbol] = []
        relations: List[Relation] = []

        def _extract(node, scope_stack: List[Tuple[str, str]]):
            # Unwrap decorated definitions
            actual = node
            if node.type == "decorated_definition":
                for child in node.children:
                    if child.type in ("function_definition", "class_definition"):
                        actual = child
                        break

            if actual.type == "function_definition":
                name_node = actual.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, code)
                    qname = ".".join([n for _, n in scope_stack] + [name])
                    sig = _node_text(actual, code).split(":")[0]
                    
                    # Capture decorators if this was wrapped in decorated_definition
                    decorators = []
                    if node.type == "decorated_definition":
                        for dec in node.children:
                            if dec.type == "decorator":
                                decorators.append(_node_text(dec, code))
                    
                    doc = _extract_doc(actual, code)
                    body = _extract_body(actual, code)
                    types = _extract_python_type_annotations(actual, code)
                    sym = Symbol(
                        type="method" if scope_stack and scope_stack[-1][0] == "class" else "function",
                        name=name,
                        qualified_name=qname,
                        signature=sig,
                        start_line=name_node.start_point[0] + 1,
                        end_line=actual.end_point[0] + 1,
                        start_col=name_node.start_point[1],
                        end_col=actual.end_point[1],
                        doc=doc,
                        body=body,
                        type_annotations=types,
                        meta={"file": file_path, "decorators": decorators}
                    )
                    symbols.append(sym)

                    # calls inside body
                    body = actual.child_by_field_name("body")
                    if body:
                        for n in _walk(body):
                            if n.type == "call":
                                func_node = n.child_by_field_name("function")
                                if func_node:
                                    call_name = _node_text(func_node, code)
                                    relations.append(Relation(
                                        source_name=qname,
                                        target_name=call_name,
                                        target_file=None,
                                        type="calls",
                                        line=func_node.start_point[0] + 1,
                                        meta=None
                                    ))

                    # recurse into body with new scope
                    if body:
                        new_scope = scope_stack + [("function", name)]
                        for child in body.children:
                            _extract(child, new_scope)
                return

            if actual.type == "class_definition":
                name_node = actual.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, code)
                    qname = ".".join([n for _, n in scope_stack] + [name])
                    
                    decorators = []
                    if node.type == "decorated_definition":
                        for dec in node.children:
                            if dec.type == "decorator":
                                decorators.append(_node_text(dec, code))
                    
                    doc = _extract_doc(actual, code)
                    if not doc:
                        # Try to find docstring as string_literal after name
                        for child in actual.children:
                            if child.type == "string_literal":
                                doc = _node_text(child, code).strip("'\"\"")
                                break
                    body = _extract_body(actual, code)
                    sym = Symbol(
                        type="class",
                        name=name,
                        qualified_name=qname,
                        signature=f"class {name}",
                        start_line=name_node.start_point[0] + 1,
                        end_line=actual.end_point[0] + 1,
                        start_col=name_node.start_point[1],
                        end_col=actual.end_point[1],
                        doc=doc,
                        body=body,
                        type_annotations=None,
                        meta={"file": file_path, "decorators": decorators}
                    )
                    symbols.append(sym)

                    # inheritance
                    bases_node = actual.child_by_field_name("bases")
                    if bases_node:
                        for base in bases_node.children:
                            if base.type not in ("(", ")", ","):
                                relations.append(Relation(
                                    source_name=qname,
                                    target_name=_node_text(base, code),
                                    target_file=None,
                                    type="inherits",
                                    line=base.start_point[0] + 1,
                                    meta=None
                                ))

                    body = actual.child_by_field_name("body")
                    if body:
                        new_scope = scope_stack + [("class", name)]
                        for child in body.children:
                            _extract(child, new_scope)
                return

            if actual.type in ("import_statement", "import_from_statement"):
                text = _node_text(actual, code)
                symbols.append(Symbol(
                    type="import",
                    name=text,
                    qualified_name=None,
                    signature=text,
                    start_line=actual.start_point[0] + 1,
                    end_line=actual.end_point[0] + 1,
                    start_col=actual.start_point[1],
                    end_col=actual.end_point[1],
                    doc=None,
                    meta={"file": file_path}
                ))
                return

            # default: recurse into children
            for child in actual.children:
                _extract(child, scope_stack)

        for child in tree.root_node.children:
            _extract(child, [])
        return symbols, relations


class JavaScriptExtractor:
    @staticmethod
    def extract(tree, code: bytes, file_path: str) -> Tuple[List[Symbol], List[Relation]]:
        symbols: List[Symbol] = []
        relations: List[Relation] = []

        def _extract(node, scope_stack: List[Tuple[str, str]]):
            if node.type in ("function_declaration", "method_definition", "function_expression", "arrow_function"):
                name = None
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, code)
                elif node.type == "arrow_function":
                    parent = node.parent
                    if parent and parent.type == "variable_declarator":
                        id_node = parent.child_by_field_name("name")
                        if id_node:
                            name = _node_text(id_node, code)

                if name:
                    qname = ".".join([n for _, n in scope_stack] + [name])
                    sig = _node_text(node, code).split("{")[0][:120]
                    doc = _extract_preceding_comment(node, code)
                    body = _extract_body(node, code)
                    types = _extract_js_type_annotations(node, code)
                    sym = Symbol(
                        type="function",
                        name=name,
                        qualified_name=qname,
                        signature=sig,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_col=node.start_point[1],
                        end_col=node.end_point[1],
                        doc=doc,
                        body=body,
                        type_annotations=types,
                        meta={"file": file_path}
                    )
                    symbols.append(sym)

                    body = node.child_by_field_name("body")
                    if body:
                        for n in _walk(body):
                            if n.type == "call_expression":
                                func_node = n.child_by_field_name("function")
                                if func_node:
                                    call_name = _node_text(func_node, code)
                                    relations.append(Relation(
                                        source_name=qname,
                                        target_name=call_name,
                                        target_file=None,
                                        type="calls",
                                        line=func_node.start_point[0] + 1,
                                        meta=None
                                    ))
                        new_scope = scope_stack + [("function", name)]
                        for child in body.children:
                            _extract(child, new_scope)
                return

            if node.type == "class_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, code)
                    qname = ".".join([n for _, n in scope_stack] + [name])
                    doc = _extract_preceding_comment(node, code)
                    body = _extract_body(node, code)
                    sym = Symbol(
                        type="class",
                        name=name,
                        qualified_name=qname,
                        signature=f"class {name}",
                        start_line=name_node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_col=name_node.start_point[1],
                        end_col=node.end_point[1],
                        doc=doc,
                        body=body,
                        type_annotations=None,
                        meta={"file": file_path}
                    )
                    symbols.append(sym)

                    superclass_node = node.child_by_field_name("superclass")
                    if superclass_node:
                        relations.append(Relation(
                            source_name=qname,
                            target_name=_node_text(superclass_node, code),
                            target_file=None,
                            type="inherits",
                            line=superclass_node.start_point[0] + 1,
                            meta=None
                        ))

                    body = node.child_by_field_name("body")
                    if body:
                        new_scope = scope_stack + [("class", name)]
                        for child in body.children:
                            _extract(child, new_scope)
                return

            if node.type in ("import_statement", "import_declaration"):
                text = _node_text(node, code)
                symbols.append(Symbol(
                    type="import",
                    name=text,
                    qualified_name=None,
                    signature=text,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    start_col=node.start_point[1],
                    end_col=node.end_point[1],
                    doc=None,
                    meta={"file": file_path}
                ))
                return

            for child in node.children:
                _extract(child, scope_stack)

        for child in tree.root_node.children:
            _extract(child, [])
        return symbols, relations


class TypeScriptExtractor:
    @staticmethod
    def extract(tree, code: bytes, file_path: str) -> Tuple[List[Symbol], List[Relation]]:
        # Reuse JS extractor for most things, TS has similar AST
        return JavaScriptExtractor.extract(tree, code, file_path)


class GenericExtractor:
    """Fallback extractor that grabs function/class-like nodes by type name heuristic."""

    FUNCTION_TYPES = {
        "function_definition", "function_declaration", "method_definition",
        "function_item", "method_declaration", "func_literal", "lambda_expression",
        "def", "function"
    }

    CLASS_TYPES = {
        "class_definition", "class_declaration", "struct_item", "interface_declaration",
        "class", "struct", "interface", "enum_declaration", "trait_item"
    }

    @staticmethod
    def extract(tree, code: bytes, file_path: str) -> Tuple[List[Symbol], List[Relation]]:
        symbols: List[Symbol] = []
        relations: List[Relation] = []

        for node in _walk(tree.root_node):
            if node.type in GenericExtractor.FUNCTION_TYPES:
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, code)
                    sig = _node_text(node, code).split("{")[0][:120]
                    symbols.append(Symbol(
                        type="function",
                        name=name,
                        qualified_name=name,
                        signature=sig,
                        start_line=name_node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_col=name_node.start_point[1],
                        end_col=name_node.end_point[1],
                        doc=None,
                        meta={"file": file_path, "node_type": node.type}
                    ))
            elif node.type in GenericExtractor.CLASS_TYPES:
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, code)
                    symbols.append(Symbol(
                        type="class" if node.type != "interface_declaration" else "interface",
                        name=name,
                        qualified_name=name,
                        signature=f"class {name}",
                        start_line=name_node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_col=name_node.start_point[1],
                        end_col=name_node.end_point[1],
                        doc=None,
                        meta={"file": file_path, "node_type": node.type}
                    ))

        return symbols, relations


EXTRACTORS = {
    "python": PythonExtractor,
    "javascript": JavaScriptExtractor,
    "typescript": TypeScriptExtractor,
    "ruby": GenericExtractor,
    "go": GenericExtractor,
    "rust": GenericExtractor,
    "java": GenericExtractor,
    "c_sharp": GenericExtractor,
    "c": GenericExtractor,
    "cpp": GenericExtractor,
}


def extract(tree, code: bytes, lang: str, file_path: str) -> Tuple[List[Symbol], List[Relation]]:
    extractor = EXTRACTORS.get(lang, GenericExtractor)
    return extractor.extract(tree, code, file_path)
