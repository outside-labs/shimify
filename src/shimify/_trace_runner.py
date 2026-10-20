"""Isolated subprocess observer. Import requests are evidence, never a removal list."""

import builtins
import json
from pathlib import Path
import platform
import runpy
import sys


def main():
    entry, roots, arguments, report_path = sys.argv[1:]
    sys.path[:0] = json.loads(roots)
    sys.argv = [entry, *json.loads(arguments)]
    original = builtins.__import__
    identity = {'implementation': platform.python_implementation(), 'version': platform.python_version(), 'platform': sys.platform}
    requests, overflow = set(), False
    before = set(sys.modules)

    def observe(name, globals=None, locals=None, fromlist=(), level=0):
        nonlocal overflow
        if type(name) is str and len(name) <= 256 and type(level) is int and -1024 <= level <= 1024:
            names = tuple(fromlist) if type(fromlist) in (tuple, list) else ()
            if len(names) <= 32 and all(type(item) is str and len(item) <= 256 for item in names):
                request = (name, level, names)
                if len(requests) < 1024 or request in requests:
                    requests.add(request)
                else:
                    overflow = True
            else:
                overflow = True
        else:
            overflow = True
        return original(name, globals, locals, fromlist, level)

    status, error_type, application_exit_code = 'completed', None, 0
    builtins.__import__ = observe
    try:
        runpy.run_path(entry, run_name='__main__')
    except SystemExit as error:
        code = error.code
        application_exit_code = code if type(code) is int else 0 if code is None else None
        if application_exit_code != 0:
            status, error_type = 'failed', 'SystemExit'
    except BaseException as error:
        status, error_type, application_exit_code = 'failed', type(error).__name__, None
    finally:
        builtins.__import__ = original
    loaded = sorted(name for name in set(sys.modules) - before if type(name) is str)
    if len(loaded) > 4096 or any(len(name) > 256 for name in loaded):
        overflow = True
        loaded = [name for name in loaded if len(name) <= 256][:4096]
    report = {'observer': 'shimify-runtime-evidence/1', 'status': status, 'error_type': error_type, 'application_exit_code': application_exit_code,
              'python': identity,
              'background_threads': len(sys._current_frames()) > 1,
              'import_requests': [{'name': name, 'level': level, 'fromlist': list(names)} for name, level, names in sorted(requests)],
              'new_module_names': loaded, 'observation_limit_reached': overflow}
    Path(report_path).write_text(json.dumps(report, ensure_ascii=True, sort_keys=True) + '\n', encoding='utf-8')
    return 0 if status == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
