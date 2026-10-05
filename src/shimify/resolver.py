"""Resolve ordinary filesystem imports without invoking application loaders."""

from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
import sys
import sysconfig

from shimify.models import Module


def environment_paths() -> tuple[Path, ...]:
    """Only ordinary installed-package locations; no custom sys.path hooks."""
    paths = sysconfig.get_paths()
    return tuple(dict.fromkeys(Path(paths[key]).resolve() for key in ("purelib", "platlib")))


class Resolver:
    def __init__(self, local_paths: tuple[Path, ...], installed_paths: tuple[Path, ...]):
        self.local_paths = tuple(dict.fromkeys(path.resolve() for path in local_paths))
        self.installed_paths = tuple(dict.fromkeys(path.resolve() for path in installed_paths))
        self.paths = tuple(dict.fromkeys((*self.local_paths, *self.installed_paths)))
        self.cache: dict[str, Module] = {}

    def resolve(self, name: str) -> Module:
        if name in self.cache:
            return self.cache[name]
        parts = name.split(".")
        if not all(part.isidentifier() for part in parts):
            return Module(name, "missing")
        # Built-ins precede filesystem imports. Other stdlib names can be shadowed.
        if parts[0] in sys.builtin_module_names:
            module = Module(name, "stdlib" if len(parts) == 1 else "missing")
        else:
            module = self._filesystem(name, parts)
        self.cache[name] = module
        return module

    def _filesystem(self, name: str, parts: list[str]) -> Module:
        local, namespace = self._search(name, parts, self.local_paths)
        if local is not None:
            return local
        if parts[0] in sys.stdlib_module_names:
            if len(parts) == 1 or name == "os.path":
                return Module(name, "stdlib")
            paths = sysconfig.get_paths()
            for root in dict.fromkeys(Path(paths[key]) for key in ("stdlib", "platstdlib")):
                base = root.joinpath(*parts)
                if self._at(base, name, root) is not None:
                    return Module(name, "stdlib")
            # A winning stdlib parent cannot get a child from a later installed
            # package with the same top-level name.
            return Module(name, "missing")
        installed, installed_namespace = self._search(name, parts, self.installed_paths)
        return installed or namespace or installed_namespace or Module(name, "missing")

    def _search(self, name: str, parts: list[str], roots: tuple[Path, ...]) -> tuple[Module | None, Module | None]:
        namespace = None
        for root in roots:
            first = self._at(root / parts[0], parts[0], root)
            if first is None:
                continue
            if first.kind == "namespace":
                # Namespace portions do not outrank a later ordinary package.
                namespace = Module(name, "namespace", first.path, root, True, first.external)
                continue
            if len(parts) == 1:
                return first, namespace
            if first.kind != "source" or not first.is_package:
                return Module(name, "missing", root=root), namespace
            current = first
            for index in range(1, len(parts)):
                if not current.is_package or current.path is None:
                    return Module(name, "missing", root=root), namespace
                candidate = self._at(current.path.parent / parts[index], ".".join(parts[: index + 1]), root)
                if candidate is None:
                    return Module(name, "missing", root=root), namespace
                current = candidate
                if current.kind != "source":
                    return Module(name, current.kind, current.path, root, external=current.external), namespace
            return current, namespace
        return None, namespace

    def _at(self, base: Path, name: str, root: Path) -> Module | None:
        external = root in self.installed_paths
        # Within one directory Python prefers a regular package to a module and
        # an extension loader to a source loader. Never silently prefer .py to .so.
        if base.is_dir():
            for suffix in EXTENSION_SUFFIXES:
                native_init = base / ("__init__" + suffix)
                if native_init.is_file():
                    return Module(name, "native", native_init.resolve(), root, True, external)
            initializer = base / "__init__.py"
            if initializer.is_file():
                return Module(name, "source", initializer.resolve(), root, True, external)
        for suffix in EXTENSION_SUFFIXES:
            native = base.with_name(base.name + suffix)
            if native.is_file():
                return Module(name, "native", native.resolve(), root, external=external)
        source = base.with_name(base.name + ".py")
        if source.is_file():
            return Module(name, "source", source.resolve(), root, external=external)
        if base.is_dir():
            return Module(name, "namespace", base.resolve(), root, True, external)
        return None
