"""Abstract syntax tree nodes for parsed Forge source code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from forge_lexer import SourceLocation, TokenKind


@dataclass(frozen=True, slots=True)
class Node:
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class TypeReference(Node):
    name: str
    array_depth: int = 0
    nullable: bool = False
    array_dimensions: tuple["Expression | None", ...] = ()
    arguments: tuple["TypeReference", ...] = ()


@dataclass(frozen=True, slots=True)
class OutcomeDeclaration(Node):
    type: TypeReference
    required: bool


@dataclass(frozen=True, slots=True)
class Parameter(Node):
    name: str
    type: TypeReference
    ownership: Literal["borrow", "take"] = "borrow"
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TypeParameter(Node):
    name: str
    constraint: str | None = None


@dataclass(frozen=True, slots=True)
class CatchHandler(Node):
    name: str
    type: TypeReference
    expression: "Expression | BlockStatement"


@dataclass(frozen=True, slots=True)
class Program(Node):
    declarations: tuple["Declaration | Statement", ...]
    attributes: tuple[str, ...] = ()
    source_name: str | None = None


class Declaration(Node):
    pass


@dataclass(frozen=True, slots=True)
class UseDeclaration(Declaration):
    path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImplementsDeclaration(Declaration):
    interfaces: tuple[TypeReference, ...]


@dataclass(frozen=True, slots=True)
class UsesDeclaration(Declaration):
    traits: tuple[TypeReference, ...]


@dataclass(frozen=True, slots=True)
class ClassDeclaration(Declaration):
    name: str | None
    members: tuple["Declaration | Statement", ...]
    modifiers: tuple[str, ...] = ()
    braced_body: bool = False
    kind: Literal["class", "trait", "interface", "struct"] = "class"
    implements: tuple[TypeReference, ...] = ()
    uses: tuple[TypeReference, ...] = ()
    type_parameters: tuple[TypeParameter, ...] = ()


@dataclass(frozen=True, slots=True)
class InlineStructType(Node):
    fields: tuple["VariableDeclaration", ...]


@dataclass(frozen=True, slots=True)
class EnumVariant(Node):
    name: str
    value: "Expression | None" = None


@dataclass(frozen=True, slots=True)
class EnumDeclaration(Declaration):
    name: str | None
    variants: tuple[EnumVariant, ...]
    value_type: TypeReference | InlineStructType | None = None
    members: tuple["Declaration | Statement", ...] = ()
    modifiers: tuple[str, ...] = ()
    braced_body: bool = True


@dataclass(frozen=True, slots=True)
class FunctionDeclaration(Declaration):
    name: str
    parameters: tuple[Parameter, ...]
    return_type: TypeReference | None
    outcomes: tuple[OutcomeDeclaration, ...]
    body: "BlockStatement | Expression | None"
    modifiers: tuple[str, ...] = ()
    kind: str = "func"
    native_name: str | None = None
    type_parameters: tuple[TypeParameter, ...] = ()
    return_ownership: Literal["borrow", "take"] = "take"


@dataclass(frozen=True, slots=True)
class VariableDeclaration(Declaration):
    name: str
    initializer: "Expression | None"
    mutable: bool = False
    type: TypeReference | None = None
    modifiers: tuple[str, ...] = ()
    field_ownership: Literal["borrow", "take"] | None = None


@dataclass(frozen=True, slots=True)
class ArrayDestructuringDeclaration(Declaration):
    bindings: tuple[VariableDeclaration, ...]
    initializer: "Expression"


class Statement(Node):
    pass


@dataclass(frozen=True, slots=True)
class BlockStatement(Statement):
    statements: tuple["Statement | Declaration", ...]


@dataclass(frozen=True, slots=True)
class PrintStatement(Statement):
    expression: "Expression"


@dataclass(frozen=True, slots=True)
class ReturnStatement(Statement):
    expression: "Expression | None"


@dataclass(frozen=True, slots=True)
class BreakStatement(Statement):
    expression: "Expression | None"


@dataclass(frozen=True, slots=True)
class IfStatement(Statement):
    condition: "Expression"
    then_branch: BlockStatement
    else_branch: "BlockStatement | IfStatement | None" = None


@dataclass(frozen=True, slots=True)
class SwitchArm(Node):
    pattern: "Expression | None"
    body: "BlockStatement | Statement"


@dataclass(frozen=True, slots=True)
class SwitchStatement(Statement):
    expression: "Expression"
    arms: tuple[SwitchArm, ...]


@dataclass(frozen=True, slots=True)
class WhileStatement(Statement):
    condition: "Expression"
    body: BlockStatement


@dataclass(frozen=True, slots=True)
class DoWhileStatement(Statement):
    body: BlockStatement
    condition: "Expression"


@dataclass(frozen=True, slots=True)
class ForStatement(Statement):
    source: "Expression"
    item: VariableDeclaration
    body: BlockStatement


@dataclass(frozen=True, slots=True)
class BorrowScopeStatement(Statement):
    source: "Expression"
    binding: VariableDeclaration
    body: BlockStatement


@dataclass(frozen=True, slots=True)
class ExpressionStatement(Statement):
    expression: "Expression"


class Expression(Node):
    pass


@dataclass(frozen=True, slots=True)
class WhileExpression(Expression):
    condition: "Expression"
    body: BlockStatement
    fallback: "Expression | None" = None


@dataclass(frozen=True, slots=True)
class DoWhileExpression(Expression):
    body: BlockStatement
    condition: "Expression"
    fallback: "Expression | None" = None


@dataclass(frozen=True, slots=True)
class ForExpression(Expression):
    source: "Expression"
    item: VariableDeclaration
    body: BlockStatement
    fallback: "Expression | None" = None


@dataclass(frozen=True, slots=True)
class LiteralExpression(Expression):
    value: Any


@dataclass(frozen=True, slots=True)
class IdentifierExpression(Expression):
    name: str


@dataclass(frozen=True, slots=True)
class ThisExpression(Expression):
    pass


@dataclass(frozen=True, slots=True)
class SelfExpression(Expression):
    pass


@dataclass(frozen=True, slots=True)
class GroupingExpression(Expression):
    expression: Expression


@dataclass(frozen=True, slots=True)
class UnaryExpression(Expression):
    operator: TokenKind
    operand: Expression


@dataclass(frozen=True, slots=True)
class MoveExpression(Expression):
    expression: Expression


@dataclass(frozen=True, slots=True)
class ForwardExpression(Expression):
    expression: Expression


@dataclass(frozen=True, slots=True)
class CatchExpression(Expression):
    expression: Expression
    handlers: tuple[CatchHandler, ...]


@dataclass(frozen=True, slots=True)
class BinaryExpression(Expression):
    left: Expression
    operator: TokenKind
    right: Expression


@dataclass(frozen=True, slots=True)
class AssignmentExpression(Expression):
    target: Expression
    value: Expression
    operator: TokenKind = TokenKind.EQUAL


@dataclass(frozen=True, slots=True)
class ConditionalExpression(Expression):
    condition: Expression
    then_expression: Expression
    else_expression: Expression


@dataclass(frozen=True, slots=True)
class CallExpression(Expression):
    callee: Expression
    arguments: tuple[Expression, ...]
    type_arguments: tuple[TypeReference, ...] = ()


@dataclass(frozen=True, slots=True)
class BulkArgumentPack(Expression):
    arguments: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class BulkCallExpression(Expression):
    callee: Expression
    arguments: tuple[Expression, ...]
    generator: bool = False
    task: bool = False


@dataclass(frozen=True, slots=True)
class ArrayLiteralExpression(Expression):
    elements: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class StructLiteralField(Node):
    name: str | None
    value: Expression


@dataclass(frozen=True, slots=True)
class StructLiteralExpression(Expression):
    fields: tuple[StructLiteralField, ...]


@dataclass(frozen=True, slots=True)
class MemberExpression(Expression):
    receiver: Expression
    member: str
    null_safe: bool = False


@dataclass(frozen=True, slots=True)
class MemberBlockExpression(Expression):
    receiver: Expression
    expressions: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class IndexExpression(Expression):
    receiver: Expression
    index: Expression
