"""Produce a new source directory from a supported static module graph."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import sys
import tempfile

from shimify import __version__
from shimify.models import ModuleGraph
from shimify.provenance import BundleError, collect_provenance

_LAUNCHER = '''#!/usr/bin/env python3
"""Run this source bundle: python -I -S run.py [arguments]."""
import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parent / "_sources"
sys.path.insert(0, str(root))
sys.argv[0] = str(root / {entrypoint!r})
runpy.run_path(sys.argv[0], run_name="__main__")
'''
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def bundle(graph: ModuleGraph, output: str | Path) -> dict:
    """Write snapshots of analyzed sources; never execute the target program."""
    requested = Path(output).absolute()
    if requested.exists() or requested.is_symlink():
        raise BundleError(f"SHIM301: Output already exists: {requested}")
    destination = requested.resolve()
    if not graph.supported:
        codes = ", ".join(sorted({item.code for item in graph.diagnostics}))
        raise BundleError(f"SHIM300: Static graph has blocking diagnostics: {codes}")
    source_modules = [module for _, module in sorted(graph.modules.items()) if module.kind == "source"]
    for module in source_modules:
        assert module.path is not None and module.root is not None
        if destination.is_relative_to(module.root) or module.root.is_relative_to(destination):
            raise BundleError(f"SHIM301: Output overlaps a source root: {module.root}")
        if not module.path.is_relative_to(module.root):
            raise BundleError(f"SHIM301: Source escapes its import root: {module.name}")
        if module.source is None or module.path.read_bytes() != module.source:
            raise BundleError(f"SHIM306: Source changed since analysis: {module.name}")
        if module.name != "__main__" and module.name.split(".")[0] in sys.stdlib_module_names:
            raise BundleError(f"SHIM301: Bundled module shadows a standard library name: {module.name}")
    provenance = collect_provenance(graph)
    files: dict[str, bytes] = {}
    paths: dict[str, str] = {}

    def add(path: str, content: bytes):
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise BundleError(f"SHIM301: Unsafe artifact path: {path}")
        for part in relative.parts:
            if part.split(".")[0].upper() in _WINDOWS_RESERVED or part.endswith((".", " ")) or any(char in part for char in '\\:*?"<>|'):
                raise BundleError(f"SHIM301: Artifact path is not portable: {path}")
        key = path.casefold()
        if key in paths and (paths[key] != path or files[path] != content):
            raise BundleError(f"SHIM301: Artifact path collision: {path}")
        for existing in paths:
            if key.startswith(existing + "/") or existing.startswith(key + "/"):
                raise BundleError(f"SHIM301: Artifact file/directory collision: {path}")
        paths[key] = path
        files[path] = content

    sources = []
    entry_name = graph.entrypoint.name
    for module in source_modules:
        relative = entry_name if module.name == "__main__" else module.name.replace(".", "/") + ("/__init__.py" if module.is_package else ".py")
        path = "_sources/" + relative
        add(path, module.source)
        sources.append({
            "module": module.name,
            "source": module.path.relative_to(module.root).as_posix(),
            "output": path,
            "sha256": module.sha256,
            "size_bytes": len(module.source),
            "distribution": provenance.owners.get(module.path),
            "origin": "distribution" if module.path in provenance.owners else "local",
        })
    add("run.py", _LAUNCHER.format(entrypoint=entry_name).encode("utf-8"))
    for path, content in sorted(provenance.notices.items()):
        add(path, content)
    manifest = {
        "schema_version": 1,
        "shimify_version": __version__,
        "mode": "modules",
        "entrypoint": "_sources/" + entry_name,
        "launcher": "run.py",
        "python": {"requires": ">=3.14", "build_version": platform.python_version(), "implementation": sys.implementation.name},
        "sources": sources,
        "stdlib_modules": sorted(module.name for module in graph.modules.values() if module.kind == "stdlib"),
        "edges": [asdict(edge) for edge in sorted(set(graph.edges))],
        "distributions": provenance.distributions,
        "files": [
            {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
            for path, content in sorted(files.items())
        ],
        "limitations": ["Conservative static imports; arbitrary runtime behavior is not proven.", "License material is preserved; redistribution compliance is not certified."],
    }
    add("SHIMIFY-MANIFEST.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".shimify-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        for path, content in sorted(files.items()):
            staged = stage / path
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(content)
        # Reserve the destination exclusively, then publish files with exclusive
        # hard links. Neither an existing output nor a raced-in file is replaced.
        destination.mkdir()
        written: list[Path] = []
        directories = {destination}
        try:
            for path in sorted(files):
                target = destination / path
                parents = []
                parent = target.parent
                while parent != destination:
                    parents.append(parent)
                    parent = parent.parent
                for parent in reversed(parents):
                    if parent not in directories:
                        parent.mkdir()
                        directories.add(parent)
                os.link(stage / path, target)
                written.append(target)
        except BaseException:
            for path in reversed(written):
                path.unlink(missing_ok=True)
            for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise
    return manifest
