"""Purpose-specific callable extraction within a deliberately narrow subset."""

import ast
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import sys

from shimify import __version__
from shimify.analyzer import analyze
from shimify.artifacts import write_directory
from shimify.provenance import BundleError, collect_provenance
from shimify.resolver import environment_paths
from shimify.symbols import SymbolGraph

_IMPORTS = {
    "base64", "binascii", "cmath", "collections", "decimal", "fractions",
    "functools", "hashlib", "hmac", "itertools", "json", "math", "operator",
    "re", "statistics", "string", "struct", "unicodedata", "urllib",
}
_REFLECTION = {
    "__builtins__", "__file__", "__name__", "__package__", "__spec__", "__loader__", "__cached__",
    "breakpoint", "compile", "delattr", "dir", "eval", "exec", "getattr", "globals",
    "hasattr", "help", "locals", "open", "setattr", "vars", "__import__",
}


def _immutable(node: ast.AST | None) -> bool:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return False

    def immutable(value):
        return isinstance(value, (str, bytes, int, float, complex, bool, type(None))) or value is Ellipsis or isinstance(value, tuple) and all(immutable(item) for item in value)

    return immutable(value)


def _validate(graph: SymbolGraph):
    def refuse(message, node=None):
        suffix = f" (line {node.lineno})" if node is not None else ""
        raise BundleError("SHIM410: " + message + suffix)

    if not graph.to_dict()["supported"]:
        refuse("Symbol graph has diagnostics or unresolved globals.")
    if not isinstance(graph.nodes[graph.symbol], (ast.FunctionDef, ast.AsyncFunctionDef)):
        refuse("The selected symbol must be a plain top-level function.")
    for index, node in enumerate(graph.tree.body):
        if node.col_offset or (index and node.lineno <= graph.tree.body[index - 1].end_lineno):
            refuse("Statements must occupy separate top-level lines.", node)
        if index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.decorator_list or node.type_params:
                refuse("Decorators and generic definitions require a separate extraction contract.", node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if len(targets) != 1 or not isinstance(targets[0], ast.Name) or not _immutable(node.value):
                refuse("Only single-name immutable literal constants are supported.", node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                if node.level or any(alias.name == "*" for alias in node.names):
                    refuse("Relative and wildcard imports are unsupported.", node)
                names = [node.module]
            else:
                names = [alias.name for alias in node.names]
            if any(name != "__future__" and name.split(".")[0] not in _IMPORTS for name in names):
                refuse("Import is outside the supported standard-library extraction profile.", node)
        else:
            refuse("Executable module initialization and classes are unsupported.", node)
    for node in ast.walk(graph.tree):
        if isinstance(node, ast.ClassDef):
            refuse("Class definitions require a separate extraction contract.", node)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                if node.level or any(alias.name == "*" for alias in node.names):
                    refuse("Relative and wildcard imports are unsupported.", node)
                names = [node.module]
            else:
                names = [alias.name for alias in node.names]
            if any(name != "__future__" and name.split(".")[0] not in _IMPORTS for name in names):
                refuse("Import is outside the supported standard-library extraction profile.", node)
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            refuse("Explicit global/nonlocal mutation is unsupported.", node)
        if isinstance(node, ast.Name) and node.id in _REFLECTION:
            refuse(f"Reflection, identity, execution or resource boundary: {node.id}", node)
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            refuse("Dunder attribute reflection is unsupported.", node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (node.decorator_list or node.type_params):
                refuse("Nested decorated/generic definitions are unsupported.", node)
            defaults = [*node.args.defaults, *(item for item in node.args.kw_defaults if item is not None)]
            if any(not _immutable(item) for item in defaults):
                refuse("Computed or mutable defaults are unsupported.", node)


def extract(graph: SymbolGraph, output: str | Path) -> dict:
    """Emit a library file and audit manifest without importing target code."""
    _validate(graph)
    if graph.path.read_bytes() != graph.source:
        raise BundleError("SHIM306: Source changed since symbol analysis.")
    modules = analyze(graph.path)
    if not modules.supported:
        raise BundleError("SHIM410: Module analysis has blocking diagnostics.")
    if any(name != "__main__" and module.kind != "stdlib" for name, module in modules.modules.items()):
        raise BundleError("SHIM410: Imports must resolve to the standard library; local shadowing is unsupported.")
    entry = modules.modules["__main__"]
    if entry.source != graph.source:
        raise BundleError("SHIM306: Source changed since symbol analysis.")
    # Preserve distribution attribution even when the target is a nested installed
    # package file supplied explicitly rather than reached through an import.
    for root in environment_paths():
        if graph.path.is_relative_to(root):
            modules.modules["__main__"] = replace(entry, root=root, external=True)
            break
    provenance = collect_provenance(modules)
    retained = set(graph.retained)
    nodes = {id(graph.nodes[name]): graph.nodes[name] for name in retained}
    for node in graph.tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            nodes[id(node)] = node
    if graph.tree.body and isinstance(graph.tree.body[0], ast.Expr):
        nodes[id(graph.tree.body[0])] = graph.tree.body[0]
    # Imports can bind several names in one preserved source segment.
    retained = {name for name, node in graph.nodes.items() if id(node) in nodes}
    lines = graph.text.splitlines(keepends=True)
    prefix = "".join(lines[:graph.tree.body[0].lineno - 1]) if graph.tree.body else ""
    text = prefix + "\n\n".join("".join(lines[node.lineno - 1:node.end_lineno]).rstrip("\r\n") for node in sorted(nodes.values(), key=lambda n: n.lineno)) + "\n"
    content = text.encode(graph.encoding)
    compile(content, "extracted.py", "exec")
    files = {"extracted.py": content, **provenance.notices}
    manifest = {
        "schema_version": 1,
        "shimify_version": __version__,
        "mode": "extract",
        "symbol": graph.symbol,
        "source": graph.path.name,
        "source_sha256": hashlib.sha256(graph.source).hexdigest(),
        "output": "extracted.py",
        "retained": sorted(retained),
        "omitted": sorted(graph.bindings.keys() - retained),
        "edges": graph.to_dict()["edges"],
        "size": {"original_source_bytes": len(graph.source), "extracted_source_bytes": len(content)},
        "python": {"requires": ">=3.14", "version": platform.python_version(), "implementation": sys.implementation.name, "platform": sys.platform},
        "distributions": provenance.distributions,
        "files": [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
            for name, data in sorted(files.items())
        ],
        "limitations": [
            "Callable behavior within the supported subset; module identity, reflection and unused import initialization are excluded.",
            "Standard-library imports remain external; source reduction does not measure interpreter size or startup speed.",
            "License material is preserved; redistribution compliance is not certified.",
        ],
    }
    files["SHIMIFY-EXTRACT.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    roots = tuple({module.root for module in modules.modules.values() if module.root is not None})
    write_directory(output, files, source_roots=roots)
    return manifest
