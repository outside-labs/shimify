import contextlib
import io
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
