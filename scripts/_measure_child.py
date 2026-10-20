"""Isolated runner for the two committed source-measurement fixtures only."""

import importlib
import json
import sys
import time


def main():
    request = json.loads(sys.stdin.read())
    sys.path.insert(0, request['source_root'])
    memory = request['memory']
    if memory:
        import tracemalloc
        tracemalloc.start()
    started = time.perf_counter_ns()
    if request['fixture'] == 'text_metrics':
        selected = importlib.import_module('text_metrics').metrics
    elif request['fixture'] == 'packaging-25.0':
        selected = importlib.import_module('version_info').describe
    else:
        raise ValueError('Unknown committed measurement fixture.')
    import_ns = time.perf_counter_ns() - started

    def workload():
        results = []
        for value in request['inputs']:
            try:
                results.append({'value': selected(value)})
            except Exception as error:
                results.append({'error': {'type': type(error).__name__, 'message': str(error)}})
        return results

    started = time.perf_counter_ns()
    first = workload()
    first_ns = time.perf_counter_ns() - started
    last = first
    started = time.perf_counter_ns()
    for _ in range(request['warm_iterations']):
        last = workload()
    warm_ns = time.perf_counter_ns() - started
    if first != last:
        raise ValueError('Fixture changed its result during repeated execution.')
    observation = {'outcome': first}
    if memory:
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_bytes = rss if sys.platform == 'darwin' else rss * 1024 if sys.platform.startswith('linux') else None
        except ImportError:
            rss, rss_bytes = None, None
        observation['memory'] = {'tracemalloc_current_bytes': current, 'tracemalloc_peak_bytes': peak,
                                 'process_peak_rss_native': rss, 'process_peak_rss_bytes': rss_bytes,
                                 'rss_native_unit': 'bytes' if sys.platform == 'darwin' else 'KiB' if sys.platform.startswith('linux') else None}
    else:
        observation.update(import_ns=import_ns, first_batch_ns=first_ns,
                           warm_total_ns=warm_ns if request['warm_iterations'] else None)
    print(json.dumps(observation, ensure_ascii=True, sort_keys=True))


if __name__ == '__main__':
    main()
