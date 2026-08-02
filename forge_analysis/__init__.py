"""AST validation and annotation for parsed Forge programs."""

from .validator import (
    AnalysisResult,
    AnnotationTable,
    Diagnostic,
    Scope,
    Symbol,
    ValidationError,
    analyze,
    validate,
)

__all__ = [
    "AnalysisResult",
    "AnnotationTable",
    "Diagnostic",
    "Scope",
    "Symbol",
    "ValidationError",
    "analyze",
    "validate",
]
