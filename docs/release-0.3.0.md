# Shimify 0.3.0

An experimental minor release for Python 3.14+, with no runtime dependencies.
The MIT license and existing module/same-module extraction contracts are retained.

## Added behavior

- `link FILE.py:NAME --output DIRECTORY` follows supported named local imports,
  aliases and re-exports, retaining the callable closure and initialization order.
- `link ... --classes` retains whole plain-class units, every method's lexical
  dependencies, literal fields and adopted property/static/class methods.
- `resources SCRIPT --resource PACKAGE:relative.txt --output DIRECTORY` includes
  only declared bounded UTF-8 text resources. `--distribution-version NAME`
  preserves a supported source-owning distribution version query and notices.
- `trace SCRIPT --allow-execution` executes an explicitly selected application
  with time/output limits and records observed import evidence. Observation
  never authorizes deleting unobserved code or runtime files.
- Versioned source/complete-artifact measurements document the text-metrics and
  pinned packaging pilots, including transfer/startup/memory methods and limits.

See [linked extraction](cross-module-linking.md), [whole classes](class-extraction.md),
[resources](explicit-resources.md), [runtime evidence](runtime-evidence.md) and
[measurements](source-measurements.md) for exact profiles and commands.

## Boundaries and compatibility

Arbitrary executable initialization, custom inheritance/metaclasses/descriptors,
reflection, dynamic/native loading and automatic data discovery remain outside
these extraction profiles. Whole-class extraction does not establish compiler
or browser compatibility. Default extraction still rejects classes unless its
explicit class profile is selected. New resource manifests identify schema 2;
ordinary module manifests preserve schema 1. Source hashes, reasons and upstream
notices remain auditable. Review any alpha manifest consumer against its named
profile; this release does not promise a stable arbitrary-package reducer.

## Publication gates

Run the regression/differential suite with the hashed `packaging==25.0` pilot,
build/check source and wheel allowlists, run the suite from an isolated installed
wheel, and require all three platform jobs on final main. Publish immutable
`v0.3.0` through the existing `pypi` Trusted Publisher, compare uploaded hashes
with workflow artifacts, and verify a fresh PyPI installation before closing
[REL-04](https://github.com/outside-labs/shimify/issues/42).
