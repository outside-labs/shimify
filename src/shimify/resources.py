"""Literal text-resource and version-query contracts for an explicit bundle profile."""

import ast
from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re

from shimify.models import Diagnostic


def distribution_key(name):
    return re.sub(r'[-_.]+', '-', name).lower()


@dataclass(frozen=True, order=True)
class TextResource:
    package: str
    path: str

    def __post_init__(self):
        if not isinstance(self.package, str) or not all(part.isidentifier() for part in self.package.split('.')):
            raise ValueError('Resource package must be an ordinary qualified module name.')
        if not isinstance(self.path, str):
            raise ValueError('Resource path must be a normalized relative .txt path.')
        path = PurePosixPath(self.path)
        if (not path.parts or path.is_absolute() or '..' in path.parts or str(path) != self.path
                or '\\' in self.path or path.suffix != '.txt'
                or any(not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*', part) or part.endswith('.') for part in path.parts)):
            raise ValueError('Resource path must be a normalized relative .txt path.')


@dataclass(frozen=True)
class ResourcePolicy:
    resources: tuple[TextResource, ...] = ()
    versions: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.resources, tuple) or any(not isinstance(item, TextResource) for item in self.resources):
            raise ValueError('resources must be a tuple of TextResource records')
        if not isinstance(self.versions, tuple) or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', name) for name in self.versions):
            raise ValueError('versions must be a tuple of explicit distribution names')
        if len(self.resources) > 32 or len({(item.package.casefold(), item.path.casefold()) for item in self.resources}) != len(self.resources):
            raise ValueError('Declare at most 32 unique text resources.')
        if len(self.versions) > 16 or len({distribution_key(name) for name in self.versions}) != len(self.versions):
            raise ValueError('Declare at most 16 unique distribution versions.')
        if not self.resources and not self.versions:
            raise ValueError('Declare at least one resource or distribution version.')
        object.__setattr__(self, 'resources', tuple(sorted(self.resources)))
        object.__setattr__(self, 'versions', tuple(sorted(self.versions)))

    def to_dict(self):
        return {'version': 1, 'resources': [{'package': item.package, 'path': item.path} for item in self.resources],
                'distribution_versions': list(self.versions)}

    def authorize(self, tree, module, aliases, qualify):
        allowed, references, diagnostics = set(), set(), []
        namespaces = ('importlib.resources', 'importlib.metadata')
        def qualified(node):
            return qualify(node, aliases)
        def literal(node):
            return node.value if isinstance(node, ast.Constant) and type(node.value) is str else None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = qualified(node.func)
            if name == 'importlib.metadata.version' and len(node.args) == 1 and not node.keywords:
                requested = literal(node.args[0])
                if requested and distribution_key(requested) in {distribution_key(value) for value in self.versions}:
                    allowed.add(id(node))
                    references.update(id(part) for part in ast.walk(node.func))
            # Authorize the files() root only as part of the entire adopted chain.
            if not isinstance(node.func, ast.Attribute) or node.func.attr != 'read_text' or node.args:
                continue
            if len(node.keywords) != 1 or node.keywords[0].arg != 'encoding' or literal(node.keywords[0].value) != 'utf-8':
                continue
            joined = node.func.value
            if not isinstance(joined, ast.Call) or not isinstance(joined.func, ast.Attribute) or joined.func.attr != 'joinpath' or len(joined.args) != 1 or joined.keywords:
                continue
            anchor = joined.func.value
            if not isinstance(anchor, ast.Call) or qualified(anchor.func) != 'importlib.resources.files' or len(anchor.args) != 1 or anchor.keywords:
                continue
            package, path = literal(anchor.args[0]), literal(joined.args[0])
            if any(item.package == package and item.path == path for item in self.resources):
                allowed.add(id(anchor))
                references.update(id(part) for part in ast.walk(anchor.func))
        roots = {name for name, target in aliases.items() if target == 'importlib' or target.startswith(namespaces)}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    target = alias.name if isinstance(node, ast.Import) else (node.module or '') + '.' + alias.name
                    if target == 'importlib' or target.startswith(namespaces):
                        roots.add(alias.asname or (alias.name.split('.')[0] if isinstance(node, ast.Import) else alias.name))
        imports = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound = alias.asname or (alias.name.split('.')[0] if isinstance(node, ast.Import) else alias.name)
                    if bound in roots:
                        imports[bound] = imports.get(bound, 0) + 1
                        if node not in tree.body:
                            diagnostics.append(Diagnostic('SHIM117', 'Resource/metadata imports must be unconditional module bindings.', module, node.lineno))
            shadow = isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in roots
            shadow = shadow or isinstance(node, ast.arg) and node.arg in roots
            shadow = shadow or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in roots
            if shadow:
                diagnostics.append(Diagnostic('SHIM117', 'Resource/metadata API bindings cannot be rebound or shadowed.', module, node.lineno))
            if isinstance(node, (ast.Name, ast.Attribute)) and id(node) not in references and qualified(node).startswith(namespaces):
                code = 'SHIM113' if qualified(node).startswith(namespaces[0]) else 'SHIM112'
                diagnostics.append(Diagnostic(code, 'Resource/metadata API reference is outside the literal policy.', module, node.lineno))
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in roots and qualified(node) == 'importlib' and id(node) not in references:
                diagnostics.append(Diagnostic('SHIM117', 'The importlib namespace cannot escape an approved literal call.', module, node.lineno))
        if any(count > 1 for count in imports.values()):
            diagnostics.append(Diagnostic('SHIM117', 'Resource/metadata API imports cannot rebind an alias.', module))
        return allowed, diagnostics

    def export_boundaries(self, graph, trees, absolute_from, qualify):
        registries, aliases = {}, {}
        for module, tree in trees.items():
            mapping, registry = {}, set()
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        bound = alias.asname or (alias.name.split('.')[0] if isinstance(node, ast.Import) else alias.name)
                        target = alias.name if isinstance(node, ast.Import) else (node.module or '') + '.' + alias.name
                        mapping[bound] = target if isinstance(node, ast.ImportFrom) or alias.asname else alias.name.split('.')[0]
                        if not getattr(node, 'level', 0) and (target == 'importlib' or target.startswith(('importlib.resources', 'importlib.metadata'))):
                            registry.add(bound)
            aliases[module], registries[module] = mapping, registry
        diagnostics = []
        for module, tree in trees.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    base = absolute_from(node, graph.modules[module])
                    if any(alias.name in registries.get(base, set()) for alias in node.names):
                        diagnostics.append(Diagnostic('SHIM117', 'Resource/metadata APIs cannot be re-exported through source modules.', module, node.lineno))
                if isinstance(node, ast.Attribute):
                    name = qualify(node, aliases[module])
                    if any(name.startswith(base + '.') and name[len(base) + 1:].split('.')[0] in registry for base, registry in registries.items()):
                        diagnostics.append(Diagnostic('SHIM117', 'Source-module resource/metadata API dispatch is unsupported.', module, node.lineno))
        return diagnostics


def resource_files(graph, provenance):
    """Snapshot only declared data and minimal source-owned version metadata."""
    from shimify.provenance import BundleError

    files, resources, versions, total = {}, [], [], 0
    for resource in graph.resource_policy.resources:
        module = graph.modules.get(resource.package)
        if module is None or module.kind != 'source' or not module.is_package:
            raise BundleError('SHIM118: Resources require an included ordinary source package.')
        anchor = module.path.parent
        path = anchor.joinpath(*PurePosixPath(resource.path).parts)
        def valid_path():
            current = anchor
            for part in PurePosixPath(resource.path).parts:
                current = current / part
                if current.is_symlink():
                    return False
            return path.is_file() and path.resolve().is_relative_to(anchor)
        if not valid_path():
            raise BundleError('SHIM118: Resource is missing or escapes its package through a symlink.')
        owner = provenance.owners.get(module.path)
        if owner is not None and provenance.recorded_files.get(path.resolve()) != owner:
            raise BundleError('SHIM118: Resource is not recorded by the source-owning distribution.')
        with path.open('rb') as stream:
            data = stream.read(1_048_577)
        if not valid_path() or len(data) > 1_048_576:
            raise BundleError('SHIM118: Resource path changed or exceeds the 1 MiB limit.')
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            raise BundleError('SHIM118: Resource must contain UTF-8 text.') from None
        total += len(data)
        if total > 8_388_608:
            raise BundleError('SHIM118: Text resources exceed the 8 MiB total limit.')
        output = '_sources/' + resource.package.replace('.', '/') + '/' + resource.path
        files[output] = data
        resources.append({'package': resource.package, 'path': resource.path, 'output': output,
                          'distribution': owner, 'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)})
    for name in graph.resource_policy.versions:
        matches = [item for item in provenance.distributions if distribution_key(item['name']) == distribution_key(name)]
        if len(matches) != 1:
            raise BundleError('SHIM118: A version query requires one included source-owning distribution.')
        distribution = matches[0]
        normalized = distribution_key(distribution['name']).replace('-', '_')
        normalized_version = re.sub(r'[^A-Za-z0-9._]', '_', distribution['version'])
        directory = f'_sources/{normalized}-{normalized_version}.dist-info'
        output = directory + '/METADATA'
        files[output] = provenance.notices[distribution['metadata']]
        files[directory + '/SHIMIFY-REDUCED.txt'] = b'Selected source-bundle version metadata. This is not a complete installed wheel.\n'
        versions.append({'requested': name, 'name': distribution['name'], 'version': distribution['version'],
                         'distribution': distribution['id'], 'output': output})
    return files, resources, versions
