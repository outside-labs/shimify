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
from shimify.linker import link
from shimify.provenance import BundleError, collect_provenance
from shimify.symbols import analyze_symbols


FIXTURE = Path(__file__).parent / 'fixtures/class_counter'


class ClassExtractionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        shutil.copytree(FIXTURE, self.source)
        (self.source / 'LICENSE').write_text('Counter fixture notice\n')
        self.output = self.root / 'reduced'

    def run_code(self, root, code):
        return subprocess.check_output([sys.executable, '-I', '-S', '-X', 'utf8', '-c',
            'import sys;sys.path.insert(0,sys.argv[1]);' + code, str(root)],
            cwd=self.root, encoding='utf-8', timeout=5)

    def test_whole_class_identity_descriptors_defaults_state_and_all_method_dependencies(self):
        code = ("import json;from counter import Counter as Public;from counter.models import Counter;"
                "first=Public.make();second=Counter.make(7);"
                "print(json.dumps([Public is Counter,first.score,second.score,Counter.calls,Public.normalize(' a '),"
                "first.unused_api(),Public.token() is Counter.token(),Counter.__module__,"
                "Counter.score.fget.__qualname__,sorted(Counter.__annotations__)]))\n"
                "try:\n    first.score=10\nexcept AttributeError:\n    print('read-only')")
        original = self.run_code(self.source, code)
        manifest = link(self.source / 'counter/__init__.py', 'Counter', self.output, include_classes=True)
        self.assertEqual(manifest['extraction_profile'], 'linked-classes/1')
        self.assertEqual(manifest['definition'], {'module': 'counter.models', 'symbol': 'Counter'})
        self.assertEqual(manifest['class_units'][0]['methods'], ['__init__', 'score', 'normalize', 'token', 'make', 'unused_api'])
        record = next(item for item in manifest['sources'] if item['module'] == 'counter.models')
        self.assertEqual(record['omitted'], ['UNUSED', 'Unused'])
        self.assertIn('spare_helper', record['retained'])
        self.assertTrue(any(edge['reason'] == 'whole class global reference' and edge['to'].endswith(':spare_helper') for edge in manifest['edges']))
        self.assertEqual((self.output / 'LICENSES/local-1/LICENSE').read_text(), 'Counter fixture notice\n')
        self.assertEqual(manifest, link(self.source / 'counter/__init__.py', 'Counter', self.root / 'second', include_classes=True))
        shutil.rmtree(self.source)
        self.assertEqual(self.run_code(self.output, code), original)
        self.assertEqual(json.loads(original.splitlines()[0])[:7], [True, 3, 8, 2, 'a', 20, True])
        self.assertEqual(original.splitlines()[1], 'read-only')
        for item in manifest['files']:
            self.assertEqual(hashlib.sha256((self.output / item['path']).read_bytes()).hexdigest(), item['sha256'])

    def test_imported_class_attribute_calls_and_cli_retain_source_class_unit(self):
        (self.source / 'consumer.py').write_text('from counter import Counter as Type\ndef selected(value=2):\n    return Type.make(value).score\n')
        code = 'from consumer import selected;from counter import Counter;print(selected(),selected(7),Counter.calls)'
        original = self.run_code(self.source, code)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['link', str(self.source / 'consumer.py') + ':selected', '--classes', '--output', str(self.output)]), 0)
        self.assertEqual(self.run_code(self.output, code), original)
        self.assertEqual(original, '3 8 2\n')
        manifest = json.loads((self.output / 'SHIMIFY-LINK.json').read_bytes())
        self.assertEqual(manifest['class_units'][0]['symbol'], 'Counter')

    def test_explicit_object_base_annotation_only_fields_and_literal_annotation_data(self):
        target = self.source / 'plain.py'
        target.write_text('class Plain(object):\n    field: int\n    def __init__(self,value: "raw"=None) -> None:\n        self.value=value\n')
        code = 'from plain import Plain;print(Plain().value,sorted(Plain.__annotations__),Plain.__init__.__annotations__["value"])'
        original = self.run_code(self.source, code)
        link(target, 'Plain', self.output, include_classes=True)
        self.assertEqual(self.run_code(self.output, code), original)
        self.assertEqual(original, "None ['field'] raw\n")

    def test_defined_class_cycle_keeps_initialization_and_uninitialized_cycle_is_refused(self):
        (self.source / 'a.py').write_text('class A:\n    @staticmethod\n    def value():\n        return 3\nfrom b import B\ndef selected():\n    return B.value()\n')
        (self.source / 'b.py').write_text('from a import A\nclass B:\n    @staticmethod\n    def value():\n        return A.value()\n')
        original = self.run_code(self.source, 'from a import selected;print(selected())')
        link(self.source / 'a.py', 'selected', self.output, include_classes=True)
        self.assertEqual(self.run_code(self.output, 'from a import selected;print(selected())'), original)
        (self.source / 'a.py').write_text('from b import B\nclass A:\n    pass\ndef selected():\n    return B()\n')
        with self.assertRaisesRegex(BundleError, 'SHIM421'):
            link(self.source / 'a.py', 'selected', self.root / 'invalid-cycle', include_classes=True)
        self.assertFalse((self.root / 'invalid-cycle').exists())

    def test_unadopted_initialization_descriptors_hooks_and_shadowing_fail_without_execution(self):
        cases = [
            'def register(cls):\n    print("executed")\n    return cls\n@register\nclass Counter:\n    pass',
            'class Counter:\n    print("executed")',
            'class Base:\n    pass\nclass Counter(Base):\n    pass',
            'class Counter(metaclass=type):\n    pass',
            'object = 7\nclass Counter(object):\n    pass',
            'class Counter:\n    cache = []',
            'REGISTRY = {}\nclass Counter:\n    pass',
            'class Counter:\n    def __init_subclass__(cls):\n        print("executed")',
            'class Counter:\n    __slots__ = ("value",)',
            'class Counter:\n    @property\n    def value(self):\n        return 1\n    @value.setter\n    def value(self, value):\n        pass',
            'property = 7\nclass Counter:\n    @property\n    def value(self):\n        return 1',
            'class Counter:\n    property = 7\n    @property\n    def value(self):\n        return 1',
            'class Counter:\n    value: list[int] = 1',
            'class Counter:\n    def value(self, item=[]):\n        return item',
            'class Counter:\n    async def value(self):\n        pass',
            'class Counter:\n    class Nested:\n        pass',
            'class Counter:\n    def value(self):\n        return super()',
        ]
        target = self.source / 'invalid.py'
        for source in cases:
            target.write_text(source)
            with self.subTest(source=source), contextlib.redirect_stdout(io.StringIO()) as stdout:
                with self.assertRaises(BundleError):
                    link(target, 'Counter', self.output, include_classes=True)
                self.assertEqual(stdout.getvalue(), '')
                self.assertFalse(self.output.exists())

    def test_default_profiles_and_changed_source_safety_remain(self):
        target = self.source / 'counter/models.py'
        with self.assertRaisesRegex(BundleError, 'classes|Class'):
            link(target, 'Counter', self.output)
        with self.assertRaises(BundleError):
            extract(analyze_symbols(target, 'Counter'), self.output)
        def change(graph):
            provenance = collect_provenance(graph)
            target.write_text('changed\n')
            return provenance
        with patch('shimify.linker.collect_provenance', side_effect=change):
            with self.assertRaisesRegex(BundleError, 'SHIM306'):
                link(target, 'Counter', self.output, include_classes=True)
        self.assertFalse(self.output.exists())
