"""Lower typed and safety-checked Forge AST into IR."""

from __future__ import annotations

from dataclasses import dataclass

from forge_analysis import Diagnostic, Symbol
from forge_lexer import TokenKind
from forge_ir import (
    IrAssignment,
    IrArrayDestructuring,
    IrArrayBulkCall,
    IrArrayLiteral,
    IrArrayPatternCheck,
    IrBinary,
    IrBlock,
    IrBreak,
    IrBuiltinRef,
    IrBulkMapCall,
    IrCall,
    IrCatch,
    IrCatchHandler,
    IrClass,
    IrConditional,
    IrDoWhile,
    IrDoWhileExpression,
    IrEnum,
    IrEnumVariant,
    IrExpression,
    IrExpressionStatement,
    IrForExpression,
    IrFunction,
    IrIf,
    IrIndex,
    IrLiteral,
    IrLocalRef,
    IrMemberBlock,
    IrMember,
    IrForward,
    IrMove,
    IrParameter,
    IrPrint,
    IrProgram,
    IrReturn,
    IrSequence,
    IrSpecialRef,
    IrStatement,
    IrStructLiteral,
    IrStructLiteralField,
    IrSwitch,
    IrSwitchArm,
    IrTaskBulkCall,
    IrUnary,
    IrVariable,
    IrWhile,
    IrWhileExpression,
)
from forge_parser import (
    AssignmentExpression,
    ArrayDestructuringDeclaration,
    ArrayLiteralExpression,
    BinaryExpression,
    BreakStatement,
    BorrowScopeStatement,
    BulkArgumentPack,
    BulkCallExpression,
    BlockStatement,
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
    ForExpression,
    ForStatement,
    ForwardExpression,
    FunctionDeclaration,
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
    TypeReference,
    UnaryExpression,
    UseDeclaration,
    VariableDeclaration,
    WhileExpression,
    WhileStatement,
)
from forge_parser.ast import Node
from forge_normalizer import normalize
from forge_resolution import BuiltinInterfaceSymbol, BuiltinSymbol, SpecialSymbol
from forge_safety import BindingState, SafetyCheckResult, check_safety
from forge_typecheck import (
    ArrayType,
    BOOL,
    ClassType,
    EnumType,
    FunctionType,
    INT,
    InterfaceType,
    NullableType,
    OutcomeType,
    StructType,
    UNKNOWN,
    VOID,
    Type,
    TypeParameterType,
)
from forge_typecheck.types import apply_type_modifiers, builtin_type


@dataclass(frozen=True, slots=True)
class LoweringResult:
    program: Program
    safety: SafetyCheckResult
    ir: IrProgram


class LoweringError(Exception):
    """Raised when lowering cannot proceed because earlier phases failed."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        first = diagnostics[0]
        super().__init__(f"{first.message} at {first.location.format()}")


class LoweringUnsupportedError(Exception):
    """Raised when a well-typed construct has no IR representation yet."""


def lower(
    program_or_safety: Program | SafetyCheckResult,
    *,
    raise_on_error: bool = True,
) -> LoweringResult:
    """Lower a parsed program or an existing safety-check result to IR."""

    if isinstance(program_or_safety, Program):
        program_or_safety = normalize(program_or_safety)
        safety = check_safety(program_or_safety, raise_on_error=False)
    else:
        safety = program_or_safety
    if raise_on_error and not safety.ok:
        typecheck = safety.typecheck
        resolution = typecheck.resolution
        diagnostics = tuple(
            diagnostic
            for diagnostic in (
                *resolution.analysis.diagnostics,
                *resolution.diagnostics,
                *typecheck.diagnostics,
                *safety.diagnostics,
            )
            if diagnostic.severity == "error"
        )
        raise LoweringError(diagnostics)

    lowerer = _Lowerer(safety)
    return LoweringResult(safety.program, safety, lowerer.run())


class _Lowerer:
    def __init__(self, safety: SafetyCheckResult) -> None:
        self.safety = safety
        self.typecheck = safety.typecheck
        self.resolution = safety.typecheck.resolution
        self._class_stack: list[ClassDeclaration | EnumDeclaration] = []
        self._function_stack: list[FunctionDeclaration] = []
        self._expected_type_stack: list[Type] = []
        self._generated_counter = 0

    def run(self) -> IrProgram:
        program = self.safety.program
        return IrProgram(
            program.location,
            self._lower_items(program.declarations),
        )

    def _lower_declaration_or_statement(self, node: Declaration | Statement):
        if isinstance(node, Declaration):
            return self._lower_declaration(node)
        return self._lower_statement(node)

    def _lower_declaration(self, declaration: Declaration):
        if isinstance(declaration, ClassDeclaration):
            if declaration.kind == "trait":
                return None
            return self._lower_class(declaration)
        if isinstance(declaration, EnumDeclaration):
            return self._lower_enum(declaration)
        if isinstance(declaration, FunctionDeclaration):
            return self._lower_function(declaration)
        if isinstance(declaration, VariableDeclaration):
            return self._lower_variable(declaration)
        if isinstance(declaration, ArrayDestructuringDeclaration):
            return self._lower_array_destructuring(declaration)
        if isinstance(declaration, UseDeclaration):
            return None
        raise TypeError(f"Unsupported declaration {type(declaration).__name__}")

    def _lower_items(
        self, items: tuple[Declaration | Statement, ...]
    ) -> tuple:
        lowered = [self._lower_declaration_or_statement(item) for item in items]
        return tuple(item for item in lowered if item is not None)

    def _lower_class(self, declaration: ClassDeclaration) -> IrClass:
        members = self._class_members_with_used_traits(declaration)
        self._class_stack.append(declaration)
        try:
            lowered_members = self._lower_items(members)
        finally:
            self._class_stack.pop()
        return IrClass(
            declaration.location,
            self._declaration_symbol(declaration),
            declaration.name,
            lowered_members,
            declaration.modifiers,
            declaration.kind,
            tuple(self._type_from_reference(reference) for reference in declaration.implements),
        )

    def _class_members_with_used_traits(
        self,
        declaration: ClassDeclaration,
    ) -> tuple[Declaration | Statement, ...]:
        own_function_names = {
            member.name
            for member in declaration.members
            if isinstance(member, FunctionDeclaration)
        }
        injected: list[Declaration | Statement] = []
        injected_names: set[str] = set()
        for trait in self._used_trait_declarations(declaration):
            for member in trait.members:
                if not isinstance(member, FunctionDeclaration):
                    continue
                if member.name in own_function_names or member.name in injected_names:
                    continue
                injected.append(member)
                injected_names.add(member.name)
        return (*injected, *declaration.members)

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

    def _lower_enum(self, declaration: EnumDeclaration) -> IrEnum:
        enum_type = self._type_of(declaration)
        value_type = enum_type.value_type if isinstance(enum_type, EnumType) else UNKNOWN
        return IrEnum(
            declaration.location,
            self._declaration_symbol(declaration),
            declaration.name,
            enum_type,
            tuple(
                IrEnumVariant(
                    variant.location,
                    variant.name,
                    self._lower_enum_variant_value(variant.value, value_type)
                    if variant.value is not None
                    else None,
                )
                for variant in declaration.variants
            ),
            declaration.modifiers,
        )

    def _lower_enum_variant_value(
        self,
        expression: Expression,
        value_type: Type,
    ) -> IrExpression:
        if isinstance(expression, StructLiteralExpression):
            return IrStructLiteral(
                expression.location,
                tuple(
                    IrStructLiteralField(
                        field.location,
                        field.name,
                        self._lower_expression(field.value),
                    )
                    for field in expression.fields
                ),
                value_type,
            )
        return self._lower_expression(expression)

    def _lower_function(self, declaration: FunctionDeclaration) -> IrFunction:
        function_type = self._type_of(declaration)
        return_type = (
            function_type.return_type
            if isinstance(function_type, FunctionType)
            else UNKNOWN
        )
        self._function_stack.append(declaration)
        try:
            body = self._lower_function_body(declaration)
        finally:
            self._function_stack.pop()
        return IrFunction(
            declaration.location,
            self._declaration_symbol(declaration),
            declaration.name,
            tuple(self._lower_parameter(parameter) for parameter in declaration.parameters),
            return_type,
            body,
            declaration.modifiers,
            declaration.kind,
            function_type,
            declaration.native_name,
        )

    def _lower_parameter(self, parameter: Parameter) -> IrParameter:
        symbol = self._required_declaration_symbol(parameter)
        return IrParameter(
            parameter.location,
            symbol,
            parameter.name,
            self._type_of(parameter),
            self.safety.safety.state_of_symbol(symbol),
            parameter.lazy,
        )

    def _lower_variable(self, declaration: VariableDeclaration) -> IrVariable:
        symbol = self._required_declaration_symbol(declaration)
        variable_type = self._type_of(declaration)
        initializer = (
            self._lower_expression_with_expected(declaration.initializer, variable_type)
            if declaration.initializer is not None
            else None
        )
        return IrVariable(
            declaration.location,
            symbol,
            declaration.name,
            variable_type,
            declaration.mutable,
            initializer,
            declaration.modifiers,
            self.safety.safety.state_of_symbol(symbol),
            self._effective_field_ownership(declaration, variable_type),
            declaration.lazy,
        )

    def _effective_field_ownership(
        self,
        declaration: VariableDeclaration,
        type_: Type,
    ) -> str | None:
        resource_type = type_.inner_type if isinstance(type_, NullableType) else type_
        if not isinstance(resource_type, ClassType) or not self._class_stack:
            return None
        enclosing = self._class_stack[-1]
        if not isinstance(enclosing, ClassDeclaration):
            return None
        if declaration.field_ownership is not None:
            return declaration.field_ownership
        return "take" if enclosing.kind == "struct" else "borrow"

    def _lower_array_destructuring(
        self, declaration: ArrayDestructuringDeclaration
    ) -> IrArrayDestructuring:
        source_expression = declaration.initializer
        ownership_source = source_expression
        if isinstance(source_expression, CatchExpression):
            checked_source = IrArrayPatternCheck(
                source_expression.expression.location,
                self._lower_expression(source_expression.expression),
                len(declaration.bindings),
                self._type_of(source_expression.expression),
                self.typecheck.types.outcomes_of(source_expression.expression),
            )
            source = self._lower_catch_expression(
                source_expression,
                inner=checked_source,
            )
            ownership_source = source_expression.expression
        else:
            source = self._lower_expression(source_expression)
        source_temp = None
        receiver = source
        if not isinstance(source, IrLocalRef):
            source_name = self._generated_name("forge_destructure_source")
            source_symbol = self._generated_symbol(source_name, declaration)
            source_temp = IrVariable(
                declaration.location,
                source_symbol,
                source_name,
                source.type,
                False,
                source,
                (),
                (
                    BindingState("borrow")
                    if (
                        isinstance(
                            ownership_source,
                            (
                                IdentifierExpression,
                                MemberExpression,
                                IndexExpression,
                            ),
                        )
                        or (
                            isinstance(source.type, ArrayType)
                            and source.type.size is not None
                        )
                    )
                    else BindingState("owner")
                ),
            )
            receiver = IrLocalRef(
                declaration.location,
                source_symbol,
                source.type,
            )

        bindings = tuple(
            self._lower_destructuring_binding(binding, receiver, index)
            for index, binding in enumerate(declaration.bindings)
        )
        return IrArrayDestructuring(
            declaration.location,
            source,
            source_temp,
            bindings,
        )

    def _lower_destructuring_binding(
        self,
        binding: VariableDeclaration,
        receiver: IrExpression,
        index: int,
    ) -> IrVariable:
        symbol = self._required_declaration_symbol(binding)
        binding_type = self._type_of(binding)
        return IrVariable(
            binding.location,
            symbol,
            binding.name,
            binding_type,
            binding.mutable,
            IrIndex(
                binding.location,
                receiver,
                IrLiteral(binding.location, index, INT),
                binding_type,
            ),
            binding.modifiers,
            self.safety.safety.state_of_symbol(symbol),
        )

    def _lower_function_body(self, declaration: FunctionDeclaration) -> IrBlock:
        if declaration.body is None:
            return IrBlock(declaration.location, ())
        if isinstance(declaration.body, BlockStatement):
            return self._lower_block(declaration.body)
        return IrBlock(
            declaration.body.location,
            (IrReturn(declaration.body.location, self._lower_expression(declaration.body)),),
        )

    def _lower_statement(self, statement: Statement) -> IrStatement:
        if isinstance(statement, BlockStatement):
            return self._lower_block(statement)
        if isinstance(statement, PrintStatement):
            return IrPrint(statement.location, self._lower_expression(statement.expression))
        if isinstance(statement, ReturnStatement):
            expected = UNKNOWN
            if self._function_stack:
                function_type = self._type_of(self._function_stack[-1])
                if isinstance(function_type, FunctionType):
                    expected = function_type.return_type
            expression = (
                self._lower_expression_with_expected(statement.expression, expected)
                if statement.expression is not None
                else None
            )
            return IrReturn(statement.location, expression)
        if isinstance(statement, BreakStatement):
            return IrBreak(
                statement.location,
                self._lower_expression(statement.expression)
                if statement.expression is not None
                else None,
            )
        if isinstance(statement, IfStatement):
            else_branch = None
            if isinstance(statement.else_branch, BlockStatement):
                else_branch = self._lower_block(statement.else_branch)
            elif isinstance(statement.else_branch, IfStatement):
                else_branch = self._lower_statement(statement.else_branch)
            return IrIf(
                statement.location,
                self._lower_expression(statement.condition),
                self._lower_block(statement.then_branch),
                else_branch,
            )
        if isinstance(statement, WhileStatement):
            return IrWhile(
                statement.location,
                self._lower_expression(statement.condition),
                self._lower_block(statement.body),
            )
        if isinstance(statement, DoWhileStatement):
            return IrDoWhile(
                statement.location,
                self._lower_block(statement.body),
                self._lower_expression(statement.condition),
            )
        if isinstance(statement, SwitchStatement):
            return IrSwitch(
                statement.location,
                self._lower_expression(statement.expression),
                tuple(
                    IrSwitchArm(
                        arm.location,
                        self._lower_expression_with_expected(arm.pattern, self._type_of(statement.expression))
                        if arm.pattern is not None
                        else None,
                        self._lower_switch_arm_body(arm.body),
                    )
                    for arm in statement.arms
                ),
            )
        if isinstance(statement, ForStatement):
            return self._lower_for(statement)
        if isinstance(statement, BorrowScopeStatement):
            symbol = self._required_declaration_symbol(statement.binding)
            binding = IrVariable(
                statement.binding.location,
                symbol,
                statement.binding.name,
                self._type_of(statement.binding),
                False,
                self._lower_expression(statement.source),
                (),
                self.safety.safety.state_of_symbol(symbol),
            )
            body = self._lower_block(statement.body)
            return IrBlock(statement.location, (binding, *body.statements))
        if isinstance(statement, ExpressionStatement):
            return IrExpressionStatement(
                statement.location,
                self._lower_expression(statement.expression),
            )
        raise TypeError(f"Unsupported statement {type(statement).__name__}")

    def _lower_switch_arm_body(self, statement: Statement) -> IrBlock:
        lowered = self._lower_statement(statement)
        if isinstance(lowered, IrBlock):
            return lowered
        return IrBlock(statement.location, (lowered,))

    def _lower_for(self, statement: ForStatement) -> IrBlock:
        source_type = self._type_of(statement.source)
        item_type = source_type.element_type if isinstance(source_type, ArrayType) else UNKNOWN
        index_name = self._generated_name("forge_for_index")
        index_symbol = self._generated_symbol(index_name, statement)
        item_symbol = self._required_declaration_symbol(statement.item)

        source = self._lower_expression(statement.source)
        index_ref = IrLocalRef(statement.location, index_symbol, INT)
        index_variable = IrVariable(
            statement.location,
            index_symbol,
            index_name,
            INT,
            True,
            IrLiteral(statement.location, 0, INT),
        )
        item_variable = IrVariable(
            statement.item.location,
            item_symbol,
            statement.item.name,
            item_type,
            False,
            IrIndex(statement.location, source, index_ref, item_type),
            statement.item.modifiers,
            self.safety.safety.state_of_symbol(item_symbol),
        )
        increment = IrExpressionStatement(
            statement.location,
            IrAssignment(
                statement.location,
                index_ref,
                IrBinary(
                    statement.location,
                    index_ref,
                    TokenKind.PLUS,
                    IrLiteral(statement.location, 1, INT),
                    INT,
                ),
                INT,
            ),
        )
        condition = IrBinary(
            statement.location,
            index_ref,
            TokenKind.LESS,
            IrMember(statement.location, source, "len", INT),
            BOOL,
        )
        body = IrBlock(
            statement.body.location,
            (item_variable, *self._lower_items(statement.body.statements), increment),
        )
        return IrBlock(
            statement.location,
            (index_variable, IrWhile(statement.location, condition, body)),
        )

    def _lower_block(self, block: BlockStatement) -> IrBlock:
        return IrBlock(
            block.location,
            self._lower_items(block.statements),
        )

    def _generated_name(self, prefix: str) -> str:
        name = f"{prefix}{self._generated_counter}"
        self._generated_counter += 1
        return name

    def _generated_symbol(self, name: str, node: Node) -> Symbol:
        scope = (
            self.resolution.analysis.annotations.scope_for(node)
            or self.resolution.analysis.annotations.root_scope
        )
        return Symbol(name, "variable", node, scope, node.location, mutable=True)

    def _lower_expression(self, expression: Expression) -> IrExpression:
        if isinstance(expression, LiteralExpression):
            return IrLiteral(expression.location, expression.value, self._type_of(expression))
        if isinstance(expression, IdentifierExpression):
            symbol = self.resolution.resolutions.symbol_for(expression)
            if isinstance(symbol, BuiltinSymbol):
                return IrBuiltinRef(
                    expression.location,
                    symbol.name,
                    self._type_of(expression),
                )
            if not isinstance(symbol, Symbol):
                raise TypeError(f"Identifier '{expression.name}' has no resolved symbol")
            return IrLocalRef(
                expression.location,
                symbol,
                self._type_of(expression),
                self.safety.safety.state_of_symbol(symbol),
                self._task_outcomes_of(expression),
            )
        if isinstance(expression, ThisExpression):
            return IrSpecialRef(expression.location, "this", self._type_of(expression))
        if isinstance(expression, SelfExpression):
            return IrSpecialRef(expression.location, "self", self._type_of(expression))
        if isinstance(expression, GroupingExpression):
            return self._lower_expression(expression.expression)
        if isinstance(expression, ForwardExpression):
            return IrForward(
                expression.location,
                self._lower_expression(expression.expression),
                self._type_of(expression),
            )
        if isinstance(expression, CatchExpression):
            return self._lower_catch_expression(expression)
        if isinstance(expression, UnaryExpression):
            return IrUnary(
                expression.location,
                expression.operator,
                self._lower_expression(expression.operand),
                self._type_of(expression),
            )
        if isinstance(expression, MoveExpression):
            return IrMove(
                expression.location,
                self._lower_expression(expression.expression),
                self._type_of(expression),
            )
        if isinstance(expression, BinaryExpression):
            return IrBinary(
                expression.location,
                self._lower_expression(expression.left),
                expression.operator,
                self._lower_expression(expression.right),
                self._type_of(expression),
            )
        if isinstance(expression, AssignmentExpression):
            target = self._lower_expression(expression.target)
            return IrAssignment(
                expression.location,
                target,
                self._lower_expression_with_expected(expression.value, target.type),
                self._type_of(expression),
                expression.operator,
            )
        if isinstance(expression, ConditionalExpression):
            return IrConditional(
                expression.location,
                self._lower_expression(expression.condition),
                self._lower_expression(expression.then_expression),
                self._lower_expression(expression.else_expression),
                self._type_of(expression),
            )
        if isinstance(expression, WhileExpression):
            type_ = self._type_of(expression)
            return IrWhileExpression(
                expression.location,
                self._lower_expression(expression.condition),
                self._lower_block(expression.body),
                self._lower_expression_with_expected(expression.fallback, type_)
                if expression.fallback is not None
                else IrLiteral(expression.location, None, type_),
                type_,
            )
        if isinstance(expression, DoWhileExpression):
            type_ = self._type_of(expression)
            return IrDoWhileExpression(
                expression.location,
                self._lower_block(expression.body),
                self._lower_expression(expression.condition),
                self._lower_expression_with_expected(expression.fallback, type_)
                if expression.fallback is not None
                else IrLiteral(expression.location, None, type_),
                type_,
            )
        if isinstance(expression, ForExpression):
            source_type = self._type_of(expression.source)
            item_type = (
                source_type.element_type
                if isinstance(source_type, ArrayType)
                else UNKNOWN
            )
            item_symbol = self._required_declaration_symbol(expression.item)
            type_ = self._type_of(expression)
            return IrForExpression(
                expression.location,
                self._lower_expression(expression.source),
                IrVariable(
                    expression.item.location,
                    item_symbol,
                    expression.item.name,
                    item_type,
                    False,
                    None,
                    expression.item.modifiers,
                    self.safety.safety.state_of_symbol(item_symbol),
                ),
                self._lower_block(expression.body),
                self._lower_expression_with_expected(expression.fallback, type_)
                if expression.fallback is not None
                else IrLiteral(expression.location, None, type_),
                type_,
            )
        if isinstance(expression, CallExpression):
            return IrCall(
                expression.location,
                self._lower_expression(expression.callee),
                tuple(self._lower_expression(argument) for argument in expression.arguments),
                self._type_of(expression),
                self._task_outcomes_of(expression),
            )
        if isinstance(expression, ArrayLiteralExpression):
            return IrArrayLiteral(
                expression.location,
                tuple(self._lower_expression(element) for element in expression.elements),
                self._type_of(expression),
            )
        if isinstance(expression, StructLiteralExpression):
            return self._lower_struct_literal(expression, self._struct_literal_type(expression))
        if isinstance(expression, BulkCallExpression):
            if (
                not expression.task
                and not expression.generator
                and len(expression.arguments) == 1
                and isinstance(self._type_of(expression.callee), ArrayType)
            ):
                return IrIndex(
                    expression.location,
                    self._lower_expression(expression.callee),
                    self._lower_expression(expression.arguments[0]),
                    self._type_of(expression),
                )
            if expression.task:
                return IrTaskBulkCall(
                    expression.location,
                    self._lower_expression(expression.callee),
                    self._lower_expression(expression.arguments[0]),
                    self._type_of(expression),
                    self._task_outcomes_of(expression),
                )
            if all(isinstance(argument, BulkArgumentPack) for argument in expression.arguments):
                return IrArrayLiteral(
                    expression.location,
                    tuple(
                        IrCall(
                            argument.location,
                            self._lower_expression(expression.callee),
                            tuple(
                                self._lower_expression(pack_argument)
                                for pack_argument in argument.arguments
                            ),
                            self._array_element_type(expression),
                            self._task_outcomes_of(expression),
                        )
                        for argument in expression.arguments
                    ),
                    self._type_of(expression),
                )
            if (
                len(expression.arguments) == 1
                and isinstance(self._type_of(expression.arguments[0]), ArrayType)
                and isinstance(self._type_of(expression), ArrayType)
            ):
                return IrBulkMapCall(
                    expression.location,
                    self._lower_expression(expression.callee),
                    self._lower_expression(expression.arguments[0]),
                    "sync",
                    self._type_of(expression),
                    self.typecheck.types.outcomes_of(expression),
                )
            if (
                len(expression.arguments) == 1
                and isinstance(self._type_of(expression.arguments[0]), ArrayType)
                and self._type_of(expression).name == "Void"
            ):
                return IrArrayBulkCall(
                    expression.location,
                    self._lower_expression(expression.callee),
                    self._lower_expression(expression.arguments[0]),
                    self._type_of(expression),
                )
            if len(expression.arguments) > 1:
                calls = tuple(
                    IrCall(
                        argument.location,
                        self._lower_expression(expression.callee),
                        (self._lower_expression(argument),),
                        self._bulk_scalar_call_result_type(expression),
                        self._task_outcomes_of(expression),
                    )
                    for argument in expression.arguments
                )
                if self._type_of(expression) == UNKNOWN:
                    raise TypeError(f"Unsupported expression {type(expression).__name__}")
                if self._type_of(expression).name == "Void":
                    return IrSequence(expression.location, calls, self._type_of(expression))
                return IrArrayLiteral(expression.location, calls, self._type_of(expression))
            return IrCall(
                expression.location,
                self._lower_expression(expression.callee),
                tuple(self._lower_expression(argument) for argument in expression.arguments),
                self._type_of(expression),
                self._task_outcomes_of(expression),
            )
        if isinstance(expression, BulkArgumentPack):
            raise TypeError(f"Unsupported expression {type(expression).__name__}")
        if isinstance(expression, MemberExpression):
            return IrMember(
                expression.location,
                self._lower_expression(expression.receiver),
                expression.member,
                self._type_of(expression),
                self._member_symbol(expression),
                expression.null_safe,
                self._task_outcomes_of(expression),
                self._effective_member_ownership(expression),
            )
        if isinstance(expression, MemberBlockExpression):
            return IrMemberBlock(
                expression.location,
                self._lower_expression(expression.receiver),
                tuple(self._lower_expression(child) for child in expression.expressions),
                self._type_of(expression),
            )
        if isinstance(expression, IndexExpression):
            return IrIndex(
                expression.location,
                self._lower_expression(expression.receiver),
                self._lower_expression(expression.index),
                self._type_of(expression),
            )
        raise TypeError(f"Unsupported expression {type(expression).__name__}")

    def _lower_catch_expression(
        self,
        expression: CatchExpression,
        *,
        inner: IrExpression | None = None,
    ) -> IrCatch:
        return IrCatch(
            expression.location,
            inner or self._lower_expression(expression.expression),
            tuple(
                IrCatchHandler(
                    handler.location,
                    handler.name,
                    self.typecheck.types.type_of(handler.type) or UNKNOWN,
                    self._lower_block(handler.expression)
                    if isinstance(handler.expression, BlockStatement)
                    else self._lower_expression(handler.expression),
                )
                for handler in expression.handlers
            ),
            self._type_of(expression),
        )

    def _lower_expression_with_expected(
        self,
        expression: Expression,
        expected: Type,
    ) -> IrExpression:
        if isinstance(expected, NullableType):
            expected = expected.inner_type
        self._expected_type_stack.append(expected)
        try:
            return self._lower_expression(expression)
        finally:
            self._expected_type_stack.pop()

    def _lower_struct_literal(
        self,
        expression: StructLiteralExpression,
        type_: Type,
    ) -> IrStructLiteral:
        field_types = self._struct_field_types(type_) if isinstance(type_, StructType) else {}
        positional_fields = tuple(field_types)
        fields = []
        for index, field in enumerate(expression.fields):
            field_name = field.name
            if field_name is None and index < len(positional_fields):
                field_name = positional_fields[index]
            target_type = field_types.get(field_name) if field_name is not None else None
            fields.append(
                IrStructLiteralField(
                    field.location,
                    field.name,
                    self._lower_expression_with_expected(field.value, target_type)
                    if target_type is not None
                    else self._lower_expression(field.value),
                    target_type,
                )
            )
        return IrStructLiteral(expression.location, tuple(fields), type_)

    def _struct_field_types(self, type_: StructType) -> dict[str, Type]:
        symbol = type_.symbol
        if symbol is None:
            return {}
        node = symbol.node
        if not isinstance(node, ClassDeclaration):
            return {}
        return {
            member.name: self._type_from_reference(member.type)
            for member in node.members
            if isinstance(member, VariableDeclaration) and member.type is not None
        }

    def _struct_literal_type(self, expression: StructLiteralExpression) -> Type:
        type_ = self._type_of(expression)
        if type_ != UNKNOWN:
            return type_
        if self._expected_type_stack:
            return self._expected_type_stack[-1]
        return UNKNOWN

    def _member_symbol(self, expression: MemberExpression) -> Symbol | None:
        receiver_type = self._type_of(expression.receiver)
        if not isinstance(receiver_type, (ClassType, StructType, EnumType, InterfaceType)) or receiver_type.symbol is None:
            return None
        class_declaration = receiver_type.symbol.node
        if not isinstance(class_declaration, (ClassDeclaration, EnumDeclaration)):
            return None
        class_scope = self.resolution.analysis.annotations.scope_for(class_declaration)
        if class_scope is None:
            return None
        symbol = class_scope.symbols.get(expression.member)
        if symbol is not None:
            return symbol
        found: Symbol | None = None
        for trait in self._used_trait_declarations(class_declaration):
            trait_scope = self.resolution.analysis.annotations.scope_for(trait)
            if trait_scope is None:
                continue
            candidate = trait_scope.symbols.get(expression.member)
            if candidate is None:
                continue
            if found is not None:
                return None
            found = candidate
        return found

    def _effective_member_ownership(
        self,
        expression: MemberExpression,
    ) -> str | None:
        member = self._member_symbol(expression)
        if member is None or not isinstance(member.node, VariableDeclaration):
            return None
        member_type = self._type_of(expression)
        resource_type = (
            member_type.inner_type
            if isinstance(member_type, NullableType)
            else member_type
        )
        if not isinstance(resource_type, ClassType):
            return None
        if member.node.field_ownership is not None:
            return member.node.field_ownership
        receiver_type = self._type_of(expression.receiver)
        if isinstance(receiver_type, NullableType):
            receiver_type = receiver_type.inner_type
        return "take" if isinstance(receiver_type, StructType) else "borrow"

    def _type_of(self, node: Node) -> Type:
        type_ = self.typecheck.types.type_of(node)
        if type_ is not None and type_ != UNKNOWN:
            return type_
        if isinstance(node, IdentifierExpression):
            resolved = self.resolution.resolutions.symbol_for(node)
            if isinstance(resolved, Symbol):
                return self._symbol_type(resolved)
        if isinstance(node, MemberExpression):
            symbol = self._member_symbol(node)
            if symbol is not None:
                receiver_type = self._type_of(node.receiver)
                enclosing = None
                if isinstance(receiver_type, (ClassType, EnumType)) and receiver_type.symbol is not None:
                    if isinstance(receiver_type.symbol.node, (ClassDeclaration, EnumDeclaration)):
                        enclosing = receiver_type.symbol.node
                return self._symbol_type(symbol, enclosing)
        if isinstance(node, Parameter):
            return self._type_from_reference(node.type)
        if isinstance(node, VariableDeclaration) and node.type is not None:
            return self._type_from_reference(node.type)
        if isinstance(node, FunctionDeclaration):
            enclosing = self._class_stack[-1] if self._class_stack else None
            return self._function_type(node, enclosing)
        return type_ if type_ is not None else UNKNOWN

    def _symbol_type(
        self,
        symbol: Symbol,
        enclosing: ClassDeclaration | EnumDeclaration | None = None,
    ) -> Type:
        node = symbol.node
        if isinstance(node, Parameter):
            return self._type_from_reference(node.type)
        if isinstance(node, VariableDeclaration) and node.type is not None:
            return self._type_from_reference(node.type)
        if isinstance(node, FunctionDeclaration):
            return self._function_type(node, enclosing)
        if isinstance(node, ClassDeclaration):
            if node.kind == "interface":
                return InterfaceType(node.name or symbol.name, symbol)
            if node.kind == "struct":
                return StructType(node.name or symbol.name, symbol)
            return ClassType(node.name or symbol.name, symbol)
        if isinstance(node, EnumDeclaration):
            return EnumType(node.name or symbol.name, symbol, UNKNOWN)
        if isinstance(node, EnumVariant):
            enum_symbol = self.resolution.analysis.annotations.symbol_for(enclosing) if enclosing is not None else None
            enum_name = enclosing.name if isinstance(enclosing, EnumDeclaration) else symbol.name
            return EnumType(enum_name or symbol.name, enum_symbol, UNKNOWN)
        return UNKNOWN

    def _function_type(
        self,
        declaration: FunctionDeclaration,
        enclosing_class: ClassDeclaration | EnumDeclaration | None,
    ) -> FunctionType:
        parameter_types = tuple(
            self._type_from_reference(parameter.type)
            for parameter in declaration.parameters
        )
        if declaration.kind == "new" and enclosing_class is not None:
            class_symbol = self.resolution.analysis.annotations.symbol_for(enclosing_class)
            if isinstance(enclosing_class, ClassDeclaration) and enclosing_class.kind == "struct":
                return_type = StructType(enclosing_class.name or "<anonymous struct>", class_symbol)
            elif isinstance(enclosing_class, EnumDeclaration):
                return_type = EnumType(enclosing_class.name or "<anonymous enum>", class_symbol, UNKNOWN)
            else:
                return_type = ClassType(enclosing_class.name or "<anonymous class>", class_symbol)
        elif declaration.return_type is not None:
            return_type = self._type_from_reference(declaration.return_type)
        else:
            return_type = VOID
        return FunctionType(
            declaration.name,
            parameter_types,
            return_type,
            tuple(parameter.ownership for parameter in declaration.parameters),
            tuple(parameter.lazy for parameter in declaration.parameters),
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

    def _type_from_reference(self, reference: TypeReference) -> Type:
        existing = self.typecheck.types.type_of(reference)
        if existing is not None and existing != UNKNOWN:
            return existing
        resolved = self.resolution.resolutions.symbol_for(reference)
        if isinstance(resolved, BuiltinSymbol):
            base = builtin_type(resolved.name)
        elif isinstance(resolved, BuiltinInterfaceSymbol):
            base = InterfaceType(resolved.name)
        elif isinstance(resolved, SpecialSymbol):
            class_symbol = self.resolution.analysis.annotations.symbol_for(resolved.node)
            if isinstance(resolved.node, EnumDeclaration):
                base = EnumType(resolved.node.name or "<anonymous enum>", class_symbol, UNKNOWN)
            elif resolved.node.kind == "struct":
                base = StructType(resolved.node.name or "<anonymous struct>", class_symbol)
            else:
                base = ClassType(resolved.node.name or "<anonymous class>", class_symbol)
        elif isinstance(resolved, Symbol) and isinstance(resolved.node, ClassDeclaration):
            if resolved.node.kind == "interface":
                base = InterfaceType(resolved.name, resolved)
            elif resolved.node.kind == "struct":
                base = StructType(resolved.name, resolved)
            else:
                base = ClassType(resolved.name, resolved)
        elif isinstance(resolved, Symbol) and isinstance(resolved.node, EnumDeclaration):
            base = EnumType(resolved.name, resolved, UNKNOWN)
        elif isinstance(resolved, Symbol) and resolved.kind == "type_parameter":
            base = TypeParameterType(resolved.name, resolved)
        else:
            base = UNKNOWN
        if reference.arguments and not isinstance(base, (TaskType, TaskCollectionType)):
            arguments = tuple(
                self._type_from_reference(argument)
                for argument in reference.arguments
            )
            if isinstance(base, ClassType):
                base = ClassType(base.name, base.symbol, arguments)
            elif isinstance(base, StructType):
                base = StructType(base.name, base.symbol, arguments)
            elif isinstance(base, InterfaceType):
                base = InterfaceType(base.name, base.symbol, arguments)
        return apply_type_modifiers(
            base,
            array_depth=reference.array_depth,
            nullable=reference.nullable,
            array_sizes=(),
        )

    def _task_outcomes_of(self, node: Node) -> tuple[OutcomeType, ...]:
        return self.typecheck.types.task_outcomes_of(node)

    def _array_element_type(self, node: Node) -> Type:
        type_ = self._type_of(node)
        return type_.element_type if hasattr(type_, "element_type") else UNKNOWN

    def _bulk_scalar_call_result_type(self, node: Node) -> Type:
        type_ = self._type_of(node)
        return type_.element_type if hasattr(type_, "element_type") else type_

    def _declaration_symbol(self, node: Node) -> Symbol | None:
        return self.resolution.analysis.annotations.symbol_for(node)

    def _required_declaration_symbol(self, node: Node) -> Symbol:
        symbol = self._declaration_symbol(node)
        if symbol is None:
            raise TypeError(f"Missing declaration symbol for {type(node).__name__}")
        return symbol
