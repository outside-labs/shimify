import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from shimify.analyzer import analyze
from shimify.bundler import bundle
from shimify.provenance import BundleError


class BundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "src"
        self.source.mkdir()
        self.output = self.root / "bundle"

    def write(self, name, content, *, root=None):
        path = (root or self.source) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def graph(self, content="print('hello')\n", *, installed_paths=()):
        return analyze(self.write("app.py", content), installed_paths=installed_paths)

    def distribution(self, *, licenses=True, declaration=True, name="sample-dist", version="1.0"):
        site = self.root / "site"
        self.write("sample/__init__.py", "from .core import value\n", root=site)
        self.write("sample/core.py", "value = 42\n", root=site)
        self.write("sample/unused.py", "raise RuntimeError('unused')\n", root=site)
        info = f"{name}-{version}.dist-info"
        metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\nLicense-Expression: MIT\n"
        if declaration:
            metadata += "License-File: LICENSE\n"
        self.write(info + "/METADATA", metadata + "\n", root=site)
        records = ["sample/__init__.py", "sample/core.py", "sample/unused.py", info + "/METADATA"]
        if licenses:
            self.write(info + "/licenses/LICENSE", "Synthetic test license\nCopyright Test Fixture\n", root=site)
            self.write(info + "/licenses/NOTICE", "Synthetic test attribution\n", root=site)
            records.extend([info + "/licenses/LICENSE", info + "/licenses/NOTICE"])
        self.write(info + "/RECORD", "".join(f"{record},,\n" for record in records), root=site)
        return site

    def test_bundle_runs_without_site_packages_or_original_sources(self):
        self.write("library/__init__.py", "from .core import answer\n")
        core = self.write("library/core.py", "answer = 42\n")
        self.write("library/unused.py", "raise RuntimeError('must be omitted')\n")
        self.write("LICENSE", "Local application license\n")
        graph = self.graph("from library import answer\nimport json\nimport sys\nprint(json.dumps([answer, sys.argv[1:]]))\n")
        original = subprocess.run([sys.executable, "-S", str(graph.entrypoint), "argument"], check=True, capture_output=True, text=True, cwd=self.root)
        manifest = bundle(graph, self.output)
        self.assertEqual((self.output / "_sources/library/core.py").read_bytes(), core.read_bytes())
        self.assertFalse((self.output / "_sources/library/unused.py").exists())
        self.assertEqual((self.output / "LICENSES/local-1/LICENSE").read_text(), "Local application license\n")
        shutil.rmtree(self.source)
        bundled = subprocess.run([sys.executable, "-I", "-S", str(self.output / "run.py"), "argument"], check=True, capture_output=True, text=True, cwd=self.root)
        self.assertEqual(original.stdout, bundled.stdout)
        self.assertEqual(json.loads(bundled.stdout), [42, ["argument"]])
        self.assertEqual(json.loads((self.output / "SHIMIFY-MANIFEST.json").read_bytes()), manifest)

    def test_preserves_distribution_ownership_licenses_and_notice_bytes(self):
        site = self.distribution()
        graph = self.graph("from sample import value\nprint(value)\n", installed_paths=(site,))
        manifest = bundle(graph, self.output)
        distribution = manifest["distributions"][0]
        self.assertEqual(distribution["name"], "sample-dist")
        self.assertEqual(distribution["license_expression"], "MIT")
        self.assertEqual(distribution["modules"], ["sample", "sample.core"])
        self.assertTrue(any(path.endswith("/NOTICE") for path in distribution["license_files"]))
        for path in distribution["license_files"]:
            source = site / path.split("/", 2)[2]
            self.assertEqual((self.output / path).read_bytes(), source.read_bytes())
        self.assertFalse((self.output / "_sources/sample/unused.py").exists())
        shutil.rmtree(site)
        result = subprocess.run([sys.executable, "-I", "-S", str(self.output / "run.py")], check=True, capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.stdout.strip(), "42")

    def test_manifests_are_deterministic_and_hashes_match(self):
        graph = self.graph()
        first = bundle(graph, self.output)
        second_output = self.root / "second"
        second = bundle(graph, second_output)
        self.assertEqual(first, second)
        self.assertEqual((self.output / "SHIMIFY-MANIFEST.json").read_bytes(), (second_output / "SHIMIFY-MANIFEST.json").read_bytes())
        for item in first["files"]:
            content = (self.output / item["path"]).read_bytes()
            self.assertEqual(item["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(item["size_bytes"], len(content))
        self.assertNotIn(str(self.root), json.dumps(first))

    def test_existing_output_is_preserved(self):
        marker = self.write("keep.txt", "keep", root=self.output)
        with self.assertRaisesRegex(BundleError, "Output already exists"):
            bundle(self.graph(), self.output)
        self.assertEqual(marker.read_text(), "keep")

    def test_output_inside_or_containing_sources_is_rejected(self):
        graph = self.graph()
        with self.assertRaisesRegex(BundleError, "overlaps"):
            bundle(graph, self.source / "output")
        self.assertFalse((self.source / "output").exists())

    def test_changed_source_is_rejected_before_writing(self):
        graph = self.graph()
        graph.entrypoint.write_text("print('changed')\n")
        with self.assertRaisesRegex(BundleError, "SHIM306"):
            bundle(graph, self.output)
        self.assertFalse(self.output.exists())

    def test_blocking_graph_is_not_emitted(self):
        with self.assertRaisesRegex(BundleError, "SHIM300"):
            bundle(self.graph("import absent_dependency\n"), self.output)
        self.assertFalse(self.output.exists())

    def test_unowned_external_source_is_rejected(self):
        site = self.root / "site"
        self.write("sample.py", "value = 42\n", root=site)
        graph = self.graph("import sample\n", installed_paths=(site,))
        with self.assertRaisesRegex(BundleError, "SHIM302"):
            bundle(graph, self.output)

    def test_missing_declared_license_is_rejected(self):
        site = self.distribution(licenses=False)
        graph = self.graph("import sample\n", installed_paths=(site,))
        with self.assertRaisesRegex(BundleError, "SHIM305"):
            bundle(graph, self.output)
        self.assertFalse(self.output.exists())

    def test_license_expression_without_text_is_rejected(self):
        site = self.distribution(licenses=False, declaration=False)
        graph = self.graph("import sample\n", installed_paths=(site,))
        with self.assertRaisesRegex(BundleError, "SHIM304"):
            bundle(graph, self.output)

    def test_stdlib_shadowing_is_a_bundle_boundary(self):
        self.write("json.py", "value = 1\n")
        with self.assertRaisesRegex(BundleError, "shadows"):
            bundle(self.graph("import json\n"), self.output)

    def test_case_collisions_are_rejected_for_portable_output(self):
        # Distinct roots allow this test to work on case-insensitive filesystems.
        other = self.root / "other"
        self.write("Upper.py", "value = 1\n")
        self.write("upper.py", "value = 2\n", root=other)
        entry = self.write("app.py", "import Upper\nimport upper\n")
        graph = analyze(entry, search_paths=(other,), installed_paths=())
        with self.assertRaisesRegex(BundleError, "collision"):
            bundle(graph, self.output)

    def test_failed_publication_rolls_back_owned_files(self):
        graph = self.graph()
        with patch("shimify.bundler.os.link", side_effect=OSError("publication failed")):
            with self.assertRaisesRegex(OSError, "publication failed"):
                bundle(graph, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob(".shimify-*")))

    def test_raced_in_output_is_never_overwritten(self):
        graph = self.graph()
        original_mkdir = Path.mkdir

        def racing_mkdir(path, *args, **kwargs):
            if path == self.output:
                original_mkdir(path)
                (path / "keep.txt").write_text("keep")
            return original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", racing_mkdir):
            with self.assertRaises(FileExistsError):
                bundle(graph, self.output)
        self.assertEqual((self.output / "keep.txt").read_text(), "keep")
