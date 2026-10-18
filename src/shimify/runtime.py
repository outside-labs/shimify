"""Describe observed static requirements without claiming runtime closure."""

from dataclasses import asdict
import platform
import sys

from shimify import __version__
from shimify.models import ModuleGraph


def runtime_requirements(graph: ModuleGraph) -> dict:
    sources = [module for _, module in sorted(graph.modules.items()) if module.kind == "source"]
    return {
        "schema_version": 1,
        "kind": "shimify-runtime-requirements",
        "shimify_version": __version__,
        "entrypoint": graph.entrypoint.name,
        "supported": graph.supported,
        "complete": False,
        "build_target": {
            "implementation": sys.implementation.name,
            "python_version": platform.python_version(),
            "platform": sys.platform,
            "machine": platform.machine(),
            "cache_tag": sys.implementation.cache_tag,
        },
        "sources": [
            {"module": module.name, "sha256": module.sha256, "size_bytes": len(module.source) if module.source is not None else None}
            for module in sources
        ],
        "source_size_bytes": sum(len(module.source) for module in sources if module.source is not None),
        "direct_stdlib_modules": sorted(module.name for module in graph.modules.values() if module.kind == "stdlib"),
        "host_builtin_modules": sorted(module.name for module in graph.modules.values() if module.kind == "stdlib" and module.name in sys.builtin_module_names),
        "native_boundaries": sorted(module.name for module in graph.modules.values() if module.kind == "native"),
        "diagnostics": [asdict(item) for item in graph.diagnostics],
        "unestablished": [
            "Interpreter bootstrap and encodings closure",
            "Transitive standard-library imports and native shared libraries",
            "Dynamic imports, resources and runtime observations",
            "Compatibility with a different implementation, Python version, ABI, OS or architecture",
        ],
        "limitations": [
            "Static requirements from application/dependency sources; conditional imports remain included.",
            "This incomplete report cannot be used as a runtime file deletion allowlist.",
        ],
    }
