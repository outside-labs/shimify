"""Data shared by source analysis, explanations, and artifact generation."""

from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
from typing import Literal

ModuleKind = Literal["source", "stdlib", "native", "namespace", "missing"]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    module: str
    line: int = 0


@dataclass(frozen=True)
class Module:
    name: str
    kind: ModuleKind
    path: Path | None = None
    root: Path | None = None
    is_package: bool = False
    external: bool = False
    source: bytes | None = field(default=None, repr=False)

    @property
    def sha256(self) -> str | None:
        return hashlib.sha256(self.source).hexdigest() if self.source is not None else None


@dataclass(frozen=True, order=True)
class ImportEdge:
    importer: str
    target: str
    line: int
    reason: str


@dataclass
class ModuleGraph:
    entrypoint: Path
    search_paths: tuple[Path, ...]
    modules: dict[str, Module] = field(default_factory=dict)
    edges: list[ImportEdge] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return not self.diagnostics

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "entrypoint": str(self.entrypoint),
            "search_paths": [str(path) for path in self.search_paths],
            "supported": self.supported,
            "modules": [
                {
                    "name": module.name,
                    "kind": module.kind,
                    "path": str(module.path) if module.path else None,
                    "is_package": module.is_package,
                    "external": module.external,
                    "sha256": module.sha256,
                    "size_bytes": len(module.source) if module.source is not None else None,
                }
                for _, module in sorted(self.modules.items())
            ],
            "edges": [asdict(edge) for edge in sorted(set(self.edges))],
            "diagnostics": [
                asdict(item)
                for item in sorted(set(self.diagnostics), key=lambda d: (d.module, d.line, d.code, d.message))
            ],
        }
