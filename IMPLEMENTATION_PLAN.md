# Shimify implementation plan

## Purpose

Given a Python script and a supported import graph, explain the implementation
it needs and emit an auditable, portable source artifact with provenance. The
first release boundary is a directory of unchanged reachable modules runnable
with only Python's standard library. Static reachability is conservative: it
does not prove the exact minimum code required for every possible execution.

This plan translates the initial Shimify gist into staged implementation. The
[GitHub Project](https://github.com/orgs/outside-labs/projects/5) and linked
issues are the canonical queue; pull requests record completed behavior and
verification. This file records architecture and sequencing.

## First milestone contract

- Input: one `.py` script, its directory, explicitly supplied import roots, and
  ordinary source packages available in the build interpreter's environment.
- Analysis: read source files, parse AST, and traverse all static imports,
  including conditional imports and package initializers. Never import or run
  target modules to discover dependencies.
- Output: a new directory preserving normal package/module names, a standard
  library launcher, `LICENSES/`, and `SHIMIFY-MANIFEST.json`.
- Runtime: Python 3.14+, with standard library modules left external. A clean
  `python -I -S` process must run acceptance fixtures without source-tree or
  site-packages access.
- Rejections: unresolved dependencies, native third-party modules, unsupported
  namespace/archive/custom import resolution, recognized dynamic loading,
  resource/metadata-dependent behavior, and incomplete third-party provenance.
- Guarantees: included source bytes and notices are preserved; hashes, graph
  edges, and distribution metadata explain the output. Analysis and generation
  never execute target code. Acceptance subprocesses execute only known tests.

Recognition of dynamic behavior is necessarily incomplete. Successful static
analysis means the documented subset was accepted, not that arbitrary reflection
or runtime behavior was proven safe. No license compatibility or redistribution
compliance certification is implied by copying license material.

## Architecture

1. **Models:** source modules, import edges, stable diagnostic codes, and graph
   serialization. Deterministic ordering supports review and reproducibility.
2. **Resolver:** filesystem inspection for ordinary modules/packages; preserve
   import-root precedence and parent initializers; identify standard library
   boundaries without calling target loaders or `find_spec` on target packages.
3. **Analyzer:** AST traversal, relative import resolution, conservative
   `from package import name` submodule candidates, cycle handling, and explicit
   unsupported-behavior diagnostics. No source rewriting in this milestone.
4. **Provenance:** associate source paths with distribution file records rather
   than assuming import names equal distribution names; gather license and
   notice files plus raw metadata. Local application code remains identified
   separately and retains its source notices.
5. **Bundler:** preflight all inputs and destinations; stage source bytes,
   launcher, licenses, and manifest; publish only to a new output directory.
   Preserve the original script as a script so its `__main__` behavior remains
   intact. Do not overwrite an existing output or write within a source root.
6. **CLI:** `shimify explain SCRIPT [--json] [--search-path ROOT]` and
   `shimify modules SCRIPT --output DIRECTORY [--search-path ROOT]`.

Keeping package names preserves relative imports and ordinary module identity.
Rewriting into `_shim` namespaces is a separate transformation with a different
semantic contract. The directory milestone establishes a usable baseline first.

## Milestones and acceptance gates

| Task | Deliverable | Dependency and completion evidence |
| --- | --- | --- |
| INIT-01 | Plan, package metadata, CLI foundation, CI, development instructions | Empty scaffold; command smoke tests and wheel/sdist build |
| MOD-01 | Read-only static import graph and explanation | INIT-01; local/installed resolution, cycles, relative imports, and rejection tests |
| BND-01 | Portable directory bundles and provenance | MOD-01; deterministic manifests, preserved licenses, source hashes, clean-runtime execution, refusal/rollback tests |
| QA-01 | Bounded real-package pilot and portability | BND-01; pinned `packaging.version` pilot, differential results, omitted modules, Linux/macOS/Windows CI |
| VND-01 | Whole-package vendor mode and resource inclusion | QA-01 plus a selected resource-using fixture and agreed resource/runtime metadata policy |
| SLC-01 | Symbol slicing or single-file experiment | QA-01 plus a selected callable and behavior fixture; semantics and rejection rules reviewed before removal/rewriting |

Execute INIT-01 through QA-01 sequentially, using one branch/PR per task and
continuing after green CI and merge. VND-01 and SLC-01 require the next
intended-use contract; they are product decision gates, not blanket permission
to remove arbitrary code or copy all package data. Package publication is a
separate boundary, including the unresolved project license.

## Verification

Use standard-library `unittest` and temporary synthetic source trees. Cover
absolute/relative imports, imported parent initializers, re-exports, conditional
imports, cycles, standard library boundaries, unresolved imports, native files,
dynamic calls, resources, metadata, shadowing, and sources whose initializers
would have side effects if executed.

For artifacts, check byte identity, SHA-256 hashes, deterministic manifests,
source/output overlap, reserved-path conflicts, existing output preservation,
license omissions, and dependency ownership. Execute known fixture bundles from
an unrelated working directory using Python `-I -S`; remove access to their
original source roots and compare representative results with the originals.

The real-package pilot uses a pinned build/test-only installation, never a new
Shimify runtime dependency. Run focused checks while developing, then the
relevant complete suite and `uv build` before each PR. CI runs the same checks;
the portability milestone extends them to Linux, macOS, and Windows.

## Deferred behavior

- Function/class extraction, dead-code elimination, and import/name rewriting.
- Package data, entry-point discovery, runtime distribution metadata, editable
  import hooks, zip imports, and namespace package merging.
- Runtime tracing, optional-import policy, platform-specific graph pruning,
  and automatic execution of user programs.
- Pure-Python conversion of native code, automatic license interpretation,
  package publication, and external services.

## Reference basis

- [Python import system](https://docs.python.org/3/reference/import.html): package
  initialization, name binding, and custom loader boundaries.
- [Distribution metadata](https://docs.python.org/3/library/importlib.metadata.html):
  file-based ownership and the distinction between import and distribution names.
- [Core metadata specification](https://packaging.python.org/en/latest/specifications/core-metadata/):
  license metadata and license-file declarations.
- [uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/):
  locked environment setup and build verification.
