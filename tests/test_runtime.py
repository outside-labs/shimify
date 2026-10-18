import contextlib
import io
import json
from pathlib import Path
import platform
import sys
import tempfile
import unittest

from shimify.analyzer import analyze
from shimify.cli import main
from shimify.runtime import runtime_requirements


class RuntimeTests(unittest.TestCase):
    def test_reports_host_identity_direct_requirements_and_incomplete_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "app.py"
            source = b"import sys\nimport json\nif False:\n    import math\nprint('never executed')\n"
            path.write_bytes(source)
            graph = analyze(path, installed_paths=())
            report = runtime_requirements(graph)
            self.assertEqual(report, runtime_requirements(graph))
            self.assertFalse(report["complete"])
            self.assertTrue(report["supported"])
            self.assertEqual(report["source_size_bytes"], len(source))
            self.assertEqual(report["direct_stdlib_modules"], ["json", "math", "sys"])
            self.assertEqual(report["host_builtin_modules"], [name for name in ["json", "math", "sys"] if name in sys.builtin_module_names])
            self.assertEqual(report["build_target"]["python_version"], platform.python_version())
            self.assertEqual(report["build_target"]["implementation"], sys.implementation.name)
            self.assertNotIn(temporary, json.dumps(report))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["runtime", str(path), "--json"]), 0)
            self.assertEqual(json.loads(output.getvalue()), report)

    def test_unsupported_graph_has_nonzero_status_and_explicit_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "app.py"
            path.write_text("import missing_pocket_runtime\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["runtime", str(path), "--json"]), 1)
            report = json.loads(output.getvalue())
            self.assertFalse(report["supported"])
            self.assertEqual(report["diagnostics"][0]["code"], "SHIM101")
