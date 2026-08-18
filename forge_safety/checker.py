"""Ownership and resource-safety checks for Forge programs."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from forge_analysis import Diagnostic, Symbol
from forge_normalizer import normalize
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
    UnaryExpression,
    UseDeclaration,
    VariableDeclaration,
    WhileStatement,
    WhileExpression,
)
from forge_parser.ast import Node
from forge_typecheck import (
    ClassType,
    FunctionType,
    NullableType,
    StructType,
    Type,
    TypeCheckResult,
    check_types,
)

Availability = Literal["available", "terminated", "moved"]
Ownership = Literal["value", "owner", "borrow"]


@dataclass(frozen=True, slots=True)
class BindingState:
    """Safety state for a local binding or parameter."""

    ownership: Ownership
    availability: Availability = "available"
    borrowed_from: Symbol | None = None
    dependencies: tuple[Symbol, ...] = ()


@dataclass(slots=True)
class SafetyTable:
    """Side-table safety annotations keyed by declaration symbols."""

    states: dict[int, BindingState] = field(default_factory=dict)

    def state_of_symbol(self, symbol: Symbol) -> BindingState | None:
        return self.states.get(id(symbol.node))


@dataclass(frozen=True, slots=True)
class SafetyCheckResult:
    program: Program
    typecheck: TypeCheckResult
    diagnostics: tuple[Diagnostic, ...]
    safety: SafetyTable

    @property
    def ok(self) -> bool:
        return self.typecheck.ok and not any(
            diagnostic.severity == "error" for diagnostic in self.diagnostics
        )


class SafetyCheckError(Exception):
    """Raised when ownership/resource-safety checks fail."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        first = diagnostics[0]
        super().__init__(f"{first.message} at {first.location.format()}")


def check_safety(
    program_or_typecheck: Program | TypeCheckResult,
    *,
    raise_on_error: bool = True,
) -> SafetyCheckResult:
    """Run Forge ownership/resource-safety checks."""

    typecheck = (
        check_types(normalize(program_or_typecheck), raise_on_error=False)
        if isinstance(program_or_typecheck, Program)
        else program_or_typecheck
    )
    checker = _SafetyChecker(typecheck)
    result = checker.run()
    if raise_on_error and not result.ok:
        resolution = typecheck.resolution
        diagnostics = tuple(
            diagnostic
            for diagnostic in (
                *resolution.analysis.diagnostics,
                *resolution.diagnostics,
                *typecheck.diagnostics,
                *result.diagnostics,
            )
            if diagnostic.severity == "error"
        )
        raise SafetyCheckError(diagnostics)
    return result


class _SafetyChecker:
    def __init__(self, typecheck: TypeCheckResult) -> None:
        self.typecheck = typecheck
        self.program = typecheck.program
        self.diagnostics: list[Diagnostic] = []
        self.safety = SafetyTable()
        self._states: dict[int, BindingState] = {}
        self._function_stack: list[FunctionDeclaration] = []
        self._loop_result_type_stack: list[Type | None] = []
        self._active_borrows: dict[int, int] = {}

    def run(self) -> SafetyCheckResult:
        self._validate_class_terminators(self.program.declarations)
        self._validate_owned_field_initialization(self.program.declarations)
        for declaration in self.program.declarations:
            self._visit_declaration_or_statement(declaration)
        self.safety.states.update(self._states)
        return SafetyCheckResult(
            self.program,
            self.typecheck,
            tuple(self.diagnostics),
            self.safety,
        )

    def _error(self, message: str, node: Node) -> None:
        self.diagnostics.append(Diagnostic(message, node.location))

    def _validate_class_terminators(
        self, declarations: tuple[Declaration | Statement, ...]
    ) -> None:
        for declaration in declarations:
            if not isinstance(declaration, ClassDeclaration):
                continue
            terminate_methods = [
                member
                for member in declaration.members
                if isinstance(member, FunctionDeclaration)
                and "terminate" in member.modifiers
            ]
            if len(terminate_methods) > 1:
                self._error("Class can declare at most one terminate method", terminate_methods[1])

    def _validate_owned_field_initialization(
        self,
        declarations: tuple[Declaration | Statement, ...],
    ) -> None:
        for declaration in declarations:
            if not isinstance(declaration, ClassDeclaration):
                continue
            required_fields = {
                member.name
                for member in declaration.members
                if isinstance(member, VariableDeclaration)
                and "static" not in member.modifiers
                and member.initializer is None
                and self._is_non_nullable_resource_type(self.typecheck.types.type_of(member))
            }
            if not required_fields:
                continue
            constructors = [
                member
                for member in declaration.members
                if isinstance(member, FunctionDeclaration) and member.kind == "new"
            ]
            for constructor in constructors:
                initialized = self._constructor_initialized_fields(constructor)
                for field_name in sorted(required_fields - initialized):
                    self._error(
                        f"Owned field '{field_name}' must be initialized by constructor",
                        constructor,
                    )

    def _constructor_initialized_fields(
        self,
        constructor: FunctionDeclaration,
    ) -> set[str]:
        initialized: set[str] = set()
        if not isinstance(constructor.body, BlockStatement):
            return initialized
        for statement in constructor.body.statements:
            self._collect_constructor_assignment(statement, initialized)
        return initialized

    def _collect_constructor_assignment(
        self,
        node: Declaration | Statement,
        initialized: set[str],
    ) -> None:
        if isinstance(node, ExpressionStatement):
            self._collect_constructor_expression(node.expression, initialized)
        elif isinstance(node, BlockStatement):
            for child in node.statements:
                self._collect_constructor_assignment(child, initialized)
        elif isinstance(node, IfStatement):
            then_fields = set(initialized)
            self._collect_constructor_assignment(node.then_branch, then_fields)
            else_fields = set(initialized)
            if node.else_branch is not None:
                self._collect_constructor_assignment(node.else_branch, else_fields)
            initialized.update(then_fields & else_fields)
        elif isinstance(node, WhileStatement):
            return
        elif isinstance(node, ForStatement):
            return

    def _collect_constructor_expression(
        self,
        expression: Expression,
        initialized: set[str],
    ) -> None:
        if isinstance(expression, AssignmentExpression):
            target = expression.target
            if (
                isinstance(target, MemberExpression)
                and isinstance(target.receiver, ThisExpression)
            ):
                initialized.add(target.member)
        elif isinstance(expression, MemberBlockExpression):
            for child in expression.expressions:
                self._collect_constructor_expression(child, initialized)

    def _visit_declaration_or_statement(self, node: Declaration | Statement) -> bool:
        if isinstance(node, Declaration):
            self._visit_declaration(node)
            return True
        else:
            return self._visit_statement(node)

    def _visit_declaration(self, declaration: Declaration) -> None:
        if isinstance(declaration, ClassDeclaration):
            for member in declaration.members:
                if isinstance(member, FunctionDeclaration):
                    self._visit_function(member)
        elif isinstance(declaration, EnumDeclaration):
            for variant in declaration.variants:
                if variant.value is not None:
                    self._visit_expression(variant.value)
            for member in declaration.members:
                if isinstance(member, FunctionDeclaration):
                    self._visit_function(member)
        elif isinstance(declaration, FunctionDeclaration):
            self._visit_function(declaration)
        elif isinstance(declaration, VariableDeclaration):
            self._visit_variable(declaration)
        elif isinstance(declaration, ArrayDestructuringDeclaration):
            self._visit_array_destructuring(declaration)
        elif isinstance(declaration, UseDeclaration):
            return

    def _visit_function(self, declaration: FunctionDeclaration) -> None:
        saved_states = self._states
        self._states = {}
        for parameter in declaration.parameters:
            self._visit_parameter(parameter)
        self._function_stack.append(declaration)
        if isinstance(declaration.body, BlockStatement):
            self._visit_statement(declaration.body)
        elif declaration.body is not None:
            self._visit_return(
                ReturnStatement(declaration.body.location, declaration.body)
            )
        self._function_stack.pop()
        self.safety.states.update(self._states)
        self._states = saved_states

    def _visit_parameter(self, parameter: Parameter) -> None:
        symbol = self._symbol_for(parameter)
        if symbol is None:
            return
        type_ = self.typecheck.types.type_of(parameter)
        if parameter.ownership == "take" and self._is_resource_type(type_):
            self._states[id(symbol.node)] = BindingState("owner")
            return
        self._states[id(symbol.node)] = (
            BindingState("borrow") if self._is_resource_type(type_) else BindingState("value")
        )

    def _visit_variable(self, declaration: VariableDeclaration) -> None:
        if declaration.initializer is not None:
            self._visit_expression(declaration.initializer)
            borrowed, _ = self._borrowed_result_origin(declaration.initializer)
            if borrowed:
                self._error(
                    "Borrowed return can only be used in scoped using or as a temporary",
                    declaration.initializer,
                )
        symbol = self._symbol_for(declaration)
        if symbol is None:
            return
        type_ = self.typecheck.types.type_of(declaration)
        self._states[id(symbol.node)] = self._initial_state(type_, declaration.initializer)

    def _visit_array_destructuring(
        self, declaration: ArrayDestructuringDeclaration
    ) -> None:
        self._visit_expression(declaration.initializer)
        borrowed_from = self._array_source_symbol(declaration.initializer)
        for binding in declaration.bindings:
            symbol = self._symbol_for(binding)
            if symbol is None:
                continue
            type_ = self.typecheck.types.type_of(binding)
            self._states[id(symbol.node)] = (
                BindingState("borrow", borrowed_from=borrowed_from)
                if self._is_resource_type(type_)
                else BindingState("value")
            )

    def _array_source_symbol(self, expression: Expression) -> Symbol | None:
        if isinstance(expression, CatchExpression):
            expression = expression.expression
        if not isinstance(expression, IdentifierExpression):
            return None
        return self._resolved_symbol(expression)

    def _visit_statement(self, statement: Statement) -> bool:
        if isinstance(statement, BlockStatement):
            for child in statement.statements:
                if not self._visit_declaration_or_statement(child):
                    return False
            return True
        elif isinstance(statement, PrintStatement):
            self._visit_expression(statement.expression)
            return True
        elif isinstance(statement, ReturnStatement):
            self._visit_return(statement)
            return False
        elif isinstance(statement, BreakStatement):
            if statement.expression is not None:
                self._visit_expression(statement.expression)
                self._check_break_transfer(statement)
            return False
        elif isinstance(statement, IfStatement):
            return self._visit_if(statement)
        elif isinstance(statement, SwitchStatement):
            self._visit_expression(statement.expression)
            continues = False
            for arm in statement.arms:
                if arm.pattern is not None:
                    self._visit_expression(arm.pattern)
                continues = self._visit_statement(arm.body) or continues
            return continues
        elif isinstance(statement, WhileStatement):
            return self._visit_while(statement)
        elif isinstance(statement, DoWhileStatement):
            before = dict(self._states)
            self._loop_result_type_stack.append(None)
            self._visit_statement(statement.body)
            self._loop_result_type_stack.pop()
            self._visit_expression(statement.condition)
            self._states = before
            return True
        elif isinstance(statement, ForStatement):
            return self._visit_for(statement)
        elif isinstance(statement, BorrowScopeStatement):
            return self._visit_borrow_scope(statement)
        elif isinstance(statement, ExpressionStatement):
            self._visit_expression(statement.expression)
            return True
        return True

    def _visit_borrow_scope(self, statement: BorrowScopeStatement) -> bool:
        self._visit_expression(statement.source)
        borrowed, origin = self._borrowed_result_origin(statement.source)
        if not borrowed:
            self._error("Scoped using requires a borrowed return value", statement.source)
            return self._visit_statement(statement.body)
        if not isinstance(origin, Symbol):
            self._error(
                "Borrowed return from a temporary owner cannot be used in scoped using",
                statement.source,
            )
            return self._visit_statement(statement.body)
        binding = self._symbol_for(statement.binding)
        before = dict(self._states)
        if binding is not None:
            binding_state = BindingState(
                "borrow",
                borrowed_from=origin,
            )
            self._states[id(binding.node)] = binding_state
            self.safety.states[id(binding.node)] = binding_state
        owner_id = id(origin.node)
        self._active_borrows[owner_id] = self._active_borrows.get(owner_id, 0) + 1
        try:
            return self._visit_statement(statement.body)
        finally:
            remaining = self._active_borrows[owner_id] - 1
            if remaining:
                self._active_borrows[owner_id] = remaining
            else:
                self._active_borrows.pop(owner_id, None)
            self._states = before

    def _visit_return(self, statement: ReturnStatement) -> None:
        if statement.expression is None:
            return
        self._visit_expression(statement.expression)
        if not self._function_stack:
            return
        function = self._function_stack[-1]
        function_type = self.typecheck.types.type_of(function)
        if (
            isinstance(function_type, FunctionType)
            and function_type.return_ownership == "borrow"
        ):
            actual = self._borrow_origin(statement.expression)
            expected: Symbol | str | None
            if function_type.return_borrow_source == "this":
                expected = "this"
            elif isinstance(function_type.return_borrow_source, int):
                parameter = function.parameters[function_type.return_borrow_source]
                expected = self._symbol_for(parameter)
            else:
                expected = None
            if actual != expected:
                self._error(
                    "Borrowed return must originate from its declared owner",
                    statement,
                )
            if isinstance(statement.expression, MoveExpression):
                self._error("Borrowed return cannot use 'move'", statement.expression)
            return
        return_type = getattr(function_type, "return_type", None)
        if not self._is_resource_type(return_type):
            return
        value_expression = (
            statement.expression.expression
            if isinstance(statement.expression, MoveExpression)
            else statement.expression
        )
        if isinstance(value_expression, LiteralExpression) and value_expression.value is None:
            return
        if not isinstance(value_expression, IdentifierExpression):
            return
        symbol = self._resolved_symbol(value_expression)
        if symbol is None:
            return
        state = self._states.get(id(symbol.node))
        if state is None:
            return
        if self._active_borrows.get(id(symbol.node), 0) > 0:
            self._error(
                f"Cannot move resource '{symbol.name}' while it is borrowed",
                expression,
            )
            return
        dependent = self._available_dependent(symbol)
        if dependent is not None:
            self._error(
                f"Cannot move resource '{symbol.name}' while '{dependent.name}' depends on it",
                expression,
            )
            return
        if state.ownership != "owner":
            self._error(f"Cannot return borrowed resource '{symbol.name}' as owned value", statement)
            return
        if state.dependencies:
            self._error(
                f"Cannot return resource '{symbol.name}' while it depends on borrowed owners",
                statement,
            )
            return
        if (
            not isinstance(statement.expression, MoveExpression)
            and not self._is_take_parameter_symbol(symbol)
        ):
            self._error(
                f"Returning owned resource '{symbol.name}' requires 'move'",
                statement,
            )
            return
        if state.availability != "available":
            return
        self._states[id(symbol.node)] = replace(state, availability="moved")

    def _visit_if(self, statement: IfStatement) -> bool:
        self._visit_expression(statement.condition)
        before = dict(self._states)

        self._states = dict(before)
        then_continues = self._visit_statement(statement.then_branch)
        then_states = dict(self._states)

        self._states = dict(before)
        if statement.else_branch is not None:
            else_continues = self._visit_statement(statement.else_branch)
        else_states = dict(self._states)
        if statement.else_branch is None:
            else_continues = True

        if then_continues and else_continues:
            self._states = self._merge_states(then_states, else_states)
            return True
        if then_continues:
            self._states = then_states
            return True
        if else_continues:
            self._states = else_states
            return True
        self._states = then_states
        return False

    def _visit_while(self, statement: WhileStatement) -> bool:
        self._visit_expression(statement.condition)
        before = dict(self._states)
        self._states = dict(before)
        self._loop_result_type_stack.append(None)
        self._visit_statement(statement.body)
        self._loop_result_type_stack.pop()
        self._states = before
        return True

    def _visit_for(self, statement: ForStatement) -> bool:
        self._visit_expression(statement.source)
        before = dict(self._states)
        self._states = dict(before)
        self._visit_variable(statement.item)
        self._loop_result_type_stack.append(None)
        self._visit_statement(statement.body)
        self._loop_result_type_stack.pop()
        self._states = before
        return True

    def _visit_expression(self, expression: Expression) -> None:
        if isinstance(expression, LiteralExpression):
            return
        if isinstance(expression, IdentifierExpression):
            self._check_identifier(expression)
        elif isinstance(expression, (ThisExpression, SelfExpression)):
            return
        elif isinstance(expression, GroupingExpression):
            self._visit_expression(expression.expression)
        elif isinstance(expression, GenericTypeExpression):
            self._visit_expression(expression.receiver)
        elif isinstance(expression, ForwardExpression):
            self._visit_expression(expression.expression)
        elif isinstance(expression, CatchExpression):
            self._visit_expression(expression.expression)
            for handler in expression.handlers:
                if isinstance(handler.expression, BlockStatement):
                    self._visit_statement(handler.expression)
                else:
                    self._visit_expression(handler.expression)
        elif isinstance(expression, UnaryExpression):
            self._visit_expression(expression.operand)
        elif isinstance(expression, MoveExpression):
            self._visit_move(expression)
        elif isinstance(expression, BinaryExpression):
            self._visit_expression(expression.left)
            self._visit_expression(expression.right)
        elif isinstance(expression, AssignmentExpression):
            self._visit_assignment(expression)
        elif isinstance(expression, ConditionalExpression):
            self._visit_expression(expression.condition)
            self._visit_expression(expression.then_expression)
            self._visit_expression(expression.else_expression)
        elif isinstance(expression, CallExpression):
            self._visit_call(expression)
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
            self._visit_expression(expression.receiver)
        elif isinstance(expression, MemberBlockExpression):
            self._visit_expression(expression.receiver)
            for child in expression.expressions:
                self._visit_expression(child)
        elif isinstance(expression, IndexExpression):
            self._visit_expression(expression.receiver)
            self._visit_expression(expression.index)
        elif isinstance(expression, WhileExpression):
            self._visit_expression(expression.condition)
            before = dict(self._states)
            self._loop_result_type_stack.append(
                self.typecheck.types.type_of(expression)
            )
            self._visit_statement(expression.body)
            self._loop_result_type_stack.pop()
            self._states = before
            if expression.fallback is not None:
                self._visit_expression(expression.fallback)
                self._check_loop_result_transfer(
                    expression.fallback,
                    self.typecheck.types.type_of(expression),
                    expression,
                )
        elif isinstance(expression, DoWhileExpression):
            before = dict(self._states)
            self._loop_result_type_stack.append(
                self.typecheck.types.type_of(expression)
            )
            self._visit_statement(expression.body)
            self._loop_result_type_stack.pop()
            self._visit_expression(expression.condition)
            self._states = before
            if expression.fallback is not None:
                self._visit_expression(expression.fallback)
                self._check_loop_result_transfer(
                    expression.fallback,
                    self.typecheck.types.type_of(expression),
                    expression,
                )
        elif isinstance(expression, ForExpression):
            self._visit_expression(expression.source)
            before = dict(self._states)
            self._visit_variable(expression.item)
            self._loop_result_type_stack.append(
                self.typecheck.types.type_of(expression)
            )
            self._visit_statement(expression.body)
            self._loop_result_type_stack.pop()
            self._states = before
            if expression.fallback is not None:
                self._visit_expression(expression.fallback)
                self._check_loop_result_transfer(
                    expression.fallback,
                    self.typecheck.types.type_of(expression),
                    expression,
                )

    def _check_break_transfer(self, statement: BreakStatement) -> None:
        if not self._loop_result_type_stack or statement.expression is None:
            return
        self._check_loop_result_transfer(
            statement.expression,
            self._loop_result_type_stack[-1],
            statement,
        )

    def _check_loop_result_transfer(
        self, expression: Expression, target_type: Type | None, node: Node
    ) -> None:
        if target_type is None or not self._is_resource_type(target_type):
            return
        if isinstance(expression, GroupingExpression):
            self._check_loop_result_transfer(expression.expression, target_type, node)
            return
        if isinstance(expression, ConditionalExpression):
            self._check_loop_result_transfer(
                expression.then_expression, target_type, node
            )
            self._check_loop_result_transfer(
                expression.else_expression, target_type, node
            )
            return
        value = (
            expression.expression
            if isinstance(expression, MoveExpression)
            else expression
        )
        if isinstance(value, LiteralExpression) and value.value is None:
            return
        if not isinstance(value, IdentifierExpression):
            if isinstance(value, MemberExpression):
                self._error(
                    "Cannot produce owned loop result from a borrowed resource member",
                    node,
                )
            return
        symbol = self._resolved_symbol(value)
        if symbol is None:
            return
        state = self._states.get(id(symbol.node))
        if state is None:
            return
        if state.ownership != "owner":
            self._error(
                f"Cannot produce owned loop result from borrowed resource '{symbol.name}'",
                node,
            )
        elif (
            not isinstance(expression, MoveExpression)
            and not self._is_take_parameter_symbol(symbol)
        ):
            self._error(
                f"Producing owned loop result from '{symbol.name}' requires 'move'",
                node,
            )

    def _visit_assignment(self, expression: AssignmentExpression) -> None:
        self._visit_expression(expression.value)
        self._visit_expression(expression.target)
        self._visit_field_transfer(expression)
        if not isinstance(expression.target, IdentifierExpression):
            return
        symbol = self._resolved_symbol(expression.target)
        if symbol is None:
            return
        target_type = self.typecheck.types.type_of(expression.target)
        if self._visit_local_transfer(expression, symbol, target_type):
            return
        self._states[id(symbol.node)] = self._initial_state(target_type, expression.value)

    def _visit_local_transfer(
        self,
        expression: AssignmentExpression,
        target_symbol: Symbol,
        target_type: Type | None,
    ) -> bool:
        if not self._is_resource_type(target_type):
            return False
        target_state = self._states.get(id(target_symbol.node))
        if target_state is not None and target_state.ownership != "owner":
            self._error(
                f"Cannot assign owned resource into borrowed local '{target_symbol.name}'",
                expression,
            )
            return True
        if isinstance(expression.value, LiteralExpression) and expression.value.value is None:
            self._states[id(target_symbol.node)] = BindingState("owner")
            return True

        value_expression = (
            expression.value.expression
            if isinstance(expression.value, MoveExpression)
            else expression.value
        )
        if not isinstance(value_expression, IdentifierExpression):
            self._states[id(target_symbol.node)] = BindingState("owner")
            return True
        source_symbol = self._resolved_symbol(value_expression)
        if source_symbol is None:
            self._states[id(target_symbol.node)] = BindingState("owner")
            return True
        source_state = self._states.get(id(source_symbol.node))
        if source_state is None:
            self._states[id(target_symbol.node)] = BindingState("owner")
            return True
        if source_state.ownership != "owner":
            self._error(
                f"Cannot assign borrowed resource '{source_symbol.name}' to owned local",
                expression,
            )
            return True
        if (
            source_symbol != target_symbol
            and not isinstance(expression.value, MoveExpression)
            and not self._is_take_parameter_symbol(source_symbol)
        ):
            self._error(
                f"Assigning owned resource '{source_symbol.name}' to owned local requires 'move'",
                expression,
            )
            return True
        if source_symbol != target_symbol and source_state.availability == "available":
            self._states[id(source_symbol.node)] = replace(source_state, availability="moved")
        self._states[id(target_symbol.node)] = BindingState("owner")
        return True

    def _visit_field_transfer(self, expression: AssignmentExpression) -> None:
        if not isinstance(expression.target, MemberExpression):
            return
        target_type = self.typecheck.types.type_of(expression.target)
        if not self._is_resource_type(target_type):
            return
        if isinstance(expression.value, LiteralExpression) and expression.value.value is None:
            return

        field_ownership = self._effective_field_ownership(expression.target)
        value_state = self._expression_state(expression.value)
        if field_ownership == "borrow":
            if isinstance(expression.value, MoveExpression):
                self._error("Cannot move ownership into a borrow field", expression)
                return
            if value_state is None or value_state.ownership != "borrow":
                self._error("Cannot assign owned resource to a borrow field", expression)
                return
            receiver_symbol = self._receiver_symbol(expression.target.receiver)
            origin = self._borrow_origin(expression.value)
            if receiver_symbol is not None and isinstance(origin, Symbol):
                receiver_state = self._states.get(id(receiver_symbol.node))
                if receiver_state is not None and origin not in receiver_state.dependencies:
                    self._states[id(receiver_symbol.node)] = replace(
                        receiver_state,
                        dependencies=(*receiver_state.dependencies, origin),
                    )
            return

        if value_state is not None and value_state.ownership != "owner":
            self._error("Cannot assign borrowed resource to a take field", expression)
            return
        value_expression = (
            expression.value.expression
            if isinstance(expression.value, MoveExpression)
            else expression.value
        )
        if not isinstance(value_expression, IdentifierExpression):
            return
        symbol = self._resolved_symbol(value_expression)
        if symbol is None:
            return
        state = self._states.get(id(symbol.node))
        if state is None:
            return
        if (
            not isinstance(expression.value, MoveExpression)
            and not self._is_take_parameter_symbol(symbol)
        ):
            self._error(
                f"Assigning owned resource '{symbol.name}' to owned field requires 'move'",
                expression,
            )
            return
        if state.availability != "available":
            return
        self._states[id(symbol.node)] = replace(state, availability="moved")

    def _visit_call(self, expression: CallExpression) -> None:
        if isinstance(expression.callee, MemberExpression):
            self._visit_member_call(expression)
            self._validate_call_borrow_arguments(expression)
            return
        self._visit_expression(expression.callee)
        lazy_parameters = self._call_lazy_parameters(expression)
        for argument, lazy in zip(expression.arguments, lazy_parameters):
            if not lazy:
                self._visit_expression(argument)
        self._validate_call_borrow_arguments(expression)

    def _call_lazy_parameters(self, expression: CallExpression) -> tuple[bool, ...]:
        callee_type = self.typecheck.types.type_of(expression.callee)
        if not isinstance(callee_type, FunctionType):
            return (False,) * len(expression.arguments)
        return callee_type.parameter_lazy or (False,) * len(expression.arguments)

    def _validate_call_borrow_arguments(self, expression: CallExpression) -> None:
        callee_type = self.typecheck.types.type_of(expression.callee)
        if not isinstance(callee_type, FunctionType):
            return
        ownerships = callee_type.parameter_ownership or (
            "borrow",
        ) * len(callee_type.parameter_types)
        for argument, ownership in zip(expression.arguments, ownerships):
            borrowed, origin = self._borrowed_result_origin(argument)
            if not borrowed:
                continue
            if ownership == "take":
                self._error(
                    "Borrowed return cannot be passed to a take parameter",
                    argument,
                )
            if not isinstance(origin, Symbol):
                self._error(
                    "Borrowed return from a temporary owner cannot be used as an argument",
                    argument,
                )

    def _visit_member_call(self, expression: CallExpression) -> None:
        callee = expression.callee
        self._visit_expression(callee.receiver)
        lazy_parameters = self._call_lazy_parameters(expression)
        for argument, lazy in zip(expression.arguments, lazy_parameters):
            if not lazy:
                self._visit_expression(argument)

        member = self._member_function(callee)
        if member is None:
            return
        receiver_symbol = self._receiver_symbol(callee.receiver)
        receiver_state = self._state_for_receiver(callee.receiver)
        receiver_has_active_borrow = (
            receiver_symbol is not None
            and self._active_borrows.get(id(receiver_symbol.node), 0) > 0
        )

        if "exclusive" in member.modifiers and receiver_state is not None:
            if receiver_has_active_borrow:
                self._error(
                    f"Cannot call exclusive method '{member.name}' while owner is borrowed",
                    callee,
                )
            elif receiver_state.ownership != "owner":
                self._error(
                    f"Cannot call exclusive method '{member.name}' through borrow",
                    callee,
                )
            elif receiver_state.availability == "terminated":
                self._error(
                    f"Cannot call method '{member.name}' after resource was terminated",
                    callee,
                )
            elif receiver_state.availability == "moved":
                self._error(
                    f"Cannot call method '{member.name}' after resource was moved",
                    callee,
                )

        if "terminate" in member.modifiers and receiver_symbol is not None:
            if receiver_state is None:
                return
            if receiver_has_active_borrow:
                self._error(
                    f"Cannot terminate resource '{receiver_symbol.name}' while it is borrowed",
                    callee,
                )
                return
            dependent = self._available_dependent(receiver_symbol)
            if dependent is not None:
                self._error(
                    f"Cannot terminate resource '{receiver_symbol.name}' while "
                    f"'{dependent.name}' depends on it",
                    callee,
                )
                return
            if receiver_state.ownership != "owner":
                self._error(
                    f"Cannot terminate borrowed resource '{receiver_symbol.name}'",
                    callee,
                )
                return
            self._states[id(receiver_symbol.node)] = replace(
                receiver_state,
                availability="terminated",
            )

    def _check_identifier(self, expression: IdentifierExpression) -> None:
        symbol = self._resolved_symbol(expression)
        if symbol is None:
            return
        state = self._states.get(id(symbol.node))
        if state is None:
            return
        if state.availability == "terminated":
            self._error(f"Cannot use terminated resource '{symbol.name}'", expression)
            return
        if state.availability == "moved":
            self._error(f"Cannot use moved resource '{symbol.name}'", expression)
            return
        for dependency in state.dependencies:
            owner_state = self._states.get(id(dependency.node))
            if owner_state is not None and owner_state.availability != "available":
                self._error(
                    f"Cannot use resource '{symbol.name}' after dependency "
                    f"'{dependency.name}' was {owner_state.availability}",
                    expression,
                )
                return
        if state.ownership == "borrow" and state.borrowed_from is not None:
            owner_state = self._states.get(id(state.borrowed_from.node))
            if owner_state is not None and owner_state.availability == "terminated":
                self._error(
                    f"Cannot use borrow '{symbol.name}' after owner "
                    f"'{state.borrowed_from.name}' was terminated",
                    expression,
                )
            elif owner_state is not None and owner_state.availability == "moved":
                self._error(
                    f"Cannot use borrow '{symbol.name}' after owner "
                    f"'{state.borrowed_from.name}' was moved",
                    expression,
                )

    def _visit_move(self, expression: MoveExpression) -> None:
        self._visit_expression(expression.expression)
        if not isinstance(expression.expression, IdentifierExpression):
            if isinstance(expression.expression, CallExpression):
                borrowed_result, _ = self._borrowed_result_origin(expression.expression)
                if borrowed_result:
                    self._error("Cannot move borrowed return value", expression)
                    return
                if self._is_resource_type(self.typecheck.types.type_of(expression.expression)):
                    return
            self._error("'move' can only be applied to a local binding", expression)
            return
        symbol = self._resolved_symbol(expression.expression)
        if symbol is None:
            return
        state = self._states.get(id(symbol.node))
        if state is None:
            return
        if state.ownership != "owner":
            self._error(f"Cannot move borrowed resource '{symbol.name}'", expression)
            return
        if state.availability != "available":
            return
        self._states[id(symbol.node)] = replace(state, availability="moved")

    def _initial_state(
        self,
        type_: Type | None,
        initializer: Expression | None,
    ) -> BindingState:
        if not self._is_resource_type(type_):
            return BindingState("value")
        if isinstance(initializer, MoveExpression):
            return BindingState("owner")
        borrowed_result, borrowed_origin = self._borrowed_result_origin(initializer)
        if borrowed_result:
            return BindingState(
                "borrow",
                borrowed_from=borrowed_origin if isinstance(borrowed_origin, Symbol) else None,
            )
        borrowed_from = self._borrowed_from(initializer)
        if borrowed_from is not None:
            return BindingState("borrow", borrowed_from=borrowed_from)
        return BindingState(
            "owner",
            dependencies=self._constructor_dependencies(initializer),
        )

    def _borrowed_from(self, initializer: Expression | None) -> Symbol | None:
        if not isinstance(initializer, IdentifierExpression):
            return None
        symbol = self._resolved_symbol(initializer)
        if symbol is None:
            return None
        state = self._states.get(id(symbol.node))
        if state is not None and state.ownership == "borrow" and state.borrowed_from:
            return state.borrowed_from
        return symbol

    def _expression_state(self, expression: Expression) -> BindingState | None:
        while isinstance(expression, (GroupingExpression, ForwardExpression)):
            expression = expression.expression
        if isinstance(expression, MoveExpression):
            state = self._expression_state(expression.expression)
            if state is None:
                return None
            return replace(state, ownership="owner")
        if isinstance(expression, IdentifierExpression):
            symbol = self._resolved_symbol(expression)
            return self._states.get(id(symbol.node)) if symbol is not None else None
        borrowed, origin = self._borrowed_result_origin(expression)
        if borrowed:
            return BindingState(
                "borrow",
                borrowed_from=origin if isinstance(origin, Symbol) else None,
            )
        if isinstance(expression, CallExpression) and self._is_resource_type(
            self.typecheck.types.type_of(expression)
        ):
            return BindingState(
                "owner",
                dependencies=self._constructor_dependencies(expression),
            )
        if isinstance(expression, MemberExpression):
            if self._effective_field_ownership(expression) == "borrow":
                origin = self._borrow_origin(expression.receiver)
                return BindingState(
                    "borrow",
                    borrowed_from=origin if isinstance(origin, Symbol) else None,
                )
        if isinstance(expression, (ThisExpression, SelfExpression)):
            return BindingState("owner")
        return None

    def _borrowed_result_origin(
        self,
        expression: Expression | None,
    ) -> tuple[bool, Symbol | str | None]:
        if expression is None:
            return False, None
        while isinstance(expression, (GroupingExpression, ForwardExpression)):
            expression = expression.expression
        if not isinstance(expression, CallExpression):
            return False, None
        function_type = self.typecheck.types.type_of(expression.callee)
        if not isinstance(function_type, FunctionType):
            return False, None
        if function_type.return_ownership != "borrow":
            return False, None
        source = function_type.return_borrow_source
        if source == "this" and isinstance(expression.callee, MemberExpression):
            return True, self._borrow_origin(expression.callee.receiver)
        if isinstance(source, int) and source < len(expression.arguments):
            return True, self._borrow_origin(expression.arguments[source])
        return True, None

    def _borrow_origin(self, expression: Expression) -> Symbol | str | None:
        while isinstance(expression, (GroupingExpression, ForwardExpression, MoveExpression)):
            expression = expression.expression
        if isinstance(expression, IdentifierExpression):
            symbol = self._resolved_symbol(expression)
            if symbol is None:
                return None
            state = self._states.get(id(symbol.node))
            if state is not None and state.ownership == "borrow" and state.borrowed_from:
                return state.borrowed_from
            return symbol
        if isinstance(expression, (ThisExpression, SelfExpression)):
            return "this"
        borrowed, origin = self._borrowed_result_origin(expression)
        if borrowed:
            return origin
        if isinstance(expression, MemberExpression):
            return self._borrow_origin(expression.receiver)
        return None

    def _effective_field_ownership(self, expression: MemberExpression) -> str:
        field = self._member_variable(expression)
        if field is None:
            return "take"
        if field.field_ownership is not None:
            return field.field_ownership
        receiver_type = self._unwrap_nullable(
            self.typecheck.types.type_of(expression.receiver)
        )
        return "take" if isinstance(receiver_type, StructType) else "borrow"

    def _member_variable(self, expression: MemberExpression) -> VariableDeclaration | None:
        receiver_type = self._unwrap_nullable(
            self.typecheck.types.type_of(expression.receiver)
        )
        if not isinstance(receiver_type, (ClassType, StructType)):
            return None
        if receiver_type.symbol is None:
            return None
        declaration = receiver_type.symbol.node
        if not isinstance(declaration, ClassDeclaration):
            return None
        scope = self.typecheck.resolution.analysis.annotations.scope_for(declaration)
        if scope is None:
            return None
        symbol = scope.symbols.get(expression.member)
        if symbol is None or not isinstance(symbol.node, VariableDeclaration):
            return None
        return symbol.node

    def _constructor_dependencies(
        self,
        expression: Expression | None,
    ) -> tuple[Symbol, ...]:
        if not isinstance(expression, CallExpression):
            return ()
        if not isinstance(expression.callee, MemberExpression):
            return ()
        if expression.callee.member != "new":
            return ()
        function_type = self.typecheck.types.type_of(expression.callee)
        result_type = self._unwrap_nullable(self.typecheck.types.type_of(expression))
        if not isinstance(function_type, FunctionType) or not isinstance(result_type, ClassType):
            return ()
        if result_type.symbol is None or not isinstance(result_type.symbol.node, ClassDeclaration):
            return ()
        constructor = self._member_function(expression.callee)
        if constructor is None:
            return ()
        field_sources = self._constructor_field_sources(constructor)
        dependencies: list[Symbol] = []
        for field_name, parameter_name in field_sources:
            parameter_index = next(
                (
                    index
                    for index, parameter in enumerate(constructor.parameters)
                    if parameter.name == parameter_name
                ),
                None,
            )
            if parameter_index is None or parameter_index >= len(expression.arguments):
                continue
            argument = expression.arguments[parameter_index]
            field = next(
                (
                    member
                    for member in result_type.symbol.node.members
                    if isinstance(member, VariableDeclaration)
                    and member.name == field_name
                ),
                None,
            )
            if field is None:
                continue
            ownership = field.field_ownership or "borrow"
            if ownership == "borrow":
                origin = self._borrow_origin(argument)
                if isinstance(origin, Symbol) and origin not in dependencies:
                    dependencies.append(origin)
            else:
                state = self._expression_state(argument)
                if state is not None:
                    for dependency in state.dependencies:
                        if dependency not in dependencies:
                            dependencies.append(dependency)
        return tuple(dependencies)

    def _constructor_field_sources(
        self,
        constructor: FunctionDeclaration,
    ) -> tuple[tuple[str, str], ...]:
        if not isinstance(constructor.body, BlockStatement):
            return ()
        result: list[tuple[str, str]] = []
        for statement in constructor.body.statements:
            if not isinstance(statement, ExpressionStatement):
                continue
            expression = statement.expression
            if not isinstance(expression, AssignmentExpression):
                continue
            if (
                isinstance(expression.target, MemberExpression)
                and isinstance(expression.target.receiver, ThisExpression)
            ):
                value = (
                    expression.value.expression
                    if isinstance(expression.value, MoveExpression)
                    else expression.value
                )
                if isinstance(value, IdentifierExpression):
                    result.append((expression.target.member, value.name))
        return tuple(result)

    def _available_dependent(self, symbol: Symbol) -> Symbol | None:
        for node_id, state in self._states.items():
            if state.availability != "available" or symbol not in state.dependencies:
                continue
            dependent = next(
                (
                    candidate
                    for candidate in self.typecheck.resolution.analysis.annotations.declaration_symbols.values()
                    if id(candidate.node) == node_id
                ),
                None,
            )
            if dependent is not None:
                return dependent
        return None

    def _member_function(self, expression: MemberExpression) -> FunctionDeclaration | None:
        receiver_type = self.typecheck.types.type_of(expression.receiver)
        receiver_type = self._unwrap_nullable(receiver_type)
        if not isinstance(receiver_type, ClassType) or receiver_type.symbol is None:
            return None
        class_declaration = receiver_type.symbol.node
        if not isinstance(class_declaration, ClassDeclaration):
            return None
        class_scope = self.typecheck.resolution.analysis.annotations.scope_for(class_declaration)
        if class_scope is None:
            return None
        member_symbol = class_scope.symbols.get(expression.member)
        if member_symbol is None:
            member_symbol = self._used_trait_member_symbol(class_declaration, expression.member)
        if member_symbol is None or not isinstance(member_symbol.node, FunctionDeclaration):
            return None
        return member_symbol.node

    def _used_trait_member_symbol(
        self,
        declaration: ClassDeclaration,
        name: str,
    ) -> Symbol | None:
        found: Symbol | None = None
        for reference in declaration.uses:
            resolved = self.typecheck.resolution.resolutions.symbol_for(reference)
            if (
                not isinstance(resolved, Symbol)
                or not isinstance(resolved.node, ClassDeclaration)
                or resolved.node.kind != "trait"
            ):
                continue
            trait_scope = self.typecheck.resolution.analysis.annotations.scope_for(resolved.node)
            if trait_scope is None:
                continue
            candidate = trait_scope.symbols.get(name)
            if candidate is None:
                continue
            if found is not None:
                return None
            found = candidate
        return found

    def _receiver_symbol(self, expression: Expression) -> Symbol | None:
        if isinstance(expression, IdentifierExpression):
            return self._resolved_symbol(expression)
        return None

    def _state_for_receiver(self, expression: Expression) -> BindingState | None:
        symbol = self._receiver_symbol(expression)
        if symbol is None:
            if isinstance(expression, (ThisExpression, SelfExpression)):
                return BindingState("owner")
            return self._expression_state(expression)
        return self._states.get(id(symbol.node))

    def _resolved_symbol(self, expression: IdentifierExpression) -> Symbol | None:
        symbol = self.typecheck.resolution.resolutions.symbol_for(expression)
        return symbol if isinstance(symbol, Symbol) else None

    def _symbol_for(self, node: Parameter | VariableDeclaration) -> Symbol | None:
        return self.typecheck.resolution.analysis.annotations.symbol_for(node)

    def _is_take_parameter_symbol(self, symbol: Symbol) -> bool:
        return isinstance(symbol.node, Parameter) and symbol.node.ownership == "take"

    def _is_resource_type(self, type_: Type | None) -> bool:
        return isinstance(self._unwrap_nullable(type_), ClassType)

    def _is_non_nullable_resource_type(self, type_: Type | None) -> bool:
        return isinstance(type_, ClassType)

    def _unwrap_nullable(self, type_: Type | None) -> Type | None:
        if isinstance(type_, NullableType):
            return type_.inner_type
        return type_

    def _merge_states(
        self,
        left: dict[int, BindingState],
        right: dict[int, BindingState],
    ) -> dict[int, BindingState]:
        merged = dict(left)
        for key, right_state in right.items():
            left_state = merged.get(key)
            if left_state is None:
                merged[key] = right_state
            elif (
                left_state.availability == "terminated"
                or right_state.availability == "terminated"
            ):
                merged[key] = replace(left_state, availability="terminated")
            elif (
                left_state.availability == "moved"
                or right_state.availability == "moved"
            ):
                merged[key] = replace(left_state, availability="moved")
        return merged
