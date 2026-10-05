# shimify

dependency extraction/bundling experiment
# Shimify

Shimify is a source-level Python dependency reducer. It aims to explain what an
application imports and produce an auditable source directory containing the
implementation needed by its supported import graph.

The first milestone is conservative static module analysis and directory
bundling. It preserves ordinary Python package layouts and source bytes. Exact
function-level slicing, single-file rewriting, native extensions, and automatic
resource discovery are later work with explicit acceptance gates.

Requires Python 3.14 or newer. There are no runtime dependencies.

```sh
uv sync --locked
uv run shimify --help
uv run shimify --version
uv run shimify explain path/to/app.py
uv run shimify explain path/to/app.py --json --search-path path/to/src
uv run python -m unittest discover -s tests -v
uv build
```

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for architecture and
milestones. The [GitHub Project](https://github.com/orgs/outside-labs/projects/5)
and its linked issues track scope, acceptance criteria, and current work.

The project license has not yet been selected. Package publication requires a
separate decision.

`explain` reads sources without importing the target application or its packages.
It includes all static imports, even those in conditional branches. JSON output
contains module paths and hashes, import edges with inclusion reasons, and stable
diagnostic codes. Exit status is 0 for a supported static graph, 1 for analysis
diagnostics, and 2 for invalid input. A supported graph is not proof that arbitrary
runtime reflection or resource use has been discovered.
