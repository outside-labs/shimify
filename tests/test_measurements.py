import gzip
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import unittest

from scripts.measure_sources import archive, measure, recorded_package, summarize


class MeasurementTests(unittest.TestCase):
    def test_archive_is_canonical_and_sizes_separate_sources_notices_and_overhead(self):
        files = {'pkg/example.py': b'VALUE = 1\n', 'LICENSES/LICENSE': b'Fixture license\n', 'manifest.json': b'{}\n'}
        summary, compressed = summarize(files, {'pkg/example.py'})
        self.assertEqual(summary['source_bytes'], 10)
        self.assertEqual(summary['notices_bytes'], 16)
        self.assertEqual(summary['other_bytes'], 3)
        self.assertEqual(summary['complete_payload_bytes'], 29)
        self.assertEqual(compressed, archive(dict(reversed(list(files.items()))))[1])
        raw = gzip.decompress(compressed)
        self.assertEqual(summary['canonical_tar_bytes'], len(raw))
        with tarfile.open(fileobj=io.BytesIO(raw)) as result:
            self.assertEqual(result.getnames(), sorted(files))
            for member in result.getmembers():
                self.assertEqual((member.mtime, member.uid, member.gid, member.mode), (0, 0, 0, 0o644))
                self.assertEqual(result.extractfile(member).read(), files[member.name])

    def test_unsafe_archive_records_and_measurement_settings_are_refused(self):
        for files in [{'../x': b'x'}, {'/x': b'x'}, {'x\\y': b'x'}, {'X': b'x', 'x': b'x'},
                      {'x': b'x', 'x/y': b'y'}, {'CON.txt': b'x'}, {'x\ny': b'x'}, {'x': bytearray(b'x')}]:
            with self.subTest(files=files), self.assertRaises(ValueError):
                archive(files)
        for repeats, iterations in [(2, 1), (32, 1), (3, 0), (3, 100001)]:
            with self.assertRaises(ValueError):
                measure('unused', 'unused', repeats=repeats, warm_iterations=iterations)

    @unittest.skipUnless(os.environ.get('SHIMIFY_PILOT_PATH'), 'Set SHIMIFY_PILOT_PATH to the pinned pilot.')
    def test_real_fixture_parity_raw_observations_and_immutable_archives(self):
        pilot = Path(os.environ['SHIMIFY_PILOT_PATH']).resolve()
        files, record_hash = recorded_package(pilot)
        self.assertIn('packaging/version.py', files)
        self.assertEqual(len(record_hash), 64)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'measurements'
            report = measure(pilot, root, repeats=3, warm_iterations=1)
            self.assertEqual(report, json.loads((root / 'report.json').read_bytes()))
            self.assertEqual(report['method']['repeats_per_mode'], 3)
            self.assertEqual(len(report['cases']), 4)
            for original, reduced in zip(report['cases'][::2], report['cases'][1::2]):
                self.assertEqual(original['outcome'], reduced['outcome'])
                for case in (original, reduced):
                    self.assertEqual(len(case['timing_observations']), 6)
                    self.assertEqual(len(case['memory_observations']), 3)
                    self.assertGreater(case['sizes']['complete_payload_bytes'], case['sizes']['source_bytes'])
                    self.assertEqual(len((root / case['archive']).read_bytes()), case['sizes']['gzip_tar_bytes'])
                    for row in case['timing_observations']:
                        self.assertGreater(row['process_wall_ns'], 0)
                        if row['mode'] == 'warm':
                            self.assertGreater(row['warm_total_ns'], 0)
                        else:
                            self.assertIsNone(row['warm_total_ns'])
                    for row in case['memory_observations']:
                        self.assertGreaterEqual(row['tracemalloc_peak_bytes'], row['tracemalloc_current_bytes'])

    def test_pilot_without_owned_pinned_sources_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                recorded_package(Path(temporary))
