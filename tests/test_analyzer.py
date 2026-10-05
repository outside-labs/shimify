from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
import tempfile
import unittest

from shimify.analyzer import analyze


class SourceTreeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def graph(self, text):
        return analyze(self.write("app.py", text), installed_paths=())

    def codes(self, graph):
        return {item.code for item in graph.diagnostics}

    def test_relative_imports_reexports_and_parent_initializers(self):
        self.write("library/__init__.py", "from .core import answer\n")
        self.write("library/core.py", "from .helpers import value\nanswer = value\n")
        self.write("library/helpers.py", "value = 42\n")
        self.write("library/unused.py", "import missing_dependency\n")
        graph = self.graph("from library import answer\nprint(answer)\n")
        self.assertTrue(graph.supported, graph.diagnostics)
        self.assertEqual(set(graph.modules), {"__main__", "library", "library.core", "library.helpers"})
        self.assertTrue(any(edge.reason == "package initializer" for edge in graph.edges))

    def test_from_import_includes_submodule_candidate(self):
        self.write("library/__init__.py", "")
        self.write("library/core.py", "value = 1\n")
        self.assertIn("library.core", self.graph("from library import core\n").modules)

    def test_nested_relative_import_and_cycle(self):
        self.write("library/__init__.py", "")
        self.write("library/sub/__init__.py", "")
        self.write("library/sub/one.py", "from .. import two\n")
        self.write("library/two.py", "from .sub import one\n")
        graph = self.graph("import library.sub.one\n")
        self.assertTrue(graph.supported, graph.diagnostics)
        self.assertEqual(len(graph.modules), 5)

    def test_analysis_does_not_execute_initializers(self):
        marker = self.root / "executed.txt"
        self.write("library/__init__.py", f"open({str(marker)!r}, 'w').write('executed')\nraise RuntimeError('must not run')\n")
        self.write("library/core.py", "value = 1\n")
        graph = self.graph("import library.core\n")
        self.assertTrue(graph.supported, graph.diagnostics)
        self.assertFalse(marker.exists())

    def test_conditional_imports_are_conservative(self):
        graph = self.graph("if False:\n    import absent_dependency\nimport json\n")
        self.assertIn("absent_dependency", graph.modules)
        self.assertEqual(graph.modules["json"].kind, "stdlib")
        self.assertIn("SHIM101", self.codes(graph))

    def test_stdlib_shadowing_follows_local_root(self):
        self.write("json.py", "value = 1\n")
        graph = self.graph("import json\nimport sys\n")
        self.assertEqual(graph.modules["json"].kind, "source")
        self.assertEqual(graph.modules["sys"].kind, "stdlib")

    def test_nonpackage_parent_does_not_resolve_child_from_later_root(self):
        self.write("library.py", "")
        other = self.root / "other"
        self.write("other/library/__init__.py", "")
        self.write("other/library/core.py", "")
        graph = analyze(self.write("app.py", "import library.core\n"), search_paths=(other,), installed_paths=())
        self.assertEqual(graph.modules["library.core"].kind, "missing")

    def test_native_extension_is_not_silently_replaced_by_source(self):
        self.write("library" + EXTENSION_SUFFIXES[0], "")
        self.write("library.py", "value = 1\n")
        graph = self.graph("import library\n")
        self.assertIn("SHIM201", self.codes(graph))

    def test_namespace_package_is_explicit_boundary(self):
        self.write("namespace/core.py", "value = 1\n")
        self.assertIn("SHIM202", self.codes(self.graph("import namespace.core\n")))

    def test_dynamic_loading_resources_and_metadata_aliases(self):
        graph = self.graph("from importlib import import_module as load\nfrom importlib import resources as data\nfrom importlib.metadata import version as ver\nload('hidden')\ndata.files('library')\nver('library')\n")
        self.assertTrue({"SHIM111", "SHIM112", "SHIM113"} <= self.codes(graph))

    def test_relative_script_wildcard_and_file_behavior_are_rejected(self):
        self.write("library.py", "value = 1\n")
        graph = self.graph("from . import library\nfrom library import *\nprint(__file__)\n")
        self.assertTrue({"SHIM103", "SHIM104", "SHIM113"} <= self.codes(graph))

    def test_compiler_errors_are_reported_without_execution(self):
        self.assertIn("SHIM102", self.codes(self.graph("return 1\n")))

    def test_source_encoding_and_deterministic_graph(self):
        entry = self.root / "app.py"
        source = b"# coding: latin-1\ntext = 'caf\xe9'\nimport json\n"
        entry.write_bytes(source)
        first = analyze(entry, installed_paths=())
        second = analyze(entry, installed_paths=())
        self.assertTrue(first.supported)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.modules["__main__"].source, source)

    def test_environment_modules_are_marked_external(self):
        site = self.root / "site"
        self.write("site/library.py", "value = 1\n")
        graph = analyze(self.write("app.py", "import library\n"), installed_paths=(site,))
        self.assertTrue(graph.modules["library"].external)

    def test_nonexistent_stdlib_children_are_not_accepted(self):
        graph = self.graph("import json.nonexistent_child\nimport sys.nonexistent_child\nimport os.path\n")
        self.assertEqual(graph.modules["json.nonexistent_child"].kind, "missing")
        self.assertEqual(graph.modules["sys.nonexistent_child"].kind, "missing")
        self.assertEqual(graph.modules["os.path"].kind, "stdlib")
