"""Command-line interface."""

import argparse
import json
from pathlib import Path
import sys

from shimify import __version__
from shimify.analyzer import analyze
from shimify.bundler import bundle
from shimify.extractor import extract
from shimify.provenance import BundleError
from shimify.runtime import runtime_requirements
from shimify.symbols import analyze_symbols, parse_target
from shimify.tracing import trace


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
    modules = commands.add_parser("modules", help="Bundle reachable source modules into a new directory.")
    modules.add_argument("script", type=Path)
    modules.add_argument("--search-path", type=Path, action="append", default=[], help="Additional local source root (repeatable).")
    modules.add_argument("--output", type=Path, required=True, help="New directory outside the source roots.")
    symbols = commands.add_parser("symbols", help="Report a top-level symbol's lexical dependency closure.")
    symbols.add_argument("target", help="FILE.py:top_level_name")
    symbols.add_argument("--json", action="store_true", help="Emit a structured symbol graph.")
    extraction = commands.add_parser("extract", help="Extract a supported function and its same-module helpers.")
    extraction.add_argument("target", help="FILE.py:top_level_name")
    extraction.add_argument("--output", type=Path, required=True, help="New directory outside the source root.")
    runtime = commands.add_parser("runtime", help="Report static runtime requirements and unestablished closure.")
    runtime.add_argument("script", type=Path)
    runtime.add_argument("--search-path", type=Path, action="append", default=[])
    runtime.add_argument("--json", action="store_true")
    tracing = commands.add_parser("trace", help="Run an explicitly opted-in script and collect bounded import evidence.")
    tracing.add_argument("script", type=Path)
    tracing.add_argument("--allow-execution", action="store_true", help="Required: run the selected application.")
    tracing.add_argument("--search-path", type=Path, action="append", default=[])
    tracing.add_argument("--argument", action="append", default=[], help="Application argument (repeatable).")
    tracing.add_argument("--timeout", type=float, default=5)
    tracing.add_argument("--max-output-bytes", type=int, default=65536)
    args = parser.parse_args(argv)
    try:
        if args.command == "extract":
            manifest = extract(analyze_symbols(*parse_target(args.target)), args.output)
            print(f"Created {args.output.resolve()} ({manifest['size']['extracted_source_bytes']} source bytes)")
            return 0
        if args.command == "symbols":
            report = analyze_symbols(*parse_target(args.target)).to_dict()
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(f"Symbol: {report['symbol']}")
                print("Retained: " + ", ".join(report["retained"]))
                print("Omitted: " + ", ".join(report["omitted"]))
                for item in report["diagnostics"]:
                    print(f"{item['code']}: {item['message']}")
                if report["unresolved_globals"]:
                    print("Unresolved globals: " + ", ".join(report["unresolved_globals"]))
            return 0 if report["supported"] else 1
        graph = analyze(args.script, search_paths=tuple(args.search_path))
        if args.command == "trace":
            report = trace(graph, allow_execution=args.allow_execution, arguments=tuple(args.argument),
                           timeout=args.timeout, max_output_bytes=args.max_output_bytes)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report['status'] == 'completed' and report['evidence_complete'] else 1
        if args.command == "runtime":
            report = runtime_requirements(graph)
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(f"Source bytes: {report['source_size_bytes']}")
                print("Direct standard library: " + ", ".join(report["direct_stdlib_modules"]))
                print("Runtime closure: incomplete; unsuitable for runtime file deletion.")
                for item in graph.diagnostics:
                    print(f"{item.code}: {item.module}: {item.message}")
            return 0 if graph.supported else 1
        if args.command == "modules":
            manifest = bundle(graph, args.output)
            print(f"Created {args.output.resolve()} ({len(manifest['sources'])} source modules)")
            print(f"Run: python -I -S {args.output.resolve() / 'run.py'}")
            return 0
    except BundleError as error:
        print(f"shimify: {error}", file=sys.stderr)
        return 1
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
