# Bounded cross-module callable extraction

Version 0.3.0 adds `shimify link FILE.py:symbol --output NEW_DIR`.
It is separate from unchanged `modules` bundles and the existing conservative
same-module `extract` command. This command is included in 0.3.0; the published 0.2.1 package predates it.

The selected export must resolve to a plain source function. Link follows named
from-imports, aliases, relative imports, package parent initializers and
re-exports through the existing static module graph. It keeps each retained
module's import path, its original statement order and function binding identity.
The result remains a selected API, not a drop-in upstream package replacement.

All top-level imports are initialization roots, including imports not referenced
by the selected function. Their imported definitions and lexical global closure
remain present. This conservative policy preserves declared import initialization
and does not claim a minimum module set. Unused function bodies and immutable
constants can be removed; no runtime trace authorizes removing an import.

Only imports, immutable literal constants, docstrings and undecorated functions
are allowed at module level. Existing reflection, class, mutable/computed-default,
global/nonlocal mutation and resource refusals remain. Imports must be
unconditional and at module level. Source imports use named from-imports;
module/object attribute dispatch is not treated as a selected function link.
The small established stdlib import allowlist remains external and cannot be
shadowed by copied local sources. Unknown exports and dynamic loaders fail.

A static initialization pass tracks when bindings become available. Cycles may
use a literal/function already bound before the cycle's import; a cycle reading
an uninitialized export fails with SHIM421. No code is executed to establish
availability. Dynamic initialization and exports are rejected. Original file
paths, code-object positions, reflection and omitted APIs remain outside this
callable profile.

SHIMIFY-LINK.json schema 1 uses mode linked-extract and records selected export,
resolved definition, per-module retained/omitted bindings, lexical/import reasons,
module initialization edges, source/output hashes, sizes and distribution notices.
Modules appear at their normal paths directly under the output directory; add
that directory to a clean process's import roots and import the recorded API.
There is no script launcher and existing schema-1 module bundles are unchanged.
`analyze_module` analyzes a library with real package identity; script bundles
continue to require `analyze`'s __main__ graph.

For text_metrics, linking text_metrics/__init__.py:metrics keeps metrics,
SEPARATORS, its aliased character_count helper and the package re-export, while
omitting unused_reverse. Clean-process comparisons cover empty/whitespace/Unicode
strings, invalid-argument errors, alias identity and a defined import cycle.
Undefined cycles, dynamic exports, initialization effects, source changes and
unsafe/failed publication are refusal tests. Source bytes are snapshotted,
rechecked before exclusive publication, and notices are preserved without a
recursive source-tree copy. Resources remain the explicit VND-01 task.

The explicit [linked-classes/1 profile](class-extraction.md), selected with
`link --classes`, extends this contract with whole plain classes. The default
function-only profile retains its existing refusal boundary.
