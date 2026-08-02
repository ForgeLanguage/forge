"""Load Forge source trees and local package metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forge_templates import TemplateExpansionError, expand_template_sources

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None

from forge_parser import ClassDeclaration, EnumDeclaration, Program, UseDeclaration, parse

_BUNDLED_PACKAGES = {
    "std": Path(__file__).resolve().parent.parent / "stdlib" / "std",
}


@dataclass(frozen=True, slots=True)
class ModuleDiagnostic:
    message: str
    path: Path


@dataclass(frozen=True, slots=True)
class NativeMetadata:
    includes: tuple[str, ...] = ()
    include_dirs: tuple[Path, ...] = ()
    sources: tuple[Path, ...] = ()
    library_dirs: tuple[Path, ...] = ()
    libraries: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    pkg_config: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageMetadata:
    name: str
    version: str
    compatible: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    path: Path
    entry_point: Path
    packages_path: Path
    package: PackageMetadata | None
    dependencies: dict[str, str]
    native: NativeMetadata = field(default_factory=NativeMetadata)


@dataclass(frozen=True, slots=True)
class ProjectPackage:
    root: Path
    src_root: Path
    metadata: PackageMetadata
    native: NativeMetadata = field(default_factory=NativeMetadata)

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def version(self) -> str:
        return self.metadata.version


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: Path
    relative_path: Path
    namespace: tuple[str, ...]
    program: Program
    imports: tuple[UseDeclaration, ...]
    package: str | None = None

    @property
    def namespace_name(self) -> str:
        return ".".join(self.namespace)


@dataclass(frozen=True, slots=True)
class _SourceInput:
    path: Path
    relative_path: Path
    namespace: tuple[str, ...]
    source_name: str
    source: str
    package: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleSymbol:
    full_name: str
    short_name: str
    namespace: tuple[str, ...]
    declaration: ClassDeclaration
    source_file: SourceFile


@dataclass(frozen=True, slots=True)
class Project:
    root: Path
    src_root: Path
    files: tuple[SourceFile, ...]
    symbols: dict[str, ModuleSymbol]
    diagnostics: tuple[ModuleDiagnostic, ...]
    manifest: ProjectManifest | None = None
    packages: tuple[ProjectPackage, ...] = ()
    dependencies: dict[str, str] = field(default_factory=dict)
    lock: dict[str, str] = field(default_factory=dict)
    native: NativeMetadata = field(default_factory=NativeMetadata)

    @property
    def ok(self) -> bool:
        return not self.diagnostics


def load_project(root: str | Path, *, src_dir: str = "src") -> Project:
    """Load Forge source files and local packages from *root*."""

    root_path = Path(root)
    if root_path.name == "forge.toml":
        root_path = root_path.parent
    root_path = root_path.resolve()

    diagnostics: list[ModuleDiagnostic] = []
    manifest = _load_project_manifest(root_path, diagnostics)
    packages: tuple[ProjectPackage, ...] = ()
    lock: dict[str, str] = {}

    if manifest is None:
        src_root = (root_path / src_dir).resolve()
        source_inputs = _load_source_inputs(src_root, src_root)
        files = _parse_source_inputs(source_inputs)
        dependencies: dict[str, str] = {}
        native = NativeMetadata()
    else:
        src_root = (root_path / src_dir).resolve()
        packages = _load_dependency_packages(manifest, diagnostics)
        lock = _load_lock(root_path, manifest.dependencies, diagnostics)
        dependency_inputs = tuple(
            source_input
            for package in packages
            for source_input in _load_source_inputs(
                package.src_root,
                package.src_root,
                namespace_prefix=(package.name,),
                package=package.name,
            )
        )
        source_inputs = (*_load_source_inputs(src_root, src_root), *dependency_inputs)
        files = _parse_source_inputs(source_inputs)
        dependencies = dict(manifest.dependencies)
        native = _merge_native(manifest.native, *(package.native for package in packages))

    symbols, symbol_diagnostics = _collect_symbols(files)
    return Project(
        root_path,
        src_root,
        files,
        symbols,
        (*diagnostics, *symbol_diagnostics),
        manifest,
        packages,
        dependencies,
        lock,
        native,
    )


def _load_source_tree(
    root: Path,
    src_root: Path,
    *,
    namespace_prefix: tuple[str, ...] = (),
    package: str | None = None,
) -> tuple[SourceFile, ...]:
    return _parse_source_inputs(
        _load_source_inputs(
            root,
            src_root,
            namespace_prefix=namespace_prefix,
            package=package,
        )
    )


def _load_source_inputs(
    root: Path,
    src_root: Path,
    *,
    namespace_prefix: tuple[str, ...] = (),
    package: str | None = None,
) -> tuple[_SourceInput, ...]:
    return tuple(
        _load_source_input(
            path,
            src_root,
            namespace_prefix=namespace_prefix,
            package=package,
        )
        for path in sorted(root.rglob("*.forge"))
    )


def _load_source_input(
    path: Path,
    src_root: Path,
    *,
    namespace_prefix: tuple[str, ...] = (),
    package: str | None = None,
) -> _SourceInput:
    relative_path = path.relative_to(src_root)
    namespace = _namespace_for(relative_path, namespace_prefix)
    source_name = Path(*namespace_prefix, relative_path).as_posix()
    source = path.read_text()
    return _SourceInput(path, relative_path, namespace, source_name, source, package)


def _parse_source_inputs(source_inputs: tuple[_SourceInput, ...]) -> tuple[SourceFile, ...]:
    try:
        expanded_sources = expand_template_sources(
            tuple((source_input.source_name, source_input.source) for source_input in source_inputs)
        )
    except TemplateExpansionError as exc:
        raise SyntaxError(str(exc)) from exc
    return tuple(
        _parse_source_input(source_input, expanded_sources[source_input.source_name])
        for source_input in source_inputs
    )


def _parse_source_input(source_input: _SourceInput, source: str) -> SourceFile:
    try:
        program = parse(source, source_name=source_input.source_name)
    except TemplateExpansionError as exc:
        raise SyntaxError(f"{exc} in {source_input.path}") from exc
    imports = tuple(
        declaration
        for declaration in program.declarations
        if isinstance(declaration, UseDeclaration)
    )
    return SourceFile(
        source_input.path,
        source_input.relative_path,
        source_input.namespace,
        program,
        imports,
        source_input.package,
    )


def _namespace_for(
    relative_path: Path,
    namespace_prefix: tuple[str, ...] = (),
) -> tuple[str, ...]:
    relative_parent = relative_path.parent
    if str(relative_parent) == ".":
        return namespace_prefix
    return (*namespace_prefix, *relative_parent.parts)


def _collect_symbols(
    files: tuple[SourceFile, ...]
) -> tuple[dict[str, ModuleSymbol], list[ModuleDiagnostic]]:
    symbols: dict[str, ModuleSymbol] = {}
    diagnostics: list[ModuleDiagnostic] = []

    for source_file in files:
        for declaration in source_file.program.declarations:
            if not isinstance(declaration, (ClassDeclaration, EnumDeclaration)) or declaration.name is None:
                continue
            full_name = _full_name(source_file.namespace, declaration.name)
            symbol = ModuleSymbol(
                full_name,
                declaration.name,
                source_file.namespace,
                declaration,
                source_file,
            )
            if full_name in symbols:
                diagnostics.append(
                    ModuleDiagnostic(
                        f"Duplicate top-level symbol '{full_name}'",
                        source_file.path,
                    )
                )
            else:
                symbols[full_name] = symbol

    return symbols, diagnostics


def _full_name(namespace: tuple[str, ...], name: str) -> str:
    return ".".join((*namespace, name)) if namespace else name


def _load_project_manifest(
    root: Path,
    diagnostics: list[ModuleDiagnostic],
) -> ProjectManifest | None:
    manifest_path = root / "forge.toml"
    if not manifest_path.exists():
        return None

    data = _read_toml(manifest_path, diagnostics)
    entry_point = _path_value(data, "entry_point", "./main.forge")
    packages_path = _path_value(data, "packages_path", "./packages/")
    return ProjectManifest(
        manifest_path,
        (root / entry_point).resolve(),
        (root / packages_path).resolve(),
        _package_metadata(data, manifest_path, diagnostics, required=False),
        _string_table(data.get("dependencies", {}), manifest_path, diagnostics),
        _native_metadata(data.get("native", {}), root, manifest_path, diagnostics),
    )


def _load_dependency_packages(
    manifest: ProjectManifest,
    diagnostics: list[ModuleDiagnostic],
) -> tuple[ProjectPackage, ...]:
    packages: list[ProjectPackage] = []
    for name, version in sorted(manifest.dependencies.items()):
        package_root = _dependency_package_root(manifest, name)
        manifest_path = package_root / "forge.toml"
        if not package_root.exists():
            diagnostics.append(
                ModuleDiagnostic(f"Missing local package '{name}'", package_root)
            )
            continue
        if not manifest_path.exists():
            diagnostics.append(
                ModuleDiagnostic(
                    f"Package '{name}' is missing forge.toml",
                    manifest_path,
                )
            )
            continue

        data = _read_toml(manifest_path, diagnostics)
        metadata = _package_metadata(data, manifest_path, diagnostics, required=True)
        if metadata is None:
            continue
        if metadata.name != name:
            diagnostics.append(
                ModuleDiagnostic(
                    f"Package directory '{name}' declares package '{metadata.name}'",
                    manifest_path,
                )
            )
        if metadata.name != package_root.name:
            diagnostics.append(
                ModuleDiagnostic(
                    f"Package name '{metadata.name}' must match directory '{package_root.name}'",
                    manifest_path,
                )
            )
        if metadata.version != version:
            diagnostics.append(
                ModuleDiagnostic(
                    f"Package '{name}' version '{metadata.version}' does not match dependency '{version}'",
                    manifest_path,
                )
            )
        packages.append(
            ProjectPackage(
                package_root,
                (package_root / "src").resolve(),
                metadata,
                _native_metadata(data.get("native", {}), package_root, manifest_path, diagnostics),
            )
        )
    return tuple(packages)


def _dependency_package_root(manifest: ProjectManifest, name: str) -> Path:
    local_root = (manifest.packages_path / name).resolve()
    if local_root.exists():
        return local_root
    bundled = _BUNDLED_PACKAGES.get(name)
    if bundled is not None:
        return bundled.resolve()
    return local_root


def _load_lock(
    root: Path,
    dependencies: dict[str, str],
    diagnostics: list[ModuleDiagnostic],
) -> dict[str, str]:
    if not dependencies:
        return {}

    lock_path = root / "forge.lock"
    if not lock_path.exists():
        diagnostics.append(
            ModuleDiagnostic("forge.lock is required when dependencies are declared", lock_path)
        )
        return {}

    data = _read_toml(lock_path, diagnostics)
    lock = _string_table(data, lock_path, diagnostics)
    missing = sorted(set(dependencies) - set(lock))
    extra = sorted(set(lock) - set(dependencies))
    if missing:
        diagnostics.append(
            ModuleDiagnostic(
                f"forge.lock is missing dependencies: {', '.join(missing)}",
                lock_path,
            )
        )
    if extra:
        diagnostics.append(
            ModuleDiagnostic(
                f"forge.lock has extra dependencies: {', '.join(extra)}",
                lock_path,
            )
        )
    for name in sorted(set(dependencies) & set(lock)):
        if dependencies[name] != lock[name]:
            diagnostics.append(
                ModuleDiagnostic(
                    f"forge.lock version for '{name}' is '{lock[name]}', expected '{dependencies[name]}'",
                    lock_path,
                )
            )
    return lock


def _read_toml(path: Path, diagnostics: list[ModuleDiagnostic]) -> dict[str, Any]:
    try:
        text = path.read_text()
        if tomllib is not None:
            return tomllib.loads(text)
        return _read_simple_toml(text)
    except Exception as exc:  # pragma: no cover - exact parser errors differ
        diagnostics.append(ModuleDiagnostic(f"Could not parse {path.name}: {exc}", path))
        return {}


def _read_simple_toml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current = data
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = data
            for part in line[1:-1].strip().split("."):
                child = current.setdefault(part, {})
                if not isinstance(child, dict):
                    raise ValueError(f"Table conflicts with scalar key '{part}'")
                current = child
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"Expected key/value line: {raw_line}")
        current[key.strip()] = _simple_toml_value(value.strip())
    return data


def _simple_toml_value(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_simple_toml_value(part.strip()) for part in inner.split(",")]
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def _path_value(data: dict[str, Any], key: str, default: str) -> Path:
    value = data.get(key, default)
    return Path(value if isinstance(value, str) else default)


def _package_metadata(
    data: dict[str, Any],
    path: Path,
    diagnostics: list[ModuleDiagnostic],
    *,
    required: bool,
) -> PackageMetadata | None:
    section = data.get("package")
    if section is None:
        if required:
            diagnostics.append(ModuleDiagnostic("Missing [package] section", path))
        return None
    if not isinstance(section, dict):
        diagnostics.append(ModuleDiagnostic("[package] must be a table", path))
        return None
    name = section.get("name")
    version = section.get("version")
    compatible = section.get("compatible")
    if not isinstance(name, str) or not isinstance(version, str):
        diagnostics.append(
            ModuleDiagnostic("[package] requires string name and version", path)
        )
        return None
    return PackageMetadata(
        name,
        version,
        compatible if isinstance(compatible, str) else None,
    )


def _native_metadata(
    data: Any,
    root: Path,
    path: Path,
    diagnostics: list[ModuleDiagnostic],
) -> NativeMetadata:
    if data in (None, {}):
        return NativeMetadata()
    if not isinstance(data, dict):
        diagnostics.append(ModuleDiagnostic("[native] must be a table", path))
        return NativeMetadata()

    return NativeMetadata(
        _string_tuple(data, "includes", path, diagnostics),
        tuple(_resolve_native_path(root, value) for value in _string_tuple(data, "include_dirs", path, diagnostics)),
        tuple(_resolve_native_path(root, value) for value in _string_tuple(data, "sources", path, diagnostics)),
        tuple(_resolve_native_path(root, value) for value in _string_tuple(data, "library_dirs", path, diagnostics)),
        _string_tuple(data, "libraries", path, diagnostics),
        _string_tuple(data, "frameworks", path, diagnostics),
        _string_tuple(data, "pkg_config", path, diagnostics),
    )


def _string_table(
    data: Any,
    path: Path,
    diagnostics: list[ModuleDiagnostic],
) -> dict[str, str]:
    if data in (None, {}):
        return {}
    if not isinstance(data, dict):
        diagnostics.append(ModuleDiagnostic("Expected TOML table", path))
        return {}
    result: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            diagnostics.append(
                ModuleDiagnostic(f"Expected string value for '{key}'", path)
            )
            continue
        result[key] = value
    return result


def _string_tuple(
    data: dict[str, Any],
    key: str,
    path: Path,
    diagnostics: list[ModuleDiagnostic],
) -> tuple[str, ...]:
    value = data.get(key, ())
    if value in (None, ()):
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        diagnostics.append(ModuleDiagnostic(f"[native].{key} must be a string array", path))
        return ()
    return tuple(value)


def _resolve_native_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _merge_native(*items: NativeMetadata) -> NativeMetadata:
    includes: list[str] = []
    include_dirs: list[Path] = []
    sources: list[Path] = []
    library_dirs: list[Path] = []
    libraries: list[str] = []
    frameworks: list[str] = []
    pkg_config: list[str] = []

    for item in items:
        _extend_unique(includes, item.includes)
        _extend_unique(include_dirs, item.include_dirs)
        _extend_unique(sources, item.sources)
        _extend_unique(library_dirs, item.library_dirs)
        _extend_unique(libraries, item.libraries)
        _extend_unique(frameworks, item.frameworks)
        _extend_unique(pkg_config, item.pkg_config)

    return NativeMetadata(
        tuple(includes),
        tuple(include_dirs),
        tuple(sources),
        tuple(library_dirs),
        tuple(libraries),
        tuple(frameworks),
        tuple(pkg_config),
    )


def _extend_unique(target: list, values: tuple) -> None:
    for value in values:
        if value not in target:
            target.append(value)
