# Shimify source reduction implementation plan

Adopted 2026-10-20. Forward plan after released 0.2.1. IMPLEMENTATION_PLAN.md and
IMPLEMENTATION_PLAN02.md retain historical release contracts. Python 3.14+ and
zero runtime dependencies remain the build-tool baseline.

## Coordinated program adopted 2026-10-20

Three parts have separate implementation and compatibility contracts. Open
issues and plans do not mean those features have shipped.

1. **Smaller source artifacts:** Shimify owns module reachability, bounded
   cross-module symbol extraction, resources, provenance and measurements.
2. **Our compiler and browser applications:** Python-JavaScript owns validated
   Python-to-JavaScript compilation and browser adapters. Pocket-python owns
   verified profiles, application assembly and offline delivery. Approved shared
   logic runs under CPython on the server and compiled code on the client;
   entrypoints and platform adapters remain explicit.
3. **Our independent interpreter:** pocket-python initially owns the plan and
   queue for a new engine that executes newly entered Python source locally.
   The separate interpreter plan defines language stages, architecture decisions,
   native/browser delivery, conformance and resource limits.

The compiler and independent interpreter must work without MicroPython or
Pyodide. An optional upstream CPython WebAssembly build is an existing-engine
distribution, not the independent interpreter. MicroPython, Pyodide and PyScript
remain separate optional compatibility routes. No silent fallback or arbitrary
package compatibility is implied.

Related plans:

- [Source reduction](https://github.com/outside-labs/shimify/blob/main/IMPLEMENTATION_PLAN03.md)
- [Compiler/browser target](https://github.com/outside-labs/Python-JavaScript/blob/main/IMPLEMENTATION_PLAN.md)
- [Application assembly](https://github.com/outside-labs/pocket-python/blob/main/IMPLEMENTATION_PLAN.md)
- [Independent interpreter](https://github.com/outside-labs/pocket-python/blob/main/IMPLEMENTATION_PLAN_INTERPRETER.md)

The compiler repository became public on 2026-10-20. Project visibility remains
separate; application artifacts still include only explicitly selected files.

## Delivered behavior and next result

Released 0.2.1 explains static imports, bundles unchanged reachable modules,
reports same-module lexical dependencies, extracts a conservative same-module
function closure and reports explicitly incomplete runtime requirements.
Cross-module extraction, classes/resources and runtime trimming are not delivered
by adopting this plan.

The next result is an auditable application-specific artifact preserving a
selected callable/API and supported input behavior, not an upstream package's
entire public API. Define module identity, initialization effects, aliases,
exceptions and side effects before removing code. Keep classes as units initially;
mutable state and method elimination require dedicated contracts.

An optional purpose-specific wheel follows an actual consumer and distinct
identity/metadata decision. Do not silently replace a full upstream distribution
or shadow an installed package with an incompatible artifact. Native slicing,
arbitrary reflection and general automatic minimization remain outside scope.

## Common acceptance application

Use a small text_metrics application: shared Python computation counts
characters, words and lines; a local pure-Python helper and immutable constants
establish module boundaries, with an unused utility for reduction. Start the
compiler with a single-module equivalent, then add local imports. Adopt results
for empty strings, Unicode/astral characters, whitespace, invalid arguments and
numeric boundaries through the source-language contract.

Run shared logic through a CPython 3.14 CLI and local standard-library HTTP test
endpoint. The browser has a text area, a button and visible results; computation
runs offline. The interpreter later accepts this source as new input after
deployment. Keep server-only adapters/data outside client allowlists. No new
framework or external service is needed for this acceptance application.

Retain packaging==25.0 as Shimify's independent real-package module regression.
For resource work, extend the local fixture with one named UTF-8 stop-word file.
The new compiler/interpreter need not support the whole packaging library to
meet their first milestones.

## Ordered queue

| Task | Scope | Depends on | Readiness |
| --- | --- | --- | --- |
| [shimify/SRC-01](https://github.com/outside-labs/shimify/issues/31) | Specify application-specific source reduction profiles | Released foundation | Ready |
| [shimify/LINK-01](https://github.com/outside-labs/shimify/issues/22) | Implement bounded cross-module callable and re-export linking | [shimify/SRC-01](https://github.com/outside-labs/shimify/issues/31) | Blocked |
| [shimify/CLASS-01](https://github.com/outside-labs/shimify/issues/25) | Define and implement bounded class and initialization extraction | [shimify/LINK-01](https://github.com/outside-labs/shimify/issues/22) | Blocked |
| [shimify/VND-01](https://github.com/outside-labs/shimify/issues/5) | Implement explicit resource and distribution metadata inclusion | [shimify/SRC-01](https://github.com/outside-labs/shimify/issues/31) | Blocked |
| [shimify/TRACE-01](https://github.com/outside-labs/shimify/issues/23) | Collect bounded opt-in runtime evidence | [shimify/SRC-01](https://github.com/outside-labs/shimify/issues/31) | Blocked |
| [shimify/PERF-01](https://github.com/outside-labs/shimify/issues/24) | Measure source reduction and complete artifacts independently | [shimify/LINK-01](https://github.com/outside-labs/shimify/issues/22), [shimify/TRACE-01](https://github.com/outside-labs/shimify/issues/23) | Blocked |
| [shimify/ART-01](https://github.com/outside-labs/shimify/issues/32) | Specify purpose-specific distributable package artifacts | [shimify/LINK-01](https://github.com/outside-labs/shimify/issues/22), [shimify/VND-01](https://github.com/outside-labs/shimify/issues/5), [shimify/PERF-01](https://github.com/outside-labs/shimify/issues/24) | Triage |

SRC-01 is the first Ready design task; LINK-01 is the priority implementation
when that contract lands. Resource/evidence work follows its own dependencies;
classes follow linking. ART-01 is an optional artifact decision. Each issue
records the detailed acceptance criteria for a focused implementation.

## Interchange and verification

Preserve schema-1 module bundles. New cross-module/resource profiles record
transformation versions, selected exports, module/symbol identities, inclusion
reasons, original/emitted hashes, notices and unsupported boundaries. Version
incompatible contracts and use the exact verified bytes downstream.

The compiler may consume unchanged supported modules before cross-module
reduction exists. Reduced source still requires independent compiler/interpreter
compatibility tests. An incomplete runtime report is never a deletion allowlist.

Execute known original/reduced fixtures in clean CPython processes; compare
values, exceptions, aliases, import/initialization order and resources. Preserve
all current shadowing, class, dynamic-import, notice/path/snapshot and overwrite
refusals; add cycle/re-export/resource negative cases before widening support.
Retain the pinned real-package differential pilot.

## Delivery, readiness and measurement

Issues and Projects hold current state; plans describe architecture/acceptance.
Ready means adopted scope and finished dependencies; Blocked means unfinished
dependencies; Triage means an optional or unselected extension. A contract or
architecture task may be Ready while later implementation awaits its decisions.
Do not mark a feature Done for documenting it. Update dependent readiness after
merges; Task, Order, Dependencies, Target and Readiness make the queue explicit.

Use rolling batches of 3-5 focused PRs. Start CI, continue independent work or
stack dependent changes, squash passing changes in dependency order and verify
final main. Preserve parent branches while open dependents target them;
reconcile, retarget and recheck descendants before deleting dependency bases.

Compare supported behavior before footprints. Separate source bytes, generated
code/helpers, interpreter assets, data/notices, source maps, complete uncompressed
bytes and compressed transfer. Record tool/engine/host versions, cold/warm
startup and memory method. No fixed size/performance/compatibility claim follows
from this roadmap. Incomplete import reports and unobserved dependencies never
authorize removal.

Keep releases/tags immutable. New runtime dependencies, services, engine
repository/package identity, release uploads and deployment retain their explicit
scope/decision requirements. This planning update changes no runtime dependencies
and publishes no package.

The development [cross-module linker](docs/cross-module-linking.md) preserves
ordinary import paths and selected callable identity while removing unused source
bindings. The existing same-module extraction and module-bundle profiles retain
their original boundaries.

The development [explicit resource profile](docs/explicit-resources.md) adds
allowlisted UTF-8 package data and source-owned distribution version metadata
to unchanged-module bundles under a separate schema-2 manifest. Callable
extraction keeps its existing resource boundary.
