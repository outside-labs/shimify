"""Command-line interface."""

import argparse
import json
from pathlib import Path
import sys

from shimify import __version__
from shimify.analyzer import analyze


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shimify", description="Explain Python dependencies and build portable source bundles."
    )
    parser.add_argument("--version", action="version", version=f"shimify {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    explain = commands.add_parser("explain", help="Explain a script's static import graph.")
    explain.add_argument("script", type=Path)
    explain.add_argument("--search-path", type=Path, action="append", default=[], help="Additional local source root (repeatable).")
    explain.add_argument("--json", action="store_true", help="Emit a structured import graph.")
    args = parser.parse_args(argv)
    try:
        graph = analyze(args.script, search_paths=tuple(args.search_path))
    except (OSError, ValueError) as error:
        print(f"shimify: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(graph.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"Entry point: {graph.entrypoint}")
        for name, module in sorted(graph.modules.items()):
            print(f"  {name} [{module.kind}]")
            for edge in graph.edges:
                if edge.importer == name:
                    print(f"    -> {edge.target} (line {edge.line}: {edge.reason})")
        for item in graph.diagnostics:
            print(f"{item.code}: {item.module}:{item.line}: {item.message}")
        count = sum(module.kind == "source" for module in graph.modules.values())
        print(f"Source modules: {count}; supported static graph: {graph.supported}")
    return 0 if graph.supported else 1
