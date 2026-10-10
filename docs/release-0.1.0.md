# Shimify 0.1.0

The initial experimental release provides conservative static Python import
analysis and portable source-directory bundles. Python 3.14 or newer is
required. Shimify has no runtime dependencies and its source is MIT licensed.

```sh
python -m pip install shimify==0.1.0
shimify --version
shimify explain path/to/app.py
shimify modules path/to/app.py --output path/outside/source/roots
python -I -S path/outside/source/roots/run.py
```

Analysis and generation never import or execute the target. Supported bundles
preserve reachable module layouts/source bytes, dependency provenance, hashes,
and available license notices. Existing output paths and paths overlapping
source roots are refused.

Dynamic imports, resources, runtime metadata access, native extensions,
namespace packages, wildcard imports, import-path mutations, and file-relative
behavior remain unsupported. Function-level slicing, single-file rewriting,
and whole-package vendoring are deferred. The tool does not certify that
redistribution satisfies third-party license obligations. See the
[README](../README.md) for the complete current contract and acceptance pilot.

The 0.x API remains experimental; future minor releases may change it. This
release does not imply a stable 1.x interface.

Publishing a GitHub release tagged `v0.1.0` runs
`.github/workflows/release.yaml`. It verifies version/tag agreement, uses the
locked development environment, runs the regression suite and pinned real
package differential pilot, builds wheel/source distributions, checks metadata
strictly, and smoke-tests an isolated wheel. Only then does the `pypi`
environment upload through PyPI trusted publishing. CI also verifies the tests,
pilot and installed wheel on Linux, macOS, and Windows.
