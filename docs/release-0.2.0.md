# Shimify 0.2.0

Experimental symbol-level analysis and a deliberately bounded callable
extractor extend the existing unchanged-module bundler. Requires Python 3.14+
and has no runtime dependencies. The package uses MIT; third-party source
retains its own licensing obligations.

## New commands

```sh
shimify symbols utility.py:checksum --json
shimify extract utility.py:checksum --output ../checksum-source
shimify runtime app.py --json
```

`symbols` uses compiler lexical tables to trace same-module global references,
including defaults, annotations and nested scopes. It reports unresolved globals,
duplicate bindings and unsupported top-level initialization without running the
source. It does not follow attributes into other modules or prove extraction
safety. Status 0 means the symbol report has no diagnostics/unresolved globals;
status 1 reports a boundary; status 2 indicates invalid input or a filesystem error.

`extract` emits `extracted.py`, `SHIMIFY-EXTRACT.json` and available `LICENSES/`
into a new directory outside source roots. Import `extracted` and invoke the
selected function yourself. Retained original source segments include a plain
function’s helper closure and immutable literal constants; unused definitions
and imports can disappear. The manifest compares original and extracted source
bytes and records file hashes and attribution.

The supported import profile includes base64, binascii, cmath, collections,
decimal, fractions, functools, hashlib, hmac, itertools, json, math, operator,
re, statistics, string, struct, unicodedata, urllib, and future directives.
Submodules must resolve through the ordinary standard library. Classes,
decorators, generic definitions, mutable/computed globals and defaults,
explicit global/nonlocal mutation, executable top-level initialization,
rebindings, wildcard/relative/third-party imports, recognized reflection,
dynamic execution, resources and metadata are refused. Boundaries in unused
code still block extraction. Nested function-local imports use the same profile.

The contract covers callable behavior in this subset, excluding source/module
identity, code-object positions, introspection and unused import initialization.
Static recognition cannot prove arbitrary behavior hidden inside called code.
No safe/balanced/aggressive modes or cross-module symbol rewriting are provided.

`runtime` reports source hashes/bytes, build-target identity, direct stdlib
requirements, host built-ins and diagnostics. Its `complete` field is always
false: interpreter bootstrap, transitive stdlib imports, shared libraries and
cross-target compatibility remain unestablished. It must not be used as a
runtime file deletion allowlist. Conditional imports stay included.

## Compatibility and future work

The 0.1 `explain`, `modules` and schema-1 source bundles remain available.
Standard-library modules remain external in every source artifact. Source-size
reduction does not imply interpreter, memory or startup-time reduction.

[IMPLEMENTATION_PLAN02.md](../IMPLEMENTATION_PLAN02.md) specifies later
cross-module symbols, tracing, resources and measurement work.
[Pocket-python](https://github.com/outside-labs/pocket-python) owns runtime
selection and browser/native application assembly, with its own validation
gates before runtime trimming.
