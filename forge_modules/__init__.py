"""Project/module loading for multi-file Forge programs."""

from .project import (
    ModuleDiagnostic,
    ModuleSymbol,
    NativeMetadata,
    PackageMetadata,
    Project,
    ProjectManifest,
    ProjectPackage,
    SourceFile,
    load_project,
)

__all__ = [
    "ModuleDiagnostic",
    "ModuleSymbol",
    "NativeMetadata",
    "PackageMetadata",
    "Project",
    "ProjectManifest",
    "ProjectPackage",
    "SourceFile",
    "load_project",
]
