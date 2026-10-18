"""Read-only lexical dependencies of top-level Python bindings."""

import ast
import builtins
from dataclasses import asdict, dataclass, field
import hashlib
import io
from pathlib import Path
import platform
import symtable
import sys
import tokenize

from shimify.models import Diagnostic


@dataclass(frozen=True)
class Binding:
    name: str
    kind: str
    line: int
    end_line: int
    references: tuple[str, ...]


@dataclass
class SymbolGraph:
    path: Path
    symbol: str
    source: bytes
    encoding: str
    text: str
    tree: ast.Module
    bindings: dict[str, Binding] = field(default_factory=dict)
    nodes: dict[str, ast.stmt] = field(default_factory=dict, repr=False)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def retained(self) -> list[str]:
        pending, visited = [self.symbol], set()
        while pending:
            name = pending.pop()
            if name in visited or name not in self.bindings:
                continue
            visited.add(name)
            pending.extend(self.bindings[name].references)
        return sorted(visited)

    def to_dict(self) -> dict:
        retained = set(self.retained)
        unknown = sorted({
            reference for name in retained for reference in self.bindings[name].references
            if reference not in self.bindings and reference not in vars(builtins)
        })
        return {
            "schema_version": 1,
            "path": str(self.path),
            "symbol": self.symbol,
            "sha256": hashlib.sha256(self.source).hexdigest(),
            "size_bytes": len(self.source),
            "python": {"version": platform.python_version(), "implementation": sys.implementation.name},
            "supported": not self.diagnostics and not unknown,
            "bindings": [asdict(binding) for _, binding in sorted(self.bindings.items())],
            "retained": sorted(retained),
            "omitted": sorted(self.bindings.keys() - retained),
            "edges": [
                {"from": name, "to": reference, "reason": "lexical global reference"}
                for name in sorted(retained) for reference in self.bindings[name].references
                if reference in self.bindings
            ],
            "unresolved_globals": unknown,
            "diagnostics": [asdict(item) for item in self.diagnostics],
            "limitations": [
                "Same-module lexical bindings; attributes and imports are not cross-module symbol links.",
                "A symbol report does not establish extraction safety or runtime reachability.",
            ],
        }


def parse_target(target: str) -> tuple[Path, str]:
    """Split at the final colon, preserving a Windows drive prefix."""
    path, separator, symbol = target.rpartition(":")
    if not separator or not path or not symbol.isidentifier():
        raise ValueError("Target must be FILE.py:top_level_name.")
    return Path(path), symbol


def _names(node: ast.stmt) -> list[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Import):
        return [alias.asname or alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [alias.asname or alias.name for alias in node.names if alias.name != "*"]
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return [child.id for target in targets for child in ast.walk(target) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)]
    return []


def _references(node: ast.stmt) -> tuple[str, ...]:
    # The compiler handles lexical shadowing, comprehensions, and closure cells.
    # Its module table also includes defaults, decorators, bases and annotations.
    source = ast.unparse(ast.Module(body=[node], type_ignores=[]))
    table = symtable.symtable(source, "<symbol>", "exec")
    references: set[str] = set()

    def visit(scope):
        for symbol in scope.get_symbols():
            if symbol.is_referenced() and (symbol.is_global() or scope.get_type() == symtable.SymbolTableType.MODULE):
                references.add(symbol.get_name())
        for child in scope.get_children():
            visit(child)

    visit(table)
    return tuple(sorted(references))


def analyze_symbols(path: str | Path, symbol: str) -> SymbolGraph:
    path = Path(path).resolve()
    if path.suffix != ".py" or not path.is_file() or not symbol.isidentifier():
        raise ValueError("Expected an existing .py file and a top-level symbol name.")
    source = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
    text = source.decode(encoding)
    try:
        tree = ast.parse(text, filename=str(path))
        compile(tree, str(path), "exec")
    except SyntaxError as error:
        raise ValueError(f"Invalid Python source: {error}") from error
    graph = SymbolGraph(path, symbol, source, encoding, text, tree)
    for index, node in enumerate(tree.body):
        if index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        names = _names(node)
        if not names:
            graph.diagnostics.append(Diagnostic("SHIM401", "Top-level statement has no supported static binding.", path.name, node.lineno))
        for name in names:
            if name in graph.bindings:
                graph.diagnostics.append(Diagnostic("SHIM402", f"Binding is defined more than once: {name}", path.name, node.lineno))
            graph.bindings[name] = Binding(name, type(node).__name__, node.lineno, node.end_lineno, _references(node))
            graph.nodes[name] = node
    if symbol not in graph.bindings:
        graph.diagnostics.append(Diagnostic("SHIM403", f"Top-level symbol was not found: {symbol}", path.name))
    graph.diagnostics = sorted(set(graph.diagnostics), key=lambda item: (item.line, item.code, item.message))
    return graph
