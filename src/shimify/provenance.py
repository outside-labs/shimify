"""Read installed file records and preserve attribution without loading code."""

from dataclasses import dataclass
from importlib.metadata import PathDistribution
from pathlib import Path, PurePosixPath
import re

from shimify.models import ModuleGraph


class BundleError(ValueError):
    """An unsupported artifact contract or unsafe output destination."""


@dataclass
class Provenance:
    distributions: list[dict]
    owners: dict[Path, str]
    notices: dict[str, bytes]


def _notice_name(name: str) -> bool:
    return name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "COPYRIGHT"))


def _relative_file(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or not path.parts:
        raise BundleError(f"SHIM302: Unsafe distribution file record: {value}")
    return path


def _identity(distribution: PathDistribution) -> str:
    name, version = distribution.metadata.get("Name"), distribution.metadata.get("Version")
    if not name or not version:
        raise BundleError("SHIM302: Distribution lacks Name/Version metadata.")
    return re.sub(r"[^A-Za-z0-9._-]", "_", name + "-" + version)


def collect_provenance(graph: ModuleGraph) -> Provenance:
    sources = {module.path: module for module in graph.modules.values() if module.kind == "source"}
    candidates: dict[Path, list[tuple[Path, PathDistribution, dict[str, Path]]]] = {}
    for root in graph.search_paths:
        for info in sorted(root.glob("*.dist-info")):
            metadata_path = info / "METADATA"
            if not info.is_dir() or not info.resolve().is_relative_to(root):
                continue
            if not metadata_path.is_file() or not metadata_path.resolve().is_relative_to(root):
                continue
            distribution = PathDistribution(info)
            records = {}
            for recorded in distribution.files or ():
                # Wheels may record interpreter scripts outside site-packages.
                # Such paths cannot own a supported source module in this root.
                try:
                    relative = _relative_file(str(recorded))
                except BundleError:
                    continue
                path = root.joinpath(*relative.parts).resolve()
                if path.is_relative_to(root):
                    records[relative.as_posix()] = path
            for path in sources.keys() & set(records.values()):
                candidates.setdefault(path, []).append((info, distribution, records))
    owners: dict[Path, str] = {}
    used: dict[Path, tuple[PathDistribution, dict[str, Path], list[str]]] = {}
    for path, module in sorted(sources.items(), key=lambda pair: pair[1].name):
        matches = candidates.get(path, [])
        if len(matches) > 1:
            raise BundleError(f"SHIM303: Multiple distributions claim {module.name}.")
        if not matches:
            if module.external:
                raise BundleError(f"SHIM302: No installed distribution file record owns {module.name}.")
            continue
        info, distribution, records = matches[0]
        identity = _identity(distribution)
        owners[path] = identity
        used.setdefault(info, (distribution, records, []))[2].append(module.name)
    notices: dict[str, bytes] = {}
    distributions = []
    identities = set()
    for info, (distribution, records, modules) in sorted(used.items()):
        name, version = distribution.metadata["Name"], distribution.metadata["Version"]
        identity = _identity(distribution)
        if identity in identities:
            raise BundleError(f"SHIM303: Multiple installations use the same distribution identity: {identity}")
        identities.add(identity)
        root = info.parent.resolve()
        selected = {
            path for relative, path in records.items()
            if _notice_name(PurePosixPath(relative).name)
            or path.is_relative_to(info / "licenses")
        }
        for declaration in distribution.metadata.get_all("License-File", []):
            relative = _relative_file(declaration)
            possible = [info / "licenses" / Path(*relative.parts), info / Path(*relative.parts), root / Path(*relative.parts)]
            found = next((path.resolve() for path in possible if path.is_file() and path.resolve().is_relative_to(root)), None)
            if found is None:
                raise BundleError(f"SHIM305: {name} declares a missing license file: {declaration}")
            selected.add(found)
        if not selected:
            raise BundleError(f"SHIM304: {name} has no available license/notice files; supply a complete installation.")
        metadata_path = info / "METADATA"
        notices[f"LICENSES/{identity}/METADATA"] = metadata_path.read_bytes()
        license_outputs = []
        for path in sorted(selected):
            content = path.read_bytes()
            if not content.strip():
                raise BundleError(f"SHIM304: {name} has an empty license/notice file: {path.name}")
            output = f"LICENSES/{identity}/{path.relative_to(root).as_posix()}"
            if output in notices:
                raise BundleError(f"SHIM301: Attribution path collision: {output}")
            notices[output] = content
            license_outputs.append(output)
        distributions.append({
            "id": identity,
            "name": name,
            "version": version,
            "license_expression": distribution.metadata.get("License-Expression"),
            "license": distribution.metadata.get("License"),
            "license_classifiers": [value for value in distribution.metadata.get_all("Classifier", []) if value.startswith("License ::")],
            "requires_python": distribution.metadata.get("Requires-Python"),
            "metadata": f"LICENSES/{identity}/METADATA",
            "license_files": sorted(license_outputs),
            "modules": sorted(modules),
        })
    # Also preserve notices for explicitly supplied application roots and the
    # ancestor package directories actually used. Do not recursively copy a repo.
    local_roots: dict[Path, set[Path]] = {}
    for path, module in sorted(sources.items(), key=lambda pair: pair[1].name):
        if path in owners or module.root is None or path is None:
            continue
        root = module.root
        directories = local_roots.setdefault(root, {root})
        current = path.parent
        while current.is_relative_to(root):
            directories.add(current)
            if current == root:
                break
            current = current.parent
    for index, (root, directories) in enumerate(local_roots.items(), 1):
        for directory in sorted(directories):
            for path in sorted(directory.iterdir()):
                if path.is_file() and _notice_name(path.name) and path.resolve().is_relative_to(root):
                    notices[f"LICENSES/local-{index}/{path.relative_to(root).as_posix()}"] = path.read_bytes()
    return Provenance(sorted(distributions, key=lambda d: d["id"]), owners, notices)
