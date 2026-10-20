# Whole-class linked extraction

CLASS-01 adopts the opt-in `linked-classes/1` profile for `link --classes`.
It is available in the development checkout; published 0.2.1 predates this profile.
The existing function extraction and default linked profile keep rejecting
classes. This profile copies ordinary source classes as complete units; it does
not eliminate methods or change the runtime's class model.

```sh
shimify link package/models.py:Counter --classes --output build/counter
```

The Python API is `link(path, symbol, output, include_classes=True)`.

The first fixture is a counter with an integer default, literal class fields,
instance state, a read-only property, static/class methods and a classmethod
updating a literal-initialized class counter. A method outside the first call's
path uses another module helper; that method and helper must remain available.

## Adopted rules

- Select a source class or function through explicit named local imports and
  re-exports. Keep normal package/module/class identity and source import order.
- Classes have no explicit base or one unshadowed builtin object base. Custom
  inheritance/MRO, metaclasses, generic classes and class decorators are deferred.
- Class bodies contain a docstring, pass, single-name immutable literal fields,
  simple annotations and ordinary methods. Instance/class state changes inside
  retained methods are preserved. Mutable module/class initialization and eager
  registration calls are rejected.
- Method decorators may be one unshadowed builtin property, staticmethod or
  classmethod. A property is read-only in this stage. Setter/deleter decorators,
  custom descriptors and registration decorators are deferred.
- __init__ is the only adopted special method. Dynamic attribute hooks,
  __new__, __init_subclass__, slots and namespace/reflection hooks are rejected.
  Other names beginning with double underscores are outside this stage.
  Async/nested classes and async methods remain outside this profile.
- Defaults are immutable literals. Class/method annotations use unshadowed
  builtin type names, None or literal strings. Strings stay annotation data;
  annotation evaluation/reflection and type-hint resolution are not adopted.
- Each retained class keeps every method body/default/annotation and all lexical
  global dependencies, including dependencies of methods not invoked by the
  acceptance workload. There is no runtime tracing authority to drop them.

Module binding rebinding, explicit global/nonlocal mutation, reflection, dynamic
imports/exports and the existing unsupported extraction boundaries remain
rejected. A class object may preserve state changed by its retained methods;
this does not authorize arbitrary mutable module initialization. Imported class
attributes may be used because the class unit is retained whole; imported module
or function attribute dispatch is still outside the linked contract.

The schema-1 link manifest records `extraction_profile: "linked-classes/1"`,
retained class units/methods, original source hashes, dependency reasons and
unchanged notices. The default profile's manifest is unchanged. Selected class
identity uses the ordinary output module path. Original source positions,
source-file inspection and APIs omitted from the selected closure remain outside
the artifact contract.

Validation compares original/reduced classes and function callers in isolated
CPython, including re-export identity, default/descriptor behavior, mutable state,
all methods' dependencies, import order and notices. Negative fixtures must fail
without importing target code or publishing output. Compiler and independent
interpreter class semantics remain separately staged; source extraction alone
does not establish browser compatibility.
