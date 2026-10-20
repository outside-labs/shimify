# Reproducing source measurements

PERF-01 measures the adopted text_metrics callable and packaging 25.0 module
pilot separately from any interpreter or browser runtime. The development
scripts execute only these declared fixtures. They add no runtime dependency.

```sh
uv sync --locked
uv pip install --python .venv/bin/python --target build/pilot \
  --require-hashes -r tests/pilot-requirements.txt
PYTHONPATH=src .venv/bin/python scripts/measure_sources.py \
  --pilot build/pilot --output build/source-measurements \
  --repeats 5 --warm-iterations 1000
```

Use a new output directory for each run. On Windows use the corresponding
`.venv/Scripts/python.exe` and set PYTHONPATH before the command. The pilot is
the existing build/test-only dependency, installed from its hash-locked input.
The script checks Name/Version and each selected package file against its
installed RECORD; that consistency check is not an independent signature of an
installation. Install the pinned fixture first, rather than editing its RECORD.

The output includes `report.json` and four deterministic `.tar.gz` artifacts.
Reports record Python/host/tool/compression versions, the repository revision
and modified-tree flag, measurement-script hashes, pilot RECORD/requirements
hashes, every selected artifact file/hash, input cases, observed outcomes and
raw timings/memory samples. No host-specific absolute source paths are recorded.
Copies of original source, metadata and notices remain subject to their licenses.

## Comparison scope

The text_metrics baseline contains its original three-module closure and notices.
The linked variant retains the selected callable, re-exports, imports and needed
constants; the unused reverse utility is removed. Both expose the same metrics
API. Unrelated resource/decorator fixtures are outside this comparison.

The packaging baseline contains all RECORD-owned `.py`/`py.typed` files under
packaging 25.0, the version_info application and notices. The reduced module
bundle contains the application's static module closure, launcher, manifest and
the same notices. This measures module selection, not extraction of Version's
methods or a change to the Python runtime. The APIs used for timing are
`text_metrics.metrics` and `version_info.describe`, imported under the same
ordinary identity for original and reduced cases.

Each baseline has an explicit file manifest. Each reduced artifact includes its
normal audit manifest and any launcher. File bytes, notice bytes and all other
metadata/launcher bytes contribute to complete payload size. Canonical USTAR
bytes include archive headers/padding; gzip level 9 compresses that whole archive
with sorted paths, mtime zero and fixed ownership/modes. These are reproducible
archive sizes, not observed HTTP compression or a wheel comparison. Source byte
savings alone do not establish smaller complete artifacts.

## Timing and memory methods

Each fixture/variant has three modes, with the requested number of fresh-process
observations per mode. Sources are copied without pyc files; children use
`python -I -S -B -X utf8`. Site packages and previous module caches are absent.
The runner preloads its own JSON/protocol/timing modules. OS filesystem/page
caches, CPU frequency, background work and allocator behavior remain uncontrolled.
Variants run in the report's listed order; no statistical speed claim is made.

- Cold observations measure process wall time through import, one complete input
  batch and shutdown. They separately record target import and first-batch time.
- Warm observations import once, run a first batch, then repeat the complete
  input batch for the requested iteration count. Reported per-batch medians divide
  each raw warm total by that count. A batch contains all listed inputs.
- Memory observations use separate processes with tracemalloc enabled before
  target import, then the same first/warm workload. Current and peak traced
  Python allocations exclude earlier runner allocations. Process peak RSS
  includes the interpreter, runner and tracing overhead; native units and a
  supported-platform byte conversion are recorded. RSS is unavailable where
  resource.getrusage is unavailable. Tracing time is excluded from timing samples.

Each child has a 30-second deadline. Repeated input batches and original/reduced
outcomes must agree; invalid text input and invalid versions have explicit
observations. Tests check this parity, archive determinism, owned source records,
path boundaries and sample shape without asserting faster execution or lower
memory. These measurements authorize neither dependency removal based on missing
trace observations nor interpreter component removal.

The [2026-10-20 observations](measurements/2026-10-20-source.json) record one
CPython 3.14.7 / Darwin arm64 run. Reproduction generates new timing/memory
samples; deterministic artifact bytes and selected behavior can be compared
exactly when source/tool inputs match. The script hashes identify the measurement
code even though the initial observations were made before its commit.

## Observed sizes

| Fixture / variant | Source bytes | Complete payload bytes | Gzip tar bytes |
| --- | ---: | ---: | ---: |
| text_metrics / original-module-closure | 716 | 2,515 | 1,486 |
| text_metrics / linked-callable | 665 | 5,437 | 2,214 |
| packaging-25.0 / original-package | 222,143 | 242,162 | 60,492 |
| packaging-25.0 / module-bundle | 19,338 | 41,403 | 12,454 |

The tiny callable saves 51 source bytes while its detailed link manifest makes
the complete artifact larger. The packaging module bundle removes unused modules
and is smaller in both complete payload and compressed archive. Neither result
establishes a startup or memory improvement. All original/reduced outcomes match.

## Observed execution medians

| Fixture / variant | Cold process ms | Target import ms | Warm batch µs | Traced peak KiB | Process peak RSS KiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| text_metrics / original-module-closure | 19.748 | 1.016 | 2.416 | 620.5 | 19552.0 |
| text_metrics / linked-callable | 17.333 | 0.894 | 2.304 | 620.4 | 19488.0 |
| packaging-25.0 / original-package | 22.096 | 5.463 | 28.902 | 1443.7 | 22336.0 |
| packaging-25.0 / module-bundle | 22.006 | 5.362 | 28.775 | 1441.2 | 22384.0 |
