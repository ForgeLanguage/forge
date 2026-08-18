"""Structural validation and side-table annotations for Forge AST nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from forge_lexer import SourceLocation, TokenKind
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
    GenericTypeExpression,
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

Severity = Literal["error", "warning"]
ScopeKind = Literal["module", "class", "function", "block"]
SymbolKind = Literal[
    "class",
    "trait",
    "interface",
    "struct",
    "enum",
    "function",
    "variable",
    "parameter",
    "type_parameter",
]

_VISIBILITY_MODIFIERS = frozenset({"public", "internal", "private"})
_PROGRAM_ATTRIBUTES = frozenset({"multidef"})


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A validation diagnostic tied to an original source location."""

    message: str
    location: SourceLocation
    severity: Severity = "error"


@dataclass(slots=True)
class Symbol:
    """A declared name in a lexical scope."""

    name: str
    kind: SymbolKind
    node: Node
    scope: "Scope"
    location: SourceLocation
    mutable: bool = False


@dataclass(slots=True)
class Scope:
    """A lexical scope discovered during AST validation."""

    id: int
    kind: ScopeKind
    owner: Node
    parent: "Scope | None" = None
    symbols: dict[str, Symbol] = field(default_factory=dict)
    overloads: dict[str, tuple[Symbol, ...]] = field(default_factory=dict)


@dataclass(slots=True)
class AnnotationTable:
    """Side-table annotations keyed by AST node identity."""

    root_scope: Scope
    node_scopes: dict[int, Scope] = field(default_factory=dict)
    declaration_symbols: dict[int, Symbol] = field(default_factory=dict)

    def scope_for(self, node: Node) -> Scope | None:
        """Return the lexical scope associated with *node*, if one was recorded."""

        return self.node_scopes.get(id(node))

    def symbol_for(self, node: Node) -> Symbol | None:
        """Return the declaration symbol associated with *node*, if any."""

        return self.declaration_symbols.get(id(node))


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """The result of validating and annotating a parsed AST."""

    program: Program
    diagnostics: tuple[Diagnostic, ...]
    annotations: AnnotationTable

    @property
    def ok(self) -> bool:
        return not any(diagnostic.severity == "error" for diagnostic in self.diagnostics)


class ValidationError(Exception):
    """Raised when validation finds one or more errors."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        first = diagnostics[0]
        super().__init__(f"{first.message} at {first.location.format()}")


def validate(program: Program, *, raise_on_error: bool = True) -> AnalysisResult:
    """Validate *program* and return side-table annotations.

    The input AST is never mutated. Diagnostics and annotations preserve original
    node locations so later phases can report errors against parsed source spans.
    """

    validator = _Validator(program)
    result = validator.run()
    if raise_on_error and not result.ok:
        raise ValidationError(result.diagnostics)
    return result


def analyze(program: Program, *, raise_on_error: bool = True) -> AnalysisResult:
    """Alias for :func:`validate` for callers that think in compiler phases."""

    return validate(program, raise_on_error=raise_on_error)


class _Validator:
    def __init__(self, program: Program) -> None:
        self.program = program
        self.diagnostics: list[Diagnostic] = []
        self._next_scope_id = 0
        root_scope = self._new_scope("module", program, None)
        self.annotations = AnnotationTable(root_scope)
        self._scope_stack: list[Scope] = [root_scope]
        self._class_stack: list[ClassDeclaration | EnumDeclaration] = []
        self._function_stack: list[FunctionDeclaration] = []
        self._loop_stack: list[Node] = []

    def run(self) -> AnalysisResult:
        self._annotate(self.program, self.annotations.root_scope)
        self._validate_program_attributes()
        self._validate_top_level_types()
        for declaration in self.program.declarations:
            self._visit_declaration_or_statement(declaration)
        return AnalysisResult(
            self.program,
            tuple(self.diagnostics),
            self.annotations,
        )

    @property
    def _scope(self) -> Scope:
        return self._scope_stack[-1]

    def _new_scope(self, kind: ScopeKind, owner: Node, parent: Scope | None) -> Scope:
        scope = Scope(self._next_scope_id, kind, owner, parent)
        self._next_scope_id += 1
        return scope

    def _push_scope(self, kind: ScopeKind, owner: Node) -> Scope:
        scope = self._new_scope(kind, owner, self._scope)
        self._scope_stack.append(scope)
        self._annotate(owner, scope)
        return scope

    def _pop_scope(self) -> None:
        self._scope_stack.pop()

    def _annotate(self, node: Node, scope: Scope) -> None:
        self.annotations.node_scopes[id(node)] = scope

    def _error(self, message: str, location: SourceLocation) -> None:
        self.diagnostics.append(Diagnostic(message, location))

    def _visit_declaration_or_statement(self, node: Declaration | Statement) -> None:
        if isinstance(node, Declaration):
            self._visit_declaration(node)
        else:
            self._visit_statement(node)

    def _validate_program_attributes(self) -> None:
        seen: set[str] = set()
        for attribute in self.program.attributes:
            if attribute in seen:
                self._error(f"Duplicate program attribute '@{attribute}'", self.program.location)
            seen.add(attribute)
            if attribute not in _PROGRAM_ATTRIBUTES:
                self._error(f"Unknown program attribute '@{attribute}'", self.program.location)

    def _validate_top_level_types(self) -> None:
        top_level_types = [
            declaration
            for declaration in self.program.declarations
            if isinstance(declaration, ClassDeclaration)
            or isinstance(declaration, EnumDeclaration)
        ]
        if "multidef" in self.program.attributes:
            for declaration in top_level_types:
                if declaration.name is None:
                    self._error(
                        "Top-level types must have explicit names in @multidef files",
                        declaration.location,
                    )
            return

        if len(top_level_types) > 1:
            self._error("Multiple top-level types require @multidef", top_level_types[1].location)

    def _visit_declaration(self, declaration: Declaration) -> None:
        self._annotate(declaration, self._scope)
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
            self._visit_use(declaration)
        elif isinstance(declaration, UsesDeclaration):
            self._visit_uses(declaration)
        else:
            self._error(
                f"Unsupported declaration node {type(declaration).__name__}",
                declaration.location,
            )

    def _visit_use(self, declaration: UseDeclaration) -> None:
        if not declaration.path:
            self._error("Expected imported name", declaration.location)

    def _visit_uses(self, declaration: UsesDeclaration) -> None:
        for trait in declaration.traits:
            self._visit_type_reference(trait)

    def _visit_class(self, declaration: ClassDeclaration) -> None:
        self._validate_modifiers(declaration.modifiers, declaration.location)
        if declaration.name is not None:
            self._declare(declaration.name, declaration.kind, declaration, declaration.location)

        self._class_stack.append(declaration)
        self._push_scope("class", declaration)
        for parameter in declaration.type_parameters:
            self._declare(parameter.name, "type_parameter", parameter, parameter.location)
        for interface in declaration.implements:
            self._visit_type_reference(interface)
        for trait in declaration.uses:
            self._visit_type_reference(trait)
        for member in declaration.members:
            self._visit_declaration_or_statement(member)
        self._pop_scope()
        self._class_stack.pop()

    def _visit_enum(self, declaration: EnumDeclaration) -> None:
        self._validate_modifiers(declaration.modifiers, declaration.location)
        if declaration.name is not None:
            self._declare(declaration.name, "enum", declaration, declaration.location)

        self._class_stack.append(declaration)  # enum methods use the same this/self rules
        self._push_scope("class", declaration)
        if isinstance(declaration.value_type, InlineStructType):
            self._visit_inline_struct_type(declaration.value_type)
        elif declaration.value_type is not None:
            self._visit_type_reference(declaration.value_type)
        for variant in declaration.variants:
            self._annotate(variant, self._scope)
            self._declare(variant.name, "variable", variant, variant.location)
            if variant.value is not None:
                self._visit_expression(variant.value)
        for member in declaration.members:
            self._visit_declaration_or_statement(member)
        self._pop_scope()
        self._class_stack.pop()

    def _visit_inline_struct_type(self, value_type: InlineStructType) -> None:
        self._annotate(value_type, self._scope)
        for field in value_type.fields:
            self._visit_variable(field)

    def _visit_function(self, declaration: FunctionDeclaration) -> None:
        self._validate_modifiers(declaration.modifiers, declaration.location)
        self._declare(declaration.name, "function", declaration, declaration.location)
        if "native" in declaration.modifiers and declaration.native_name is None:
            self._error("Native function requires a C symbol binding", declaration.location)

        self._function_stack.append(declaration)
        self._push_scope("function", declaration)
        for parameter in declaration.type_parameters:
            self._declare(parameter.name, "type_parameter", parameter, parameter.location)
        for parameter in declaration.parameters:
            self._visit_parameter(parameter)
        if declaration.return_type is not None:
            self._visit_type_reference(declaration.return_type)
        for outcome in declaration.outcomes:
            self._annotate(outcome, self._scope)
            self._visit_type_reference(outcome.type)
        if isinstance(declaration.body, BlockStatement):
            self._visit_block(declaration.body)
        elif declaration.body is not None:
            self._visit_expression(declaration.body)
        elif (
            declaration.native_name is None
            and (not self._class_stack or getattr(self._class_stack[-1], "kind", None) != "interface")
        ):
            self._error("Function declaration requires a body", declaration.location)
        self._pop_scope()
        self._function_stack.pop()

    def _visit_parameter(self, parameter: Parameter) -> None:
        self._annotate(parameter, self._scope)
        if parameter.modifiers:
            if not self._function_stack or self._function_stack[-1].kind != "new":
                self._error(
                    "Parameter modifiers are only supported in constructors",
                    parameter.location,
                )
            self._validate_modifiers(parameter.modifiers, parameter.location)
        self._declare(parameter.name, "parameter", parameter, parameter.location)
        self._visit_type_reference(parameter.type)

    def _visit_variable(self, declaration: VariableDeclaration) -> None:
        self._validate_modifiers(declaration.modifiers, declaration.location)
        self._declare(
            declaration.name,
            "variable",
            declaration,
            declaration.location,
            mutable=declaration.mutable,
        )
        if declaration.type is not None:
            self._visit_type_reference(declaration.type)
        if declaration.initializer is not None:
            self._visit_expression(declaration.initializer)

    def _visit_array_destructuring(
        self, declaration: ArrayDestructuringDeclaration
    ) -> None:
        if self._scope.kind not in {"function", "block"}:
            self._error(
                "Array destructuring is only supported for local declarations",
                declaration.location,
            )
        self._visit_expression(declaration.initializer)
        for binding in declaration.bindings:
            self._annotate(binding, self._scope)
            self._visit_variable(binding)

    def _visit_type_reference(self, type_reference: TypeReference) -> None:
        self._annotate(type_reference, self._scope)
        if not type_reference.name:
            self._error("Expected type name", type_reference.location)
        if type_reference.array_depth < 0:
            self._error("Array type depth cannot be negative", type_reference.location)
        for argument in type_reference.arguments:
            self._visit_type_reference(argument)

    def _visit_statement(self, statement: Statement) -> None:
        self._annotate(statement, self._scope)
        if isinstance(statement, BlockStatement):
            self._push_scope("block", statement)
            for child in statement.statements:
                self._visit_declaration_or_statement(child)
            self._pop_scope()
        elif isinstance(statement, PrintStatement):
            self._visit_expression(statement.expression)
        elif isinstance(statement, ReturnStatement):
            if not self._function_stack:
                self._error("'return' can only be used inside a function", statement.location)
            if statement.expression is not None:
                self._visit_expression(statement.expression)
        elif isinstance(statement, BreakStatement):
            if not self._loop_stack:
                self._error("'break' can only be used inside a loop", statement.location)
            if statement.expression is not None:
                self._visit_expression(statement.expression)
        elif isinstance(statement, IfStatement):
            self._visit_expression(statement.condition)
            self._visit_block(statement.then_branch)
            if isinstance(statement.else_branch, BlockStatement):
                self._visit_block(statement.else_branch)
            elif isinstance(statement.else_branch, IfStatement):
                self._visit_statement(statement.else_branch)
        elif isinstance(statement, SwitchStatement):
            self._visit_expression(statement.expression)
            for arm in statement.arms:
                if arm.pattern is not None:
                    self._visit_expression(arm.pattern)
                if isinstance(arm.body, BlockStatement):
                    self._visit_block(arm.body)
                else:
                    self._visit_statement(arm.body)
        elif isinstance(statement, WhileStatement):
            self._visit_expression(statement.condition)
            self._loop_stack.append(statement)
            self._visit_block(statement.body)
            self._loop_stack.pop()
        elif isinstance(statement, DoWhileStatement):
            self._loop_stack.append(statement)
            self._visit_block(statement.body)
            self._loop_stack.pop()
            self._visit_expression(statement.condition)
        elif isinstance(statement, ForStatement):
            self._visit_expression(statement.source)
            self._loop_stack.append(statement)
            self._push_scope("block", statement.body)
            self._visit_variable(statement.item)
            for child in statement.body.statements:
                self._visit_declaration_or_statement(child)
            self._pop_scope()
            self._loop_stack.pop()
        elif isinstance(statement, BorrowScopeStatement):
            self._visit_expression(statement.source)
            self._push_scope("block", statement.body)
            self._visit_variable(statement.binding)
            for child in statement.body.statements:
                self._visit_declaration_or_statement(child)
            self._pop_scope()
        elif isinstance(statement, ExpressionStatement):
            self._visit_expression(statement.expression)
        else:
            self._error(
                f"Unsupported statement node {type(statement).__name__}",
                statement.location,
            )

    def _visit_block(self, block: BlockStatement) -> None:
        self._visit_statement(block)

    def _visit_expression(self, expression: Expression) -> None:
        self._annotate(expression, self._scope)
        if isinstance(expression, LiteralExpression):
            return
        if isinstance(expression, IdentifierExpression):
            return
        if isinstance(expression, ThisExpression):
            if not self._class_stack:
                self._error("'this' can only be used inside a class", expression.location)
            return
        if isinstance(expression, SelfExpression):
            if not self._class_stack:
                self._error("'self' can only be used inside a class", expression.location)
            return
        if isinstance(expression, GroupingExpression):
            self._visit_expression(expression.expression)
        elif isinstance(expression, GenericTypeExpression):
            self._visit_expression(expression.receiver)
            for argument in expression.arguments:
                self._visit_type_reference(argument)
        elif isinstance(expression, ForwardExpression):
            if not self._function_stack:
                self._error("'forward' can only be used inside a function", expression.location)
            self._visit_expression(expression.expression)
        elif isinstance(expression, CatchExpression):
            self._visit_expression(expression.expression)
            for handler in expression.handlers:
                self._push_scope("block", handler)
                self._declare(handler.name, "parameter", handler, handler.location)
                self._visit_type_reference(handler.type)
                if isinstance(handler.expression, BlockStatement):
                    self._visit_statement(handler.expression)
                else:
                    self._visit_expression(handler.expression)
                self._pop_scope()
        elif isinstance(expression, UnaryExpression):
            if expression.operator is TokenKind.AWAIT and not self._in_async_function():
                self._error(
                    "'await' can only be used inside an async function",
                    expression.location,
                )
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
            for type_argument in expression.type_arguments:
                self._visit_type_reference(type_argument)
            self._visit_expression(expression.callee)
            for argument in expression.arguments:
                self._visit_expression(argument)
        elif isinstance(expression, ArrayLiteralExpression):
            for element in expression.elements:
                self._visit_expression(element)
        elif isinstance(expression, StructLiteralExpression):
            for field in expression.fields:
                self._annotate(field, self._scope)
                self._visit_expression(field.value)
        elif isinstance(expression, BulkArgumentPack):
            for argument in expression.arguments:
                self._visit_expression(argument)
        elif isinstance(expression, BulkCallExpression):
            self._visit_expression(expression.callee)
            for argument in expression.arguments:
                self._visit_expression(argument)
        elif isinstance(expression, MemberExpression):
            self._visit_expression(expression.receiver)
        elif isinstance(expression, MemberBlockExpression):
            for child in expression.expressions:
                self._visit_expression(child)
        elif isinstance(expression, IndexExpression):
            self._visit_expression(expression.receiver)
            self._visit_expression(expression.index)
        elif isinstance(expression, WhileExpression):
            self._visit_expression(expression.condition)
            self._loop_stack.append(expression)
            self._visit_block(expression.body)
            self._loop_stack.pop()
            if expression.fallback is not None:
                self._visit_expression(expression.fallback)
        elif isinstance(expression, DoWhileExpression):
            self._loop_stack.append(expression)
            self._visit_block(expression.body)
            self._loop_stack.pop()
            self._visit_expression(expression.condition)
            if expression.fallback is not None:
                self._visit_expression(expression.fallback)
        elif isinstance(expression, ForExpression):
            self._visit_expression(expression.source)
            self._loop_stack.append(expression)
            self._push_scope("block", expression.body)
            self._visit_variable(expression.item)
            for child in expression.body.statements:
                self._visit_declaration_or_statement(child)
            self._pop_scope()
            self._loop_stack.pop()
            if expression.fallback is not None:
                self._visit_expression(expression.fallback)
        else:
            self._error(
                f"Unsupported expression node {type(expression).__name__}",
                expression.location,
            )

    def _validate_modifiers(
        self, modifiers: tuple[str, ...], location: SourceLocation
    ) -> None:
        seen: set[str] = set()
        visibility_modifiers: list[str] = []
        for modifier in modifiers:
            if modifier in seen:
                self._error(f"Duplicate modifier '{modifier}'", location)
            seen.add(modifier)
            if modifier in _VISIBILITY_MODIFIERS:
                visibility_modifiers.append(modifier)

        if len(visibility_modifiers) > 1:
            self._error("Only one visibility modifier is allowed", location)

    def _declare(
        self,
        name: str,
        kind: SymbolKind,
        node: Node,
        location: SourceLocation,
        *,
        mutable: bool = False,
    ) -> Symbol | None:
        if name in self._scope.symbols:
            original = self._scope.symbols[name]
            if self._can_overload(name, kind, node, original):
                symbol = Symbol(name, kind, node, self._scope, location, mutable)
                self._scope.overloads[name] = (*self._scope.overloads[name], symbol)
                self.annotations.declaration_symbols[id(node)] = symbol
                return symbol
            self._error(
                f"Duplicate {kind} '{name}' in {self._scope.kind} scope; "
                f"previous declaration at {original.location.format()}",
                location,
            )
            return None

        symbol = Symbol(name, kind, node, self._scope, location, mutable)
        self._scope.symbols[name] = symbol
        self._scope.overloads[name] = (symbol,)
        self.annotations.declaration_symbols[id(node)] = symbol
        return symbol

    def _can_overload(
        self,
        name: str,
        kind: SymbolKind,
        node: Node,
        original: Symbol,
    ) -> bool:
        if kind != "function" or original.kind != "function":
            return False
        if not isinstance(node, FunctionDeclaration):
            return False
        existing = self._scope.overloads.get(name, (original,))
        existing_functions = [
            symbol.node
            for symbol in existing
            if isinstance(symbol.node, FunctionDeclaration)
        ]
        is_async = "async" in node.modifiers
        if any(("async" in function.modifiers) == is_async for function in existing_functions):
            return False
        return all(
            self._same_function_parameters(node, function)
            for function in existing_functions
        )

    def _same_function_parameters(
        self,
        left: FunctionDeclaration,
        right: FunctionDeclaration,
    ) -> bool:
        if len(left.parameters) != len(right.parameters):
            return False
        return all(
            self._same_type_reference(left_parameter.type, right_parameter.type)
            and left_parameter.ownership == right_parameter.ownership
            for left_parameter, right_parameter in zip(left.parameters, right.parameters)
        )

    def _same_type_reference(self, left: TypeReference, right: TypeReference) -> bool:
        return (
            left.name == right.name
            and left.array_depth == right.array_depth
            and left.nullable == right.nullable
            and len(left.array_dimensions) == len(right.array_dimensions)
            and len(left.arguments) == len(right.arguments)
            and all(
                self._same_type_reference(left_argument, right_argument)
                for left_argument, right_argument in zip(left.arguments, right.arguments)
            )
        )

    def _in_async_function(self) -> bool:
        return bool(
            self._function_stack and "async" in self._function_stack[-1].modifiers
        )
