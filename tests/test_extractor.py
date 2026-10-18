import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from shimify.cli import main
from shimify.extractor import extract
from shimify.provenance import BundleError
from shimify.symbols import analyze_symbols


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.path = self.source / "utility.py"
        self.output = self.root / "result"

    def graph(self, text):
        self.path.write_text(text, encoding="utf-8")
        return analyze_symbols(self.path, "selected")

    def run_callable(self, path):
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            f"from {path.stem} import selected; "
            "print([selected(value) for value in [b'', b'hello', b'world']])"
        )
        return subprocess.run([sys.executable, "-I", "-S", "-c", code, str(path.parent)], check=True, capture_output=True, text=True, cwd=self.root).stdout

    def test_checksum_closure_reduces_source_and_matches_isolated_original(self):
        graph = self.graph(
            "# Copyright Synthetic Fixture\nimport hashlib as digest\nimport json\nimport urllib.request\n"
            "PREFIX = 'checksum:'\n"
            "def helper(value):\n    return digest.sha256(value).hexdigest()\n"
            "def selected(value):\n    return PREFIX + helper(value)\n"
            "def decode(value):\n    return json.loads(value)\n"
            "def download(url):\n    return urllib.request.urlopen(url).read()\n"
        )
        (self.source / "LICENSE").write_text("Synthetic fixture license\n")
        original = self.run_callable(self.path)
        manifest = extract(graph, self.output)
        self.assertLess(manifest["size"]["extracted_source_bytes"], manifest["size"]["original_source_bytes"])
        self.assertEqual(manifest["omitted"], ["decode", "download", "json", "urllib"])
        text = (self.output / "extracted.py").read_text()
        self.assertIn("# Copyright Synthetic Fixture", text)
        self.assertNotIn("import json", text)
        self.assertNotIn("urllib", text)
        self.assertEqual((self.output / "LICENSES/local-1/LICENSE").read_text(), "Synthetic fixture license\n")
        shutil.rmtree(self.source)
        self.assertEqual(original, self.run_callable(self.output / "extracted.py"))
        self.assertEqual(json.loads((self.output / "SHIMIFY-EXTRACT.json").read_bytes()), manifest)
        for item in manifest["files"]:
            self.assertEqual(hashlib.sha256((self.output / item["path"]).read_bytes()).hexdigest(), item["sha256"])

    def test_recursion_closures_shadowing_and_literal_defaults(self):
        graph = self.graph("unused = 99\ndef selected(n=4):\n    unused = n\n    def inner():\n        return unused\n    return inner() * selected(n - 1) if n else 1\n")
        extract(graph, self.output)
        result = subprocess.run([sys.executable, "-I", "-S", "-c", "import sys; sys.path.insert(0,sys.argv[1]); from extracted import selected; print(selected())", str(self.output)], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout, "24\n")

    def test_boundary_matrix_is_refused_without_publication(self):
        examples = [
            "@print\ndef selected():\n    return 1\n",
            "class selected:\n    pass\n",
            "VALUE = []\ndef selected():\n    return VALUE\n",
            "print('initialization')\ndef selected():\n    return 1\n",
            "def selected(value=list()):\n    return value\n",
            "def selected():\n    return globals()\n",
            "def selected():\n    alias = eval\n    return alias('1')\n",
            "def selected():\n    return selected.__globals__\n",
            "VALUE = 1\ndef selected():\n    global VALUE\n    VALUE += 1\n",
            "from local_package import value\ndef selected():\n    return value\n",
            "def selected():\n    import absent_package\n    return absent_package.value\n",
            "from . import value\ndef selected():\n    return value\n",
            "from math import *\ndef selected():\n    return 1\n",
            "def selected():\n    return __name__\n",
            "def selected[T](x: T):\n    return x\n",
            "VALUE = 1; OTHER = 2\ndef selected():\n    return VALUE\n",
        ]
        for text in examples:
            with self.subTest(source=text), self.assertRaises(BundleError):
                extract(self.graph(text), self.output)
            self.assertFalse(self.output.exists())

    def test_source_changes_overlap_existing_output_and_write_failure(self):
        graph = self.graph("def selected():\n    return 1\n")
        self.path.write_text("changed")
        with self.assertRaisesRegex(BundleError, "SHIM306"):
            extract(graph, self.output)
        graph = self.graph("def selected():\n    return 1\n")
        with self.assertRaisesRegex(BundleError, "overlaps"):
            extract(graph, self.source / "result")
        with patch("shimify.artifacts.os.link", side_effect=OSError("test failure")):
            with self.assertRaises(OSError):
                extract(graph, self.output)
        self.assertFalse(self.output.exists())
        self.output.mkdir()
        marker = self.output / "keep"
        marker.write_text("keep")
        with self.assertRaisesRegex(BundleError, "already exists"):
            extract(graph, self.output)
        self.assertEqual(marker.read_text(), "keep")

    def test_latin1_source_and_future_directives_are_preserved(self):
        self.path.write_bytes("# coding: latin-1\nfrom __future__ import annotations\nTEXT = 'caf\xe9'\ndef selected():\n    return TEXT\n".encode("latin-1"))
        graph = analyze_symbols(self.path, "selected")
        extract(graph, self.output)
        content = (self.output / "extracted.py").read_bytes()
        self.assertIn(b"caf\xe9", content)
        self.assertIn(b"from __future__ import annotations", content)
        compile(content, "extracted.py", "exec")

    def test_cli_and_deterministic_manifest(self):
        graph = self.graph("def selected():\n    return 1\n")
        first = extract(graph, self.output)
        self.assertEqual(first, extract(graph, self.root / "second"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["extract", str(self.path) + ":selected", "--output", str(self.root / "third")]), 0)
