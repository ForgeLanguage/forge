"""Lexical name resolution for validated Forge AST programs."""

from .resolver import (
    BuiltinSymbol,
    BuiltinInterfaceSymbol,
    NameResolutionError,
    ResolutionResult,
    ResolutionTable,
    SpecialSymbol,
    resolve,
)

__all__ = [
    "BuiltinSymbol",
    "BuiltinInterfaceSymbol",
    "NameResolutionError",
    "ResolutionResult",
    "ResolutionTable",
    "SpecialSymbol",
    "resolve",
]
