"""Dataclasses for Forge's backend-neutral lowered IR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from forge_analysis import Symbol
from forge_lexer import SourceLocation, TokenKind
from forge_safety import BindingState
from forge_typecheck import OutcomeType, Type

SpecialRefKind = Literal["this", "self"]


@dataclass(frozen=True, slots=True)
class IrNode:
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class IrProgram(IrNode):
    declarations: tuple["IrDeclaration | IrStatement", ...]


class IrDeclaration(IrNode):
    pass


@dataclass(frozen=True, slots=True)
class IrClass(IrDeclaration):
    symbol: Symbol | None
    name: str | None
    members: tuple["IrDeclaration | IrStatement", ...]
    modifiers: tuple[str, ...]
    kind: str = "class"
    implements: tuple[Type, ...] = ()


@dataclass(frozen=True, slots=True)
class IrEnumVariant(IrNode):
    name: str
    value: "IrExpression | None"


@dataclass(frozen=True, slots=True)
class IrEnum(IrDeclaration):
    symbol: Symbol | None
    name: str | None
    value_type: Type
    variants: tuple[IrEnumVariant, ...]
    modifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IrParameter(IrNode):
    symbol: Symbol
    name: str
    type: Type
    safety: BindingState | None = None
    lazy: bool = False


@dataclass(frozen=True, slots=True)
class IrFunction(IrDeclaration):
    symbol: Symbol | None
    name: str
    parameters: tuple[IrParameter, ...]
    return_type: Type
    body: "IrBlock"
    modifiers: tuple[str, ...]
    kind: str
    function_type: Type
    native_name: str | None = None


@dataclass(frozen=True, slots=True)
class IrVariable(IrDeclaration):
    symbol: Symbol
    name: str
    type: Type
    mutable: bool
    initializer: "IrExpression | None" = None
    modifiers: tuple[str, ...] = ()
    safety: BindingState | None = None
    field_ownership: str | None = None
    lazy: bool = False


@dataclass(frozen=True, slots=True)
class IrArrayDestructuring(IrDeclaration):
    source: "IrExpression"
    source_temp: IrVariable | None
    bindings: tuple[IrVariable, ...]


class IrStatement(IrNode):
    pass


@dataclass(frozen=True, slots=True)
class IrBlock(IrStatement):
    statements: tuple["IrStatement | IrDeclaration", ...]


@dataclass(frozen=True, slots=True)
class IrPrint(IrStatement):
    expression: "IrExpression"


@dataclass(frozen=True, slots=True)
class IrReturn(IrStatement):
    expression: "IrExpression | None"


@dataclass(frozen=True, slots=True)
class IrBreak(IrStatement):
    expression: "IrExpression | None"


@dataclass(frozen=True, slots=True)
class IrIf(IrStatement):
    condition: "IrExpression"
    then_branch: IrBlock
    else_branch: "IrBlock | IrIf | None" = None


@dataclass(frozen=True, slots=True)
class IrSwitchArm(IrNode):
    pattern: "IrExpression | None"
    body: IrBlock


@dataclass(frozen=True, slots=True)
class IrSwitch(IrStatement):
    expression: "IrExpression"
    arms: tuple[IrSwitchArm, ...]


@dataclass(frozen=True, slots=True)
class IrWhile(IrStatement):
    condition: "IrExpression"
    body: IrBlock


@dataclass(frozen=True, slots=True)
class IrDoWhile(IrStatement):
    body: IrBlock
    condition: "IrExpression"


@dataclass(frozen=True, slots=True)
class IrExpressionStatement(IrStatement):
    expression: "IrExpression"


class IrExpression(IrNode):
    type: Type


@dataclass(frozen=True, slots=True)
class IrLiteral(IrExpression):
    value: Any
    type: Type


@dataclass(frozen=True, slots=True)
class IrLocalRef(IrExpression):
    symbol: Symbol
    type: Type
    safety: BindingState | None = None
    task_outcomes: tuple[OutcomeType, ...] = ()


@dataclass(frozen=True, slots=True)
class IrBuiltinRef(IrExpression):
    name: str
    type: Type


@dataclass(frozen=True, slots=True)
class IrSpecialRef(IrExpression):
    kind: SpecialRefKind
    type: Type


@dataclass(frozen=True, slots=True)
class IrUnary(IrExpression):
    operator: TokenKind
    operand: IrExpression
    type: Type


@dataclass(frozen=True, slots=True)
class IrMove(IrExpression):
    expression: IrExpression
    type: Type


@dataclass(frozen=True, slots=True)
class IrForward(IrExpression):
    expression: IrExpression
    type: Type


@dataclass(frozen=True, slots=True)
class IrCatchHandler(IrNode):
    name: str
    type: Type
    expression: "IrExpression | IrBlock"


@dataclass(frozen=True, slots=True)
class IrCatch(IrExpression):
    expression: IrExpression
    handlers: tuple[IrCatchHandler, ...]
    type: Type


@dataclass(frozen=True, slots=True)
class IrArrayPatternCheck(IrExpression):
    source: IrExpression
    required_count: int
    type: Type
    outcomes: tuple[OutcomeType, ...]


@dataclass(frozen=True, slots=True)
class IrBinary(IrExpression):
    left: IrExpression
    operator: TokenKind
    right: IrExpression
    type: Type


@dataclass(frozen=True, slots=True)
class IrAssignment(IrExpression):
    target: IrExpression
    value: IrExpression
    type: Type
    operator: TokenKind = TokenKind.EQUAL


@dataclass(frozen=True, slots=True)
class IrConditional(IrExpression):
    condition: IrExpression
    then_expression: IrExpression
    else_expression: IrExpression
    type: Type


@dataclass(frozen=True, slots=True)
class IrWhileExpression(IrExpression):
    condition: IrExpression
    body: IrBlock
    fallback: IrExpression
    type: Type


@dataclass(frozen=True, slots=True)
class IrDoWhileExpression(IrExpression):
    body: IrBlock
    condition: IrExpression
    fallback: IrExpression
    type: Type


@dataclass(frozen=True, slots=True)
class IrForExpression(IrExpression):
    source: IrExpression
    item: IrVariable
    body: IrBlock
    fallback: IrExpression
    type: Type


@dataclass(frozen=True, slots=True)
class IrCall(IrExpression):
    callee: IrExpression
    arguments: tuple[IrExpression, ...]
    type: Type
    task_outcomes: tuple[OutcomeType, ...] = ()


@dataclass(frozen=True, slots=True)
class IrArrayLiteral(IrExpression):
    elements: tuple[IrExpression, ...]
    type: Type


@dataclass(frozen=True, slots=True)
class IrStructLiteralField(IrNode):
    name: str | None
    value: IrExpression
    target_type: Type | None = None


@dataclass(frozen=True, slots=True)
class IrStructLiteral(IrExpression):
    fields: tuple[IrStructLiteralField, ...]
    type: Type


@dataclass(frozen=True, slots=True)
class IrSequence(IrExpression):
    expressions: tuple[IrExpression, ...]
    type: Type


@dataclass(frozen=True, slots=True)
class IrArrayBulkCall(IrExpression):
    callee: IrExpression
    array: IrExpression
    type: Type


@dataclass(frozen=True, slots=True)
class IrBulkMapCall(IrExpression):
    callee: IrExpression
    array: IrExpression
    mode: Literal["sync", "task"]
    type: Type
    outcomes: tuple[OutcomeType, ...] = ()


@dataclass(frozen=True, slots=True)
class IrTaskBulkCall(IrExpression):
    callee: IrExpression
    array: IrExpression
    type: Type
    task_outcomes: tuple[OutcomeType, ...] = ()


@dataclass(frozen=True, slots=True)
class IrMember(IrExpression):
    receiver: IrExpression
    member: str
    type: Type
    symbol: Symbol | None = None
    null_safe: bool = False
    task_outcomes: tuple[OutcomeType, ...] = ()
    field_ownership: str | None = None


@dataclass(frozen=True, slots=True)
class IrMemberBlock(IrExpression):
    receiver: IrExpression
    expressions: tuple[IrExpression, ...]
    type: Type


@dataclass(frozen=True, slots=True)
class IrIndex(IrExpression):
    receiver: IrExpression
    index: IrExpression
    type: Type
