"""Type checking for resolved Forge AST programs."""

from __future__ import annotations

from dataclasses import dataclass, field

from forge_analysis import Diagnostic, Symbol
from forge_intrinsics import STRING_INTRINSICS, string_intrinsic
from forge_lexer import TokenKind
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
    EnumVariant,
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
from forge_resolution import (
    BuiltinInterfaceSymbol,
    BuiltinSymbol,
    ResolutionResult,
    SpecialSymbol,
    resolve,
)

from .types import (
    BOOL,
    DOUBLE,
    INT,
    NULL,
    PATTERN_MISMATCH,
    STRING,
    UNKNOWN,
    VOID,
    ArrayType,
    BuiltinType,
    ClassType,
    EnumType,
    FunctionType,
    InterfaceType,
    NullableType,
    OutcomeType,
    StructType,
    TaskCollectionType,
    TaskType,
    Type,
    apply_type_modifiers,
    builtin_type,
    is_assignable,
    is_numeric,
    is_unknown,
)


@dataclass(slots=True)
class TypeTable:
    """Side-table type annotations keyed by AST nodes and symbols."""

    expressions: dict[int, Type] = field(default_factory=dict)
    symbols: dict[int, Type] = field(default_factory=dict)
    type_references: dict[int, Type] = field(default_factory=dict)
    expression_outcomes: dict[int, tuple[OutcomeType, ...]] = field(default_factory=dict)
    task_outcomes: dict[int, tuple[OutcomeType, ...]] = field(default_factory=dict)

    def type_of(self, node: Node) -> Type | None:
        node_id = id(node)
        return (
            self.expressions.get(node_id)
            or self.type_references.get(node_id)
            or self.symbols.get(node_id)
        )

    def type_of_symbol(self, symbol: Symbol) -> Type | None:
        return self.symbols.get(id(symbol.node))

    def outcomes_of(self, node: Node) -> tuple[OutcomeType, ...]:
        return self.expression_outcomes.get(id(node), ())

    def task_outcomes_of(self, node: Node) -> tuple[OutcomeType, ...]:
        return self.task_outcomes.get(id(node), ())


@dataclass(frozen=True, slots=True)
class TypeCheckResult:
    program: Program
    resolution: ResolutionResult
    diagnostics: tuple[Diagnostic, ...]
    types: TypeTable

    @property
    def ok(self) -> bool:
        return self.resolution.ok and not any(
            diagnostic.severity == "error" for diagnostic in self.diagnostics
        )


@dataclass(slots=True)
class _LoopTypeContext:
    expression: bool
    break_values: list[tuple[Type, Node]] = field(default_factory=list)


class TypeCheckError(Exception):
    """Raised when type checking finds one or more errors."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        first = diagnostics[0]
        super().__init__(f"{first.message} at {first.location.format()}")


def check_types(
    program_or_resolution: Program | ResolutionResult,
    *,
    raise_on_error: bool = True,
) -> TypeCheckResult:
    """Type-check a parsed program or an existing name-resolution result."""

    resolution = (
        resolve(program_or_resolution, raise_on_error=False)
        if isinstance(program_or_resolution, Program)
        else program_or_resolution
    )
    checker = _TypeChecker(resolution)
    result = checker.run()
    if raise_on_error and not result.ok:
        diagnostics = tuple(
            diagnostic
            for diagnostic in (
                *resolution.analysis.diagnostics,
                *resolution.diagnostics,
                *result.diagnostics,
            )
            if diagnostic.severity == "error"
        )
        raise TypeCheckError(diagnostics)
    return result


class _TypeChecker:
    def __init__(self, resolution: ResolutionResult) -> None:
        self.resolution = resolution
        self.program = resolution.program
        self.diagnostics: list[Diagnostic] = []
        self.types = TypeTable()
        self._function_stack: list[FunctionDeclaration] = []
        self._class_stack: list[ClassDeclaration | EnumDeclaration] = []
        self._non_null_stack: list[set[str]] = []
        self._prefer_async_call_stack: list[int] = []
        self._prefer_sync_call_stack: list[int] = []
        self._selected_symbols: dict[int, Symbol] = {}
        self._expected_type_stack: list[Type] = []
        self._loop_stack: list[_LoopTypeContext] = []
        self._pattern_catch_expressions: set[int] = set()

    def run(self) -> TypeCheckResult:
        self._declare_signatures(self.program.declarations)
        for declaration in self.program.declarations:
            self._visit_declaration_or_statement(declaration)
        return TypeCheckResult(
            self.program,
            self.resolution,
            tuple(self.diagnostics),
            self.types,
        )

    def _error(self, message: str, node: Node) -> None:
        self.diagnostics.append(Diagnostic(message, node.location))

    def _declare_signatures(
        self,
        declarations: tuple[Declaration | Statement, ...],
        enclosing_class: ClassDeclaration | EnumDeclaration | None = None,
    ) -> None:
        for declaration in declarations:
            if isinstance(declaration, ClassDeclaration):
                symbol = self.resolution.analysis.annotations.symbol_for(declaration)
                if symbol is not None:
                    if declaration.kind == "interface":
                        self.types.symbols[id(declaration)] = InterfaceType(
                            declaration.name or "<anonymous interface>",
                            symbol,
                        )
                    elif declaration.kind == "struct":
                        self.types.symbols[id(declaration)] = StructType(
                            declaration.name or "<anonymous struct>",
                            symbol,
                        )
                    else:
                        self.types.symbols[id(declaration)] = ClassType(
                            declaration.name or "<anonymous class>",
                            symbol,
                        )
                self._declare_signatures(declaration.members, declaration)
            elif isinstance(declaration, EnumDeclaration):
                symbol = self.resolution.analysis.annotations.symbol_for(declaration)
                if symbol is not None:
                    value_type = self._enum_value_type(declaration)
                    self.types.symbols[id(declaration)] = EnumType(
                        declaration.name or "<anonymous enum>",
                        symbol,
                        value_type,
                    )
                self._declare_signatures(declaration.members, declaration)
            elif isinstance(declaration, FunctionDeclaration):
                symbol = self.resolution.analysis.annotations.symbol_for(declaration)
                if symbol is not None:
                    self.types.symbols[id(declaration)] = self._function_type(
                        declaration,
                        enclosing_class,
                    )

    def _function_type(
        self,
        declaration: FunctionDeclaration,
        enclosing_class: ClassDeclaration | EnumDeclaration | None = None,
    ) -> FunctionType:
        parameter_types = tuple(
            self._type_from_reference(parameter.type) for parameter in declaration.parameters
        )
        if declaration.kind == "new" and enclosing_class is not None:
            class_symbol = self.resolution.analysis.annotations.symbol_for(enclosing_class)
            if isinstance(enclosing_class, ClassDeclaration) and enclosing_class.kind == "struct":
                return_type = StructType(enclosing_class.name or "<anonymous struct>", class_symbol)
            elif isinstance(enclosing_class, EnumDeclaration):
                return_type = EnumType(
                    enclosing_class.name or "<anonymous enum>",
                    class_symbol,
                    self._enum_value_type(enclosing_class),
                )
            else:
                return_type = ClassType(
                    enclosing_class.name or "<anonymous class>",
                    class_symbol,
                )
        elif declaration.return_type is not None:
            return_type = self._type_from_reference(declaration.return_type)
        else:
            return_type = VOID
        return FunctionType(
            declaration.name,
            parameter_types,
            return_type,
            tuple(parameter.ownership for parameter in declaration.parameters),
            tuple(
                OutcomeType(self._type_from_reference(outcome.type), outcome.required)
                for outcome in declaration.outcomes
            ),
            declaration.return_ownership,
            self._borrow_return_source(declaration, enclosing_class, parameter_types),
        )

    def _borrow_return_source(
        self,
        declaration: FunctionDeclaration,
        enclosing_class: ClassDeclaration | EnumDeclaration | None,
        parameter_types: tuple[Type, ...],
    ) -> str | int | None:
        if declaration.return_ownership != "borrow":
            return None
        if enclosing_class is not None and "static" not in declaration.modifiers:
            return "this"
        candidates = []
        for index, (parameter, type_) in enumerate(
            zip(declaration.parameters, parameter_types)
        ):
            resource_type = type_.inner_type if isinstance(type_, NullableType) else type_
            if parameter.ownership == "borrow" and isinstance(resource_type, ClassType):
                candidates.append(index)
        return candidates[0] if len(candidates) == 1 else None

    def _enum_value_type(self, declaration: EnumDeclaration) -> Type:
        if isinstance(declaration.value_type, TypeReference):
            return self._type_from_reference(declaration.value_type)
        if isinstance(declaration.value_type, InlineStructType):
            symbol = self.resolution.analysis.annotations.symbol_for(declaration)
            return StructType(f"{declaration.name or '<anonymous enum>'}.Value", symbol)
        return UNKNOWN

    def _visit_declaration_or_statement(self, node: Declaration | Statement) -> None:
        if isinstance(node, Declaration):
            self._visit_declaration(node)
        else:
            self._visit_statement(node)

    def _visit_declaration(self, declaration: Declaration) -> None:
        if isinstance(declaration, ClassDeclaration):
            self._class_stack.append(declaration)
            for interface in declaration.implements:
                self._type_from_reference(interface)
            for trait in declaration.uses:
                self._check_used_trait(trait)
            for member in declaration.members:
                self._visit_declaration_or_statement(member)
            self._check_implemented_interfaces(declaration)
            self._class_stack.pop()
        elif isinstance(declaration, EnumDeclaration):
            self._class_stack.append(declaration)
            value_type = self._enum_value_type(declaration)
            for variant in declaration.variants:
                symbol = self.resolution.analysis.annotations.symbol_for(variant)
                enum_symbol = self.resolution.analysis.annotations.symbol_for(declaration)
                variant_type = EnumType(
                    declaration.name or "<anonymous enum>",
                    enum_symbol,
                    value_type,
                )
                if symbol is not None:
                    self.types.symbols[id(symbol.node)] = variant_type
                if variant.value is not None:
                    actual = (
                        self._struct_literal_type(variant.value, value_type)
                        if isinstance(variant.value, StructLiteralExpression)
                        else self._visit_expression(variant.value)
                    )
                    self._check_assignable(actual, value_type, variant.value)
            for member in declaration.members:
                self._visit_declaration_or_statement(member)
            self._class_stack.pop()
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
                self._check_used_trait(trait)

    def _check_used_trait(self, reference: TypeReference) -> None:
        self._type_from_reference(reference)
        resolved = self.resolution.resolutions.symbol_for(reference)
        if (
            isinstance(resolved, Symbol)
            and isinstance(resolved.node, ClassDeclaration)
            and resolved.node.kind == "trait"
        ):
            return
        self._error(f"uses expects a trait, got {reference.name}", reference)

    def _visit_function(self, declaration: FunctionDeclaration) -> None:
        self._validate_borrowed_return(declaration)
        for parameter in declaration.parameters:
            self._visit_parameter(parameter)

        self._function_stack.append(declaration)
        if isinstance(declaration.body, BlockStatement):
            self._visit_statement(declaration.body)
        elif declaration.body is not None:
            function_type = self.types.type_of(declaration)
            if (
                isinstance(function_type, FunctionType)
                and isinstance(declaration.body, StructLiteralExpression)
                and isinstance(
                    self._struct_literal_expected_type(function_type.return_type),
                    StructType,
                )
            ):
                body_type = self._struct_literal_type(
                    declaration.body,
                    self._struct_literal_expected_type(function_type.return_type),
                )
                self.types.expressions[id(declaration.body)] = body_type
            elif isinstance(function_type, FunctionType) and not isinstance(function_type.return_type, TaskType):
                body_type = self._with_preferred_sync_call(
                    declaration.body,
                    lambda: self._visit_expression(declaration.body),
                )
            else:
                body_type = self._visit_expression(declaration.body)
            if isinstance(function_type, FunctionType):
                self._check_assignable(body_type, function_type.return_type, declaration.body)
        self._function_stack.pop()

    def _validate_borrowed_return(self, declaration: FunctionDeclaration) -> None:
        if declaration.return_ownership != "borrow":
            return
        function_type = self.types.type_of(declaration)
        return_type = (
            function_type.return_type
            if isinstance(function_type, FunctionType)
            else UNKNOWN
        )
        resource_type = (
            return_type.inner_type
            if isinstance(return_type, NullableType)
            else return_type
        )
        if not isinstance(resource_type, ClassType):
            self._error("Borrowed return type must be a class resource", declaration)
        if declaration.kind == "new":
            self._error("Constructor cannot return a borrowed value", declaration)
        if declaration.kind == "generator" or "async" in declaration.modifiers:
            self._error(
                "Borrowed returns are not supported for async or generator functions",
                declaration,
            )
        if (
            isinstance(function_type, FunctionType)
            and function_type.return_borrow_source is None
        ):
            self._error(
                "Borrowed return requires an instance receiver or exactly one borrow resource parameter",
                declaration,
            )

    def _visit_parameter(self, parameter: Parameter) -> None:
        symbol = self.resolution.analysis.annotations.symbol_for(parameter)
        parameter_type = self._type_from_reference(parameter.type)
        if symbol is not None:
            self.types.symbols[id(symbol.node)] = parameter_type

    def _visit_variable(self, declaration: VariableDeclaration) -> None:
        declared_type = (
            self._type_from_reference(declaration.type)
            if declaration.type is not None
            else None
        )
        initializer_type = None
        if declaration.initializer is not None:
            if (
                isinstance(declaration.initializer, ArrayLiteralExpression)
                and isinstance(declared_type, ArrayType)
            ):
                initializer_type = self._array_literal_type(
                    declaration.initializer,
                    expected=declared_type,
                )
                self.types.expressions[id(declaration.initializer)] = initializer_type
            elif isinstance(declaration.initializer, StructLiteralExpression) and isinstance(
                self._struct_literal_expected_type(declared_type), StructType
            ):
                initializer_type = self._struct_literal_type(
                    declaration.initializer,
                    self._struct_literal_expected_type(declared_type),
                )
                self.types.expressions[id(declaration.initializer)] = initializer_type
            else:
                if isinstance(declared_type, TaskType):
                    initializer_type = self._with_preferred_async_call(
                        declaration.initializer,
                        lambda: self._visit_expression(declaration.initializer),
                    )
                elif declared_type is not None:
                    initializer_type = self._with_preferred_sync_call(
                        declaration.initializer,
                        lambda: self._visit_expression_with_expected(
                            declaration.initializer, declared_type
                        ),
                    )
                else:
                    initializer_type = self._visit_expression(declaration.initializer)
            self._check_unhandled_required_outcomes(declaration.initializer)
        variable_type = declared_type or initializer_type or UNKNOWN

        symbol = self.resolution.analysis.annotations.symbol_for(declaration)
        if symbol is not None:
            self.types.symbols[id(symbol.node)] = variable_type
            if declaration.initializer is not None:
                task_outcomes = self._task_outcomes_of(declaration.initializer)
                self._set_task_outcomes(declaration, task_outcomes)
                self._set_task_outcomes(symbol.node, task_outcomes)

        if declared_type is not None and initializer_type is not None:
            self._check_assignable(initializer_type, declared_type, declaration.initializer)

    def _visit_array_destructuring(
        self, declaration: ArrayDestructuringDeclaration
    ) -> None:
        initializer = declaration.initializer
        caught = isinstance(initializer, CatchExpression)
        source = initializer.expression if caught else initializer
        if caught:
            self._pattern_catch_expressions.add(id(initializer))
            try:
                source_type = self._visit_expression(initializer)
            finally:
                self._pattern_catch_expressions.remove(id(initializer))
        else:
            source_type = self._visit_expression(initializer)
        self._check_unhandled_required_outcomes(declaration.initializer)
        if isinstance(source_type, ArrayType):
            element_type = source_type.element_type
            static_length = self._array_destructuring_static_length(source, source_type)
            if static_length is not None and static_length < len(declaration.bindings):
                self._error(
                    f"Array destructuring requires {len(declaration.bindings)} elements, "
                    f"but source has {static_length}",
                    source,
                )
            elif static_length is None and not caught:
                self._error(
                    "Array destructuring of unknown length requires "
                    "'catch ... { issue: PatternMismatch => ... }'",
                    initializer,
                )
        else:
            element_type = UNKNOWN
            if not is_unknown(source_type):
                self._error(
                    f"Array destructuring requires an array, got {source_type.display_name}",
                    declaration.initializer,
                )

        for binding in declaration.bindings:
            symbol = self.resolution.analysis.annotations.symbol_for(binding)
            if symbol is not None:
                self.types.symbols[id(symbol.node)] = element_type

    def _array_destructuring_static_length(
        self,
        source: Expression,
        source_type: ArrayType,
    ) -> int | None:
        while isinstance(source, GroupingExpression):
            source = source.expression
        if isinstance(source, ArrayLiteralExpression):
            return len(source.elements)
        return source_type.size

    def _visit_statement(self, statement: Statement) -> None:
        if isinstance(statement, BlockStatement):
            for child in statement.statements:
                self._visit_declaration_or_statement(child)
        elif isinstance(statement, PrintStatement):
            self._visit_expression(statement.expression)
            self._check_unhandled_required_outcomes(statement.expression)
        elif isinstance(statement, ReturnStatement):
            self._visit_return(statement)
        elif isinstance(statement, BreakStatement):
            self._visit_break(statement)
        elif isinstance(statement, IfStatement):
            condition_type = self._visit_expression(statement.condition)
            self._check_condition_type(condition_type, statement.condition)
            self._with_non_null(
                self._then_narrowed_key(statement.condition),
                lambda: self._visit_statement(statement.then_branch),
            )
            if statement.else_branch is not None:
                self._with_non_null(
                    self._else_narrowed_key(statement.condition),
                    lambda: self._visit_statement(statement.else_branch),
                )
        elif isinstance(statement, SwitchStatement):
            expression_type = self._visit_expression(statement.expression)
            for arm in statement.arms:
                if arm.pattern is not None:
                    pattern_type = self._visit_expression(arm.pattern)
                    self._check_assignable(pattern_type, expression_type, arm.pattern)
                self._visit_statement(arm.body)
        elif isinstance(statement, WhileStatement):
            condition_type = self._visit_expression(statement.condition)
            self._check_condition_type(condition_type, statement.condition)
            self._loop_stack.append(_LoopTypeContext(False))
            self._with_non_null(
                self._then_narrowed_key(statement.condition),
                lambda: self._visit_statement(statement.body),
            )
            self._loop_stack.pop()
        elif isinstance(statement, DoWhileStatement):
            self._loop_stack.append(_LoopTypeContext(False))
            self._visit_statement(statement.body)
            self._loop_stack.pop()
            condition_type = self._visit_expression(statement.condition)
            self._check_condition_type(condition_type, statement.condition)
        elif isinstance(statement, ForStatement):
            source_type = self._visit_expression(statement.source)
            if isinstance(source_type, ArrayType):
                item_type = source_type.element_type
            else:
                item_type = UNKNOWN
                if not is_unknown(source_type):
                    self._error(
                        f"Cannot iterate value of type {source_type.display_name}",
                        statement.source,
                    )
            symbol = self.resolution.analysis.annotations.symbol_for(statement.item)
            if symbol is not None:
                self.types.symbols[id(symbol.node)] = item_type
            self._loop_stack.append(_LoopTypeContext(False))
            self._visit_statement(statement.body)
            self._loop_stack.pop()
        elif isinstance(statement, BorrowScopeStatement):
            source_type = self._visit_expression(statement.source)
            self._check_unhandled_required_outcomes(statement.source)
            symbol = self.resolution.analysis.annotations.symbol_for(statement.binding)
            if symbol is not None:
                self.types.symbols[id(symbol.node)] = source_type
            resource_type = (
                source_type.inner_type
                if isinstance(source_type, NullableType)
                else source_type
            )
            if not isinstance(resource_type, ClassType):
                self._error("Scoped borrow requires a class resource", statement.source)
            self._visit_statement(statement.body)
        elif isinstance(statement, ExpressionStatement):
            self._visit_expression(statement.expression)
            self._check_unhandled_required_outcomes(statement.expression)

    def _visit_return(self, statement: ReturnStatement) -> None:
        if not self._function_stack:
            return
        function = self._function_stack[-1]
        function_type = self.types.type_of(function)
        expected = function_type.return_type if isinstance(function_type, FunctionType) else VOID
        struct_expected = self._struct_literal_expected_type(expected)
        if (
            statement.expression is not None
            and isinstance(statement.expression, StructLiteralExpression)
            and isinstance(struct_expected, StructType)
        ):
            actual = self._struct_literal_type(statement.expression, struct_expected)
            self.types.expressions[id(statement.expression)] = actual
        elif statement.expression is not None and not isinstance(expected, TaskType):
            actual = self._with_preferred_sync_call(
                statement.expression,
                lambda: self._visit_expression_with_expected(
                    statement.expression, expected
                ),
            )
        else:
            actual = self._visit_expression(statement.expression) if statement.expression else VOID
        if statement.expression is not None:
            self._check_unhandled_required_outcomes(statement.expression)
        if (
            isinstance(function_type, FunctionType)
            and statement.expression is not None
            and any(self._same_type(outcome.type, actual) for outcome in function_type.outcomes)
        ):
            return
        self._check_assignable(actual, expected, statement)

    def _visit_break(self, statement: BreakStatement) -> None:
        if not self._loop_stack:
            return
        context = self._loop_stack[-1]
        if statement.expression is None:
            return
        actual = self._visit_expression(statement.expression)
        if not context.expression:
            self._error("A valued break requires an expression loop", statement)
            return
        context.break_values.append((actual, statement.expression))

    def _check_implemented_interfaces(self, declaration: ClassDeclaration) -> None:
        if declaration.kind == "interface":
            return
        for reference in declaration.implements:
            interface_type = self._type_from_reference(reference)
            if isinstance(interface_type, InterfaceType):
                self._check_interface_contract(declaration, interface_type, reference)

    def _check_interface_contract(
        self,
        declaration: ClassDeclaration,
        interface_type: InterfaceType,
        reference: TypeReference,
    ) -> None:
        required = self._interface_methods(interface_type)
        class_methods = self._class_methods(declaration)
        for name, expected in required.items():
            actual = class_methods.get(name)
            if actual is None:
                self._error(
                    f"Type {declaration.name} implements {interface_type.name} "
                    f"but is missing method '{name}'",
                    reference,
                )
            elif (
                actual.parameter_types != expected.parameter_types
                or actual.return_type != expected.return_type
                or actual.parameter_ownership != expected.parameter_ownership
                or actual.return_ownership != expected.return_ownership
                or actual.return_borrow_source != expected.return_borrow_source
            ):
                self._error(
                    f"Method '{name}' does not match interface {interface_type.name}",
                    reference,
                )

    def _interface_methods(self, interface_type: InterfaceType) -> dict[str, FunctionType]:
        if interface_type.name == "Stringable":
            return {"toString": FunctionType("toString", (), STRING)}
        symbol = interface_type.symbol
        if symbol is None or not isinstance(symbol.node, ClassDeclaration):
            return {}
        return {
            member.name: self._function_type(member, symbol.node)
            for member in symbol.node.members
            if isinstance(member, FunctionDeclaration)
        }

    def _class_methods(self, declaration: ClassDeclaration) -> dict[str, FunctionType]:
        methods: dict[str, FunctionType] = {}
        for trait in self._used_trait_declarations(declaration):
            for member in trait.members:
                if isinstance(member, FunctionDeclaration):
                    methods.setdefault(member.name, self._function_type(member, declaration))
        for member in declaration.members:
            if isinstance(member, FunctionDeclaration):
                methods[member.name] = self._function_type(member, declaration)
        return methods

    def _used_trait_declarations(self, declaration: ClassDeclaration) -> tuple[ClassDeclaration, ...]:
        traits: list[ClassDeclaration] = []
        for reference in declaration.uses:
            resolved = self.resolution.resolutions.symbol_for(reference)
            if (
                isinstance(resolved, Symbol)
                and isinstance(resolved.node, ClassDeclaration)
                and resolved.node.kind == "trait"
            ):
                traits.append(resolved.node)
        return tuple(traits)

    def _visit_expression(self, expression: Expression | None) -> Type:
        if expression is None:
            return VOID
        if isinstance(expression, LiteralExpression):
            result = self._literal_type(expression)
        elif isinstance(expression, IdentifierExpression):
            result = self._identifier_type(expression)
        elif isinstance(expression, ThisExpression):
            result = self._special_type(expression)
        elif isinstance(expression, SelfExpression):
            result = self._special_type(expression)
        elif isinstance(expression, GroupingExpression):
            result = self._visit_expression(expression.expression)
            self._set_outcomes(expression, self._outcomes_of(expression.expression))
            self._set_task_outcomes(
                expression,
                self._task_outcomes_of(expression.expression),
            )
        elif isinstance(expression, ForwardExpression):
            result = self._forward_type(expression)
        elif isinstance(expression, CatchExpression):
            result = self._catch_type(expression)
        elif isinstance(expression, UnaryExpression):
            result = self._unary_type(expression)
        elif isinstance(expression, MoveExpression):
            result = self._visit_expression(expression.expression)
            self._set_outcomes(expression, self._outcomes_of(expression.expression))
            self._set_task_outcomes(
                expression,
                self._task_outcomes_of(expression.expression),
            )
        elif isinstance(expression, BinaryExpression):
            result = self._binary_type(expression)
        elif isinstance(expression, AssignmentExpression):
            result = self._assignment_type(expression)
        elif isinstance(expression, ConditionalExpression):
            result = self._conditional_type(expression)
        elif isinstance(expression, CallExpression):
            result = self._call_type(expression)
        elif isinstance(expression, ArrayLiteralExpression):
            result = self._array_literal_type(expression)
        elif isinstance(expression, StructLiteralExpression):
            result = self._struct_literal_type(expression, None)
        elif isinstance(expression, BulkArgumentPack):
            for argument in expression.arguments:
                self._visit_expression(argument)
            self._set_outcomes(
                expression,
                tuple(
                    outcome
                    for argument in expression.arguments
                    for outcome in self._outcomes_of(argument)
                ),
            )
            result = UNKNOWN
        elif isinstance(expression, BulkCallExpression):
            result = self._bulk_call_type(expression)
        elif isinstance(expression, MemberExpression):
            result = self._member_type(expression)
        elif isinstance(expression, MemberBlockExpression):
            receiver_type = self._visit_expression(expression.receiver)
            for child in expression.expressions:
                self._visit_expression(child)
            self._set_outcomes(
                expression,
                tuple(
                    outcome
                    for child in expression.expressions
                    for outcome in self._outcomes_of(child)
                ),
            )
            result = receiver_type
        elif isinstance(expression, IndexExpression):
            result = self._index_type(expression)
        elif isinstance(expression, (WhileExpression, DoWhileExpression, ForExpression)):
            result = self._loop_expression_type(expression)
        else:
            result = UNKNOWN
        if isinstance(result, NullableType) and self._is_non_null(expression):
            result = result.inner_type
        self.types.expressions[id(expression)] = result
        self.types.expression_outcomes.setdefault(id(expression), ())
        return result

    def _visit_expression_with_expected(
        self, expression: Expression, expected: Type
    ) -> Type:
        self._expected_type_stack.append(expected)
        try:
            return self._visit_expression(expression)
        finally:
            self._expected_type_stack.pop()

    def _loop_expression_type(
        self, expression: WhileExpression | DoWhileExpression | ForExpression
    ) -> Type:
        if isinstance(expression, ForExpression):
            source_type = self._visit_expression(expression.source)
            if isinstance(source_type, ArrayType):
                item_type = source_type.element_type
            else:
                item_type = UNKNOWN
                if not is_unknown(source_type):
                    self._error(
                        f"Cannot iterate value of type {source_type.display_name}",
                        expression.source,
                    )
            symbol = self.resolution.analysis.annotations.symbol_for(expression.item)
            if symbol is not None:
                self.types.symbols[id(symbol.node)] = item_type
        elif isinstance(expression, WhileExpression):
            condition = self._visit_expression_with_expected(expression.condition, BOOL)
            self._check_condition_type(condition, expression.condition)

        context = _LoopTypeContext(True)
        self._loop_stack.append(context)
        self._visit_statement(expression.body)
        self._loop_stack.pop()

        if isinstance(expression, DoWhileExpression):
            condition = self._visit_expression_with_expected(expression.condition, BOOL)
            self._check_condition_type(condition, expression.condition)

        expected = self._expected_type_stack[-1] if self._expected_type_stack else None
        if expression.fallback is not None:
            fallback_type = (
                self._visit_expression_with_expected(expression.fallback, expected)
                if expected is not None
                else self._visit_expression(expression.fallback)
            )
        elif isinstance(expected, NullableType):
            fallback_type = NULL
        else:
            self._error(
                "Loop expression requires an else fallback or a contextual nullable type",
                expression,
            )
            fallback_type = UNKNOWN

        if expected is not None:
            self._check_assignable(fallback_type, expected, expression)
            for actual, node in context.break_values:
                self._check_assignable(actual, expected, node)
            return expected

        result = fallback_type
        for actual, node in context.break_values:
            if result == NULL:
                result = NullableType(f"{actual.name}?", actual)
            elif actual == NULL and not isinstance(result, NullableType):
                result = NullableType(f"{result.name}?", result)
            elif is_assignable(actual, result):
                continue
            elif is_assignable(result, actual):
                result = actual
            else:
                self._error(
                    f"Loop result has incompatible types "
                    f"{actual.display_name} and {result.display_name}",
                    node,
                )
                result = UNKNOWN
        return result

    def _outcomes_of(self, expression: Expression) -> tuple[OutcomeType, ...]:
        return self.types.expression_outcomes.get(id(expression), ())

    def _set_outcomes(
        self,
        expression: Expression,
        outcomes: tuple[OutcomeType, ...],
    ) -> None:
        self.types.expression_outcomes[id(expression)] = self._dedupe_outcomes(outcomes)

    def _task_outcomes_of(self, expression: Expression) -> tuple[OutcomeType, ...]:
        return self.types.task_outcomes.get(id(expression), ())

    def _set_task_outcomes(
        self,
        node: Node,
        outcomes: tuple[OutcomeType, ...],
    ) -> None:
        self.types.task_outcomes[id(node)] = self._dedupe_outcomes(outcomes)

    def _dedupe_outcomes(
        self,
        outcomes: tuple[OutcomeType, ...],
    ) -> tuple[OutcomeType, ...]:
        merged: list[OutcomeType] = []
        for outcome in outcomes:
            existing_index = next(
                (
                    index
                    for index, existing in enumerate(merged)
                    if self._same_type(existing.type, outcome.type)
                ),
                None,
            )
            if existing_index is None:
                merged.append(outcome)
            else:
                existing = merged[existing_index]
                merged[existing_index] = OutcomeType(
                    existing.type,
                    existing.required or outcome.required,
                )
        return tuple(merged)

    def _check_unhandled_required_outcomes(self, expression: Expression) -> None:
        for outcome in self._outcomes_of(expression):
            if outcome.required:
                self._error(
                    f"Unhandled required outcome {outcome.type.display_name}",
                    expression,
                )

    def _forward_type(self, expression: ForwardExpression) -> Type:
        result = self._visit_expression(expression.expression)
        function_type = self._current_function_type()
        if not isinstance(function_type, FunctionType):
            self._error("'forward' can only be used inside a function", expression)
            self._set_outcomes(expression, ())
            return result
        for outcome in self._outcomes_of(expression.expression):
            declared_outcome = next(
                (
                    candidate
                    for candidate in function_type.outcomes
                    if self._same_type(candidate.type, outcome.type)
                ),
                None,
            )
            if declared_outcome is None:
                self._error(
                    f"Cannot forward undeclared outcome {outcome.type.display_name}",
                    expression,
                )
                continue
            if outcome.required and not declared_outcome.required:
                self._error(
                    f"Cannot forward required outcome {outcome.type.display_name} as optional",
                    expression,
                )
        self._set_outcomes(expression, ())
        return result

    def _catch_type(self, expression: CatchExpression) -> Type:
        result = self._visit_expression(expression.expression)
        if id(expression) in self._pattern_catch_expressions:
            self._set_outcomes(
                expression.expression,
                (
                    *self._outcomes_of(expression.expression),
                    OutcomeType(PATTERN_MISMATCH, True),
                ),
            )
        remaining = list(self._outcomes_of(expression.expression))
        for handler in expression.handlers:
            handler_type = self._type_from_reference(handler.type)
            symbol = self.resolution.analysis.annotations.symbol_for(handler)
            if symbol is not None:
                self.types.symbols[id(symbol.node)] = handler_type
            matched = [
                outcome
                for outcome in remaining
                if self._same_type(outcome.type, handler_type)
            ]
            if not matched:
                self._error(
                    f"Cannot catch undeclared outcome {handler_type.display_name}",
                    handler,
                )
            remaining = [
                outcome
                for outcome in remaining
                if not self._same_type(outcome.type, handler_type)
            ]
            if isinstance(handler.expression, BlockStatement):
                self._visit_statement(handler.expression)
                if not self._block_exits_with_return(handler.expression):
                    self._error(
                        "Catch handler block must return from the current function",
                        handler.expression,
                    )
            else:
                actual = self._visit_expression(handler.expression)
                self._check_assignable(actual, result, handler.expression)
                remaining.extend(self._outcomes_of(handler.expression))
        self._set_outcomes(expression, tuple(remaining))
        return result

    def _block_exits_with_return(self, block: BlockStatement) -> bool:
        return bool(block.statements and isinstance(block.statements[-1], ReturnStatement))

    def _same_type(self, left: Type, right: Type) -> bool:
        return left == right

    def _current_function_type(self) -> Type | None:
        if not self._function_stack:
            return None
        return self.types.type_of(self._function_stack[-1])

    def _literal_type(self, expression: LiteralExpression) -> Type:
        value = expression.value
        if isinstance(value, bool):
            return BOOL
        if isinstance(value, int):
            return INT
        if isinstance(value, float):
            return DOUBLE
        if isinstance(value, str):
            return STRING
        if value is None:
            return NULL
        return UNKNOWN

    def _identifier_type(self, expression: IdentifierExpression) -> Type:
        symbol = self.resolution.resolutions.symbol_for(expression)
        if isinstance(symbol, BuiltinSymbol):
            return builtin_type(symbol.name)
        if (
            isinstance(symbol, Symbol)
            and isinstance(symbol.node, ClassDeclaration)
            and symbol.node.kind == "struct"
        ):
            return StructType(symbol.name, symbol)
        if (
            isinstance(symbol, Symbol)
            and isinstance(symbol.node, ClassDeclaration)
            and symbol.node.kind == "interface"
        ):
            return InterfaceType(symbol.name, symbol)
        if isinstance(symbol, Symbol) and isinstance(symbol.node, ClassDeclaration):
            return ClassType(symbol.name, symbol)
        if isinstance(symbol, Symbol) and isinstance(symbol.node, EnumDeclaration):
            return EnumType(symbol.name, symbol, self._enum_value_type(symbol.node))
        if isinstance(symbol, Symbol):
            symbol = self._selected_overload_symbol(expression, symbol)
            self._set_task_outcomes(
                expression,
                self.types.task_outcomes.get(id(symbol.node), ()),
            )
            return self.types.symbols.get(id(symbol.node), UNKNOWN)
        return UNKNOWN

    def _selected_overload_symbol(
        self,
        expression: IdentifierExpression,
        symbol: Symbol,
    ) -> Symbol:
        overloads = symbol.scope.overloads.get(symbol.name, (symbol,))
        if len(overloads) <= 1:
            self._selected_symbols[id(expression)] = symbol
            self.resolution.resolutions.identifiers[id(expression)] = symbol
            return symbol
        prefer_async = self._call_prefers_async(expression)
        selected = next(
            (
                candidate
                for candidate in overloads
                if isinstance(candidate.node, FunctionDeclaration)
                and ("async" in candidate.node.modifiers) == prefer_async
            ),
            None,
        )
        selected_symbol = selected or symbol
        self._selected_symbols[id(expression)] = selected_symbol
        self.resolution.resolutions.identifiers[id(expression)] = selected_symbol
        return selected_symbol

    def _with_preferred_async_call(self, expression: Expression, callback):
        if isinstance(expression, CallExpression) and isinstance(expression.callee, IdentifierExpression):
            self._prefer_async_call_stack.append(id(expression.callee))
            try:
                return callback()
            finally:
                self._prefer_async_call_stack.pop()
        return callback()

    def _with_preferred_sync_call(self, expression: Expression, callback):
        if isinstance(expression, CallExpression) and isinstance(expression.callee, IdentifierExpression):
            self._prefer_sync_call_stack.append(id(expression.callee))
            try:
                return callback()
            finally:
                self._prefer_sync_call_stack.pop()
        return callback()

    def _call_prefers_async(self, callee: Expression) -> bool:
        return (
            isinstance(callee, IdentifierExpression)
            and bool(self._prefer_async_call_stack)
            and self._prefer_async_call_stack[-1] == id(callee)
        )

    def _call_prefers_sync(self, callee: Expression) -> bool:
        return (
            isinstance(callee, IdentifierExpression)
            and bool(self._prefer_sync_call_stack)
            and self._prefer_sync_call_stack[-1] == id(callee)
        )

    def _special_type(self, expression: ThisExpression | SelfExpression) -> Type:
        symbol = self.resolution.resolutions.symbol_for(expression)
        if isinstance(symbol, SpecialSymbol):
            class_symbol = self.resolution.analysis.annotations.symbol_for(symbol.node)
            if isinstance(symbol.node, EnumDeclaration):
                if symbol.kind == "this":
                    return self._enum_value_type(symbol.node)
                return EnumType(
                    symbol.node.name or "<anonymous enum>",
                    class_symbol,
                    self._enum_value_type(symbol.node),
                )
            if symbol.node.kind == "struct":
                return StructType(symbol.node.name or "<anonymous struct>", class_symbol)
            return ClassType(symbol.node.name or "<anonymous class>", class_symbol)
        return UNKNOWN

    def _unary_type(self, expression: UnaryExpression) -> Type:
        if expression.operator is TokenKind.AWAIT:
            operand = self._with_preferred_async_call(
                expression.operand,
                lambda: self._visit_expression(expression.operand),
            )
        else:
            operand = self._visit_expression(expression.operand)
        self._set_outcomes(expression, self._outcomes_of(expression.operand))
        if expression.operator is TokenKind.AWAIT:
            if isinstance(operand, TaskType):
                self._set_outcomes(
                    expression,
                    (
                        *self._outcomes_of(expression.operand),
                        *self._task_outcomes_of(expression.operand),
                    ),
                )
                return operand.result_type
            if not is_unknown(operand):
                self._error(
                    f"'await' requires Task<T>, got {operand.display_name}",
                    expression.operand,
                )
            return UNKNOWN
        if expression.operator in {TokenKind.BANG, TokenKind.NOT}:
            self._check_assignable(operand, BOOL, expression.operand)
            return BOOL
        if expression.operator is TokenKind.MINUS:
            if not is_numeric(operand) and not is_unknown(operand):
                self._error(
                    f"Unary '-' requires numeric operand, got {operand.display_name}",
                    expression.operand,
                )
            return operand
        return operand

    def _binary_type(self, expression: BinaryExpression) -> Type:
        left = self._visit_expression(expression.left)
        right = self._visit_expression(expression.right)
        self._set_outcomes(
            expression,
            (*self._outcomes_of(expression.left), *self._outcomes_of(expression.right)),
        )
        return self._binary_operator_type(expression.operator, left, right, expression)

    def _binary_operator_type(
        self,
        operator: TokenKind,
        left: Type,
        right: Type,
        expression: Expression,
    ) -> Type:
        if operator in {TokenKind.AND_AND, TokenKind.OR_OR}:
            self._check_assignable(left, BOOL, expression)
            self._check_assignable(right, BOOL, expression)
            return BOOL
        if operator in {TokenKind.PLUS, TokenKind.MINUS, TokenKind.STAR, TokenKind.SLASH, TokenKind.PERCENT}:
            if operator is TokenKind.PLUS and left == STRING and right == STRING:
                return STRING
            if (
                operator is TokenKind.PLUS
                and (left == STRING or right == STRING)
                and left not in {VOID, NULL}
                and right not in {VOID, NULL}
            ):
                return STRING
            if is_numeric(left) and is_numeric(right):
                return DOUBLE if DOUBLE in {left, right} else INT
            if not is_unknown(left) and not is_unknown(right):
                self._error(
                    f"Operator '{operator.value}' cannot be applied to "
                    f"{left.display_name} and {right.display_name}",
                    expression,
                )
            return UNKNOWN
        if operator in {
            TokenKind.EQUAL_EQUAL,
            TokenKind.BANG_EQUAL,
            TokenKind.LESS,
            TokenKind.LESS_EQUAL,
            TokenKind.GREATER,
            TokenKind.GREATER_EQUAL,
            TokenKind.IN,
            TokenKind.NOT,
        }:
            return BOOL
        if operator is TokenKind.NULL_COALESCE:
            if left == NULL:
                return right
            return left
        return UNKNOWN

    def _assignment_type(self, expression: AssignmentExpression) -> Type:
        target = self._visit_expression(expression.target)
        struct_expected = self._struct_literal_expected_type(target)
        if isinstance(expression.value, StructLiteralExpression) and isinstance(struct_expected, StructType):
            value = self._struct_literal_type(expression.value, struct_expected)
            self.types.expressions[id(expression.value)] = value
        else:
            value = self._visit_expression_with_expected(expression.value, target)
        self._set_outcomes(
            expression,
            (*self._outcomes_of(expression.target), *self._outcomes_of(expression.value)),
        )
        if isinstance(expression.target, IdentifierExpression):
            symbol = self.resolution.resolutions.symbol_for(expression.target)
            if isinstance(symbol, Symbol) and symbol.kind in {"variable", "parameter"}:
                if not symbol.mutable:
                    self._error(f"Cannot assign to immutable '{symbol.name}'", expression.target)
        if expression.operator is not TokenKind.EQUAL:
            result = self._binary_operator_type(
                expression.operator,
                target,
                value,
                expression,
            )
            self._check_assignable(result, target, expression)
            return target
        self._check_assignable(value, target, expression.value)
        return target

    def _conditional_type(self, expression: ConditionalExpression) -> Type:
        condition = self._visit_expression(expression.condition)
        self._check_condition_type(condition, expression.condition)
        then_type = self._with_non_null(
            self._then_narrowed_key(expression.condition),
            lambda: self._visit_expression(expression.then_expression),
        )
        else_type = self._with_non_null(
            self._else_narrowed_key(expression.condition),
            lambda: self._visit_expression(expression.else_expression),
        )
        self._set_outcomes(
            expression,
            (
                *self._outcomes_of(expression.condition),
                *self._outcomes_of(expression.then_expression),
                *self._outcomes_of(expression.else_expression),
            ),
        )
        if is_assignable(then_type, else_type):
            return else_type
        if is_assignable(else_type, then_type):
            return then_type
        self._error(
            f"Conditional branches have incompatible types "
            f"{then_type.display_name} and {else_type.display_name}",
            expression,
        )
        return UNKNOWN

    def _call_type(self, expression: CallExpression) -> Type:
        callee_type = self._visit_expression(expression.callee)
        if self._is_task_await_method_call(expression) and self._inside_async_function():
            self._error(
                "Task.await() cannot be used inside an async function; use the await operator",
                expression,
            )
        if not isinstance(callee_type, FunctionType):
            for argument in expression.arguments:
                self._visit_expression(argument)
            child_outcomes = self._call_child_outcomes(expression)
            self._set_outcomes(expression, child_outcomes)
            if not is_unknown(callee_type):
                self._error(f"Cannot call value of type {callee_type.display_name}", expression)
            return UNKNOWN
        is_async_function = self._call_is_async_function(expression.callee)
        returns_task = is_async_function and not self._call_prefers_sync(expression.callee)
        if len(expression.arguments) != len(callee_type.parameter_types):
            for argument in expression.arguments:
                self._visit_expression(argument)
            call_outcomes = self._call_child_outcomes(expression)
            if not returns_task:
                call_outcomes = (*call_outcomes, *callee_type.outcomes)
            self._set_outcomes(expression, call_outcomes)
            target = self._call_target_name(expression.callee) or callee_type.name
            self._error(
                f"Expected {len(callee_type.parameter_types)} arguments for {target}, "
                f"got {len(expression.arguments)}",
                expression,
            )
            return callee_type.return_type
        parameter_ownership = callee_type.parameter_ownership or (
            "borrow",
        ) * len(callee_type.parameter_types)
        target = self._call_target_name(expression.callee) or callee_type.name
        for index, (argument, expected, ownership) in enumerate(
            zip(expression.arguments, callee_type.parameter_types, parameter_ownership),
            start=1,
        ):
            is_move = isinstance(argument, MoveExpression)
            if ownership == "take" and not is_move:
                self._error(
                    f"Parameter {index} of {target} takes ownership; pass it with 'move'",
                    argument,
                )
            elif ownership != "take" and is_move:
                self._error(
                    f"Parameter {index} of {target} does not take ownership; remove 'move'",
                    argument,
            )
            actual = self._visit_call_argument(argument, expected)
            if self._is_string_intrinsic_member(expression.callee):
                self._check_assignable(actual, expected, argument)
            else:
                self._check_call_argument_assignable(actual, expected, argument)
        call_outcomes = self._call_child_outcomes(expression)
        if not returns_task:
            call_outcomes = (*call_outcomes, *callee_type.outcomes)
        self._set_outcomes(expression, call_outcomes)
        if returns_task:
            self._set_task_outcomes(expression, callee_type.outcomes)
            return TaskType(
                f"Task<{callee_type.return_type.display_name}>",
                callee_type.return_type,
            )
        callee_task_outcomes = self._task_outcomes_of(expression.callee)
        if isinstance(callee_type.return_type, (TaskType, TaskCollectionType)):
            self._set_task_outcomes(expression, callee_task_outcomes)
        return callee_type.return_type

    def _call_child_outcomes(self, expression: CallExpression) -> tuple[OutcomeType, ...]:
        return (
            *self._outcomes_of(expression.callee),
            *(
                outcome
                for argument in expression.arguments
                for outcome in self._outcomes_of(argument)
            ),
        )

    def _is_string_intrinsic_member(self, callee: Expression) -> bool:
        if not isinstance(callee, MemberExpression):
            return False
        receiver_type = self.types.type_of(callee.receiver)
        if receiver_type != STRING:
            return False
        return string_intrinsic(
            callee.member,
            static=self._is_class_receiver(callee.receiver),
        ) is not None

    def _inside_async_function(self) -> bool:
        return bool(self._function_stack) and "async" in self._function_stack[-1].modifiers

    def _is_task_await_method_call(self, expression: CallExpression) -> bool:
        if expression.arguments:
            return False
        if not isinstance(expression.callee, MemberExpression):
            return False
        if expression.callee.member != "await":
            return False
        receiver_type = self.types.type_of(expression.callee.receiver)
        return isinstance(receiver_type, (TaskType, TaskCollectionType))

    def _visit_call_argument(self, argument: Expression, expected: Type) -> Type:
        struct_expected = self._struct_literal_expected_type(expected)
        if isinstance(argument, StructLiteralExpression) and isinstance(struct_expected, StructType):
            actual = self._struct_literal_type(argument, struct_expected)
            self.types.expressions[id(argument)] = actual
            return actual
        return self.types.type_of(argument) or self._visit_expression_with_expected(
            argument, expected
        )

    def _array_literal_type(
        self,
        expression: ArrayLiteralExpression,
        *,
        expected: ArrayType | None = None,
    ) -> Type:
        element_types = tuple(
            self._visit_expression_with_expected(element, expected.element_type)
            if expected is not None
            else self._visit_expression(element)
            for element in expression.elements
        )
        self._set_outcomes(
            expression,
            tuple(
                outcome
                for element in expression.elements
                for outcome in self._outcomes_of(element)
            ),
        )
        if expected is not None and expected.size is not None:
            if len(expression.elements) != expected.size:
                self._error(
                    f"Expected {expected.size} array elements, got {len(expression.elements)}",
                    expression,
                )
            for element, element_type in zip(expression.elements, element_types):
                self._check_assignable(element_type, expected.element_type, element)
            return expected
        if expected is not None:
            for element, element_type in zip(expression.elements, element_types):
                self._check_assignable(element_type, expected.element_type, element)
            return ArrayType(f"{expected.element_type.name}[]", expected.element_type)
        if not element_types:
            self._error("Cannot infer element type of empty array literal", expression)
            return UNKNOWN
        element_type = element_types[0]
        for element, current_type in zip(expression.elements[1:], element_types[1:]):
            if not is_assignable(current_type, element_type):
                self._error(
                    f"Array literal element has type {current_type.display_name}, "
                    f"expected {element_type.display_name}",
                    element,
                )
        return ArrayType(f"{element_type.name}[]", element_type)

    def _struct_literal_type(
        self,
        expression: StructLiteralExpression,
        expected: StructType | None,
    ) -> Type:
        self._set_outcomes(
            expression,
            tuple(
                outcome
                for field in expression.fields
                for outcome in self._outcomes_of(field.value)
            ),
        )
        if expected is None:
            for field in expression.fields:
                self._visit_expression(field.value)
            self._error("Cannot infer type of struct literal", expression)
            return UNKNOWN
        field_types = self._struct_fields(expected)
        positional_fields = tuple(field_types)
        for index, field in enumerate(expression.fields):
            expected_field = field.name
            if expected_field is None:
                if index >= len(positional_fields):
                    self._error(
                        f"Too many values for struct literal {expected.display_name}",
                        field,
                    )
                    continue
                expected_field = positional_fields[index]
            expected_type = field_types.get(expected_field)
            if expected_type is None:
                self._error(
                    f"Type {expected.display_name} has no field '{expected_field}'",
                    field,
                )
                continue
            field_struct_expected = self._struct_literal_expected_type(expected_type)
            if isinstance(field.value, StructLiteralExpression) and isinstance(field_struct_expected, StructType):
                actual = self._struct_literal_type(field.value, field_struct_expected)
                self.types.expressions[id(field.value)] = actual
            else:
                actual = self._visit_expression_with_expected(
                    field.value, expected_type
                )
            self._check_assignable(actual, expected_type, field.value)
        return expected

    def _struct_literal_expected_type(self, type_: Type | None) -> StructType | None:
        if isinstance(type_, StructType):
            return type_
        if isinstance(type_, NullableType) and isinstance(type_.inner_type, StructType):
            return type_.inner_type
        return None

    def _struct_fields(self, type_: StructType) -> dict[str, Type]:
        symbol = type_.symbol
        if symbol is None:
            return {}
        node = symbol.node
        fields: tuple[VariableDeclaration, ...]
        if isinstance(node, ClassDeclaration):
            fields = tuple(member for member in node.members if isinstance(member, VariableDeclaration))
        elif isinstance(node, EnumDeclaration) and isinstance(node.value_type, InlineStructType):
            fields = node.value_type.fields
        else:
            fields = ()
        return {
            field.name: self._type_from_reference(field.type) if field.type is not None else UNKNOWN
            for field in fields
        }

    def _bulk_call_type(self, expression: BulkCallExpression) -> Type:
        callee_type = self._visit_expression(expression.callee)
        child_outcomes = [*self._outcomes_of(expression.callee)]
        if isinstance(callee_type, ArrayType) and not expression.task and not expression.generator:
            if len(expression.arguments) != 1:
                self._error("Index expression expects one index", expression)
                for argument in expression.arguments:
                    self._visit_expression(argument)
                return UNKNOWN
            index_type = self._visit_expression(expression.arguments[0])
            self._check_assignable(index_type, INT, expression.arguments[0])
            self._set_outcomes(
                expression,
                (*child_outcomes, *self._outcomes_of(expression.arguments[0])),
            )
            return callee_type.element_type
        if not isinstance(callee_type, FunctionType):
            if not is_unknown(callee_type):
                self._error(f"Cannot bulk-call value of type {callee_type.display_name}", expression)
            return UNKNOWN
        bulk_outcomes = tuple(child_outcomes)
        if not expression.task:
            bulk_outcomes = (*bulk_outcomes, *callee_type.outcomes)
        self._set_outcomes(expression, bulk_outcomes)
        if expression.generator:
            self._error("Generator bulk calls are not implemented yet", expression)
            return UNKNOWN
        if expression.task:
            return self._task_bulk_call_type(expression, callee_type)
        if all(isinstance(argument, BulkArgumentPack) for argument in expression.arguments):
            for pack in expression.arguments:
                self._check_bulk_argument_pack(pack, callee_type, expression.callee)
            return ArrayType(f"{callee_type.return_type.name}[]", callee_type.return_type)
        if len(expression.arguments) == 1:
            argument_type = self._visit_expression(expression.arguments[0])
            if isinstance(argument_type, ArrayType) and len(callee_type.parameter_types) == 1:
                self._check_call_argument_assignable(
                    argument_type.element_type,
                    callee_type.parameter_types[0],
                    expression.arguments[0],
                )
                if callee_type.return_type == VOID:
                    return VOID
                return ArrayType(f"{callee_type.return_type.name}[]", callee_type.return_type)
        if len(expression.arguments) == len(callee_type.parameter_types):
            for argument, expected in zip(expression.arguments, callee_type.parameter_types):
                actual = self.types.type_of(argument) or self._visit_expression(argument)
                self._check_call_argument_assignable(actual, expected, argument)
            return callee_type.return_type
        if len(callee_type.parameter_types) == 1 and len(expression.arguments) > 1:
            expected = callee_type.parameter_types[0]
            for argument in expression.arguments:
                actual = self._visit_expression(argument)
                self._check_call_argument_assignable(actual, expected, argument)
            if callee_type.return_type == VOID:
                return VOID
            return ArrayType(f"{callee_type.return_type.name}[]", callee_type.return_type)
        for argument in expression.arguments:
            self._visit_expression(argument)
        self._error("Bulk calls over this argument shape are not implemented yet", expression)
        return UNKNOWN

    def _task_bulk_call_type(
        self,
        expression: BulkCallExpression,
        callee_type: FunctionType,
    ) -> Type:
        if not self._call_is_async_function(expression.callee):
            self._error("Task bulk calls require an async function", expression.callee)
            return UNKNOWN
        if len(expression.arguments) == 1:
            argument_type = self._visit_expression(expression.arguments[0])
            if isinstance(argument_type, ArrayType) and len(callee_type.parameter_types) == 1:
                self._check_call_argument_assignable(
                    argument_type.element_type,
                    callee_type.parameter_types[0],
                    expression.arguments[0],
                )
                self._set_task_outcomes(expression, callee_type.outcomes)
                return TaskCollectionType(
                    f"TaskCollection<{callee_type.return_type.display_name}>",
                    callee_type.return_type,
                )
        self._error("Task bulk calls require one array argument", expression)
        return UNKNOWN

    def _check_bulk_argument_pack(
        self,
        pack: BulkArgumentPack,
        callee_type: FunctionType,
        callee: Expression,
    ) -> None:
        for argument in pack.arguments:
            self._visit_expression(argument)
        if len(pack.arguments) != len(callee_type.parameter_types):
            target = self._call_target_name(callee) or callee_type.name
            self._error(
                f"Expected {len(callee_type.parameter_types)} arguments for {target}, "
                f"got {len(pack.arguments)}",
                pack,
            )
            return
        for argument, expected in zip(pack.arguments, callee_type.parameter_types):
            actual = self.types.type_of(argument) or UNKNOWN
            self._check_call_argument_assignable(actual, expected, argument)

    def _check_call_argument_assignable(
        self,
        actual: Type,
        expected: Type,
        node: Node,
    ) -> None:
        if expected == STRING and self._implements_stringable(actual):
            return
        self._check_assignable(actual, expected, node)

    def _implements_stringable(self, type_: Type) -> bool:
        if type_ == STRING:
            return True
        if isinstance(type_, BuiltinType) and type_ not in {VOID, NULL, UNKNOWN}:
            return True
        if not isinstance(type_, ClassType) or type_.symbol is None:
            return False
        declaration = type_.symbol.node
        if not isinstance(declaration, ClassDeclaration):
            return False
        return any(reference.name == "Stringable" for reference in declaration.implements)

    def _call_target_name(self, callee: Expression) -> str | None:
        if isinstance(callee, IdentifierExpression):
            return callee.name
        if isinstance(callee, MemberExpression):
            receiver_type = self.types.type_of(callee.receiver)
            if isinstance(receiver_type, ClassType):
                return f"{receiver_type.name}.{callee.member}"
            return callee.member
        return None

    def _call_is_async_function(self, callee: Expression) -> bool:
        symbol = self._selected_symbols.get(id(callee))
        if symbol is None:
            symbol = self.resolution.resolutions.symbol_for(callee)
        return (
            isinstance(symbol, Symbol)
            and isinstance(symbol.node, FunctionDeclaration)
            and "async" in symbol.node.modifiers
        )

    def _member_type(self, expression: MemberExpression) -> Type:
        if expression.member == "await":
            receiver_type = self._with_preferred_async_call(
                expression.receiver,
                lambda: self._visit_expression(expression.receiver),
            )
        else:
            receiver_type = self._visit_expression(expression.receiver)
        if isinstance(receiver_type, NullableType):
            if expression.null_safe:
                member_type = self._member_type_for_receiver(
                    receiver_type.inner_type,
                    expression,
                )
                return self._nullable_type(member_type)
            if not self._is_non_null(expression.receiver):
                self._error(
                    f"Cannot access member '{expression.member}' on nullable "
                    f"{receiver_type.display_name} without a non-null check",
                    expression,
                )
                return UNKNOWN
            receiver_type = receiver_type.inner_type
        return self._member_type_for_receiver(receiver_type, expression)

    def _member_type_for_receiver(
        self,
        receiver_type: Type,
        expression: MemberExpression,
    ) -> Type:
        if isinstance(receiver_type, TaskType):
            if expression.member == "await":
                return FunctionType(
                    "await",
                    (),
                    receiver_type.result_type,
                    outcomes=self._task_outcomes_of(expression.receiver),
                )
            self._error(
                f"Type {receiver_type.display_name} has no member '{expression.member}'",
                expression,
            )
            return UNKNOWN
        if isinstance(receiver_type, TaskCollectionType):
            receiver_outcomes = self._task_outcomes_of(expression.receiver)
            if expression.member == "all":
                result_type = ArrayType(
                    f"{receiver_type.result_type.name}[]",
                    receiver_type.result_type,
                )
                task_type = TaskType(
                    f"Task<{result_type.display_name}>",
                    result_type,
                )
                self._set_task_outcomes(expression, receiver_outcomes)
                return FunctionType(
                    "all",
                    (),
                    task_type,
                )
            if expression.member in {"any", "first", "last"}:
                task_type = TaskType(
                    f"Task<{receiver_type.result_type.display_name}>",
                    receiver_type.result_type,
                )
                self._set_task_outcomes(expression, receiver_outcomes)
                return FunctionType(
                    expression.member,
                    (),
                    task_type,
                )
            if expression.member == "concurrency":
                self._set_task_outcomes(expression, receiver_outcomes)
                return FunctionType("concurrency", (INT,), receiver_type)
            self._error(
                f"Type {receiver_type.display_name} has no member '{expression.member}'",
                expression,
            )
            return UNKNOWN
        if isinstance(receiver_type, ArrayType):
            if expression.member == "len" and receiver_type.size is None:
                return INT
            self._error(
                f"Type {receiver_type.display_name} has no member '{expression.member}'",
                expression,
            )
            return UNKNOWN
        if isinstance(receiver_type, BuiltinType):
            if receiver_type == STRING:
                is_static = self._is_class_receiver(expression.receiver)
                intrinsic = string_intrinsic(expression.member, static=is_static)
                if intrinsic is not None:
                    return FunctionType(
                        intrinsic.name,
                        tuple(
                            self._intrinsic_type(type_name)
                            for type_name in intrinsic.parameter_types
                        ),
                        self._intrinsic_type(intrinsic.return_type),
                    )
                opposite = STRING_INTRINSICS.get(expression.member)
                if opposite is not None:
                    receiver_kind = "instance" if opposite.static else "class"
                    self._error(
                        f"Cannot access {'static' if opposite.static else 'instance'} "
                        f"member '{expression.member}' through {receiver_kind}",
                        expression,
                    )
                    return UNKNOWN
            if expression.member == "toString" and receiver_type not in {VOID, NULL, UNKNOWN}:
                if self._is_class_receiver(expression.receiver):
                    self._error(
                        "Cannot access instance member 'toString' through class",
                        expression,
                    )
                    return UNKNOWN
                return FunctionType("toString", (), STRING)
            self._error(
                f"Type {receiver_type.display_name} has no member '{expression.member}'",
                expression,
            )
            return UNKNOWN
        if isinstance(receiver_type, EnumType) and receiver_type.symbol is not None:
            enum_declaration = receiver_type.symbol.node
            if not isinstance(enum_declaration, EnumDeclaration):
                return UNKNOWN
            enum_scope = self.resolution.analysis.annotations.scope_for(enum_declaration)
            if enum_scope is None:
                return UNKNOWN
            member_symbol = enum_scope.symbols.get(expression.member)
            if member_symbol is None:
                self._error(
                    f"Type {receiver_type.display_name} has no member '{expression.member}'",
                    expression,
                )
                return UNKNOWN
            self._selected_symbols[id(expression)] = member_symbol
            return self._member_symbol_type(member_symbol, enum_declaration)
        if isinstance(receiver_type, StructType) and receiver_type.symbol is not None:
            struct_declaration = receiver_type.symbol.node
            struct_scope = self.resolution.analysis.annotations.scope_for(struct_declaration)
            if struct_scope is None:
                return UNKNOWN
            member_symbol = struct_scope.symbols.get(expression.member)
            if member_symbol is None:
                self._error(
                    f"Type {receiver_type.display_name} has no member '{expression.member}'",
                    expression,
                )
                return UNKNOWN
            self._check_member_receiver_kind(expression, member_symbol)
            self._selected_symbols[id(expression)] = member_symbol
            return self._member_symbol_type(member_symbol, struct_declaration)
        if isinstance(receiver_type, InterfaceType) and receiver_type.symbol is not None:
            interface_declaration = receiver_type.symbol.node
            if not isinstance(interface_declaration, ClassDeclaration):
                return UNKNOWN
            interface_scope = self.resolution.analysis.annotations.scope_for(interface_declaration)
            if interface_scope is None:
                return UNKNOWN
            member_symbol = interface_scope.symbols.get(expression.member)
            if member_symbol is None:
                self._error(
                    f"Type {receiver_type.display_name} has no member '{expression.member}'",
                    expression,
                )
                return UNKNOWN
            self._selected_symbols[id(expression)] = member_symbol
            return self._member_symbol_type(member_symbol, interface_declaration)
        if not isinstance(receiver_type, ClassType) or receiver_type.symbol is None:
            return UNKNOWN
        class_declaration = receiver_type.symbol.node
        if not isinstance(class_declaration, ClassDeclaration):
            return UNKNOWN
        class_scope = self.resolution.analysis.annotations.scope_for(class_declaration)
        if class_scope is None:
            return UNKNOWN
        member_symbol = class_scope.symbols.get(expression.member)
        if member_symbol is None:
            member_symbol = self._used_trait_member_symbol(class_declaration, expression.member)
        if member_symbol is None:
            self._error(
                f"Type {receiver_type.display_name} has no member '{expression.member}'",
                expression,
            )
            return UNKNOWN
        self._check_member_receiver_kind(expression, member_symbol)
        self._selected_symbols[id(expression)] = member_symbol
        return self._member_symbol_type(member_symbol, class_declaration)

    def _used_trait_member_symbol(
        self,
        declaration: ClassDeclaration,
        name: str,
    ) -> Symbol | None:
        found: Symbol | None = None
        for trait in self._used_trait_declarations(declaration):
            trait_scope = self.resolution.analysis.annotations.scope_for(trait)
            if trait_scope is None:
                continue
            candidate = trait_scope.symbols.get(name)
            if candidate is None:
                continue
            if found is not None:
                return None
            found = candidate
        return found

    def _check_member_receiver_kind(
        self,
        expression: MemberExpression,
        member_symbol: Symbol,
    ) -> None:
        member_node = member_symbol.node
        if not isinstance(member_node, (FunctionDeclaration, VariableDeclaration)):
            return
        is_static_member = (
            isinstance(member_node, FunctionDeclaration)
            and (member_node.kind == "new" or "static" in member_node.modifiers)
        ) or (
            isinstance(member_node, VariableDeclaration)
            and "static" in member_node.modifiers
        )
        is_class_receiver = self._is_class_receiver(expression.receiver)
        if is_class_receiver and not is_static_member:
            self._error(
                f"Cannot access instance member '{expression.member}' through class",
                expression,
            )
        if not is_class_receiver and is_static_member:
            self._error(
                f"Cannot access static member '{expression.member}' through instance",
                expression,
            )

    def _is_class_receiver(self, expression: Expression) -> bool:
        resolved = self.resolution.resolutions.symbol_for(expression)
        return (
            isinstance(resolved, Symbol)
            and isinstance(resolved.node, (ClassDeclaration, EnumDeclaration))
        ) or isinstance(resolved, BuiltinSymbol) or (
            isinstance(resolved, SpecialSymbol)
            and resolved.kind == "self"
        )

    def _intrinsic_type(self, name: str) -> Type:
        if name.endswith("[]"):
            element_type = builtin_type(name[:-2])
            return ArrayType(name, element_type)
        return builtin_type(name)

    def _nullable_type(self, type_: Type) -> Type:
        if isinstance(type_, NullableType) or type_ == UNKNOWN:
            return type_
        return NullableType(f"{type_.name}?", type_)

    def _member_symbol_type(
        self,
        member_symbol: Symbol,
        class_declaration: ClassDeclaration | EnumDeclaration,
    ) -> Type:
        existing = self.types.symbols.get(id(member_symbol.node))
        if existing is not None:
            return existing
        if isinstance(member_symbol.node, FunctionDeclaration):
            result = self._function_type(member_symbol.node, class_declaration)
        elif isinstance(member_symbol.node, EnumVariant):
            enum_symbol = self.resolution.analysis.annotations.symbol_for(class_declaration)
            result = EnumType(
                class_declaration.name or "<anonymous enum>",
                enum_symbol,
                self._enum_value_type(class_declaration) if isinstance(class_declaration, EnumDeclaration) else None,
            )
        elif isinstance(member_symbol.node, VariableDeclaration):
            result = (
                self._type_from_reference(member_symbol.node.type)
                if member_symbol.node.type is not None
                else UNKNOWN
            )
        else:
            result = UNKNOWN
        self.types.symbols[id(member_symbol.node)] = result
        return result

    def _index_type(self, expression: IndexExpression) -> Type:
        receiver_type = self._visit_expression(expression.receiver)
        index_type = self._visit_expression(expression.index)
        self._check_assignable(index_type, INT, expression.index)
        if hasattr(receiver_type, "element_type"):
            return receiver_type.element_type
        if not is_unknown(receiver_type):
            self._error(f"Cannot index value of type {receiver_type.display_name}", expression)
        return UNKNOWN

    def _type_from_reference(self, reference: TypeReference | None) -> Type:
        if reference is None:
            return VOID
        resolved = self.resolution.resolutions.symbol_for(reference)
        if isinstance(resolved, BuiltinSymbol):
            if resolved.name in {"Task", "task"}:
                base = self._task_type_from_reference(reference)
            elif resolved.name in {"TaskCollection", "taskCollection"}:
                base = self._task_collection_type_from_reference(reference)
            else:
                base = builtin_type(resolved.name)
        elif isinstance(resolved, BuiltinInterfaceSymbol):
            base = InterfaceType(resolved.name)
        elif isinstance(resolved, SpecialSymbol):
            class_symbol = self.resolution.analysis.annotations.symbol_for(resolved.node)
            if isinstance(resolved.node, EnumDeclaration):
                base = EnumType(
                    resolved.node.name or "<anonymous enum>",
                    class_symbol,
                    self._enum_value_type(resolved.node),
                )
            elif resolved.node.kind == "struct":
                base = StructType(resolved.node.name or "<anonymous struct>", class_symbol)
            else:
                base = ClassType(resolved.node.name or "<anonymous class>", class_symbol)
        elif isinstance(resolved, Symbol) and isinstance(resolved.node, ClassDeclaration) and resolved.node.kind == "interface":
            base = InterfaceType(resolved.name, resolved)
        elif isinstance(resolved, Symbol) and isinstance(resolved.node, ClassDeclaration) and resolved.node.kind == "struct":
            base = StructType(resolved.name, resolved)
        elif isinstance(resolved, Symbol) and isinstance(resolved.node, ClassDeclaration):
            base = ClassType(resolved.name, resolved)
        elif isinstance(resolved, Symbol) and isinstance(resolved.node, EnumDeclaration):
            base = EnumType(resolved.name, resolved, self._enum_value_type(resolved.node))
        else:
            base = UNKNOWN
        if reference.arguments and not isinstance(base, (TaskType, TaskCollectionType)):
            self._error(
                f"Type {base.display_name} does not accept type arguments",
                reference,
            )
        result = apply_type_modifiers(
            base,
            array_depth=reference.array_depth,
            nullable=reference.nullable,
            array_sizes=self._array_sizes(reference),
        )
        self.types.type_references[id(reference)] = result
        return result

    def _task_type_from_reference(self, reference: TypeReference) -> Type:
        if len(reference.arguments) != 1:
            self._error("Task requires exactly one type argument", reference)
            return UNKNOWN
        result_type = self._type_from_reference(reference.arguments[0])
        return TaskType(f"Task<{result_type.display_name}>", result_type)

    def _task_collection_type_from_reference(self, reference: TypeReference) -> Type:
        if len(reference.arguments) != 1:
            self._error("TaskCollection requires exactly one type argument", reference)
            return UNKNOWN
        result_type = self._type_from_reference(reference.arguments[0])
        return TaskCollectionType(
            f"TaskCollection<{result_type.display_name}>",
            result_type,
        )

    def _array_sizes(self, reference: TypeReference) -> tuple[int | None, ...]:
        if not reference.array_dimensions:
            return (None,) * reference.array_depth
        sizes: list[int | None] = []
        for dimension in reference.array_dimensions:
            if dimension is None:
                sizes.append(None)
                continue
            size = self._constant_int_expression(dimension)
            if size is None:
                self._error("Array size must be a compile-time integer constant", dimension)
                sizes.append(None)
                continue
            if size < 0:
                self._error("Array size cannot be negative", dimension)
                sizes.append(None)
                continue
            sizes.append(size)
        return tuple(sizes)

    def _constant_int_expression(self, expression: Expression) -> int | None:
        if isinstance(expression, LiteralExpression) and isinstance(expression.value, int):
            return expression.value
        if isinstance(expression, GroupingExpression):
            return self._constant_int_expression(expression.expression)
        if isinstance(expression, UnaryExpression):
            value = self._constant_int_expression(expression.operand)
            if value is None:
                return None
            if expression.operator is TokenKind.MINUS:
                return -value
            return None
        if isinstance(expression, BinaryExpression):
            left = self._constant_int_expression(expression.left)
            right = self._constant_int_expression(expression.right)
            if left is None or right is None:
                return None
            if expression.operator is TokenKind.PLUS:
                return left + right
            if expression.operator is TokenKind.MINUS:
                return left - right
            if expression.operator is TokenKind.STAR:
                return left * right
            if expression.operator is TokenKind.SLASH:
                return None if right == 0 else left // right
            if expression.operator is TokenKind.PERCENT:
                return None if right == 0 else left % right
        return None

    def _check_assignable(self, actual: Type, expected: Type, node: Node) -> None:
        if not is_assignable(actual, expected):
            self._error(
                f"Cannot assign {actual.display_name} to {expected.display_name}",
                node,
            )

    def _check_condition_type(self, actual: Type, node: Node) -> None:
        if isinstance(actual, NullableType):
            return
        self._check_assignable(actual, BOOL, node)

    def _with_non_null(self, key: str | None, callback):
        if key is None:
            return callback()
        self._non_null_stack.append({key})
        try:
            return callback()
        finally:
            self._non_null_stack.pop()

    def _is_non_null(self, expression: Expression) -> bool:
        key = self._narrowed_key(expression)
        return key is not None and any(key in scope for scope in reversed(self._non_null_stack))

    def _narrowed_key(self, expression: Expression) -> str | None:
        if isinstance(expression, IdentifierExpression):
            symbol = self.resolution.resolutions.symbol_for(expression)
            if isinstance(symbol, Symbol):
                return f"symbol:{id(symbol.node)}"
            return None
        if isinstance(expression, ThisExpression):
            return "this"
        if isinstance(expression, SelfExpression):
            return "self"
        if isinstance(expression, GroupingExpression):
            return self._narrowed_key(expression.expression)
        if isinstance(expression, MemberExpression):
            receiver_key = self._narrowed_key(expression.receiver)
            if receiver_key is None:
                return None
            return f"{receiver_key}.{expression.member}"
        return None

    def _then_narrowed_key(self, expression: Expression) -> str | None:
        comparison = self._null_comparison(expression)
        if comparison is not None:
            compared, operator = comparison
            return self._narrowed_key(compared) if operator is TokenKind.BANG_EQUAL else None
        return self._narrowed_key(expression)

    def _else_narrowed_key(self, expression: Expression) -> str | None:
        comparison = self._null_comparison(expression)
        if comparison is not None:
            compared, operator = comparison
            return self._narrowed_key(compared) if operator is TokenKind.EQUAL_EQUAL else None
        return None

    def _null_comparison(self, expression: Expression) -> tuple[Expression, TokenKind] | None:
        if not isinstance(expression, BinaryExpression):
            return None
        if expression.operator not in {TokenKind.EQUAL_EQUAL, TokenKind.BANG_EQUAL}:
            return None
        if isinstance(expression.left, LiteralExpression) and expression.left.value is None:
            return (expression.right, expression.operator)
        if isinstance(expression.right, LiteralExpression) and expression.right.value is None:
            return (expression.left, expression.operator)
        return None
