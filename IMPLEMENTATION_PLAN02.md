# Shimify 0.2 implementation plan

Forward roadmap adopted 2026-10-20: [source reduction, browser compiler and
independent interpreter program](IMPLEMENTATION_PLAN03.md). This document
retains its historical release contract.

## Mission and boundary

Transform a supported Python program or callable into an auditable, smaller
source artifact while preserving its documented behavior. Size reduction,
import cost, and interpreter size are separate measurements. No static result
proves the minimum implementation for every possible Python execution.

The 0.2 design brief extends the existing 0.1 module graph and byte-preserving
bundler. Keep those APIs and artifact contracts compatible. Build symbol
analysis alongside them, without moving the existing modules into a new package
hierarchy merely to match the suggested directory sketch.

The GitHub Project and linked issues are the development queue. This document
specifies architecture, acceptance gates, and sequencing; PRs record validation.

## Feasibility and division of responsibilities

Three independent layers contribute to a small application:

1. **Source reachability:** omit whole modules, then supported unused symbols.
   Shimify owns parsing, resolution, dependency reasons, transformations,
   source hashes, attribution, and the source artifact.
2. **Runtime assembly:** choose an interpreter distribution, preserve bootstrap
   requirements and native dependencies, and assemble a target-specific app.
   The separate **pocket-python** project owns runtime profiles, asset locks,
   launchers, distribution assembly, and footprint reports.
3. **Browser execution:** choose an existing WebAssembly Python implementation.
   MicroPython is the small-runtime route for a restricted Python subset;
   Pyodide is the broader CPython-compatibility route. PyScript is an optional
   browser integration layer using those runtimes, not an interpreter that
   translates arbitrary CPython applications into MicroPython.

Removing unused source is practical today. A general behavior-preserving Python
tree shaker is not decidable. Removing optional runtime modules is practical
only with an explicit target and bootstrap closure. Removing arbitrary CPython
object-model or VM internals is a compiler/linker research project, outside 0.2.

## Release contract: 0.2.0

Ship an experimental, useful foundation with Python 3.14+ and zero runtime
dependencies:

- Keep `explain` and `modules` compatible with 0.1.
- Add `symbols FILE:NAME [--json]`: a read-only top-level symbol graph with
  lexical global references, transitive inclusion reasons, source hashes,
  unsupported boundaries, and build-interpreter identity.
- Add `extract FILE:NAME --output DIRECTORY`: extract a named top-level
  function, its same-module helper closure, immutable constants, and retained
  standard-library imports, within the explicitly supported subset below.
- Add `runtime SCRIPT [--search-path ROOT] [--json]`: emit a versioned runtime
  requirements report from the existing module graph. Distinguish direct
  standard-library requirements from a complete runtime dependency closure.
- Preserve source/distribution attribution in extracted artifacts and report
  original versus emitted source bytes separately from total artifact bytes.
- Verify original/extracted behavior in isolated subprocesses using known
  fixtures, preserve the existing real-package module pilot, and build/test
  installed distributions on Linux, macOS, and Windows.

Today’s publication target is conditional on passing these gates and available
PyPI publication authorization. Publishing 0.2 does not imply all later phases
below are implemented.

## Symbol graph architecture

Parse source and compile syntax without executing target code. Index top-level
definitions, imports, and assignments by bound name and source span. Use the
compiler’s `symtable` lexical classifications to distinguish globals from
parameters, locals, comprehensions, and closure cells. Include global names
referenced by nested scopes and names evaluated in defaults, decorators, class
bases, and annotations. Record unresolved globals explicitly in the report.

Graph edges explain why a binding is retained. Walk the selected root’s
transitive closure with cycle detection; mutual recursion must terminate.
Stable ordering and source SHA-256 support repeatable reports. Duplicate or
conditional binding, wildcard imports, and unsupported top-level statements
are boundaries, not opportunities to guess. Attribute access does not establish
which class method will execute; retain class bodies as units in read-only
reports and defer method removal.

Cross-file symbol linking is a later extension: first resolve an import through
the existing module graph, then connect a specific exported binding while
preserving package initialization and re-exports. Until that is supported,
extraction must refuse non-standard-library imports rather than imply that a
same-file closure is independently distributable.

## Conservative extraction subset

The first fixture is a checksum utility with one used function, a same-module
helper and constant, and unused JSON/network helpers. The contract is callable
results and exceptions for supported inputs, not preservation of module identity,
source inspection, code-object positions, or unused import initialization.

Supported top-level forms are a module docstring, static standard-library
imports, plain functions, and immutable literal constants. Keep retained source
segments and leading comments. Preserve function order and names, recursion,
closures, local shadowing, future directives, and ordinary function-local
control flow. A literal default must be immutable. No rewriting to an invented
namespace, concatenation of imported module bodies, or inlining of C code.

Reject extraction for decorators, classes, executable top-level initialization,
rebinding, mutable global constants, computed defaults, explicit global/nonlocal
mutation, wildcard/relative/local/third-party imports, generic definitions,
recognized reflection/dynamic execution, resources, and runtime metadata.
Reject boundaries anywhere in the source when removing them could hide module
initialization behavior. Report why; do not silently switch to an aggressive
mode. These checks define a bounded supported contract, not a proof against
arbitrary reflective behavior hidden inside an imported implementation.

Output is a new directory containing `extracted.py`, `SHIMIFY-EXTRACT.json`, and
`LICENSES/`. The manifest records the requested symbol, retained/omitted names,
dependency reasons, original/transformed hashes, source size comparison,
interpreter/platform identity, notices, and explicit limitations. The extracted
file is a library; importing it does not automatically invoke the callable.

Preflight destination overlap, portable names, existing output, and source
changes. Reserve new output exclusively and roll back only files created by
this operation. Never execute the target while analyzing or generating it.

## Runtime requirements interchange

The runtime report identifies schema/tool version, entrypoint/source hashes,
build Python version/implementation/platform, source modules and bytes, direct
stdlib imports, build-host built-ins, unresolved/native boundaries, and graph
diagnostics. State that optional imports remain included and stdlib transitive
imports, bootstrap components, native shared-library closure, resources, and
runtime observations have not been established. `complete` remains false.

Pocket-python consumes the existing source-bundle manifest and verified file
hashes. It must not interpret this report as permission to delete runtime
files. A future fully closed target profile must pin Python implementation,
version, ABI, OS, architecture, bootstrap files, standard-library closure,
extension modules, and native libraries. Host observations are never silently
treated as browser or cross-platform compatibility.

## Ordered work and acceptance criteria

| Task | Scope | Depends on | Acceptance gate |
| --- | --- | --- | --- |
| SLC-01 / SYM-01 | Adopt this contract; implement lexical symbol reporting | Existing QA-01 | Alias/default/annotation/closure/shadowing/cycle tests; no target execution; stable JSON |
| EXT-01 | Conservative same-module callable extraction with provenance | SYM-01 | Positive differential fixture; negative boundary matrix; new-output/overlap/hash checks |
| RUN-01 | Versioned runtime requirements report | Existing MOD-01 | Identity, module/source sizes, direct stdlib names and incomplete-closure declaration; CLI exit tests |
| REL-02 | 0.2 documentation, metadata, installed distribution checks, publication | EXT-01, RUN-01 | Full cross-platform CI; clean wheel/sdist; matching release tag; PyPI installation and digest receipts |
| LINK-01 | Cross-module binding/re-export linking | EXT-01 | Package-initializer semantics and explicit export contract; fixture selected first |
| TRACE-01 | Opt-in runtime evidence | RUN-01 | Explicit execution consent; isolated invocation; timeout and JSON trace; observations never prove absence |
| PERF-01 | Reproducible footprint/startup measurements | EXT-01, TRACE-01 | Separate source/artifact/compressed size, cold/warm timing and peak memory; environment recorded |
| VND-01 | Explicit resources and metadata policy | Existing QA-01 | Selected resource-using fixture, allowlist, metadata policy, provenance and clean execution |
| CLASS-01 | Classes, decorators, mutable initialization | LINK-01 | Dedicated semantics and differential fixtures before widening extraction |

Use a rolling batch of focused branches/PRs. Start CI, continue independent work
or stack on the preceding branch, then squash passing changes oldest first.
Preserve parent branches until all dependent PRs have been reconciled and
retargeted. Require fresh checks after reconciliation and verify final main.

## Verification matrix

- Graph: functions, imports/aliases, constants, defaults, annotations, recursion,
  nested closures, comprehensions, local shadowing, unknown globals, duplicate
  definitions, syntax/compiler errors, non-UTF-8 source and deterministic JSON.
- Extraction: checksum/helper closure, unused imports/functions removed,
  immutable constants, recursive behavior, argument/default and exception
  parity, no generation-time side effects, attribution, source mutation,
  destination collision/overlap and interrupted publication.
- Boundaries: reflection aliases, dynamic execution, decorators/default calls,
  mutable globals, classes, imports outside the accepted contract, resources,
  namespace/native targets, top-level initialization and rebinding.
- Regression: all current module bundler fixtures and hashed `packaging==25.0`
  pilot. New features must not weaken existing graph/bundle rejection rules.
- Packaging: wheel/sdist allowlists and metadata/version parity; installed CLI
  and extraction smoke tests outside the checkout; no accidental build fixtures,
  internal drafts, caches, credentials or developer-only runtime dependencies.

## Later runtime and browser milestones

Pocket-python begins with runtime planning and a local-asset MicroPython PWA
builder, validated with a pinned real interpreter. Desktop packaging first
preserves a complete supplied relocatable runtime. Trimming becomes opt-in only
after bootstrap closure, native dependencies and differential execution are
verified for one specific target. Pyodide and PyScript adapters are separate
profiles; no automatic fallback changes Python semantics.

An offline browser artifact needs all runtime JS/WASM/data, sources, notices,
web manifest, and service worker locally. Test first load, service-worker
activation, cached reload without a server, errors, and deployment below a URL
subdirectory. Browser storage may be evicted; offline installation requires a
successful initial load. Use a worker for Python execution so termination can
stop a long computation. Native desktop extensions cannot simply be copied to
WASM; browser filesystem/network/process constraints need explicit diagnosis.

## Reference basis (reviewed 2026-10-18)

- [Python 3.14 symtable](https://docs.python.org/3.14/library/symtable.html):
  lexical global/local/free-variable classifications.
- [Python AST](https://docs.python.org/3.14/library/ast.html): source spans,
  syntax representation and compile-time validation.
- [Python import system](https://docs.python.org/3.14/reference/import.html):
  package initialization, binding, loaders and import side effects.
- [MicroPython WebAssembly port](https://github.com/micropython/micropython/blob/master/ports/webassembly/README.md):
  existing interpreter JS/WASM assets and embedding API.
- [MicroPython libraries](https://docs.micropython.org/en/latest/library/index.html):
  port-specific standard-library subsets.
- [Pyodide compatibility](https://pyodide.org/en/stable/usage/wasm-constraints.html):
  browser and WebAssembly constraints.
- [PyScript offline deployment](https://docs.pyscript.net/2026.7.3/user-guide/offline/):
  self-hosted interpreter and integration assets.

## Release exclusions

0.2 does not compile or rebuild Python, prove arbitrary behavior equivalence,
slice native binaries, provide safe/balanced/aggressive policy switches, run
untrusted applications for profiling, discover resources automatically, or
promise a startup/memory improvement from source byte reduction. Such features
require their own explicit contracts and measurements.
