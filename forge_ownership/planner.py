"""Ownership cleanup decisions for lowered Forge IR.

The C backend still owns the concrete syntax of cleanup statements, but this
module owns the semantic decision of which lowered values need cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from forge_ir import (
    IrAssignment,
    IrArrayLiteral,
    IrArrayPatternCheck,
    IrBinary,
    IrCall,
    IrCatch,
    IrConditional,
    IrExpression,
    IrForExpression,
    IrForward,
    IrIndex,
    IrLocalRef,
    IrMember,
    IrDoWhileExpression,
    IrVariable,
    IrProgram,
    IrWhileExpression,
)
from forge_lexer import TokenKind
from forge_safety import BindingState
from forge_typecheck import (
    STRING,
    ArrayType,
    BuiltinType,
    ClassType,
    NullableType,
    StructType,
    TaskCollectionType,
    Type,
)

CleanupKind = Literal["none", "string", "class", "array"]
ArrayElementCleanupKind = Literal["none", "string", "class"]


@dataclass(frozen=True, slots=True)
class OwnershipPlan:
    """Cleanup policy derived for an IR program."""

    program: IrProgram

    def owned_class_binding(self, binding) -> bool:
        return (
            self._class_type(binding.type) is not None
            and binding.safety is not None
            and binding.safety.ownership == "owner"
            and binding.safety.availability == "available"
        )

    def local_cleanup_kind(self, variable: IrVariable) -> CleanupKind:
        if "static" in variable.modifiers:
            return "none"
        if self._is_string_type(variable.type) and self.string_local_owns_initializer(variable):
            return "string"
        if self.owned_class_binding(variable):
            return "class"
        if self.array_local_needs_cleanup(variable):
            return "array"
        return "none"

    def string_local_owns_initializer(self, variable: IrVariable) -> bool:
        if not self._is_string_type(variable.type) or variable.initializer is None:
            return False
        return (
            variable.mutable
            or isinstance(variable.initializer, IrConditional)
            or self.owned_string_expression(variable.initializer)
        )

    def array_local_needs_cleanup(self, variable: IrVariable) -> bool:
        return (
            (
                isinstance(variable.type, ArrayType)
                or isinstance(variable.type, TaskCollectionType)
            )
            and "static" not in variable.modifiers
            and (
                variable.safety is None
                or variable.safety.ownership != "borrow"
            )
        )

    def fixed_array_local_needs_cleanup(self, variable: IrVariable) -> bool:
        return (
            isinstance(variable.type, ArrayType)
            and variable.type.size is not None
            and self.array_element_cleanup_kind(variable.type) != "none"
            and "static" not in variable.modifiers
        )

    def destructor_field_cleanup_kind(self, field: IrVariable) -> CleanupKind:
        if field.field_ownership == "borrow":
            return "none"
        type_ = field.type
        if type_ == STRING:
            return "string"
        if self._class_type(type_) is not None:
            return "class"
        if isinstance(type_, ArrayType):
            return "array"
        return "none"

    def array_element_cleanup_kind(self, type_: ArrayType) -> ArrayElementCleanupKind:
        if type_.element_type == STRING:
            return "string"
        if self._class_type(type_.element_type) is not None:
            return "class"
        return "none"

    def tracks_struct_string_field_assignment(self, expression: IrAssignment) -> bool:
        if not isinstance(expression.target, IrMember):
            return False
        if expression.target.type != STRING or expression.value.type != STRING:
            return False
        if not isinstance(expression.target.receiver, IrLocalRef):
            return False
        if not isinstance(expression.target.receiver.type, StructType):
            return False
        return self.owned_string_assignment_value(expression.value)

    def owned_string_assignment_value(self, expression: IrExpression) -> bool:
        return self.owned_string_expression(expression) or isinstance(expression, (IrForward, IrCatch))

    def owned_string_expression(self, expression: IrExpression) -> bool:
        if self.string_from_array_index(expression):
            return True
        if (
            isinstance(
                expression,
                (IrForExpression, IrWhileExpression, IrDoWhileExpression),
            )
            and self._is_string_type(expression.type)
        ):
            return True
        return (
            isinstance(expression, IrBinary)
            and expression.operator is TokenKind.PLUS
            and expression.type == STRING
        ) or self.allocating_string_call(expression)

    def string_from_temporary_array_index(self, expression: IrExpression) -> bool:
        return (
            self.string_from_array_index(expression)
            and self.owned_array_expression(expression.receiver)
        )

    def string_from_array_index(self, expression: IrExpression) -> bool:
        return (
            isinstance(expression, IrIndex)
            and expression.type == STRING
            and isinstance(expression.receiver.type, ArrayType)
            and expression.receiver.type.element_type == STRING
        )

    def allocating_string_call(self, expression: IrExpression) -> bool:
        if not isinstance(expression, IrCall) or expression.type != STRING:
            return False
        return not self.non_allocating_string_to_string_call(expression)

    def allocating_array_call(self, expression: IrExpression) -> bool:
        return (
            isinstance(expression, IrCall)
            and isinstance(expression.type, ArrayType)
            and expression.type.size is None
        )

    def owned_array_expression(self, expression: IrExpression) -> bool:
        if isinstance(expression, IrArrayPatternCheck):
            return self.owned_array_expression(expression.source)
        if isinstance(expression, IrCatch) and isinstance(expression.type, ArrayType):
            return self.owned_array_expression(expression.expression)
        if self.allocating_array_call(expression):
            return True
        if (
            isinstance(expression, IrArrayLiteral)
            and isinstance(expression.type, ArrayType)
            and expression.type.size is None
        ):
            return True
        return (
            isinstance(expression, IrConditional)
            and isinstance(expression.type, ArrayType)
            and expression.type.size is None
        )

    def allocating_primitive_to_string_call(self, expression: IrExpression) -> bool:
        return (
            self.primitive_to_string_call(expression)
            and isinstance(expression, IrCall)
            and expression.callee.receiver.type != STRING
        )

    def primitive_to_string_call(self, expression: IrExpression) -> bool:
        return (
            isinstance(expression, IrCall)
            and isinstance(expression.callee, IrMember)
            and expression.callee.member == "toString"
            and isinstance(expression.callee.receiver.type, BuiltinType)
        )

    def non_allocating_string_to_string_call(self, expression: IrExpression) -> bool:
        return (
            self.primitive_to_string_call(expression)
            and isinstance(expression, IrCall)
            and expression.callee.receiver.type == STRING
        )

    def _class_type(self, type_: Type) -> ClassType | None:
        if isinstance(type_, NullableType):
            type_ = type_.inner_type
        return type_ if isinstance(type_, ClassType) else None

    def _is_string_type(self, type_: Type) -> bool:
        if isinstance(type_, NullableType):
            type_ = type_.inner_type
        return type_ == STRING


def analyze_ownership(program: IrProgram) -> OwnershipPlan:
    """Build an ownership cleanup plan for a lowered IR program."""

    return OwnershipPlan(program)
