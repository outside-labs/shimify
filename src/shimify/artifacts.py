"""Exclusive publication of small, preflighted artifact directories."""

import os
from pathlib import Path, PurePosixPath
import tempfile

from shimify.provenance import BundleError


def write_directory(output: str | Path, files: dict[str, bytes], *, source_roots: tuple[Path, ...]) -> Path:
    requested = Path(output).absolute()
    if requested.exists() or requested.is_symlink():
        raise BundleError(f"SHIM301: Output already exists: {requested}")
    destination = requested.resolve()
    if any(destination.is_relative_to(root) or root.is_relative_to(destination) for root in source_roots):
        raise BundleError("SHIM301: Output overlaps a source root.")
    names = set()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    for name in sorted(files):
        path = PurePosixPath(name)
        if not path.parts or path.is_absolute() or ".." in path.parts or str(path) != name:
            raise BundleError(f"SHIM301: Unsafe artifact path: {name}")
        for part in path.parts:
            if part.split(".")[0].upper() in reserved or part.endswith((".", " ")) or any(c in part for c in '\\:*?"<>|'):
                raise BundleError(f"SHIM301: Nonportable artifact path: {name}")
        key = name.casefold()
        if key in names or any(key.startswith(other + "/") or other.startswith(key + "/") for other in names):
            raise BundleError(f"SHIM301: Artifact path collision: {name}")
        names.add(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".shimify-", dir=destination.parent) as directory:
        stage = Path(directory)
        for name, content in files.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        destination.mkdir()
        written, directories = [], {destination}
        try:
            for name in sorted(files):
                path = destination / name
                parents = []
                parent = path.parent
                while parent != destination:
                    parents.append(parent)
                    parent = parent.parent
                for parent in reversed(parents):
                    if parent not in directories:
                        parent.mkdir()
                        directories.add(parent)
                os.link(stage / name, path)
                written.append(path)
        except BaseException:
            for path in reversed(written):
                path.unlink(missing_ok=True)
            for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
                try:
                    path.rmdir()
                except OSError:
                    pass
            raise
    return destination
