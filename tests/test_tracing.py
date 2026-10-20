import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from shimify.analyzer import analyze
from shimify.cli import main
from shimify.provenance import BundleError
from shimify.tracing import trace


class TracingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'app.py'

    def graph(self, source):
        self.source.write_text(source, encoding='utf-8')
        return analyze(self.source)

    def test_execution_is_explicit_and_sources_must_still_match(self):
        marker = self.root / 'marker'
        graph = self.graph(f'open({str(marker)!r}, "w").write("executed")')
        with patch('shimify.tracing.subprocess.Popen') as start:
            with self.assertRaisesRegex(BundleError, 'SHIM430'):
                trace(graph)
            start.assert_not_called()
        self.assertFalse(marker.exists())
        self.source.write_text('changed')
        with self.assertRaisesRegex(BundleError, 'SHIM306'):
            trace(graph, allow_execution=True)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['trace', str(self.source)]), 1)

    def test_known_fixture_observations_are_deterministic_and_never_removal_authority(self):
        fixture = Path(__file__).parent / 'fixtures/text_metrics/app.py'
        graph = analyze(fixture)
        first = trace(graph, allow_execution=True, arguments=('A😀 text',))
        second = trace(graph, allow_execution=True, arguments=('A😀 text',))
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'completed')
        self.assertTrue(first['evidence_complete'])
        self.assertFalse(first['removal_authorized'])
        self.assertTrue(first['sources_unchanged'])
        self.assertEqual(first['runtime']['python']['version'], sys.version.split()[0])
        self.assertIn('text_metrics', {item['name'] for item in first['runtime']['import_requests']})
        self.assertNotIn('A😀 text', json.dumps(first))
        self.assertGreater(first['stdout']['captured_bytes'], 0)
        self.assertFalse(first['stdout']['truncated'])

    def test_failure_and_static_dynamic_diagnostics_remain_explicit(self):
        graph = self.graph('import importlib\nimportlib.import_module("json")\nraise ValueError("private error detail")\n')
        self.assertFalse(graph.supported)
        report = trace(graph, allow_execution=True)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['runtime']['error_type'], 'ValueError')
        self.assertFalse(report['static_supported'])
        self.assertIn('SHIM111', {item['code'] for item in report['static_diagnostics']})
        self.assertNotIn('private error detail', json.dumps(report))
        self.assertFalse(report['removal_authorized'])
        report = trace(self.graph('raise SystemExit(7)'), allow_execution=True)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['runtime']['application_exit_code'], 7)

    def test_timeout_output_limit_and_abrupt_exit_are_bounded(self):
        report = trace(self.graph('while True:\n    pass'), allow_execution=True, timeout=0.15)
        self.assertEqual(report['status'], 'timeout')
        self.assertFalse(report['evidence_complete'])
        report = trace(self.graph('print("x" * 1000000)'), allow_execution=True, max_output_bytes=1024)
        self.assertEqual(report['status'], 'output-limit')
        self.assertEqual(report['stdout']['captured_bytes'], 1024)
        self.assertTrue(report['stdout']['truncated'])
        report = trace(self.graph('import os\nos._exit(9)'), allow_execution=True)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['process_exit_code'], 9)
        self.assertIsNone(report['runtime'])
        self.assertFalse(report['evidence_complete'])

    def test_changed_sources_and_cli_report_are_visible(self):
        graph = self.graph('from pathlib import Path\nPath(__file__).write_text("changed")')
        report = trace(graph, allow_execution=True)
        self.assertFalse(report['sources_unchanged'])
        self.assertFalse(report['evidence_complete'])
        self.graph('print("hello")')
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(main(['trace', str(self.source), '--allow-execution']), 0)
        self.assertEqual(json.loads(stream.getvalue())['status'], 'completed')
        for options in [dict(timeout=0), dict(timeout=float('nan')), dict(max_output_bytes=0), dict(arguments=('bad\0value',))]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                trace(analyze(self.source), allow_execution=True, **options)
