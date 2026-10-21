# Explicit text resources and distribution versions

VND-01 adopts an opt-in module-bundle profile. Original modules stay unchanged;
same-module and linked callable extraction retain their resource refusals.

The command is `shimify resources app.py --resource text_metrics:stopwords.txt --output NEW_DIR`.
Add `--distribution-version synthetic-text-metrics` only when the application
queries that source-owning distribution's version. Library callers pass
`ResourcePolicy((TextResource('text_metrics', 'stopwords.txt'),), versions=())`
to `analyze(..., resource_policy=policy)` and then `bundle(graph, output)`.
This profile is included in 0.3.0; the published 0.2.1 package predates it.

Each resource declaration names an ordinary source package and one normalized
relative .txt path. Only that file is copied. The first loader form is an
explicit `importlib.resources.files('package').joinpath('file.txt').read_text(encoding='utf-8')`
call, including stable import aliases. Package/path/encoding must be literals.
Directory enumeration, dynamic paths, file-relative loading, other resource
APIs and rebinding/shadowing the resource API alias remain unsupported.
Source-module re-exports/attribute dispatch of these APIs are also refused.

An optional distribution-version declaration permits only
`importlib.metadata.version('distribution-name')`, including stable aliases.
The distribution must uniquely own included source through installed file
records. Copy its exact METADATA into an explicitly marked reduced .dist-info
directory so the isolated bundle can answer that query. This is a private
source-bundle runtime record, not an installable wheel or a claim that every
upstream package API/file is present. Plugin discovery and other metadata APIs
remain unsupported.

Resources must remain inside the package, without symlink components, and must
decode as UTF-8. Limit the first profile to 32 text files, 1 MiB each and 8 MiB
total. Distribution-owned resources must be recorded by that same source-owning
distribution; local resources retain local notice attribution. Output records
exact hashes/sizes, resource/package/owner mapping and requested version records.
No package-directory recursion or runtime package installation is implied.

The new manifest has schema_version 2 and mode modules-resources, preserving
the _sources layout and script launcher. Existing schema-1 bundles remain
unchanged. Consumers that support only schema 1 must reject this profile.
Snapshots feed exclusive publication; declared files, provenance and notices
enter the complete artifact hash list. Tests must run the resource fixture in a
clean CPython process after removing original inputs/site packages, and reject
undeclared access, unsafe paths, symlinks and ambiguous ownership.
Static policy recognizes the adopted loader forms; it is not a general Python
I/O sandbox or proof of complete runtime dependency closure.
