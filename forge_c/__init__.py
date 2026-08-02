"""Direct C source emission from Forge IR."""

from .emitter import CEmissionError, emit_c, emit_c_header
from .project import CProjectOutput, emit_c_project

__all__ = [
    "CEmissionError",
    "CProjectOutput",
    "emit_c",
    "emit_c_header",
    "emit_c_project",
]
