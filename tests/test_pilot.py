import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from shimify.analyzer import analyze
from shimify.bundler import bundle


@unittest.skipUnless(os.environ.get("SHIMIFY_PILOT_PATH"), "Set SHIMIFY_PILOT_PATH to the pinned packaging fixture installation.")
class PackagingPilotTests(unittest.TestCase):
    def test_pinned_dependency_matches_in_clean_runtime(self):
        installed = Path(os.environ["SHIMIFY_PILOT_PATH"]).resolve()
        entry = Path(__file__).resolve().parents[1] / "examples/version_info.py"
        graph = analyze(entry, installed_paths=(installed,))
        self.assertTrue(graph.supported, graph.diagnostics)
        cases = ["0", "1.0", "1.0rc1", "1.0.post2", "2!1.0", "1.0+linux.1", "1.0.dev3", "v2.0", "", "not-a-version"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "bundle"
            manifest = bundle(graph, output)
            self.assertEqual({source["module"] for source in manifest["sources"]}, {"__main__", "packaging", "packaging.version", "packaging._structures"})
            distribution = manifest["distributions"][0]
            self.assertEqual((distribution["name"], distribution["version"]), ("packaging", "25.0"))
            self.assertEqual({Path(path).name for path in distribution["license_files"]}, {"LICENSE", "LICENSE.APACHE", "LICENSE.BSD"})
            for path in distribution["license_files"]:
                self.assertEqual((output / path).read_bytes(), (installed / path.split("/", 2)[2]).read_bytes())
            for item in manifest["files"]:
                self.assertEqual(hashlib.sha256((output / item["path"]).read_bytes()).hexdigest(), item["sha256"])
            self.assertFalse((output / "_sources/packaging/requirements.py").exists())
            original_bootstrap = (
                "import runpy, sys; "
                f"sys.path.insert(0, {str(installed)!r}); "
                f"sys.argv = [{str(entry)!r}, *sys.argv[1:]]; "
                f"runpy.run_path({str(entry)!r}, run_name='__main__')"
            )
            original = subprocess.run([sys.executable, "-I", "-S", "-c", original_bootstrap, *cases], check=True, capture_output=True, text=True, cwd=root)
            bundled = subprocess.run([sys.executable, "-I", "-S", str(output / "run.py"), *cases], check=True, capture_output=True, text=True, cwd=root)
            self.assertEqual(bundled.stdout, original.stdout)
            results = json.loads(bundled.stdout)
            self.assertFalse(results[-1]["valid"])
            self.assertEqual(results[5]["local"], "linux.1")
            self.assertEqual(manifest, bundle(graph, root / "second"))
