"""Conservative static import analysis. Application sources are never executed."""

import ast
from dataclasses import replace
import io
from pathlib import Path
import tokenize

from shimify.models import Diagnostic, ImportEdge, Module, ModuleGraph
from shimify.resolver import Resolver, environment_paths


def analyze(
    entrypoint: str | Path,
    *,
    search_paths: tuple[Path, ...] = (),
    installed_paths: tuple[Path, ...] | None = None,
) -> ModuleGraph:
    entry = Path(entrypoint).resolve()
    if not entry.is_file() or entry.suffix != ".py":
        raise ValueError(f"Entry point must be an existing .py script: {entry}")
    local = (entry.parent, *search_paths)
    resolver = Resolver(local, environment_paths() if installed_paths is None else installed_paths)
    graph = ModuleGraph(entry, resolver.paths)
    pending = [Module("__main__", "source", entry, entry.parent)]

    def include(name: str, importer: str, line: int, reason: str):
        resolved = resolver.resolve(name)
        graph.edges.append(ImportEdge(importer, name, line, reason))
        if name == "__main__":
            graph.diagnostics.append(Diagnostic("SHIM114", "Importing the entry module by __main__ is unsupported.", importer, line))
            return
        if name not in graph.modules:
            graph.modules[name] = resolved
            pending.append(resolved)
        if resolved.kind == "source":
            for index in range(1, len(name.split("."))):
                parent = ".".join(name.split(".")[:index])
                parent_module = resolver.resolve(parent)
                graph.edges.append(ImportEdge(name, parent, line, "package initializer"))
                if parent not in graph.modules:
                    graph.modules[parent] = parent_module
                    pending.append(parent_module)

    scanned: set[str] = set()
    while pending:
        module = pending.pop()
        if module.name in scanned:
            continue
        scanned.add(module.name)
        graph.modules[module.name] = module
        if module.kind != "source":
            if module.kind != "stdlib":
                code, message = {
                    "native": ("SHIM201", "Native extension cannot be converted to Python source."),
                    "namespace": ("SHIM202", "Namespace package resolution is unsupported; use ordinary packages."),
                    "missing": ("SHIM101", "Module was not found in the supported filesystem import roots."),
                }[module.kind]
                graph.diagnostics.append(Diagnostic(code, message, module.name))
            continue
        assert module.path is not None
        try:
            source = module.path.read_bytes()
            encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
            tree = ast.parse(source.decode(encoding), filename=str(module.path))
            # Parsing alone accepts constructs (e.g. return outside a function)
            # which the compiler rejects. Compilation does not execute the source.
            compile(tree, str(module.path), "exec")
        except (OSError, SyntaxError, UnicodeError, LookupError) as error:
            graph.diagnostics.append(Diagnostic("SHIM102", str(error), module.name, getattr(error, "lineno", 0) or 0))
            continue
        graph.modules[module.name] = replace(module, source=source)
        graph.diagnostics.extend(_boundaries(tree, module.name))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    include(alias.name, module.name, node.lineno, "import")
            elif isinstance(node, ast.ImportFrom):
                base = _absolute_from(node, module)
                if base is None:
                    graph.diagnostics.append(Diagnostic("SHIM103", "Relative import escapes the package or appears in a script.", module.name, node.lineno))
                    continue
                if base == "__future__":
                    include(base, module.name, node.lineno, "compiler directive")
                    continue
                include(base, module.name, node.lineno, "from import")
                base_module = resolver.resolve(base)
                for alias in node.names:
                    if alias.name == "*":
                        graph.diagnostics.append(Diagnostic("SHIM104", "Wildcard import is unsupported; name imports explicitly.", module.name, node.lineno))
                    elif base_module.is_package and base_module.kind == "source":
                        candidate = base + "." + alias.name
                        if resolver.resolve(candidate).kind != "missing":
                            include(candidate, module.name, node.lineno, "possible imported submodule")
    graph.edges = sorted(set(graph.edges))
    graph.diagnostics = sorted(set(graph.diagnostics), key=lambda d: (d.module, d.line, d.code, d.message))
    return graph


def _absolute_from(node: ast.ImportFrom, module: Module) -> str | None:
    if not node.level:
        return node.module
    if module.name == "__main__":
        return None
    package = module.name if module.is_package else module.name.rpartition(".")[0]
    parts = package.split(".") if package else []
    if node.level > len(parts):
        return None
    prefix = parts[: len(parts) - node.level + 1]
    return ".".join((*prefix, node.module)) if node.module else ".".join(prefix)


def _qualified(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified(node.value, aliases)
        return parent + "." + node.attr if parent else ""
    return ""


def _boundaries(tree: ast.Module, module: str) -> list[Diagnostic]:
    aliases: dict[str, str] = {}
    nodes = list(ast.walk(tree))
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = node.module + "." + alias.name
    diagnostics = []
    for node in nodes:
        if isinstance(node, ast.Call):
            name = _qualified(node.func, aliases)
            if name in {"__import__", "builtins.__import__", "importlib.import_module", "importlib.util.find_spec", "importlib.util.spec_from_file_location", "importlib.util.module_from_spec", "runpy.run_path", "runpy.run_module", "exec", "builtins.exec", "eval", "builtins.eval"}:
                diagnostics.append(Diagnostic("SHIM111", f"Dynamic loading/execution via {name} is unsupported.", module, node.lineno))
            elif name.startswith(("importlib.resources.", "pkgutil.get_data", "pkg_resources.resource")):
                diagnostics.append(Diagnostic("SHIM113", f"Package resource access via {name} needs an explicit resource policy.", module, node.lineno))
            elif name.startswith(("importlib.metadata.", "pkg_resources.", "pkgutil.iter_modules", "pkgutil.walk_packages")):
                diagnostics.append(Diagnostic("SHIM112", f"Runtime metadata/plugin discovery via {name} is unsupported.", module, node.lineno))
        if isinstance(node, ast.Name) and node.id == "__file__":
            diagnostics.append(Diagnostic("SHIM113", "File-relative behavior requires an explicit resource policy.", module, node.lineno))
        if isinstance(node, ast.FunctionDef) and node.name == "__getattr__":
            diagnostics.append(Diagnostic("SHIM115", "Dynamic attribute resolution is unsupported.", module, node.lineno))
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_qualified(target, aliases) == "__path__" for target in targets):
                diagnostics.append(Diagnostic("SHIM116", "Package search-path mutation is unsupported.", module, node.lineno))
        if isinstance(node, ast.Call) and _qualified(node.func, aliases).startswith(("sys.path.", "sys.meta_path.", "sys.path_hooks.")):
            diagnostics.append(Diagnostic("SHIM116", "Import-path mutation is unsupported.", module, node.lineno))
    return diagnostics
