"""Project/module loading for multi-file Forge programs."""

from .project import (
    ExpandedSource,
    ModuleDiagnostic,
    ModuleSymbol,
    NativeMetadata,
    PackageMetadata,
    Project,
    ProjectManifest,
    ProjectPackage,
    SourceFile,
    expand_project_sources,
    load_project,
)

__all__ = [
    "ExpandedSource",
    "ModuleDiagnostic",
    "ModuleSymbol",
    "NativeMetadata",
    "PackageMetadata",
    "Project",
    "ProjectManifest",
    "ProjectPackage",
    "SourceFile",
    "expand_project_sources",
    "load_project",
]
