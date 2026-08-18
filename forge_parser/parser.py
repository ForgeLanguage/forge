"""A hand-written recursive descent parser for the Forge language."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import PurePath

from forge_lexer import SourceLocation, Token, TokenKind, lex

from .ast import (
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
    CatchHandler,
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
    ImplementsDeclaration,
    InlineStructType,
    IndexExpression,
    LiteralExpression,
    MemberBlockExpression,
    MemberExpression,
    MoveExpression,
    OutcomeDeclaration,
    Parameter,
    PrintStatement,
    Program,
    ReturnStatement,
    SelfExpression,
    Statement,
    StructLiteralExpression,
    StructLiteralField,
    SwitchArm,
    SwitchStatement,
    ThisExpression,
    TypeParameter,
    TypeReference,
    UnaryExpression,
    UseDeclaration,
    UsesDeclaration,
    VariableDeclaration,
    WhileStatement,
    WhileExpression,
)


_MODIFIERS = {
    TokenKind.PUBLIC,
    TokenKind.INTERNAL,
    TokenKind.PRIVATE,
    TokenKind.STATIC,
    TokenKind.NATIVE,
    TokenKind.ASYNC,
    TokenKind.EXCLUSIVE,
    TokenKind.TERMINATE,
    TokenKind.TEMPLATE,
}

_COMPOUND_ASSIGNMENT_OPERATORS = {
    TokenKind.PLUS_EQUAL: TokenKind.PLUS,
    TokenKind.MINUS_EQUAL: TokenKind.MINUS,
    TokenKind.STAR_EQUAL: TokenKind.STAR,
    TokenKind.SLASH_EQUAL: TokenKind.SLASH,
    TokenKind.PERCENT_EQUAL: TokenKind.PERCENT,
}

_INCREMENT_OPERATORS = {
    TokenKind.PLUS_PLUS: TokenKind.PLUS,
    TokenKind.MINUS_MINUS: TokenKind.MINUS,
}


class ParserError(SyntaxError):
    """Raised when Forge source cannot be parsed."""

    def __init__(self, message: str, location: SourceLocation) -> None:
        super().__init__(f"{message} at {location.format()}")
        self.message = message
        self.location = location


class Parser:
    """Parse Forge tokens into a typed AST."""

    def __init__(
        self,
        source_or_tokens: str | Sequence[Token],
        *,
        source_name: str | None = None,
    ) -> None:
        self.tokens = (
            lex(source_or_tokens)
            if isinstance(source_or_tokens, str)
            else list(source_or_tokens)
        )
        if source_name is not None:
            self.tokens = [
                replace(token, location=replace(token.location, source_name=source_name))
                for token in self.tokens
            ]
        self._current = 0
        self.source_name = source_name
        self._attributes: tuple[str, ...] = ()

    def parse(self) -> Program:
        declarations: list[Declaration | Statement] = []
        location = self._peek().location
        self._attributes = self._program_attributes()

        while not self._check(TokenKind.EOF):
            declarations.append(self._declaration())

        return Program(
            location,
            self._fold_single_type_members(tuple(declarations)),
            self._attributes,
            self.source_name,
        )

    def parse_expression(self) -> Expression:
        expression = self._expression()
        self._consume(TokenKind.EOF, "Expected end of expression")
        return expression

    def _program_attributes(self) -> tuple[str, ...]:
        attributes: list[str] = []
        while self._match(TokenKind.AT):
            attribute = self._consume_identifier("Expected attribute name after '@'")
            attributes.append(attribute.lexeme)
        return tuple(attributes)

    def _declaration(self) -> Declaration | Statement:
        modifiers = self._modifiers()
        ownership = None
        if self._match(TokenKind.TAKE, TokenKind.BORROW):
            ownership = "take" if self._previous().kind is TokenKind.TAKE else "borrow"

        if self._match(TokenKind.USE):
            if modifiers or ownership is not None:
                raise ParserError("'use' cannot have modifiers", self._previous().location)
            return self._use_declaration()
        if self._match(TokenKind.IMPLEMENTS):
            if modifiers or ownership is not None:
                raise ParserError("'implements' cannot have modifiers", self._previous().location)
            return ImplementsDeclaration(self._previous().location, self._implements_list())
        if self._match(TokenKind.USES):
            if modifiers or ownership is not None:
                raise ParserError("'uses' cannot have modifiers", self._previous().location)
            return UsesDeclaration(self._previous().location, self._uses_list())
        if self._match(TokenKind.CLASS, TokenKind.TRAIT, TokenKind.INTERFACE, TokenKind.STRUCT):
            if ownership is not None:
                raise ParserError("Type declaration cannot have ownership modifier", self._previous().location)
            return self._class_declaration(modifiers)
        if self._match(TokenKind.ENUM):
            if ownership is not None:
                raise ParserError("Enum declaration cannot have ownership modifier", self._previous().location)
            return self._enum_declaration(modifiers)
        if self._is_switch_function_declaration():
            self._advance()
            return self._switch_function_declaration(
                modifiers,
                self._previous(),
                ownership or "take",
            )
        if self._match(TokenKind.FUNC, TokenKind.GENERATOR):
            return self._function_declaration(
                modifiers,
                self._previous(),
                ownership or "take",
            )
        if self._match(TokenKind.NEW):
            return self._function_declaration(
                modifiers,
                self._previous(),
                ownership or "take",
            )
        if self._match(TokenKind.CONST, TokenKind.LET, TokenKind.LAZY):
            if ownership is not None:
                raise ParserError(
                    "Local declaration cannot have ownership modifier",
                    self._previous().location,
                )
            return self._variable_declaration(modifiers, self._previous())
        if (modifiers or ownership is not None) and self._check(TokenKind.IDENTIFIER):
            return self._field_declaration(modifiers, ownership)
        if modifiers or ownership is not None:
            token = self._peek()
            raise ParserError("Expected declaration after modifier", token.location)

        return self._statement()

    def _class_declaration(self, modifiers: tuple[str, ...]) -> ClassDeclaration:
        keyword = self._previous()
        name = self._advance().lexeme if self._check(TokenKind.IDENTIFIER) else None
        type_parameters = self._function_type_parameters() if name is not None or self._check(TokenKind.LESS) else ()
        if name is None and "multidef" not in self._attributes:
            name = self._inferred_type_name()
        members: list[Declaration | Statement] = []
        implements: list[TypeReference] = []
        uses: list[TypeReference] = []
        braced_body = False

        if self._match(TokenKind.LEFT_BRACE):
            braced_body = True
            while not self._check(TokenKind.RIGHT_BRACE) and not self._check(TokenKind.EOF):
                if self._match(TokenKind.IMPLEMENTS):
                    implements.extend(self._implements_list())
                elif self._match(TokenKind.USES):
                    uses.extend(self._uses_list())
                else:
                    members.append(self._declaration())
            self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after class body")

        return ClassDeclaration(
            keyword.location,
            name,
            tuple(members),
            modifiers,
            braced_body,
            keyword.lexeme,
            tuple(implements),
            tuple(uses),
            type_parameters,
        )

    def _enum_declaration(self, modifiers: tuple[str, ...]) -> EnumDeclaration:
        keyword = self._previous()
        name = self._advance().lexeme if self._check(TokenKind.IDENTIFIER) else None
        if name is None and "multidef" not in self._attributes:
            name = self._inferred_type_name()

        value_type: TypeReference | InlineStructType | None = None
        if self._match(TokenKind.COLON):
            if self._match(TokenKind.STRUCT):
                value_type = self._inline_struct_type()
            else:
                value_type = self._type_reference()

        self._consume(TokenKind.LEFT_BRACE, "Expected '{' after enum declaration")
        variants: list[EnumVariant] = []
        members: list[Declaration | Statement] = []
        while not self._check(TokenKind.RIGHT_BRACE) and not self._check(TokenKind.EOF):
            item_modifiers = self._modifiers()
            if self._match(TokenKind.FUNC, TokenKind.GENERATOR):
                members.append(self._function_declaration(item_modifiers, self._previous()))
                continue
            if self._match(TokenKind.NEW):
                members.append(self._function_declaration(item_modifiers, self._previous()))
                continue
            if item_modifiers:
                token = self._peek()
                raise ParserError("Expected enum method after modifier", token.location)
            variant = self._consume_identifier("Expected enum variant name")
            value = None
            if self._match(TokenKind.FAT_ARROW):
                value = self._expression()
            variants.append(EnumVariant(variant.location, variant.lexeme, value))
            self._match(TokenKind.COMMA, TokenKind.SEMICOLON)
        self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after enum body")
        return EnumDeclaration(
            keyword.location,
            name,
            tuple(variants),
            value_type,
            tuple(members),
            modifiers,
            True,
        )

    def _inline_struct_type(self) -> InlineStructType:
        keyword = self._previous()
        fields: list[VariableDeclaration] = []
        self._consume(TokenKind.LEFT_BRACE, "Expected '{' after inline struct")
        while not self._check(TokenKind.RIGHT_BRACE) and not self._check(TokenKind.EOF):
            modifiers = self._modifiers()
            fields.append(self._field_declaration(modifiers))
            self._match(TokenKind.COMMA, TokenKind.SEMICOLON)
        self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after inline struct")
        return InlineStructType(keyword.location, tuple(fields))

    def _fold_single_type_members(
        self, declarations: tuple[Declaration | Statement, ...]
    ) -> tuple[Declaration | Statement, ...]:
        if "multidef" in self._attributes:
            return declarations

        class_index = None
        class_declaration = None
        for index, declaration in enumerate(declarations):
            if isinstance(declaration, UseDeclaration):
                continue
            if isinstance(declaration, (ClassDeclaration, EnumDeclaration)):
                class_index = index
                class_declaration = declaration
            break

        if (
            class_index is None
            or class_declaration is None
            or class_declaration.braced_body
            or (
                isinstance(class_declaration, ClassDeclaration)
                and class_declaration.members
            )
            or (
                isinstance(class_declaration, EnumDeclaration)
                and (class_declaration.members or class_declaration.variants)
            )
        ):
            return declarations
        if isinstance(class_declaration, EnumDeclaration):
            return declarations

        prefix = declarations[:class_index]
        members: list[Declaration | Statement] = []
        implements: list[TypeReference] = list(class_declaration.implements)
        uses: list[TypeReference] = list(class_declaration.uses)
        for declaration in declarations[class_index + 1 :]:
            if isinstance(declaration, UseDeclaration):
                continue
            if isinstance(declaration, ImplementsDeclaration):
                implements.extend(declaration.interfaces)
            elif isinstance(declaration, UsesDeclaration):
                uses.extend(declaration.traits)
            else:
                members.append(declaration)
        suffix = tuple(
            declaration
            for declaration in declarations[class_index + 1 :]
            if isinstance(declaration, UseDeclaration)
        )
        folded = ClassDeclaration(
            class_declaration.location,
            class_declaration.name,
            members,
            class_declaration.modifiers,
            class_declaration.braced_body,
            class_declaration.kind,
            tuple(implements),
            tuple(uses),
        )
        return (*prefix, *suffix, folded)

    def _implements_list(self) -> tuple[TypeReference, ...]:
        interfaces = [self._type_reference()]
        while self._match(TokenKind.COMMA):
            interfaces.append(self._type_reference())
        self._match(TokenKind.SEMICOLON)
        return tuple(interfaces)

    def _uses_list(self) -> tuple[TypeReference, ...]:
        traits = [self._type_reference()]
        while self._match(TokenKind.COMMA):
            traits.append(self._type_reference())
        self._match(TokenKind.SEMICOLON)
        return tuple(traits)

    def _use_declaration(self) -> UseDeclaration:
        keyword = self._previous()
        parts = [self._consume_identifier("Expected imported name").lexeme]

        while self._match(TokenKind.DOT):
            if self._match(TokenKind.STAR):
                raise ParserError("Wildcard imports are not supported", self._previous().location)
            parts.append(
                self._consume_identifier("Expected imported name after '.'").lexeme
            )

        self._match(TokenKind.SEMICOLON)
        return UseDeclaration(keyword.location, tuple(parts))

    def _is_switch_function_declaration(self) -> bool:
        return (
            self._check(TokenKind.SWITCH)
            and self._current + 2 < len(self.tokens)
            and self.tokens[self._current + 1].kind in {TokenKind.IDENTIFIER, TokenKind.PRINT}
            and self.tokens[self._current + 2].kind is TokenKind.LEFT_PAREN
        )

    def _function_declaration(
        self,
        modifiers: tuple[str, ...],
        keyword: Token,
        return_ownership: str = "take",
    ) -> FunctionDeclaration:
        if keyword.kind is TokenKind.NEW:
            name = keyword.lexeme
        else:
            name = self._consume_function_name("Expected function name").lexeme

        type_parameters = self._function_type_parameters()
        self._consume(TokenKind.LEFT_PAREN, "Expected '(' after function name")
        parameters = self._parameters()
        self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after function parameters")

        return_type = None
        outcomes: tuple[OutcomeDeclaration, ...] = ()
        if self._match(TokenKind.COLON):
            return_type, outcomes = self._function_results()

        native_name = None
        if self._match(TokenKind.EQUAL):
            if "native" not in modifiers:
                raise ParserError("Only native functions can bind to a C symbol", self._previous().location)
            native_name = self._consume(TokenKind.STRING, "Expected native C symbol name").literal
            body: BlockStatement | Expression | None = None
            self._match(TokenKind.SEMICOLON)
        elif self._match(TokenKind.FAT_ARROW):
            body: BlockStatement | Expression | None = self._expression()
        elif self._check(TokenKind.LEFT_BRACE):
            body = self._block()
        else:
            body = None
            self._match(TokenKind.SEMICOLON)

        return FunctionDeclaration(
            keyword.location,
            name,
            tuple(parameters),
            return_type,
            outcomes,
            body,
            modifiers,
            keyword.lexeme,
            native_name if isinstance(native_name, str) else None,
            type_parameters,
            return_ownership,
        )

    def _switch_function_declaration(
        self,
        modifiers: tuple[str, ...],
        keyword: Token,
        return_ownership: str = "take",
    ) -> FunctionDeclaration:
        name = self._consume_function_name("Expected switch function name").lexeme
        type_parameters = self._function_type_parameters()
        self._consume(TokenKind.LEFT_PAREN, "Expected '(' after switch function name")
        parameters = self._parameters()
        self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after switch function parameters")

        if not self._match(TokenKind.COLON):
            raise ParserError(
                "Switch function must declare a return type",
                self._peek().location,
            )
        return_type, outcomes = self._function_results()
        if return_type is None:
            raise ParserError(
                "Switch function must declare a return type",
                self._peek().location,
            )

        body = self._switch_function_body(keyword.location)
        return FunctionDeclaration(
            keyword.location,
            name,
            tuple(parameters),
            return_type,
            outcomes,
            body,
            modifiers,
            keyword.lexeme,
            None,
            type_parameters,
            return_ownership,
        )

    def _switch_function_body(self, location: SourceLocation) -> BlockStatement:
        self._consume(TokenKind.LEFT_BRACE, "Expected switch function body")
        conditional_arms: list[tuple[Expression, BlockStatement]] = []
        default_body: BlockStatement | None = None
        seen_default = False

        while not self._check(TokenKind.RIGHT_BRACE) and not self._check(TokenKind.EOF):
            if self._match(TokenKind.DEFAULT):
                default_token = self._previous()
                if seen_default:
                    raise ParserError(
                        "Switch function can have only one default arm",
                        default_token.location,
                    )
                seen_default = True
                self._consume(TokenKind.FAT_ARROW, "Expected '=>' after switch arm pattern")
                default_body = self._switch_function_arm_body()
            else:
                if seen_default:
                    raise ParserError(
                        "Switch function default arm must be last",
                        self._peek().location,
                    )
                condition = self._expression()
                self._consume(TokenKind.FAT_ARROW, "Expected '=>' after switch arm pattern")
                conditional_arms.append((condition, self._switch_function_arm_body()))
            self._match(TokenKind.COMMA, TokenKind.SEMICOLON)

        self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after switch function")
        if default_body is None:
            raise ParserError("Switch function must have a default arm", location)

        statement: BlockStatement | IfStatement = default_body
        for condition, arm_body in reversed(conditional_arms):
            statement = IfStatement(condition.location, condition, arm_body, statement)
        return BlockStatement(location, (statement,))

    def _switch_function_arm_body(self) -> BlockStatement:
        if self._check(TokenKind.LEFT_BRACE):
            return self._block()
        expression = self._expression()
        return BlockStatement(
            expression.location,
            (ReturnStatement(expression.location, expression),),
        )

    def _function_type_parameters(self) -> tuple[TypeParameter, ...]:
        if not self._match(TokenKind.LESS):
            return ()
        parameters: list[TypeParameter] = []
        while True:
            name = self._consume_identifier("Expected type parameter name")
            constraint = None
            if self._match(TokenKind.COLON):
                if not self._match(TokenKind.IDENTIFIER, TokenKind.STRUCT, TokenKind.CLASS, TokenKind.ENUM):
                    raise ParserError(
                        "Expected type parameter constraint",
                        self._peek().location,
                    )
                constraint_token = self._previous()
                constraint = constraint_token.lexeme
            parameters.append(TypeParameter(name.location, name.lexeme, constraint))
            if not self._match(TokenKind.COMMA):
                break
        self._consume(TokenKind.GREATER, "Expected '>' after type parameters")
        return tuple(parameters)

    def _function_results(
        self,
    ) -> tuple[TypeReference | None, tuple[OutcomeDeclaration, ...]]:
        return_type: TypeReference | None = None
        outcomes: list[OutcomeDeclaration] = []

        while True:
            required = None
            marker = None
            if self._match(TokenKind.BANG, TokenKind.QUESTION):
                marker = self._previous()
                required = marker.kind is TokenKind.BANG
            type_reference = self._type_reference()
            if required is None:
                if return_type is not None:
                    raise ParserError(
                        "Function signature can declare only one success type",
                        type_reference.location,
                    )
                return_type = type_reference
            else:
                outcomes.append(
                    OutcomeDeclaration(
                        marker.location if marker is not None else type_reference.location,
                        type_reference,
                        required,
                    )
                )
            if not self._match(TokenKind.COMMA):
                return return_type, tuple(outcomes)

    def _parameters(self) -> list[Parameter]:
        parameters: list[Parameter] = []
        if self._check(TokenKind.RIGHT_PAREN):
            return parameters

        while True:
            modifiers = self._modifiers()
            lazy = self._match(TokenKind.LAZY)
            ownership = "borrow"
            if self._match(TokenKind.TAKE, TokenKind.BORROW):
                ownership = "take" if self._previous().kind is TokenKind.TAKE else "borrow"
            name = self._consume_identifier("Expected parameter name")
            self._consume(TokenKind.COLON, "Expected ':' after parameter name")
            parameters.append(
                Parameter(
                    name.location,
                    name.lexeme,
                    self._type_reference(),
                    ownership,
                    modifiers,
                    lazy,
                )
            )
            if not self._match(TokenKind.COMMA):
                return parameters

    def _variable_declaration(
        self, modifiers: tuple[str, ...], keyword: Token
    ) -> VariableDeclaration | ArrayDestructuringDeclaration:
        if self._match(TokenKind.LEFT_BRACKET):
            if modifiers:
                raise ParserError(
                    "Array destructuring cannot have modifiers",
                    keyword.location,
                )
            return self._array_destructuring_declaration(keyword)

        name = self._consume_identifier("Expected variable name")
        declared_type = None
        if self._match(TokenKind.COLON):
            declared_type = self._type_reference()

        initializer = None
        if self._match(TokenKind.EQUAL):
            initializer = self._expression()

        if declared_type is None and initializer is None:
            raise ParserError(
                "Expected variable type or initializer", self._peek().location
            )
        if keyword.kind is TokenKind.LAZY and initializer is None:
            raise ParserError("Lazy declaration requires an initializer", keyword.location)

        self._match(TokenKind.SEMICOLON)
        return VariableDeclaration(
            keyword.location,
            name.lexeme,
            initializer,
            keyword.kind is TokenKind.LET,
            declared_type,
            modifiers,
            None,
            keyword.kind is TokenKind.LAZY,
        )

    def _array_destructuring_declaration(
        self, keyword: Token
    ) -> ArrayDestructuringDeclaration:
        if self._check(TokenKind.RIGHT_BRACKET):
            raise ParserError(
                "Array destructuring requires at least one binding",
                self._peek().location,
            )

        bindings: list[VariableDeclaration] = []
        while True:
            name = self._consume_identifier(
                "Expected binding name in array destructuring"
            )
            bindings.append(
                VariableDeclaration(
                    name.location,
                    name.lexeme,
                    None,
                    keyword.kind is TokenKind.LET,
                )
            )
            if not self._match(TokenKind.COMMA):
                break
            if self._check(TokenKind.RIGHT_BRACKET):
                raise ParserError(
                    "Expected binding name after ',' in array destructuring",
                    self._peek().location,
                )

        self._consume(
            TokenKind.RIGHT_BRACKET,
            "Expected ']' after array destructuring bindings",
        )
        self._consume(
            TokenKind.EQUAL,
            "Expected '=' after array destructuring bindings",
        )
        initializer = self._expression()
        self._match(TokenKind.SEMICOLON)
        return ArrayDestructuringDeclaration(
            keyword.location,
            tuple(bindings),
            initializer,
        )

    def _field_declaration(
        self,
        modifiers: tuple[str, ...],
        ownership: str | None = None,
    ) -> VariableDeclaration:
        name = self._consume_identifier("Expected field name")
        declared_type = None
        if self._match(TokenKind.COLON):
            declared_type = self._type_reference()

        initializer = None
        if self._match(TokenKind.EQUAL):
            initializer = self._expression()

        if declared_type is None and initializer is None:
            raise ParserError(
                "Expected field type or initializer", self._peek().location
            )

        self._match(TokenKind.SEMICOLON)
        return VariableDeclaration(
            name.location,
            name.lexeme,
            initializer,
            False,
            declared_type,
            modifiers,
            ownership,
            False,
        )

    def _type_reference(self) -> TypeReference:
        start = self._peek()
        parts = [self._consume_type_name("Expected type name").lexeme]
        while self._match(TokenKind.DOT):
            parts.append(self._consume_type_name("Expected type name after '.'").lexeme)

        arguments: list[TypeReference] = []
        if self._match(TokenKind.LESS):
            while True:
                arguments.append(self._type_reference())
                if not self._match(TokenKind.COMMA):
                    break
            self._consume(TokenKind.GREATER, "Expected '>' after type arguments")

        array_dimensions: list[Expression | None] = []
        while self._match(TokenKind.LEFT_BRACKET):
            if self._check(TokenKind.RIGHT_BRACKET):
                array_dimensions.append(None)
            else:
                array_dimensions.append(self._expression())
            self._consume(TokenKind.RIGHT_BRACKET, "Expected ']' in array type")

        nullable = self._match(TokenKind.QUESTION)
        return TypeReference(
            start.location,
            ".".join(parts),
            len(array_dimensions),
            nullable,
            tuple(array_dimensions),
            tuple(arguments),
        )

    def _statement(self) -> Statement:
        if self._match(TokenKind.LEFT_BRACE):
            return self._block_after_left_brace(self._previous().location)
        if self._match(TokenKind.PRINT):
            return self._print_statement()
        if self._match(TokenKind.RETURN):
            return self._return_statement()
        if self._match(TokenKind.BREAK):
            return self._break_statement()
        if self._match(TokenKind.IF):
            return self._if_statement()
        if self._match(TokenKind.SWITCH):
            return self._switch_statement()
        if self._match(TokenKind.FOR):
            return self._for_statement()
        if self._match(TokenKind.WHILE):
            return self._while_statement()
        if self._match(TokenKind.DO):
            return self._do_while_statement()
        return self._expression_statement()

    def _block(self) -> BlockStatement:
        left = self._consume(TokenKind.LEFT_BRACE, "Expected function body")
        return self._block_after_left_brace(left.location)

    def _block_after_left_brace(self, location: SourceLocation) -> BlockStatement:
        statements: list[Statement | Declaration] = []
        while not self._check(TokenKind.RIGHT_BRACE) and not self._check(TokenKind.EOF):
            statements.append(self._declaration())
        self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after block")
        return BlockStatement(location, tuple(statements))

    def _print_statement(self) -> PrintStatement:
        keyword = self._previous()
        expression = self._expression()
        self._match(TokenKind.SEMICOLON)
        return PrintStatement(keyword.location, expression)

    def _return_statement(self) -> ReturnStatement:
        keyword = self._previous()
        if self._check(TokenKind.RIGHT_BRACE) or self._check(TokenKind.SEMICOLON):
            expression = None
        else:
            expression = self._expression()
        self._match(TokenKind.SEMICOLON)
        return ReturnStatement(keyword.location, expression)

    def _break_statement(self) -> BreakStatement:
        keyword = self._previous()
        if self._check(TokenKind.RIGHT_BRACE) or self._check(TokenKind.SEMICOLON):
            expression = None
        else:
            expression = self._expression()
        self._match(TokenKind.SEMICOLON)
        return BreakStatement(keyword.location, expression)

    def _if_statement(self) -> IfStatement:
        keyword = self._previous()
        condition = self._expression()
        then_branch = self._block()
        else_branch = None

        if self._match(TokenKind.ELSEIF):
            else_branch = self._if_statement()
        elif self._match(TokenKind.ELSE):
            if self._match(TokenKind.IF):
                else_branch = self._if_statement()
            else:
                else_branch = self._block()

        return IfStatement(keyword.location, condition, then_branch, else_branch)

    def _switch_statement(self) -> SwitchStatement:
        keyword = self._previous()
        expression = self._expression()
        self._consume(TokenKind.LEFT_BRACE, "Expected '{' after switch expression")
        arms: list[SwitchArm] = []
        seen_default = False

        while not self._check(TokenKind.RIGHT_BRACE) and not self._check(TokenKind.EOF):
            if self._match(TokenKind.DEFAULT):
                pattern = None
                if seen_default:
                    raise ParserError("Switch can have only one default arm", self._previous().location)
                seen_default = True
            else:
                if seen_default:
                    raise ParserError("Switch default arm must be last", self._peek().location)
                pattern = self._expression()
            self._consume(TokenKind.FAT_ARROW, "Expected '=>' after switch arm pattern")
            if self._check(TokenKind.LEFT_BRACE):
                body: BlockStatement | Statement = self._block()
            else:
                body = self._statement()
            arms.append(SwitchArm((pattern or body).location, pattern, body))
            self._match(TokenKind.COMMA, TokenKind.SEMICOLON)

        self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after switch")
        return SwitchStatement(keyword.location, expression, tuple(arms))

    def _while_statement(self) -> WhileStatement:
        keyword = self._previous()
        condition = self._expression()
        return WhileStatement(keyword.location, condition, self._block())

    def _do_while_statement(self) -> DoWhileStatement:
        keyword = self._previous()
        body = self._block()
        self._consume(TokenKind.WHILE, "Expected 'while' after do body")
        condition = self._expression()
        self._match(TokenKind.SEMICOLON)
        return DoWhileStatement(keyword.location, body, condition)

    def _for_statement(self) -> ForStatement:
        keyword = self._previous()
        source = self._expression()
        self._consume(TokenKind.AS, "Expected 'as' after for source")
        item = self._consume_identifier("Expected for item name")
        body = self._block()
        return ForStatement(
            keyword.location,
            source,
            VariableDeclaration(item.location, item.lexeme, None),
            body,
        )

    def _expression_statement(self) -> ExpressionStatement:
        expression = self._expression()
        if self._match(TokenKind.AS):
            binding = self._consume_identifier("Expected scoped borrow name after 'as'")
            body = self._block()
            return BorrowScopeStatement(
                expression.location,
                expression,
                VariableDeclaration(binding.location, binding.lexeme, None),
                body,
            )
        self._match(TokenKind.SEMICOLON)
        return ExpressionStatement(expression.location, expression)

    def _expression(self) -> Expression:
        return self._assignment()

    def _assignment(self) -> Expression:
        expression = self._conditional()
        if self._match(
            TokenKind.EQUAL,
            TokenKind.PLUS_EQUAL,
            TokenKind.MINUS_EQUAL,
            TokenKind.STAR_EQUAL,
            TokenKind.SLASH_EQUAL,
            TokenKind.PERCENT_EQUAL,
        ):
            operator = self._previous()
            value = self._assignment()
            self._ensure_assignment_target(expression, operator)
            return AssignmentExpression(
                operator.location,
                expression,
                value,
                _COMPOUND_ASSIGNMENT_OPERATORS.get(operator.kind, TokenKind.EQUAL),
            )
        return expression

    def _conditional(self) -> Expression:
        expression = self._null_coalescing()
        if self._match(TokenKind.QUESTION):
            then_expression = self._expression()
            self._consume(TokenKind.COLON, "Expected ':' in conditional expression")
            else_expression = self._conditional()
            return ConditionalExpression(
                expression.location, expression, then_expression, else_expression
            )
        return expression

    def _null_coalescing(self) -> Expression:
        return self._left_associative(
            self._logical_or, {TokenKind.NULL_COALESCE, TokenKind.APPLY}
        )

    def _logical_or(self) -> Expression:
        return self._left_associative(self._logical_and, {TokenKind.OR_OR})

    def _logical_and(self) -> Expression:
        return self._left_associative(self._equality, {TokenKind.AND_AND})

    def _equality(self) -> Expression:
        return self._left_associative(
            self._comparison, {TokenKind.EQUAL_EQUAL, TokenKind.BANG_EQUAL}
        )

    def _comparison(self) -> Expression:
        expression = self._term()
        while self._match(
            TokenKind.LESS,
            TokenKind.LESS_EQUAL,
            TokenKind.GREATER,
            TokenKind.GREATER_EQUAL,
            TokenKind.IN,
        ):
            operator = self._previous()
            right = self._term()
            expression = BinaryExpression(
                expression.location, expression, operator.kind, right
            )
        if self._match(TokenKind.NOT):
            operator = self._previous()
            self._consume(TokenKind.IN, "Expected 'in' after 'not'")
            right = self._term()
            expression = BinaryExpression(
                expression.location, expression, operator.kind, right
            )
        return expression

    def _term(self) -> Expression:
        return self._left_associative(self._factor, {TokenKind.PLUS, TokenKind.MINUS})

    def _factor(self) -> Expression:
        return self._left_associative(
            self._unary, {TokenKind.STAR, TokenKind.SLASH, TokenKind.PERCENT}
        )

    def _unary(self) -> Expression:
        if self._match(TokenKind.CATCH):
            return self._catch_expression(self._previous())
        if self._match(TokenKind.FORWARD):
            keyword = self._previous()
            return ForwardExpression(keyword.location, self._unary())
        if self._match(TokenKind.MOVE):
            keyword = self._previous()
            return MoveExpression(keyword.location, self._unary())
        if self._match(TokenKind.BANG, TokenKind.MINUS, TokenKind.NOT, TokenKind.AWAIT):
            operator = self._previous()
            return UnaryExpression(operator.location, operator.kind, self._unary())
        if self._match(TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS):
            operator = self._previous()
            target = self._unary()
            self._ensure_assignment_target(target, operator)
            return AssignmentExpression(
                operator.location,
                target,
                LiteralExpression(operator.location, 1),
                _INCREMENT_OPERATORS[operator.kind],
            )
        return self._postfix()

    def _catch_expression(self, keyword: Token) -> CatchExpression:
        expression = self._unary()
        self._consume(TokenKind.LEFT_BRACE, "Expected '{' after catch expression")
        handlers: list[CatchHandler] = []
        while not self._check(TokenKind.RIGHT_BRACE) and not self._check(TokenKind.EOF):
            name = self._consume_identifier("Expected catch binding name")
            self._consume(TokenKind.COLON, "Expected ':' after catch binding name")
            type_reference = self._type_reference()
            self._consume(TokenKind.FAT_ARROW, "Expected '=>' after catch outcome type")
            if self._check(TokenKind.LEFT_BRACE):
                handler_expression = self._block()
            else:
                handler_expression = self._expression()
            handlers.append(
                CatchHandler(
                    name.location,
                    name.lexeme,
                    type_reference,
                    handler_expression,
                )
            )
            self._match(TokenKind.COMMA, TokenKind.SEMICOLON)
        self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after catch handlers")
        return CatchExpression(keyword.location, expression, tuple(handlers))

    def _postfix(self) -> Expression:
        expression = self._primary()

        while True:
            if self._match(TokenKind.LEFT_PAREN):
                expression = self._finish_call(expression)
            elif self._check(TokenKind.LESS):
                generic_call = self._try_generic_call(expression)
                if generic_call is None:
                    return expression
                expression = generic_call
            elif self._match(TokenKind.DOT, TokenKind.NULL_SAFE_DOT):
                operator = self._previous()
                if self._match(TokenKind.LEFT_BRACE):
                    if operator.kind is TokenKind.NULL_SAFE_DOT:
                        raise ParserError(
                            "Null-safe member blocks are not supported",
                            operator.location,
                        )
                    expression = self._finish_member_block(expression, operator.location)
                    continue
                member = self._consume_member_name("Expected member name")
                expression = MemberExpression(
                    expression.location,
                    expression,
                    member.lexeme,
                    operator.kind is TokenKind.NULL_SAFE_DOT,
                )
            elif self._match(TokenKind.LEFT_BRACKET):
                arguments = self._bulk_arguments()
                if self._is_bulk_call_callee(expression, arguments):
                    expression = BulkCallExpression(
                        expression.location, expression, tuple(arguments)
                    )
                elif len(arguments) == 1:
                    expression = IndexExpression(
                        expression.location, expression, arguments[0]
                    )
                else:
                    raise ParserError(
                        "Index expression expects one index",
                        expression.location,
                    )
            elif self._match(TokenKind.GENERATOR):
                generator = self._previous()
                self._consume(TokenKind.LEFT_BRACKET, "Expected '[' after generator")
                arguments = self._bulk_arguments()
                expression = BulkCallExpression(
                    expression.location,
                    expression,
                    tuple(arguments),
                    generator=True,
                )
            elif self._match(TokenKind.TASK):
                task = self._previous()
                self._consume(TokenKind.LEFT_BRACKET, "Expected '[' after task")
                arguments = self._bulk_arguments()
                expression = BulkCallExpression(
                    expression.location,
                    expression,
                    tuple(arguments),
                    task=task.kind is TokenKind.TASK,
                )
            elif self._match(TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS):
                operator = self._previous()
                self._ensure_assignment_target(expression, operator)
                expression = AssignmentExpression(
                    operator.location,
                    expression,
                    LiteralExpression(operator.location, 1),
                    _INCREMENT_OPERATORS[operator.kind],
                )
            else:
                return expression

    def _ensure_assignment_target(self, expression: Expression, operator: Token) -> None:
        if isinstance(
            expression,
            (IdentifierExpression, MemberExpression, IndexExpression),
        ):
            return
        raise ParserError("Invalid assignment target", operator.location)

    def _consume_member_name(self, message: str) -> Token:
        if self._match(TokenKind.IDENTIFIER, TokenKind.NEW, TokenKind.AWAIT):
            return self._previous()
        token = self._peek()
        raise ParserError(message, token.location)

    def _finish_call(self, callee: Expression) -> CallExpression:
        arguments: list[Expression] = []
        if not self._check(TokenKind.RIGHT_PAREN):
            while True:
                arguments.append(self._expression())
                if not self._match(TokenKind.COMMA):
                    break
        self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after arguments")
        return CallExpression(callee.location, callee, tuple(arguments))

    def _try_generic_call(self, callee: Expression) -> CallExpression | None:
        checkpoint = self._current
        try:
            self._consume(TokenKind.LESS, "Expected '<' before type arguments")
            type_arguments = [self._type_reference()]
            while self._match(TokenKind.COMMA):
                type_arguments.append(self._type_reference())
            self._consume(TokenKind.GREATER, "Expected '>' after type arguments")
            self._consume(TokenKind.LEFT_PAREN, "Expected '(' after generic call type arguments")
            arguments: list[Expression] = []
            if not self._check(TokenKind.RIGHT_PAREN):
                while True:
                    arguments.append(self._expression())
                    if not self._match(TokenKind.COMMA):
                        break
            self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after arguments")
            return CallExpression(callee.location, callee, tuple(arguments), tuple(type_arguments))
        except ParserError:
            self._current = checkpoint
            return None

    def _bulk_arguments(self) -> list[Expression]:
        arguments: list[Expression] = []
        if not self._check(TokenKind.RIGHT_BRACKET):
            while True:
                arguments.append(self._bulk_argument())
                if not self._match(TokenKind.COMMA):
                    break
                if self._check(TokenKind.RIGHT_BRACKET):
                    break
        self._consume(TokenKind.RIGHT_BRACKET, "Expected ']' after arguments")
        return arguments

    def _bulk_argument(self) -> Expression:
        if self._match(TokenKind.LEFT_PAREN):
            left = self._previous()
            first = self._expression()
            if not self._match(TokenKind.COMMA):
                self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after expression")
                return GroupingExpression(left.location, first)
            arguments = [first]
            while True:
                arguments.append(self._expression())
                if not self._match(TokenKind.COMMA):
                    break
                if self._check(TokenKind.RIGHT_PAREN):
                    break
            self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after argument pack")
            return BulkArgumentPack(left.location, tuple(arguments))
        return self._expression()

    def _is_bulk_call_callee(
        self, expression: Expression, arguments: list[Expression]
    ) -> bool:
        if (
            len(arguments) == 1
            and isinstance(arguments[0], LiteralExpression)
            and isinstance(arguments[0].value, int)
        ):
            return False
        if isinstance(expression, IdentifierExpression):
            return True
        if isinstance(expression, MemberExpression):
            return not isinstance(expression.receiver, (ThisExpression, SelfExpression))
        if isinstance(expression, CallExpression):
            return self._is_bulk_call_callee(expression.callee, arguments)
        return False

    def _finish_member_block(
        self,
        receiver: Expression,
        location: SourceLocation,
    ) -> MemberBlockExpression:
        expressions: list[Expression] = []
        while not self._check(TokenKind.RIGHT_BRACE) and not self._check(TokenKind.EOF):
            member = self._consume_member_name("Expected member name")
            member_expression = MemberExpression(member.location, receiver, member.lexeme)
            if self._match(
                TokenKind.EQUAL,
                TokenKind.PLUS_EQUAL,
                TokenKind.MINUS_EQUAL,
                TokenKind.STAR_EQUAL,
                TokenKind.SLASH_EQUAL,
                TokenKind.PERCENT_EQUAL,
            ):
                operator = self._previous()
                expressions.append(
                    AssignmentExpression(
                        operator.location,
                        member_expression,
                        self._expression(),
                        _COMPOUND_ASSIGNMENT_OPERATORS.get(operator.kind, TokenKind.EQUAL),
                    )
                )
            elif self._match(TokenKind.LEFT_PAREN):
                expressions.append(self._finish_call(member_expression))
            else:
                expressions.append(member_expression)
            self._match(TokenKind.SEMICOLON)
        self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after member block")
        return MemberBlockExpression(location, receiver, tuple(expressions))

    def _primary(self) -> Expression:
        if self._match(TokenKind.FOR):
            return self._for_expression(self._previous())
        if self._match(TokenKind.WHILE):
            return self._while_expression(self._previous())
        if self._match(TokenKind.DO):
            return self._do_while_expression(self._previous())
        if self._match(TokenKind.INTEGER, TokenKind.FLOAT, TokenKind.STRING):
            token = self._previous()
            return LiteralExpression(token.location, token.literal)
        if self._match(TokenKind.TRUE):
            return LiteralExpression(self._previous().location, True)
        if self._match(TokenKind.FALSE):
            return LiteralExpression(self._previous().location, False)
        if self._match(TokenKind.NULL):
            return LiteralExpression(self._previous().location, None)
        if self._match(TokenKind.THIS):
            return ThisExpression(self._previous().location)
        if self._match(TokenKind.SELF):
            return SelfExpression(self._previous().location)
        if self._match(TokenKind.IDENTIFIER):
            token = self._previous()
            return IdentifierExpression(token.location, token.lexeme)
        if self._match(TokenKind.LEFT_PAREN):
            left = self._previous()
            expression = self._expression()
            self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after expression")
            return GroupingExpression(left.location, expression)
        if self._match(TokenKind.LEFT_BRACKET):
            left = self._previous()
            elements: list[Expression] = []
            if not self._check(TokenKind.RIGHT_BRACKET):
                while True:
                    elements.append(self._expression())
                    if not self._match(TokenKind.COMMA):
                        break
                    if self._check(TokenKind.RIGHT_BRACKET):
                        break
            self._consume(TokenKind.RIGHT_BRACKET, "Expected ']' after array literal")
            return ArrayLiteralExpression(left.location, tuple(elements))
        if self._match(TokenKind.LEFT_BRACE):
            return self._struct_literal(self._previous())

        token = self._peek()
        raise ParserError(f"Expected expression, got {token.kind.value!r}", token.location)

    def _loop_fallback(self) -> Expression | None:
        return self._expression() if self._match(TokenKind.ELSE) else None

    def _while_expression(self, keyword: Token) -> WhileExpression:
        condition = self._expression()
        body = self._block()
        return WhileExpression(
            keyword.location,
            condition,
            body,
            self._loop_fallback(),
        )

    def _do_while_expression(self, keyword: Token) -> DoWhileExpression:
        body = self._block()
        self._consume(TokenKind.WHILE, "Expected 'while' after do body")
        condition = self._expression()
        return DoWhileExpression(
            keyword.location,
            body,
            condition,
            self._loop_fallback(),
        )

    def _for_expression(self, keyword: Token) -> ForExpression:
        source = self._expression()
        self._consume(TokenKind.AS, "Expected 'as' after for source")
        item = self._consume_identifier("Expected for item name")
        body = self._block()
        return ForExpression(
            keyword.location,
            source,
            VariableDeclaration(item.location, item.lexeme, None),
            body,
            self._loop_fallback(),
        )

    def _struct_literal(self, left: Token) -> StructLiteralExpression:
        fields: list[StructLiteralField] = []
        if not self._check(TokenKind.RIGHT_BRACE):
            while True:
                name = None
                if (
                    self._check(TokenKind.IDENTIFIER)
                    and self._current + 1 < len(self.tokens)
                    and self.tokens[self._current + 1].kind is TokenKind.COLON
                ):
                    name = self._advance().lexeme
                    self._consume(TokenKind.COLON, "Expected ':' after struct literal field")
                value = self._expression()
                fields.append(StructLiteralField(value.location, name, value))
                if not self._match(TokenKind.COMMA):
                    break
                if self._check(TokenKind.RIGHT_BRACE):
                    break
        self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after struct literal")
        return StructLiteralExpression(left.location, tuple(fields))

    def _left_associative(self, parse_operand, operators: set[TokenKind]) -> Expression:
        expression = parse_operand()
        while self._peek().kind in operators:
            operator = self._advance()
            right = parse_operand()
            expression = BinaryExpression(
                expression.location, expression, operator.kind, right
            )
        return expression

    def _modifiers(self) -> tuple[str, ...]:
        modifiers: list[str] = []
        while self._peek().kind in _MODIFIERS:
            modifiers.append(self._advance().lexeme)
        return tuple(modifiers)

    def _consume_identifier(self, message: str) -> Token:
        return self._consume(TokenKind.IDENTIFIER, message)

    def _consume_function_name(self, message: str) -> Token:
        if self._match(TokenKind.IDENTIFIER, TokenKind.PRINT):
            return self._previous()
        token = self._peek()
        raise ParserError(message, token.location)

    def _consume_type_name(self, message: str) -> Token:
        if self._match(TokenKind.IDENTIFIER, TokenKind.SELF):
            return self._previous()
        token = self._peek()
        raise ParserError(message, token.location)

    def _match(self, *kinds: TokenKind) -> bool:
        if self._peek().kind not in kinds:
            return False
        self._advance()
        return True

    def _consume(self, kind: TokenKind, message: str) -> Token:
        if self._check(kind):
            return self._advance()
        raise ParserError(message, self._peek().location)

    def _check(self, kind: TokenKind) -> bool:
        return self._peek().kind is kind

    def _advance(self) -> Token:
        if not self._check(TokenKind.EOF):
            self._current += 1
        return self._previous()

    def _peek(self) -> Token:
        return self.tokens[self._current]

    def _previous(self) -> Token:
        return self.tokens[self._current - 1]

    def _inferred_type_name(self) -> str | None:
        if self.source_name is None:
            return None
        stem = PurePath(self.source_name).stem
        return stem or None


def parse(
    source_or_tokens: str | Sequence[Token],
    *,
    source_name: str | None = None,
) -> Program:
    """Parse Forge source or tokens into a :class:`Program` AST."""

    return Parser(source_or_tokens, source_name=source_name).parse()


def parse_expression(
    source_or_tokens: str | Sequence[Token],
    *,
    source_name: str | None = None,
) -> Expression:
    """Parse Forge source or tokens into a single expression AST."""

    return Parser(source_or_tokens, source_name=source_name).parse_expression()
