import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from shimify.cli import main


class CommandLineTests(unittest.TestCase):
    def test_help_is_successful(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
            main(["--help"])
        self.assertEqual(result.exception.code, 0)
        self.assertIn("portable source bundles", output.getvalue())

    def test_version_is_successful(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
            main(["--version"])
        self.assertEqual(result.exception.code, 0)
        self.assertTrue(output.getvalue().startswith("shimify "))

    def test_explain_json_and_diagnostic_status(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "app.py"
            entry.write_text("import absent_shimify_test_dependency\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["explain", str(entry), "--json"])
            graph = json.loads(output.getvalue())
            self.assertEqual(status, 1)
            self.assertFalse(graph["supported"])
            self.assertEqual(graph["diagnostics"][0]["code"], "SHIM101")

    def test_invalid_input_is_a_usage_error_without_traceback(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            status = main(["explain", "/nonexistent_shimify_test_script.py"])
        self.assertEqual(status, 2)
        self.assertIn("existing .py script", output.getvalue())
