import json
from pathlib import Path
import tempfile
import unittest

from shimify.symbols import analyze_symbols, parse_target


class SymbolTests(unittest.TestCase):
    def analyze(self, text, symbol="selected"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "utility.py"
        path.write_text(text, encoding="utf-8")
        return analyze_symbols(path, symbol)

    def test_dependencies_include_defaults_annotations_and_nested_globals(self):
        report = self.analyze(
            "import hashlib as digest\nFACTOR = 2\nDEFAULT = 3\nKIND = int\n"
            "def helper(value):\n    return digest.sha256(value).hexdigest()\n"
            "def selected(value: KIND = DEFAULT):\n"
            "    def inner(local):\n        return helper(local) * FACTOR\n"
            "    return inner(value)\n"
            "def unused():\n    return 'unused'\n"
        ).to_dict()
        self.assertEqual(report["retained"], ["DEFAULT", "FACTOR", "KIND", "digest", "helper", "selected"])
        self.assertEqual(report["omitted"], ["unused"])
        self.assertEqual(report["unresolved_globals"], [])

    def test_locals_closure_cells_and_comprehensions_do_not_retain_globals(self):
        graph = self.analyze(
            "local = 100\ncell = 200\nitem = 300\n"
            "def selected(local):\n    cell = local\n"
            "    def inner():\n        return cell\n"
            "    return [item + inner() for item in range(local)]\n"
        )
        self.assertEqual(graph.retained, ["selected"])

    def test_mutual_recursion_terminates(self):
        graph = self.analyze("def selected(n):\n    return helper(n - 1) if n else 0\ndef helper(n):\n    return selected(n)\n")
        self.assertEqual(graph.retained, ["helper", "selected"])
        self.assertEqual(len(graph.to_dict()["edges"]), 2)

    def test_unknown_globals_and_rebindings_are_reported(self):
        graph = self.analyze("VALUE = 1\nVALUE = 2\ndef selected():\n    return missing + VALUE\n")
        self.assertEqual(graph.to_dict()["unresolved_globals"], ["missing"])
        self.assertEqual(graph.diagnostics[0].code, "SHIM402")
        self.assertFalse(graph.to_dict()["supported"])

    def test_module_initialization_is_never_executed(self):
        graph = self.analyze("raise RuntimeError('do not execute')\ndef selected():\n    return 1\n")
        self.assertEqual(graph.diagnostics[0].code, "SHIM401")

    def test_report_is_deterministic_and_missing_symbol_is_explicit(self):
        graph = self.analyze("answer = 42\n")
        self.assertEqual(json.dumps(graph.to_dict()), json.dumps(graph.to_dict()))
        self.assertEqual(graph.diagnostics[0].code, "SHIM403")

    def test_target_preserves_windows_drive_and_rejects_missing_symbol(self):
        self.assertEqual(parse_target("C:/source/app.py:main"), (Path("C:/source/app.py"), "main"))
        for target in ["app.py", "app.py:", "app.py:thing.method"]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                parse_target(target)

    def test_compiler_invalid_source_is_a_value_error(self):
        with self.assertRaisesRegex(ValueError, "Invalid Python source"):
            self.analyze("return 1\n")
