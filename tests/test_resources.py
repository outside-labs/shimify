import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from shimify.analyzer import analyze
from shimify.bundler import bundle
from shimify.cli import main
from shimify.provenance import BundleError
from shimify.resources import ResourcePolicy, TextResource


FIXTURE = Path(__file__).parent / 'fixtures/text_metrics'


class ResourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        shutil.copytree(FIXTURE, self.source)
        (self.source / 'LICENSE').write_text('Synthetic local notice\n')
        self.output = self.root / 'bundle'
        self.policy = ResourcePolicy((TextResource('text_metrics', 'stopwords.txt'),))
        self.script = self.source / 'resources_app.py'

    def run_bundle(self, output):
        return subprocess.run([sys.executable, '-I', '-X', 'utf8', '-S', str(output / 'run.py')],
                              check=True, capture_output=True, text=True, encoding='utf-8', timeout=5, cwd=self.root).stdout

    def distribution(self, *, resource_record=True):
        info = self.source / 'synthetic_text_metrics-1.0.dist-info'
        (info / 'licenses').mkdir(parents=True)
        (info / 'METADATA').write_text('Metadata-Version: 2.4\nName: synthetic-text-metrics\nVersion: 1.0\nLicense-File: LICENSE\n')
        (info / 'licenses/LICENSE').write_text('Synthetic distribution license\n')
        records = [path.relative_to(self.source).as_posix() for path in self.source.rglob('*.py')]
        records += [path.relative_to(self.source).as_posix() for path in [info / 'METADATA', info / 'licenses/LICENSE']]
        if resource_record:
            records.append('text_metrics/stopwords.txt')
        with (info / 'RECORD').open('w', newline='') as stream:
            csv.writer(stream).writerows([name, '', ''] for name in records)

    def test_declared_utf8_resource_is_the_only_copied_data_and_runs_cleanly(self):
        (self.source / 'text_metrics/private.txt').write_text('unlisted data')
        graph = analyze(self.script, resource_policy=self.policy)
        self.assertTrue(graph.supported, graph.diagnostics)
        manifest = bundle(graph, self.output)
        self.assertEqual(manifest['schema_version'], 2)
        self.assertEqual(manifest['mode'], 'modules-resources')
        self.assertEqual(manifest['resources'][0]['path'], 'stopwords.txt')
        self.assertIsNone(manifest['resources'][0]['distribution'])
        self.assertFalse((self.output / '_sources/text_metrics/private.txt').exists())
        self.assertEqual(manifest, bundle(graph, self.root / 'second'))
        for record in manifest['files']:
            data = (self.output / record['path']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), record['sha256'])
            self.assertEqual(len(data), record['size_bytes'])
        shutil.rmtree(self.source)
        self.assertEqual(self.run_bundle(self.output), '(7, 2, 1)\nand\nor\ncafé\n')

    def test_owned_version_metadata_and_notices_survive_without_original_install(self):
        self.script.write_text(self.script.read_text() + '\nfrom text_metrics.versions import source_version\nprint(source_version())\n')
        self.distribution()
        policy = ResourcePolicy(self.policy.resources, ('synthetic-text-metrics',))
        graph = analyze(self.script, resource_policy=policy)
        self.assertTrue(graph.supported, graph.diagnostics)
        manifest = bundle(graph, self.output)
        self.assertEqual(manifest['resources'][0]['distribution'], 'synthetic-text-metrics-1.0')
        metadata = manifest['distribution_versions'][0]
        self.assertEqual(metadata['version'], '1.0')
        self.assertIn('synthetic_text_metrics-1.0.dist-info', metadata['output'])
        self.assertEqual((self.output / Path(metadata['output']).parent / 'SHIMIFY-REDUCED.txt').is_file(), True)
        self.assertIn('Synthetic distribution license', '\n'.join((self.output / record['path']).read_text() for record in manifest['files'] if record['path'].startswith('LICENSES/') and record['path'].endswith('LICENSE')))
        shutil.rmtree(self.source)
        self.assertEqual(self.run_bundle(self.output), '(7, 2, 1)\nand\nor\ncafé\n1.0\n')

    def test_missing_policy_dynamic_paths_shadowing_and_api_reexports_are_refused(self):
        graph = analyze(self.script)
        self.assertIn('SHIM113', {item.code for item in graph.diagnostics})
        with self.assertRaises(BundleError):
            bundle(graph, self.output)
        variants = [
            'from importlib.resources import files\ndef read(path):\n    return files("text_metrics").joinpath(path).read_text(encoding="utf-8")\n',
            'from importlib.resources import files\ndef read(files):\n    return files("text_metrics").joinpath("stopwords.txt").read_text(encoding="utf-8")\n',
            'from importlib.resources import files\nloader = files\n',
            'import importlib\nloader = importlib\n',
            'from importlib.resources import files\ndef read():\n    from other import files\n    return files("text_metrics").joinpath("stopwords.txt").read_text(encoding="utf-8")\n',
            'from importlib.metadata import version\nprint(version("synthetic-text-metrics"))\n',
            'from importlib.metadata import entry_points\nentry_points()\n',
            'from text_metrics.resources import files\nfiles("text_metrics").joinpath("private.txt").read_text(encoding="utf-8")\n',
            'import text_metrics.resources as loader\nloader.files("text_metrics").joinpath("private.txt").read_text(encoding="utf-8")\n',
        ]
        for source in variants:
            self.script.write_text(source)
            graph = analyze(self.script, resource_policy=self.policy)
            with self.subTest(source=source):
                self.assertFalse(graph.supported)
                with self.assertRaises(BundleError):
                    bundle(graph, self.output)
                self.assertFalse(self.output.exists())

    def test_resource_limits_missing_files_utf8_and_record_ownership_fail_before_publication(self):
        resource = self.source / 'text_metrics/stopwords.txt'
        for data in [b'\xff', b'x' * 1_048_577]:
            resource.write_bytes(data)
            with self.assertRaisesRegex(BundleError, 'SHIM118'):
                bundle(analyze(self.script, resource_policy=self.policy), self.output)
            self.assertFalse(self.output.exists())
        resource.unlink()
        with self.assertRaisesRegex(BundleError, 'SHIM118'):
            bundle(analyze(self.script, resource_policy=self.policy), self.output)
        resource.write_text('and\n')
        self.distribution(resource_record=False)
        with self.assertRaisesRegex(BundleError, 'not recorded'):
            bundle(analyze(self.script, resource_policy=self.policy), self.output)
        policy = ResourcePolicy(self.policy.resources, ('unowned-distribution',))
        # Remove the claimed source ownership to test missing version ownership separately.
        shutil.rmtree(self.source / 'synthetic_text_metrics-1.0.dist-info')
        with self.assertRaisesRegex(BundleError, 'source-owning distribution'):
            bundle(analyze(self.script, resource_policy=policy), self.output)

    def test_resource_symlinks_are_never_copied(self):
        path = self.source / 'text_metrics/stopwords.txt'
        path.unlink()
        target = self.root / 'outside.txt'
        target.write_text('outside')
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation is unavailable.')
        with self.assertRaisesRegex(BundleError, 'symlink'):
            bundle(analyze(self.script, resource_policy=self.policy), self.output)
        self.assertFalse(self.output.exists())

    def test_alias_cli_and_existing_schema_one_remain_distinct(self):
        helper = self.source / 'text_metrics/resources.py'
        helper.write_text('import importlib.resources as resource_api\ndef stopword_text():\n    return resource_api.files("text_metrics").joinpath("stopwords.txt").read_text(encoding="utf-8")\n')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['resources', str(self.script), '--resource', 'text_metrics:stopwords.txt', '--output', str(self.output)]), 0)
        self.assertEqual(self.run_bundle(self.output), '(7, 2, 1)\nand\nor\ncafé\n')
        original = bundle(analyze(self.source / 'app.py'), self.root / 'ordinary')
        self.assertEqual((original['schema_version'], original['mode']), (1, 'modules'))
        self.assertNotIn('resources', original)

    def test_declarations_reject_unsafe_ambiguous_and_empty_inputs(self):
        for path in ['../secret.txt', '/secret.txt', 'data\\secret.txt', './stopwords.txt', 'file.py', 'file?.txt', 'x\n.txt']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                TextResource('text_metrics', path)
        with self.assertRaises(ValueError):
            ResourcePolicy()
        with self.assertRaises(ValueError):
            ResourcePolicy((TextResource('pkg', 'A.txt'), TextResource('pkg', 'a.txt')))
        with self.assertRaises(ValueError):
            ResourcePolicy(versions=('some-name', 'some_name'))
