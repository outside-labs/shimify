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
uv run shimify modules path/to/app.py --output path/outside/source/roots
python -I -S path/outside/source/roots/run.py
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

`modules` emits unchanged reachable sources under `_sources/`, `run.py`,
`LICENSES/`, and `SHIMIFY-MANIFEST.json`. Run the launcher with `-I -S` to exclude
environment paths and site packages. Target code is never executed by analysis or
generation. Output must be a new directory outside all included import roots;
existing files and overlapping sources are refused. Bundling refusals return 1,
and invalid inputs or filesystem errors return 2.

Sources in the interpreter's ordinary installed-package directories require
distribution file records. Sources supplied through `--search-path` are treated
as application code unless matching distribution records identify their owner.
The manifest preserves source hashes, import reasons, distribution metadata,
and available license/notice files. Missing declared third-party license files
or an installation with no license text block output. Local application notices
are copied when found in the included roots/package directories. Review the
original licensing obligations before redistributing an artifact.

Recognized dynamic imports, package resources, runtime metadata, native
extensions, namespace packages, wildcard imports, import-path mutations, and
file-relative behavior are unsupported. Conditional and type-checking imports
remain included. Sources shadowing standard library module names are rejected
by bundling because the launcher uses standard library modules itself.

## Real-package example

The acceptance pilot uses the pinned pure-Python `packaging==25.0` wheel. Install
it into an explicit build-only directory, explain the example, and bundle it:

```sh
uv pip install --python 3.14 --target build/pilot --no-deps --only-binary :all: --require-hashes -r tests/pilot-requirements.txt
uv run shimify explain examples/version_info.py --search-path build/pilot
uv run shimify modules examples/version_info.py --search-path build/pilot --output build/version-info
python -I -S build/version-info/run.py 1.0rc1 1.0 invalid
```

This use case includes 3 of the dependency's 16 Python modules: 18,601 of 221,406
source bytes. The bundle also contains the application script, launcher,
manifest, raw distribution metadata, and all three upstream license files.
These counts describe this pinned fixture's module reachability, not arbitrary
function-level reduction or total artifact size.

Run its differential acceptance test locally with:

```sh
SHIMIFY_PILOT_PATH=build/pilot uv run python -m unittest discover -s tests -v
uv build
uv run python scripts/check_wheel.py
```

On PowerShell, set `$env:SHIMIFY_PILOT_PATH = "build/pilot"` before running tests.
Without this explicit fixture path, the real-package test is skipped; synthetic
tests remain available offline. CI always installs the hashed fixture and runs
the complete suite and isolated wheel smoke test on Linux, macOS, and Windows.
