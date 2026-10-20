"""Measure committed source fixtures; executing these fixtures is intentional."""

import argparse
import base64
from datetime import datetime, UTC
import gzip
import hashlib
from importlib.metadata import PathDistribution
import io
import json
from pathlib import Path, PurePosixPath
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import zlib

from shimify import __version__
from shimify.analyzer import analyze
from shimify.artifacts import write_directory
from shimify.bundler import bundle
from shimify.linker import link
from shimify.provenance import BundleError


ROOT = Path(__file__).resolve().parents[1]
TEXT_INPUTS = ['', 'hello world', ' \t\n\r\v\f', 'one\ntwo\n', 'one\rtwo', 'A😀é', 'a\u00a0b', None]
VERSION_INPUTS = ['0', '1.0', '1.0rc1', '1.0.post2', '2!1.0', '1.0+linux.1', '1.0.dev3', 'v2.0', '', 'not-a-version']


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + '\n').encode()


def archive(files):
    """Canonical USTAR+gzip bytes, independent of filesystem modes/timestamps."""
    names, stream = set(), io.BytesIO()
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as output:
        for name, data in sorted(files.items()):
            path = PurePosixPath(name)
            if (not isinstance(name, str) or not path.parts or path.is_absolute() or '..' in path.parts
                    or path.as_posix() != name or '\\' in name or any(ord(char) < 32 for char in name)
                    or any(part.split('.')[0].upper() in reserved or part.endswith(('.', ' '))
                           or any(char in part for char in ':*?"<>|') for part in path.parts)
                    or type(data) is not bytes):
                raise ValueError('Archive needs portable relative names and immutable bytes.')
            key = name.casefold()
            if key in names or any(key.startswith(other + '/') or other.startswith(key + '/') for other in names):
                raise ValueError('Archive paths collide.')
            names.add(key)
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            output.addfile(info, io.BytesIO(data))
    raw = stream.getvalue()
    compressed = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=compressed, compresslevel=9, mtime=0) as output:
        output.write(raw)
    return raw, compressed.getvalue()


def summarize(files, source_paths):
    raw, compressed = archive(files)
    source = sum(len(files[path]) for path in source_paths)
    notices = sum(len(data) for path, data in files.items() if path.startswith('LICENSES/'))
    total = sum(map(len, files.values()))
    return {'source_bytes': source, 'notices_bytes': notices, 'other_bytes': total - source - notices,
            'complete_payload_bytes': total, 'canonical_tar_bytes': len(raw), 'gzip_tar_bytes': len(compressed),
            'gzip_tar_sha256': hashlib.sha256(compressed).hexdigest(),
            'files': [{'path': path, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                       'role': 'source' if path in source_paths else 'notice' if path.startswith('LICENSES/') else 'other'}
                      for path, data in sorted(files.items())]}, compressed


def recorded_package(root):
    """Use the declared pilot installation and reject inconsistent owned bytes."""
    info = root / 'packaging-25.0.dist-info'
    if info.is_symlink() or not info.is_dir():
        raise ValueError('Install the declared packaging==25.0 pilot first.')
    distribution = PathDistribution(info)
    if (distribution.metadata['Name'].casefold(), distribution.version) != ('packaging', '25.0'):
        raise ValueError('The measurement pilot must be packaging==25.0.')
    selected = {}
    for record in distribution.files or ():
        relative = PurePosixPath(str(record))
        if not relative.parts or relative.parts[0] != 'packaging':
            continue
        if relative.is_absolute() or '..' in relative.parts or '\\' in str(record):
            raise ValueError('Unsafe pilot RECORD path.')
        if relative.suffix != '.py' and relative.name != 'py.typed':
            raise ValueError('Unadopted pilot asset: ' + relative.as_posix())
        path = root.joinpath(*relative.parts)
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent.is_relative_to(root)):
            raise ValueError('Pilot source symlinks are unsupported.')
        data = path.read_bytes()
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        if record.hash is None or record.hash.mode != 'sha256' or record.hash.value != digest or record.size != len(data):
            raise ValueError('Pilot source differs from its installation RECORD: ' + relative.as_posix())
        selected[relative.as_posix()] = data
    if not {'packaging/__init__.py', 'packaging/version.py', 'packaging/_structures.py'} <= selected.keys():
        raise ValueError('The pilot source installation is incomplete.')
    return selected, hashlib.sha256((info / 'RECORD').read_bytes()).hexdigest()


def observe(fixture, source_root, inputs, *, repeats, warm_iterations):
    timings, memory, outcome = [], [], None
    for mode in ['cold', 'warm', 'memory']:
        memory_run = mode == 'memory'
        for _ in range(repeats):
            request = {'fixture': fixture, 'source_root': str(source_root), 'inputs': inputs,
                       'memory': memory_run, 'warm_iterations': 0 if mode == 'cold' else warm_iterations}
            started = time.perf_counter_ns()
            result = subprocess.run([sys.executable, '-I', '-S', '-B', '-X', 'utf8', str(ROOT / 'scripts/_measure_child.py')],
                                    input=json.dumps(request), check=True, capture_output=True,
                                    text=True, encoding='utf-8', timeout=30, cwd=source_root.parent)
            wall = time.perf_counter_ns() - started
            observation = json.loads(result.stdout)
            if outcome is None:
                outcome = observation.pop('outcome')
            elif observation.pop('outcome') != outcome:
                raise ValueError('Fixture outcomes differ across observations.')
            if memory_run:
                memory.append(observation['memory'])
            else:
                timings.append({'mode': mode, 'process_wall_ns': wall, **observation})
    return {'outcome': outcome, 'timing_observations': timings, 'memory_observations': memory,
            'median_import_ns': statistics.median(row['import_ns'] for row in timings),
            'median_cold_process_wall_ns': statistics.median(row['process_wall_ns'] for row in timings if row['mode'] == 'cold'),
            'median_warm_ns_per_batch': statistics.median(row['warm_total_ns'] / warm_iterations for row in timings if row['mode'] == 'warm')}


def baseline(files, output):
    result = dict(files)
    result['BASELINE-MANIFEST.json'] = json_bytes({'kind': 'source-measurement-baseline', 'schema_version': 1,
        'files': [{'path': path, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for path, data in sorted(files.items())]})
    write_directory(output, result, source_roots=())
    return result


def measure(pilot, output, *, repeats=5, warm_iterations=1000):
    if not 3 <= repeats <= 31 or not 1 <= warm_iterations <= 100_000:
        raise ValueError('Use 3–31 repeats and 1–100000 warm iterations.')
    pilot = Path(pilot).resolve()
    package, record_hash = recorded_package(pilot)
    cases, archives = [], {}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / 'text-source'
        source.mkdir()
        for relative in ['text_metrics/__init__.py', 'text_metrics/metrics.py', 'text_metrics/helpers.py']:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'tests/fixtures/text_metrics' / relative, path)
        shutil.copyfile(ROOT / 'LICENSE', source / 'LICENSE')
        reduced_root = root / 'text-reduced'
        manifest = link(source / 'text_metrics/__init__.py', 'metrics', reduced_root)
        reduced = {record['path']: (reduced_root / record['path']).read_bytes() for record in manifest['files']}
        reduced['SHIMIFY-LINK.json'] = (reduced_root / 'SHIMIFY-LINK.json').read_bytes()
        original = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob('*.py')}
        original.update({path: data for path, data in reduced.items() if path.startswith('LICENSES/')})
        original_root = root / 'text-original'
        original = baseline(original, original_root)
        cases.append(('text_metrics', 'original-module-closure', original, original_root, TEXT_INPUTS))
        cases.append(('text_metrics', 'linked-callable', reduced, reduced_root, TEXT_INPUTS))

        app = root / 'version-source'
        app.mkdir()
        shutil.copyfile(ROOT / 'examples/version_info.py', app / 'version_info.py')
        shutil.copyfile(ROOT / 'LICENSE', app / 'LICENSE')
        reduced_root = root / 'version-reduced'
        manifest = bundle(analyze(app / 'version_info.py', installed_paths=(pilot,)), reduced_root)
        reduced = {record['path']: (reduced_root / record['path']).read_bytes() for record in manifest['files']}
        reduced['SHIMIFY-MANIFEST.json'] = (reduced_root / 'SHIMIFY-MANIFEST.json').read_bytes()
        for record in manifest['sources']:
            if record['distribution'] == 'packaging-25.0' and reduced[record['output']] != package[record['source']]:
                raise ValueError('Pilot source changed after the verified baseline snapshot.')
        original = {**package, 'version_info.py': (app / 'version_info.py').read_bytes()}
        original.update({path: data for path, data in reduced.items() if path.startswith('LICENSES/')})
        original_root = root / 'version-original'
        original = baseline(original, original_root)
        cases.append(('packaging-25.0', 'original-package', original, original_root, VERSION_INPUTS))
        cases.append(('packaging-25.0', 'module-bundle', reduced, reduced_root / '_sources', VERSION_INPUTS))
        records, expected = [], {}
        for fixture, variant, files, source_root, inputs in cases:
            source_paths = {path for path in files if path.endswith('.py') and path != 'run.py'}
            sizes, compressed = summarize(files, source_paths)
            observations = observe(fixture, source_root, inputs, repeats=repeats, warm_iterations=warm_iterations)
            if fixture in expected and expected[fixture] != observations['outcome']:
                raise ValueError('Original/reduced behavior differs: ' + fixture)
            expected[fixture] = observations['outcome']
            name = fixture + '-' + variant + '.tar.gz'
            archives['artifacts/' + name] = compressed
            records.append({'fixture': fixture, 'variant': variant, 'archive': 'artifacts/' + name,
                            'inputs': inputs, 'sizes': sizes, **observations})
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        modified = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True))
    except (OSError, subprocess.CalledProcessError):
        revision, modified = None, None
    report = {'kind': 'shimify-source-measurements', 'schema_version': 1,
              'collected_at_utc': datetime.now(UTC).isoformat(), 'shimify_version': __version__,
              'repository_revision': revision, 'working_tree_modified': modified,
              'python': {'implementation': platform.python_implementation(), 'version': platform.python_version()},
              'host': {'system': platform.system(), 'release': platform.release(), 'machine': platform.machine()},
              'compression': {'archive': 'USTAR', 'gzip_level': 9, 'mtime': 0, 'zlib_version': zlib.ZLIB_RUNTIME_VERSION},
              'scripts': {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest() for name in ['measure_sources.py', '_measure_child.py']},
              'pilot': {'name': 'packaging', 'version': '25.0', 'installed_record_sha256': record_hash,
                        'requirements_sha256': hashlib.sha256((ROOT / 'tests/pilot-requirements.txt').read_bytes()).hexdigest()},
              'method': {'repeats_per_mode': repeats, 'warm_iterations_per_batch': warm_iterations,
                         'cold': 'fresh isolated process and module cache through first batch and shutdown; no pyc files; OS page cache uncontrolled',
                         'warm': 'same imported module; one batch runs all declared inputs',
                         'memory': 'separate fresh processes; tracemalloc after runner imports, peak RSS includes interpreter',
                         'timing': 'monotonic perf_counter_ns; cold wall time includes process/protocol/first batch/shutdown; warm observations are separate; no tracemalloc',
                         'artifact': 'selected source deployment plus all notices/manifests/wrappers; gzip is a canonical tar, not observed HTTP transfer'},
              'cases': records}
    write_directory(output, {**archives, 'report.json': json_bytes(report)}, source_roots=(pilot, ROOT / 'tests/fixtures/text_metrics'))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--warm-iterations', type=int, default=1000)
    args = parser.parse_args()
    try:
        report = measure(args.pilot, args.output, repeats=args.repeats, warm_iterations=args.warm_iterations)
    except (BundleError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({'cases': len(report['cases']), 'behavior_parity': True, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
