"""Smoke-test the built wheel in an isolated environment."""

from pathlib import Path
import subprocess

wheels = list(Path("dist").glob("shimify-*.whl"))
if len(wheels) != 1:
    raise SystemExit("Expected exactly one built Shimify wheel in dist/.")

subprocess.run(
    ["uv", "run", "--isolated", "--no-project", "--with", str(wheels[0]), "python", "-I", "-m", "shimify", "--help"],
    check=True,
)
