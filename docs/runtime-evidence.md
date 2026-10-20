# Opt-in runtime evidence

The development checkout adds
`shimify trace app.py --allow-execution --argument 'example input'`.
Without the explicit flag, analysis remains read-only and no process starts.
The library equivalent is `trace(analyze(path), allow_execution=True, ...)`.
Existing explain, modules, symbols, extract and runtime commands never trace.

The selected application runs in a new CPython process with -I, -S and explicit
analyzed import roots, a temporary working directory, closed stdin and supplied
arguments. This isolates normal environment/site startup and keeps application
execution separate from analysis. It is not a security sandbox: the opted-in
application retains the invoking user's filesystem/network authority and may
cause side effects. Source bytes must still match the static analysis before
execution; changes during execution make observations incomplete.

The observer records bounded builtin import requests (including cached imports
through that hook), relative levels/fromlists, and newly loaded sys.modules
names. Dynamic imports that reuse cached modules or bypass the hook may remain
unobserved. Requests include workload/harness imports and are not proof that
every requested import completed or is necessary. Each report retains static
diagnostics, source hashes and the actual target implementation/version/platform.
Dynamic-loader diagnostics remain even when a traced workload succeeds.
Local source modules shadowing the stdlib are refused, since observer startup
preloads stdlib modules. Cache/observer introspection is outside this profile.

The default timeout is five seconds (allowed range 0.05–60). Each output stream
captures and hashes at most 64 KiB (configurable 1024–1,048,576 bytes); raw stdout,
stderr and exception messages are not included. Output overflow terminates the
invocation. Timeout/overflow, application failure, abrupt exit, missing observer
results and observation limits remain explicit. POSIX teardown kills the owned
process group; Windows terminates the active process tree through taskkill.
No memory limit is imposed. Captured output limits bound observer memory, not
the target application's allocations or all possible escaped child processes.

Reports have schema_version 1 and mode runtime-evidence. Runtime fields record
status, error class, requested SystemExit code, import requests, module names
and observation-limit state. Host fields record process exit, capture hashes,
limits and source integrity. evidence_complete means the bounded observer
finished with unchanged sources and no truncation; it never means complete
dependency or runtime closure. A failed application can have complete observer
records. CLI exits nonzero for failure or incomplete observations.
Live background Python threads at observer completion make the report incomplete;
this initial observer targets the selected main-script workload.

Unobserved dependencies remain unknown. removal_authorized is always false:
this command cannot approve deleting source, stdlib, native libraries or VM
components. Compare source reduction and runtime requirements through their own
contracts. Tests cover the text_metrics workload, deterministic evidence fields,
missing opt-in, failure, timeout, output overflow, abrupt exit and changed sources.
