# Application-specific source reduction contract

SRC-01 adopts the text_metrics fixture in tests/fixtures/text_metrics, alongside
the existing pinned packaging==25.0 module pilot. These are separate from
compiler or interpreter compatibility claims.

## Selected API and behavior

The selected API is text_metrics.metrics(text), including its re-export from the
package initializer and aliased import of helpers.character_count. Accept exact
built-in Python strings; reject non-string values with
TypeError("text must be str"). String-subclass overrides are outside the selected
input domain. The result is a tuple of three Python integers.

Characters count Unicode code points, without normalization: an astral character
counts once and a combining mark counts separately. Words are maximal runs
separated by one of six explicitly selected ASCII characters: space, tab, LF,
CR, vertical tab and form feed. Other Unicode whitespace remains part of a word.
Lines are zero for an empty string, otherwise one plus the number of LF
characters, including a final empty line after trailing LF. CR alone does not
start a line. These application rules deliberately avoid implicit platform or
locale behavior.

## Reduction profiles and observables

| Profile | Preserved behavior | Boundaries |
| --- | --- | --- |
| Unchanged modules, delivered | Reachable source bytes, normal module/package layout, imports and initializers. | Current dynamic/native/resource/metadata refusals. |
| Cross-module callable, development LINK-01 | Selected callable result/exception, ordinary import and binding identity, declared initialization order, notices and hashes. | Unsupported initialization, reflective access, dynamic exports, arbitrary class dispatch and undeclared resources. |
| Purpose-specific distribution, optional ART-01 | Explicit selected API and consumer installation contract. | No automatic replacement for an upstream package's full public API. |

The fixture has only imports, immutable constants and function definitions at
module level. LINK-01 must follow the re-export and alias, retain the imported
helper and SEPARATORS, and omit the unreferenced unused_reverse function. It
must preserve source attribution and explain every included binding/file.

Ordinary function/module binding identity among retained references must stay
consistent. Source inspection, original file paths, code-object line positions
and access to omitted APIs are outside the callable profile. Do not infer that
an attribute access selects a specific method. Keep initializers with effects
unchanged or reject extraction when their supported behavior cannot be kept.

Before widening support, require negative fixtures for executable initialization,
rebinding, dynamic exports/imports, mutable globals, class/decorator behavior,
cycles with undefined initialization order and undeclared resources. Refusal
must occur before output publication. Runtime traces cannot prove removability.

## Evidence and downstream use

SRC-01 verifies the original application and unchanged-module bundle in clean
CPython processes, including Unicode and invalid input. The development
[cross-module linker](cross-module-linking.md) now compares the same original
against its reduced artifact and checks retained/omitted bindings and notices.

Source, complete artifact, runtime, compressed transfer, startup and memory are
separate measurements. Standard-library/runtime trimming belongs to a verified
target profile in pocket-python. A smaller source artifact still needs the
selected compiler/interpreter's own syntax, library and host compatibility tests.
