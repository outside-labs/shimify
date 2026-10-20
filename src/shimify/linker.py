"""Selected callable closure with ordinary package/import identity preserved."""

import ast
import builtins
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys

from shimify import __version__
from shimify.analyzer import _absolute_from, analyze_module
from shimify.artifacts import write_directory
from shimify.extractor import _IMPORTS, _validate
from shimify.provenance import BundleError, collect_provenance
from shimify.symbols import symbols_from_source


def _identity(path):
    path = Path(path).resolve()
    if not path.is_file() or path.suffix != ".py":
        raise ValueError("Expected an existing .py library file.")
    parts = [] if path.name == "__init__.py" else [path.stem]
    root = path.parent
    while (root / "__init__.py").is_file():
        parts.insert(0, root.name)
        root = root.parent
    if not parts or not all(part.isidentifier() for part in parts):
        raise BundleError("SHIM420: Linked extraction requires ordinary module/package names.")
    return path, ".".join(parts), root


def link(path: str | Path, symbol: str, output: str | Path, *, include_classes: bool = False) -> dict:
    """Extract an explicit callable closure without importing any target module."""
    if type(include_classes) is not bool:
        raise TypeError('include_classes must be bool')
    path, entry_name, root = _identity(path)
    if not symbol.isidentifier():
        raise ValueError("Expected a top-level symbol name.")
    graph = analyze_module(entry_name, search_paths=(root,))
    if graph.modules[entry_name].path != path or not graph.supported:
        raise BundleError("SHIM420: Module graph has blocking diagnostics or ambiguous identity.")
    sources = {name: module for name, module in graph.modules.items() if module.kind == "source"}
    tables = {}
    for name, module in sorted(sources.items()):
        if module.path is None or module.root is None or not module.path.is_relative_to(module.root):
            raise BundleError("SHIM301: Source escapes its import root.")
        if name.split(".")[0] in sys.stdlib_module_names:
            raise BundleError("SHIM420: Local standard-library shadowing is unsupported.")
        table = symbols_from_source(module.path, module.source)
        _validate(table, linked=True, include_classes=include_classes)
        tables[name] = table

    def imported(module_name, node, alias):
        base = _absolute_from(node, sources[module_name])
        if base in tables:
            if alias.name not in tables[base].bindings:
                raise BundleError(f"SHIM420: Unresolved export or module attribute dispatch: {base}:{alias.name}")
            return base, alias.name
        if base in graph.modules and graph.modules[base].kind == "stdlib":
            if base != "__future__" and base.split(".")[0] not in _IMPORTS:
                raise BundleError("SHIM420: Import is outside the approved standard-library profile.")
            return None
        raise BundleError("SHIM420: Unresolved imported binding.")

    # Simulate only static binding availability, never application execution.
    # This rejects a cycle which reads a not-yet-initialized export.
    state, available = {}, {name: set() for name in tables}
    def initialize(name):
        if state.get(name) in {"initializing", "done"}:
            return
        for index in range(1, len(name.split("."))):
            parent = ".".join(name.split(".")[:index])
            if parent in tables:
                initialize(parent)
        if state.get(name) in {"initializing", "done"}:
            return
        state[name] = "initializing"
        table = tables[name]
        for node in table.tree.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    target = imported(name, node, alias)
                    if target:
                        initialize(target[0])
                        if target[1] not in available[target[0]]:
                            raise BundleError(f"SHIM421: Import cycle reads an uninitialized binding: {target[0]}:{target[1]}")
            available[name].update(binding for binding, original in table.nodes.items() if original is node)
        state[name] = "done"
    initialize(entry_name)

    retained = {name: set() for name in tables}
    pending, edges = [(entry_name, symbol)], set()
    # All imports remain initialization roots; imported definitions retain their
    # lexical globals. This deliberately avoids dropping unused import effects.
    for name, table in tables.items():
        pending.extend((name, binding) for binding, node in table.nodes.items()
                       if isinstance(node, (ast.Import, ast.ImportFrom)))
    while pending:
        name, binding = pending.pop()
        if binding in retained[name]:
            continue
        table = tables[name]
        if binding not in table.bindings:
            if binding in vars(builtins):
                continue
            raise BundleError(f"SHIM420: Unresolved lexical binding: {name}:{binding}")
        retained[name].add(binding)
        node = table.nodes[binding]
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                target = imported(name, node, alias)
                if target:
                    edges.add((f"{name}:{alias.asname or alias.name}", f"{target[0]}:{target[1]}", "imported binding"))
                    pending.append(target)
        for reference in table.bindings[binding].references:
            if reference in table.bindings:
                reason = 'whole class global reference' if isinstance(node, ast.ClassDef) else 'lexical global reference'
                edges.add((f"{name}:{binding}", f"{name}:{reference}", reason))
                pending.append((name, reference))
            elif reference not in vars(builtins):
                raise BundleError(f"SHIM420: Unresolved lexical binding: {name}:{reference}")

    current, seen = (entry_name, symbol), set()
    while current not in seen:
        seen.add(current)
        node = tables[current[0]].nodes.get(current[1])
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or (include_classes and isinstance(node, ast.ClassDef)):
            break
        if isinstance(node, ast.ImportFrom):
            alias = next(alias for alias in node.names if (alias.asname or alias.name) == current[1])
            current = imported(current[0], node, alias)
            if current is not None:
                continue
        raise BundleError("SHIM420: Selected export must resolve to an adopted source function/class." if include_classes else "SHIM420: Selected export must resolve to a source function.")
    else:
        raise BundleError("SHIM420: Re-export cycle has no source function.")

    def class_export(target):
        seen = set()
        while target and target not in seen:
            seen.add(target)
            node = tables[target[0]].nodes[target[1]]
            if isinstance(node, ast.ClassDef):
                return True
            if not isinstance(node, ast.ImportFrom):
                return False
            alias = next(alias for alias in node.names if (alias.asname or alias.name) == target[1])
            target = imported(target[0], node, alias)
        return False

    # Imported source classes permit attributes only when their whole unit is kept.
    for name, table in tables.items():
        local_imports = {alias.asname or alias.name: imported(name, node, alias) for node in table.tree.body if isinstance(node, ast.ImportFrom)
                         for alias in node.names if imported(name, node, alias)}
        for binding in retained[name]:
            for node in ast.walk(table.nodes[binding]):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in local_imports and not (include_classes and class_export(local_imports[node.value.id])):
                    raise BundleError("SHIM420: Attribute dispatch on an imported source binding is unsupported.")

    provenance = collect_provenance(graph)
    files, records = dict(provenance.notices), []
    for name, table in sorted(tables.items()):
        nodes = {id(table.nodes[binding]): table.nodes[binding] for binding in retained[name]}
        if table.tree.body and isinstance(table.tree.body[0], ast.Expr):
            nodes[id(table.tree.body[0])] = table.tree.body[0]
        lines = table.text.splitlines(keepends=True)
        prefix = "".join(lines[:table.tree.body[0].lineno - 1]) if table.tree.body else table.text
        text = prefix + "\n\n".join("".join(lines[node.lineno - 1:node.end_lineno]).rstrip("\r\n") for node in sorted(nodes.values(), key=lambda item: item.lineno)) + "\n"
        data = text.encode(table.encoding)
        compile(data, name, "exec")
        module = sources[name]
        output_path = name.replace(".", "/") + ("/__init__.py" if module.is_package else ".py")
        if output_path in files:
            raise BundleError("SHIM301: Source/notice path collision.")
        files[output_path] = data
        records.append({"module": name, "source": module.path.relative_to(module.root).as_posix(),
                        "output": output_path, "source_sha256": module.sha256,
                        "retained": sorted(retained[name]), "omitted": sorted(table.bindings.keys() - retained[name]),
                        "distribution": provenance.owners.get(module.path)})
    for module in sources.values():
        if module.path.read_bytes() != module.source:
            raise BundleError("SHIM306: Source changed since module analysis.")
    manifest = {"schema_version": 1, "shimify_version": __version__, "mode": "linked-extract",
                "entrypoint": {"module": entry_name, "symbol": symbol}, "definition": {"module": current[0], "symbol": current[1]},
                "sources": records, "distributions": provenance.distributions,
                "edges": [{"from": left, "to": right, "reason": reason} for left, right, reason in sorted(edges)],
                "module_edges": [asdict(edge) for edge in graph.edges],
                "python": {"requires": ">=3.14", "version": platform.python_version()},
                "size": {"original_source_bytes": sum(len(module.source) for module in sources.values()),
                         "extracted_source_bytes": sum(len(files[record['output']]) for record in records)},
                "files": [{"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)} for name, data in sorted(files.items())],
                "limitations": ["Selected callable API; omitted APIs, reflection, original source positions and filesystem paths are excluded.",
                                "All static imports remain initialization roots; executable initialization and dynamic exports are rejected.",
                                "Source reduction does not establish interpreter size or general package compatibility."]}
    if include_classes:
        manifest['limitations'][1] = 'All static imports remain initialization roots; unadopted initialization and dynamic exports are rejected.'
        manifest['extraction_profile'] = 'linked-classes/1'
        manifest['class_units'] = [{'module': name, 'symbol': binding,
                                    'methods': [node.name for node in table.nodes[binding].body if isinstance(node, ast.FunctionDef)]}
                                   for name, table in sorted(tables.items()) for binding in sorted(retained[name]) if isinstance(table.nodes[binding], ast.ClassDef)]
        manifest['limitations'].append('Whole plain-class units and adopted builtin descriptors; no method elimination, custom inheritance or registration.')
    files["SHIMIFY-LINK.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    write_directory(output, files, source_roots=tuple({module.root for module in sources.values()}))
    return manifest
