"""Resolve lexical names and type references in Forge AST nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from forge_analysis import AnalysisResult, Diagnostic, Scope, Symbol, validate
from forge_parser import (
    AssignmentExpression,
    ArrayDestructuringDeclaration,
    ArrayLiteralExpression,
    BinaryExpression,
    BlockStatement,
    BorrowScopeStatement,
    BreakStatement,
    BulkArgumentPack,
    BulkCallExpression,
    CatchExpression,
    CallExpression,
    ClassDeclaration,
    ConditionalExpression,
    Declaration,
    DoWhileExpression,
    DoWhileStatement,
    EnumDeclaration,
    Expression,
    ExpressionStatement,
    ForStatement,
    ForExpression,
    ForwardExpression,
    FunctionDeclaration,
    GroupingExpression,
    IdentifierExpression,
    IfStatement,
    IndexExpression,
    InlineStructType,
    LiteralExpression,
    MemberBlockExpression,
    MemberExpression,
    MoveExpression,
    Parameter,
    PrintStatement,
    Program,
    ReturnStatement,
    SelfExpression,
    Statement,
    StructLiteralExpression,
    SwitchStatement,
    ThisExpression,
    TypeReference,
    UnaryExpression,
    UseDeclaration,
    UsesDeclaration,
    VariableDeclaration,
    WhileStatement,
    WhileExpression,
)
from forge_parser.ast import Node

BuiltinKind = Literal["builtin_type"]
SpecialKind = Literal["this", "self"]

_BUILTIN_TYPES = frozenset(
    {
        "Byte",
        "UByte",
        "Short",
        "UShort",
        "Int",
        "UInt",
        "Long",
        "ULong",
        "Float",
        "Double",
        "Bool",
        "String",
        "PatternMismatch",
        "Task",
        "TaskCollection",
        "Void",
        "byte",
        "ubyte",
        "short",
        "ushort",
        "int",
        "uint",
        "long",
        "ulong",
        "float",
        "double",
        "bool",
        "string",
        "task",
        "taskCollection",
        "void",
        "null",
    }
)
_BUILTIN_INTERFACES = frozenset({"Stringable"})


@dataclass(frozen=True, slots=True)
class BuiltinSymbol:
    """A compiler-provided type available without declaration or import."""

    name: str
    kind: BuiltinKind = "builtin_type"


@dataclass(frozen=True, slots=True)
class BuiltinInterfaceSymbol:
    """A compiler-provided interface available without declaration or import."""

    name: str
    kind: Literal["builtin_interface"] = "builtin_interface"


@dataclass(frozen=True, slots=True)
class SpecialSymbol:
    """A contextual receiver name such as ``this`` or ``self``."""

    name: str
    kind: SpecialKind
    node: ClassDeclaration | EnumDeclaration


ResolvedSymbol = Symbol | BuiltinSymbol | BuiltinInterfaceSymbol | SpecialSymbol


@dataclass(slots=True)
class ResolutionTable:
    """Resolved names keyed by AST node identity."""

    identifiers: dict[int, Symbol | BuiltinSymbol] = field(default_factory=dict)
    types: dict[int, Symbol | BuiltinSymbol | BuiltinInterfaceSymbol | SpecialSymbol] = field(default_factory=dict)
    specials: dict[int, SpecialSymbol] = field(default_factory=dict)

    def symbol_for(self, node: Node) -> ResolvedSymbol | None:
        """Return the resolved target for an identifier, type, ``this`` or ``self``."""

        node_id = id(node)
        return (
            self.identifiers.get(node_id)
            or self.types.get(node_id)
            or self.specials.get(node_id)
        )


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """The result of lexical name resolution."""

    program: Program
    analysis: AnalysisResult
    diagnostics: tuple[Diagnostic, ...]
    resolutions: ResolutionTable

    @property
    def ok(self) -> bool:
        return self.analysis.ok and not any(
            diagnostic.severity == "error" for diagnostic in self.diagnostics
        )


class NameResolutionError(Exception):
    """Raised when one or more names cannot be resolved."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        first = diagnostics[0]
        super().__init__(f"{first.message} at {first.location.format()}")


def resolve(
    program_or_analysis: Program | AnalysisResult,
    *,
    raise_on_error: bool = True,
    imports: dict[str, Symbol] | None = None,
) -> ResolutionResult:
    """Resolve names for *program_or_analysis*.

    Pass a :class:`Program` to run validation first, or an existing
    :class:`AnalysisResult` to reuse validation annotations.
    """

    analysis = (
        validate(program_or_analysis, raise_on_error=False)
        if isinstance(program_or_analysis, Program)
        else program_or_analysis
    )
    resolver = _Resolver(analysis, imports or {})
    result = resolver.run()
    if raise_on_error and not result.ok:
        diagnostics = tuple(
            diagnostic
            for diagnostic in (*analysis.diagnostics, *result.diagnostics)
            if diagnostic.severity == "error"
        )
        raise NameResolutionError(diagnostics)
    return result


class _Resolver:
    def __init__(self, analysis: AnalysisResult, imports: dict[str, Symbol]) -> None:
        self.analysis = analysis
        self.program = analysis.program
        self.imports = imports
        self.diagnostics: list[Diagnostic] = []
        self.resolutions = ResolutionTable()
        self._class_stack: list[ClassDeclaration | EnumDeclaration] = []
        self._member_receiver_stack: list[int] = []

    def run(self) -> ResolutionResult:
        for declaration in self.program.declarations:
            self._visit_declaration_or_statement(declaration)
        return ResolutionResult(
            self.program,
            self.analysis,
            tuple(self.diagnostics),
            self.resolutions,
        )

    def _scope_for(self, node: Node) -> Scope:
        scope = self.analysis.annotations.scope_for(node)
        if scope is None:
            raise RuntimeError(f"Missing scope annotation for {type(node).__name__}")
        return scope

    def _error(self, message: str, node: Node) -> None:
        self.diagnostics.append(Diagnostic(message, node.location))

    def _visit_declaration_or_statement(self, node: Declaration | Statement) -> None:
        if isinstance(node, Declaration):
            self._visit_declaration(node)
        else:
            self._visit_statement(node)

    def _visit_declaration(self, declaration: Declaration) -> None:
        if isinstance(declaration, ClassDeclaration):
            self._visit_class(declaration)
        elif isinstance(declaration, EnumDeclaration):
            self._visit_enum(declaration)
        elif isinstance(declaration, FunctionDeclaration):
            self._visit_function(declaration)
        elif isinstance(declaration, VariableDeclaration):
            self._visit_variable(declaration)
        elif isinstance(declaration, ArrayDestructuringDeclaration):
            self._visit_array_destructuring(declaration)
        elif isinstance(declaration, UseDeclaration):
            return
        elif isinstance(declaration, UsesDeclaration):
            for trait in declaration.traits:
                self._visit_type_reference(trait)

    def _visit_class(self, declaration: ClassDeclaration) -> None:
        self._class_stack.append(declaration)
        for interface in declaration.implements:
            self._visit_type_reference(interface)
        for trait in declaration.uses:
            self._visit_type_reference(trait)
        for member in declaration.members:
            self._visit_declaration_or_statement(member)
        self._class_stack.pop()

    def _visit_enum(self, declaration: EnumDeclaration) -> None:
        self._class_stack.append(declaration)
        if isinstance(declaration.value_type, InlineStructType):
            for field in declaration.value_type.fields:
                self._visit_variable(field)
        elif declaration.value_type is not None:
            self._visit_type_reference(declaration.value_type)
        for variant in declaration.variants:
            if variant.value is not None:
                self._visit_expression(variant.value)
        for member in declaration.members:
            self._visit_declaration_or_statement(member)
        self._class_stack.pop()

    def _visit_function(self, declaration: FunctionDeclaration) -> None:
        for parameter in declaration.parameters:
            self._visit_parameter(parameter)
        if declaration.return_type is not None:
            self._visit_type_reference(declaration.return_type)
        for outcome in declaration.outcomes:
            self._visit_type_reference(outcome.type)
        if isinstance(declaration.body, BlockStatement):
            self._visit_statement(declaration.body)
        else:
            self._visit_expression(declaration.body)

    def _visit_parameter(self, parameter: Parameter) -> None:
        self._visit_type_reference(parameter.type)

    def _visit_variable(self, declaration: VariableDeclaration) -> None:
        if declaration.type is not None:
            self._visit_type_reference(declaration.type)
        if declaration.initializer is not None:
            self._visit_expression(declaration.initializer)

    def _visit_array_destructuring(
        self, declaration: ArrayDestructuringDeclaration
    ) -> None:
        self._visit_expression(declaration.initializer)

    def _visit_type_reference(self, type_reference: TypeReference) -> None:
        target = self._resolve_type(type_reference)
        if target is None:
            if type_reference.name == "self":
                self._error(
                    "Type 'self' can only be used inside a class",
                    type_reference,
                )
            else:
                self._error(f"Unknown type '{type_reference.name}'", type_reference)
            return
        self.resolutions.types[id(type_reference)] = target
        for argument in type_reference.arguments:
            self._visit_type_reference(argument)

    def _visit_statement(self, statement: Statement) -> None:
        if isinstance(statement, BlockStatement):
            for child in statement.statements:
                self._visit_declaration_or_statement(child)
        elif isinstance(statement, PrintStatement):
            self._visit_expression(statement.expression)
        elif isinstance(statement, ReturnStatement):
            if statement.expression is not None:
                self._visit_expression(statement.expression)
        elif isinstance(statement, BreakStatement):
            if statement.expression is not None:
                self._visit_expression(statement.expression)
        elif isinstance(statement, IfStatement):
            self._visit_expression(statement.condition)
            self._visit_statement(statement.then_branch)
            if statement.else_branch is not None:
                self._visit_statement(statement.else_branch)
        elif isinstance(statement, SwitchStatement):
            self._visit_expression(statement.expression)
            for arm in statement.arms:
                if arm.pattern is not None:
                    self._visit_expression(arm.pattern)
                self._visit_statement(arm.body)
        elif isinstance(statement, WhileStatement):
            self._visit_expression(statement.condition)
            self._visit_statement(statement.body)
        elif isinstance(statement, DoWhileStatement):
            self._visit_statement(statement.body)
            self._visit_expression(statement.condition)
        elif isinstance(statement, ForStatement):
            self._visit_expression(statement.source)
            self._visit_statement(statement.body)
        elif isinstance(statement, BorrowScopeStatement):
            self._visit_expression(statement.source)
            self._visit_statement(statement.body)
        elif isinstance(statement, ExpressionStatement):
            self._visit_expression(statement.expression)

    def _visit_expression(self, expression: Expression) -> None:
        if isinstance(expression, LiteralExpression):
            return
        if isinstance(expression, IdentifierExpression):
            self._resolve_identifier(expression)
        elif isinstance(expression, ThisExpression):
            self._resolve_special(expression, "this")
        elif isinstance(expression, SelfExpression):
            self._resolve_special(expression, "self")
        elif isinstance(expression, GroupingExpression):
            self._visit_expression(expression.expression)
        elif isinstance(expression, ForwardExpression):
            self._visit_expression(expression.expression)
        elif isinstance(expression, CatchExpression):
            self._visit_expression(expression.expression)
            for handler in expression.handlers:
                self._visit_type_reference(handler.type)
                if isinstance(handler.expression, BlockStatement):
                    self._visit_statement(handler.expression)
                else:
                    self._visit_expression(handler.expression)
        elif isinstance(expression, UnaryExpression):
            self._visit_expression(expression.operand)
        elif isinstance(expression, MoveExpression):
            self._visit_expression(expression.expression)
        elif isinstance(expression, BinaryExpression):
            self._visit_expression(expression.left)
            self._visit_expression(expression.right)
        elif isinstance(expression, AssignmentExpression):
            self._visit_expression(expression.target)
            self._visit_expression(expression.value)
        elif isinstance(expression, ConditionalExpression):
            self._visit_expression(expression.condition)
            self._visit_expression(expression.then_expression)
            self._visit_expression(expression.else_expression)
        elif isinstance(expression, CallExpression):
            self._visit_expression(expression.callee)
            for argument in expression.arguments:
                self._visit_expression(argument)
        elif isinstance(expression, ArrayLiteralExpression):
            for element in expression.elements:
                self._visit_expression(element)
        elif isinstance(expression, StructLiteralExpression):
            for field in expression.fields:
                self._visit_expression(field.value)
        elif isinstance(expression, BulkArgumentPack):
            for argument in expression.arguments:
                self._visit_expression(argument)
        elif isinstance(expression, BulkCallExpression):
            self._visit_expression(expression.callee)
            for argument in expression.arguments:
                self._visit_expression(argument)
        elif isinstance(expression, MemberExpression):
            self._member_receiver_stack.append(id(expression.receiver))
            try:
                self._visit_expression(expression.receiver)
            finally:
                self._member_receiver_stack.pop()
        elif isinstance(expression, MemberBlockExpression):
            self._visit_expression(expression.receiver)
            for child in expression.expressions:
                self._visit_expression(child)
        elif isinstance(expression, IndexExpression):
            self._visit_expression(expression.receiver)
            self._visit_expression(expression.index)
        elif isinstance(expression, WhileExpression):
            self._visit_expression(expression.condition)
            self._visit_statement(expression.body)
            if expression.fallback is not None:
                self._visit_expression(expression.fallback)
        elif isinstance(expression, DoWhileExpression):
            self._visit_statement(expression.body)
            self._visit_expression(expression.condition)
            if expression.fallback is not None:
                self._visit_expression(expression.fallback)
        elif isinstance(expression, ForExpression):
            self._visit_expression(expression.source)
            self._visit_statement(expression.body)
            if expression.fallback is not None:
                self._visit_expression(expression.fallback)

    def _resolve_identifier(self, expression: IdentifierExpression) -> None:
        symbol = self._lookup(expression.name, self._scope_for(expression))
        if (
            symbol is None
            and expression.name in _BUILTIN_TYPES
            and self._member_receiver_stack
            and self._member_receiver_stack[-1] == id(expression)
        ):
            self.resolutions.identifiers[id(expression)] = BuiltinSymbol(expression.name)
            return
        if symbol is None:
            self._error(f"Unknown name '{expression.name}'", expression)
            return
        self.resolutions.identifiers[id(expression)] = symbol

    def _resolve_special(
        self, expression: ThisExpression | SelfExpression, kind: SpecialKind
    ) -> None:
        if not self._class_stack:
            return
        self.resolutions.specials[id(expression)] = SpecialSymbol(
            kind,
            kind,
            self._class_stack[-1],
        )

    def _resolve_type(
        self, type_reference: TypeReference
    ) -> Symbol | BuiltinSymbol | BuiltinInterfaceSymbol | SpecialSymbol | None:
        if type_reference.name in _BUILTIN_TYPES:
            return BuiltinSymbol(type_reference.name)
        if type_reference.name in _BUILTIN_INTERFACES:
            return BuiltinInterfaceSymbol(type_reference.name)
        if type_reference.name == "self":
            if not self._class_stack:
                return None
            return SpecialSymbol("self", "self", self._class_stack[-1])
        if "." in type_reference.name:
            return None

        symbol = self._lookup(type_reference.name, self._scope_for(type_reference))
        if symbol is None or symbol.kind not in {"class", "trait", "interface", "struct", "enum"}:
            return None
        return symbol

    def _lookup(self, name: str, scope: Scope) -> Symbol | None:
        current: Scope | None = scope
        while current is not None:
            symbol = current.symbols.get(name)
            if symbol is not None:
                return symbol
            current = current.parent
        return self.imports.get(name)
