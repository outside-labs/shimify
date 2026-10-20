"""Bounded explicit runtime observations, separate from read-only analysis."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time

from shimify import __version__
from shimify.models import ModuleGraph
from shimify.provenance import BundleError


def _capture(pipe, limit, exceeded, result):
    digest, captured, truncated = hashlib.sha256(), 0, False
    try:
        while chunk := pipe.read(4096):
            remaining = max(0, limit - captured)
            selected = chunk[:remaining]
            digest.update(selected)
            captured += len(selected)
            if len(selected) != len(chunk):
                truncated = True
                exceeded.set()
    finally:
        result.update(captured_bytes=captured, sha256=digest.hexdigest(), truncated=truncated)
        pipe.close()


def _stop(process):
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _same_source(module):
    try:
        return module.source is not None and module.path is not None and module.path.read_bytes() == module.source
    except OSError:
        return False


def _valid_runtime(value):
    return (isinstance(value, dict) and value.get('observer') == 'shimify-runtime-evidence/1'
            and isinstance(value.get('status'), str) and value.get('status') in {'completed', 'failed'} and isinstance(value.get('python'), dict)
            and isinstance(value.get('import_requests'), list) and isinstance(value.get('new_module_names'), list)
            and type(value.get('background_threads')) is bool
            and type(value.get('observation_limit_reached')) is bool)


def trace(graph: ModuleGraph, *, allow_execution: bool = False, arguments: tuple[str, ...] = (),
          timeout: float = 5, max_output_bytes: int = 65_536) -> dict:
    """Run an explicitly opted-in script; observations never establish complete closure."""
    if allow_execution is not True:
        raise BundleError('SHIM430: Runtime evidence requires explicit allow_execution=True or --allow-execution.')
    if not isinstance(timeout, (int, float)) or not 0.05 <= timeout <= 60:
        raise ValueError('timeout must be between 0.05 and 60 seconds')
    if type(max_output_bytes) is not int or not 1024 <= max_output_bytes <= 1_048_576:
        raise ValueError('max_output_bytes must be between 1024 and 1048576')
    if not isinstance(arguments, tuple) or any(not isinstance(value, str) or '\0' in value for value in arguments):
        raise ValueError('arguments must be a tuple of strings without null characters')
    if '__main__' not in graph.modules:
        raise ValueError('Runtime evidence requires a script graph.')
    sources = [module for module in graph.modules.values() if module.kind == 'source']
    if any(module.name != '__main__' and module.name.split('.')[0] in sys.stdlib_module_names for module in sources):
        raise BundleError('SHIM430: Runtime observation does not support source modules shadowing the standard library.')
    if not all(_same_source(module) for module in sources):
        raise BundleError('SHIM306: Source changed since static analysis.')
    runner = Path(__file__).with_name('_trace_runner.py')
    exceeded = Event()
    stdout, stderr = {}, {}
    with tempfile.TemporaryDirectory(prefix='shimify-trace-') as temporary:
        report_path = Path(temporary) / 'evidence.json'
        command = [sys.executable, '-I', '-X', 'utf8', '-S', str(runner), str(graph.entrypoint),
                   json.dumps([str(root) for root in graph.search_paths]), json.dumps(arguments), str(report_path)]
        process = subprocess.Popen(command, cwd=temporary, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=os.name == 'posix')
        readers = [Thread(target=_capture, args=(pipe, max_output_bytes, exceeded, result), daemon=True)
                   for pipe, result in [(process.stdout, stdout), (process.stderr, stderr)]]
        for reader in readers:
            reader.start()
        deadline, stopped = time.monotonic() + timeout, None
        try:
            while process.poll() is None:
                if exceeded.is_set():
                    stopped = 'output-limit'
                    break
                if time.monotonic() >= deadline:
                    stopped = 'timeout'
                    break
                exceeded.wait(min(0.02, max(0, deadline - time.monotonic())))
            if stopped:
                _stop(process)
            process.wait(timeout=5)
        finally:
            # Terminate remaining members of the owned POSIX process group too.
            _stop(process)
            for reader in readers:
                reader.join(timeout=5)
        if any(reader.is_alive() for reader in readers):
            raise BundleError('SHIM431: Output pipes did not close after trace teardown.')
        if exceeded.is_set():
            stopped = stopped or 'output-limit'
        runtime = None
        if report_path.is_file() and report_path.stat().st_size <= 1_048_576:
            try:
                runtime = json.loads(report_path.read_text(encoding='utf-8'))
                if not _valid_runtime(runtime):
                    runtime = None
            except (ValueError, OSError):
                pass
        unchanged = all(_same_source(module) for module in sources)
        status = stopped or (runtime['status'] if runtime else 'failed')
        return {'schema_version': 1, 'shimify_version': __version__, 'mode': 'runtime-evidence',
                'entrypoint': graph.entrypoint.name, 'arguments_sha256': hashlib.sha256(json.dumps(arguments).encode()).hexdigest(),
                'status': status, 'process_exit_code': process.returncode, 'runtime': runtime,
                'observation_method': 'builtin-import-requests-and-module-diff',
                'stdout': stdout, 'stderr': stderr, 'sources_unchanged': unchanged,
                'sources': [{'module': module.name, 'sha256': module.sha256} for module in sorted(sources, key=lambda item: item.name)],
                'static_supported': graph.supported, 'static_diagnostics': [asdict(item) for item in graph.diagnostics],
                'limits': {'timeout_seconds': timeout, 'output_bytes_per_stream': max_output_bytes, 'memory_limit': None},
                'evidence_complete': runtime is not None and not stopped and unchanged and not runtime['observation_limit_reached'] and not runtime['background_threads'],
                'removal_authorized': False,
                'limitations': ['Observed imports are workload evidence; unobserved dependencies remain unknown.',
                                'Isolated Python flags and a separate process are not a security sandbox.',
                                'Output is bounded and hashed; raw output and error messages are not included.',
                                'No process memory limit is imposed; this report cannot justify runtime file deletion.']}
