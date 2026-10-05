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
uv run python -m unittest discover -s tests -v
uv build
```

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for architecture and
milestones. The [GitHub Project](https://github.com/orgs/outside-labs/projects/5)
and its linked issues track scope, acceptance criteria, and current work.

The project license has not yet been selected. Package publication requires a
separate decision.
