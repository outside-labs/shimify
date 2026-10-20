from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from shimify.analyzer import analyze
from shimify.bundler import bundle


FIXTURE = Path(__file__).parent / "fixtures" / "text_metrics"


class SourceProfileTests(unittest.TestCase):
    def test_original_and_module_bundle_obey_selected_contract(self):
        graph = analyze(FIXTURE / "app.py")
        self.assertTrue(graph.supported, graph.diagnostics)
        cases = [
            ("", [0, 0, 0]),
            ("hello world", [11, 2, 1]),
            (" \t\n\r\v\f", [6, 0, 2]),
            ("one\ntwo\n", [8, 2, 3]),
            ("one\rtwo", [7, 2, 1]),
            ("A😀e\u0301", [4, 1, 1]),
            ("a\u00a0b", [3, 1, 1]),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "bundle"
            manifest = bundle(graph, output)
            self.assertEqual(
                {source["module"] for source in manifest["sources"]},
                {"__main__", "text_metrics", "text_metrics.metrics", "text_metrics.helpers"},
            )
            commands = [
                [sys.executable, "-I", "-S", "-c",
                 "import runpy,sys; sys.path.insert(0,sys.argv[1]); "
                 "sys.argv=sys.argv[2:]; runpy.run_path(sys.argv[0],run_name='__main__')",
                 str(FIXTURE.resolve()), str((FIXTURE / "app.py").resolve())],
                [sys.executable, "-I", "-S", str(output / "run.py")],
            ]
            for text, expected in cases:
                for command in commands:
                    with self.subTest(text=text, command=command[:3]):
                        result = subprocess.run(command + [text], cwd=root, check=True,
                                                capture_output=True, text=True, timeout=5)
                        self.assertEqual(json.loads(result.stdout), expected)
            for source_root in [FIXTURE.resolve(), output / "_sources"]:
                result = subprocess.run(
                    [sys.executable, "-I", "-S", "-c",
                     "import sys; sys.path.insert(0,sys.argv[1]); "
                     "from text_metrics import metrics; metrics(None)", str(source_root)],
                    cwd=root, capture_output=True, text=True, timeout=5,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("TypeError: text must be str", result.stderr)
