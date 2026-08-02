"""AST normalization for Forge programs."""

from .normalizer import NormalizationResult, normalize, normalize_program

__all__ = [
    "NormalizationResult",
    "normalize",
    "normalize_program",
]
