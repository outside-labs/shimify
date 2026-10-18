"""Smoke-test the built wheel in an isolated environment."""

from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

directory = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
wheels = list(directory.glob("shimify-*.whl"))
if len(wheels) != 1:
    raise SystemExit("Expected exactly one built Shimify wheel in dist/.")

project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
version = project["version"]
modules = {path.relative_to("src").as_posix() for path in Path("src/shimify").glob("*.py")}
info = f"shimify-{version}.dist-info"
expected = modules | {f"{info}/{name}" for name in ["METADATA", "WHEEL", "entry_points.txt", "RECORD", "licenses/LICENSE"]}
with zipfile.ZipFile(wheels[0]) as archive:
    assert {item.filename for item in archive.infolist() if not item.is_dir()} == expected, "Unexpected wheel files"
    for name in modules:
        assert archive.read(name) == (Path("src") / name).read_bytes()
    metadata = archive.read(f"{info}/METADATA").decode()
    assert f"Version: {version}\n" in metadata and "License-Expression: MIT\n" in metadata
    assert "Requires-Dist:" not in metadata
sdists = list(directory.glob("shimify-*.tar.gz"))
assert len(sdists) == 1
with tarfile.open(sdists[0]) as archive:
    expected_source = {f"shimify-{version}/{name}" for name in ["pyproject.toml", "pyproject.toml.orig", "README.md", "LICENSE", "PKG-INFO"]}
    expected_source |= {f"shimify-{version}/src/{name}" for name in modules}
    assert {item.name for item in archive.getmembers() if item.isfile()} == expected_source, "Unexpected source distribution files"

subprocess.run(
    ["uv", "run", "--isolated", "--no-project", "--with", str(wheels[0]), "python", "-I", "-m", "shimify", "--help"],
    check=True,
)

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    source = root / "source"
    source.mkdir()
    (source / "utility.py").write_text("import math\ndef selected(x):\n    return math.sqrt(x)\ndef unused():\n    return 0\n")
    output = root / "extracted"
    subprocess.run(["uv", "run", "--isolated", "--no-project", "--with", str(wheels[0].resolve()), "python", "-I", "-m", "shimify", "extract", str(source / "utility.py") + ":selected", "--output", str(output)], check=True, cwd=root)
    manifest = json.loads((output / "SHIMIFY-EXTRACT.json").read_bytes())
    assert manifest["omitted"] == ["unused"]
    assert manifest["files"][0]["sha256"] == hashlib.sha256((output / "extracted.py").read_bytes()).hexdigest()
    result = subprocess.run([sys.executable, "-I", "-S", "-c", "import sys; sys.path.insert(0,sys.argv[1]); from extracted import selected; print(selected(81))", str(output)], check=True, capture_output=True, text=True, cwd=root)
    assert result.stdout.strip() == "9.0"
