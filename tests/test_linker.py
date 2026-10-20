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

from shimify.analyzer import analyze_module
from shimify.bundler import bundle
from shimify.cli import main
from shimify.linker import link
from shimify.provenance import BundleError, collect_provenance


FIXTURE = Path(__file__).parent / 'fixtures' / 'text_metrics'


class LinkerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        shutil.copytree(FIXTURE, self.source)
        (self.source / 'LICENSE').write_text('Synthetic fixture notice\n')
        self.output = self.root / 'linked'

    def run_code(self, root, source):
        return subprocess.run([sys.executable, '-I', '-X', 'utf8', '-S', '-c',
                               'import sys;sys.path.insert(0,sys.argv[1]);' + source, str(root)],
                              check=True, capture_output=True, text=True, encoding='utf-8', timeout=5,
                              cwd=self.root).stdout

    def test_selected_closure_reexports_identity_and_clean_original_parity(self):
        source = ("import importlib,json; from text_metrics import metrics; "
                  "module=importlib.import_module('text_metrics.metrics'); "
                  "helper=importlib.import_module('text_metrics.helpers'); "
                  "assert metrics is module.metrics; assert module.count_characters is helper.character_count; "
                  "values=['','hello world',' \\t\\n\\r\\v\\f','one\\ntwo\\n','one\\rtwo','A😀é','a\\u00a0b']; "
                  "print(json.dumps([metrics(value) for value in values])); "
                  "print(metrics.__module__)")
        original = self.run_code(self.source, source)
        manifest = link(self.source / 'text_metrics/__init__.py', 'metrics', self.output)
        modules = {item['module']: item for item in manifest['sources']}
        self.assertEqual(modules['text_metrics.helpers']['omitted'], ['unused_reverse'])
        self.assertEqual(modules['text_metrics.helpers']['retained'], ['character_count'])
        self.assertEqual(manifest['definition'], {'module': 'text_metrics.metrics', 'symbol': 'metrics'})
        self.assertLess(manifest['size']['extracted_source_bytes'], manifest['size']['original_source_bytes'])
        self.assertTrue(any(edge['reason'] == 'imported binding' for edge in manifest['edges']))
        self.assertEqual((self.output / 'LICENSES/local-1/LICENSE').read_text(), 'Synthetic fixture notice\n')
        self.assertEqual(manifest, link(self.source / 'text_metrics/__init__.py', 'metrics', self.root / 'second'))
        shutil.rmtree(self.source)
        self.assertEqual(self.run_code(self.output, source), original)
        invalid = "from text_metrics import metrics\ntry: metrics(None)\nexcept Exception as error: print(type(error).__name__+': '+str(error))"
        self.assertEqual(self.run_code(self.output, invalid), 'TypeError: text must be str\n')
        self.assertEqual(json.loads((self.output / 'SHIMIFY-LINK.json').read_bytes()), manifest)
        for record in manifest['files']:
            data = (self.output / record['path']).read_bytes()
            self.assertEqual(len(data), record['size_bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), record['sha256'])

    def test_entry_submodule_includes_parent_initializer_and_cli(self):
        graph = analyze_module('text_metrics.metrics', search_paths=(self.source,))
        self.assertIn('text_metrics', graph.modules)
        with self.assertRaisesRegex(BundleError, 'script graph'):
            bundle(graph, self.output)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['link', str(self.source / 'text_metrics/metrics.py') + ':metrics', '--output', str(self.output)]), 0)
        self.assertIn('text_metrics/__init__.py', {record['path'] for record in json.loads((self.output / 'SHIMIFY-LINK.json').read_bytes())['files']})

    def test_defined_cycle_keeps_literal_availability_and_import_order(self):
        (self.source / 'a.py').write_text("FIRST = 7\nfrom b import helper as selected_helper\ndef selected():\n    return selected_helper()\ndef unused():\n    return 99\n")
        (self.source / 'b.py').write_text("from a import FIRST\ndef helper():\n    return FIRST\n")
        original = self.run_code(self.source, 'from a import selected; print(selected())')
        link(self.source / 'a.py', 'selected', self.output)
        self.assertEqual(self.run_code(self.output, 'from a import selected; print(selected())'), original)
        self.assertLess((self.output / 'a.py').read_text().index('FIRST = 7'), (self.output / 'a.py').read_text().index('from b import'))
        self.assertNotIn('unused', (self.output / 'a.py').read_text())

    def test_uninitialized_cycle_and_dynamic_boundaries_fail_before_publication(self):
        (self.source / 'a.py').write_text('from b import helper\ndef selected():\n    return helper()\n')
        (self.source / 'b.py').write_text('from a import selected\ndef helper():\n    return 7\n')
        with self.assertRaisesRegex(BundleError, 'SHIM421'):
            link(self.source / 'a.py', 'selected', self.output)
        self.assertFalse(self.output.exists())
        invalid = [
            'print("initialization")\ndef selected():\n    return 1\n',
            'from missing_package import helper\ndef selected():\n    return helper()\n',
            'from text_metrics import *\ndef selected():\n    return 1\n',
            'from text_metrics.helpers import character_count\ndef selected(value):\n    return character_count.other(value)\n',
            'import text_metrics\ndef selected(value):\n    return text_metrics.metrics(value)\n',
            'def __getattr__(name):\n    return 7\ndef selected():\n    return 1\n',
            'def selected():\n    from text_metrics import metrics\n    return metrics("")\n',
            'VALUE = []\ndef selected():\n    return VALUE\n',
        ]
        for source in invalid:
            (self.source / 'bad.py').write_text(source)
            with self.subTest(source=source), self.assertRaises(BundleError):
                link(self.source / 'bad.py', 'selected', self.output)
            self.assertFalse(self.output.exists())

    def test_source_changes_unsafe_output_and_publication_failure_are_safe(self):
        target = self.source / 'text_metrics/helpers.py'
        def change(graph):
            result = collect_provenance(graph)
            target.write_text('changed\n')
            return result
        with patch('shimify.linker.collect_provenance', side_effect=change):
            with self.assertRaisesRegex(BundleError, 'SHIM306'):
                link(self.source / 'text_metrics/__init__.py', 'metrics', self.output)
        self.assertFalse(self.output.exists())
        shutil.copyfile(FIXTURE / 'text_metrics/helpers.py', target)
        with self.assertRaisesRegex(BundleError, 'overlaps'):
            link(self.source / 'text_metrics/__init__.py', 'metrics', self.source / 'linked')
        with patch('shimify.artifacts.os.link', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                link(self.source / 'text_metrics/__init__.py', 'metrics', self.output)
        self.assertFalse(self.output.exists())
        self.output.mkdir()
        (self.output / 'keep').write_text('keep')
        with self.assertRaises(BundleError):
            link(self.source / 'text_metrics/__init__.py', 'metrics', self.output)
        self.assertEqual((self.output / 'keep').read_text(), 'keep')
