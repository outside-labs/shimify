"""Command-line interface."""

import argparse

from shimify import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shimify", description="Explain Python dependencies and build portable source bundles."
    )
    parser.add_argument("--version", action="version", version=f"shimify {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
