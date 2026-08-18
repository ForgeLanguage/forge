import unittest

from forge_lexer import TokenKind, lex
from forge_parser import (
    AssignmentExpression,
    ArrayDestructuringDeclaration,
    ArrayLiteralExpression,
    BinaryExpression,
    BlockStatement,
    BulkArgumentPack,
    BulkCallExpression,
    CatchExpression,
    CallExpression,
    ClassDeclaration,
    DoWhileExpression,
    EnumDeclaration,
    ForStatement,
    ForExpression,
    ForwardExpression,
    FunctionDeclaration,
    IdentifierExpression,
    IfStatement,
    IndexExpression,
    LiteralExpression,
    MemberBlockExpression,
    MemberExpression,
    MoveExpression,
    OutcomeDeclaration,
    WhileExpression,
    ParserError,
    PrintStatement,
    ReturnStatement,
    StructLiteralExpression,
    SwitchStatement,
    TypeParameter,
    TypeReference,
    UseDeclaration,
    VariableDeclaration,
    WhileStatement,
    parse,
    parse_expression,
)


class ParserTests(unittest.TestCase):
    def test_parses_hello_world_program(self) -> None:
        program = parse(
            '''
class

public static main(args: String[]): Void
{
    print "Hello, World!"
}
'''
        )

        self.assertEqual(len(program.declarations), 1)
        self.assertIsInstance(program.declarations[0], ClassDeclaration)
        self.assertEqual(len(program.declarations[0].members), 1)

        function = program.declarations[0].members[0]
        self.assertIsInstance(function, FunctionDeclaration)
        self.assertEqual(function.name, "main")
        self.assertEqual(function.modifiers, ("public", "static"))
        self.assertEqual(function.return_type.name, "Void")
        self.assertEqual(function.parameters[0].name, "args")
        self.assertEqual(function.parameters[0].type.name, "String")
        self.assertEqual(function.parameters[0].type.array_depth, 1)
        self.assertEqual(function.parameters[0].type.array_dimensions, (None,))

        self.assertIsInstance(function.body, BlockStatement)
        statement = function.body.statements[0]
        self.assertIsInstance(statement, PrintStatement)
        self.assertEqual(statement.expression.value, "Hello, World!")

    def test_parses_fixed_size_array_type(self) -> None:
        declaration = parse("var values: Int[2 + 3]").declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        self.assertEqual(declaration.type.name, "Int")
        self.assertEqual(declaration.type.array_depth, 1)
        self.assertIsInstance(declaration.type.array_dimensions[0], BinaryExpression)

    def test_variable_declarations_can_use_inferred_or_explicit_types(self) -> None:
        program = parse(
            """
const name = "Forge"
var counter: Int = 0
lazy delayed: Int = 1
"""
        )

        inferred, explicit, delayed = program.declarations
        self.assertIsInstance(inferred, VariableDeclaration)
        self.assertEqual(inferred.name, "name")
        self.assertFalse(inferred.mutable)
        self.assertFalse(inferred.lazy)
        self.assertIsNone(inferred.type)
        self.assertIsInstance(explicit, VariableDeclaration)
        self.assertEqual(explicit.name, "counter")
        self.assertTrue(explicit.mutable)
        self.assertEqual(explicit.type.name, "Int")
        self.assertIsInstance(delayed, VariableDeclaration)
        self.assertEqual(delayed.name, "delayed")
        self.assertFalse(delayed.mutable)
        self.assertTrue(delayed.lazy)
        self.assertEqual(delayed.type.name, "Int")

    def test_parses_lazy_parameter(self) -> None:
        function = parse("consume(lazy value: Int): Int => value").declarations[0]

        self.assertIsInstance(function, FunctionDeclaration)
        self.assertTrue(function.parameters[0].lazy)
        self.assertEqual(function.parameters[0].name, "value")

    def test_parses_template_function_type_parameter(self) -> None:
        function = parse("public template parse<T:struct>(): T").declarations[0]

        self.assertIsInstance(function, FunctionDeclaration)
        self.assertEqual(function.modifiers, ("public", "template"))
        self.assertIsInstance(function.type_parameters[0], TypeParameter)
        self.assertEqual(function.type_parameters[0].name, "T")
        self.assertEqual(function.type_parameters[0].constraint, "struct")
        self.assertEqual(function.return_type.name, "T")

    def test_parses_generic_call_type_arguments(self) -> None:
        expression = parse_expression("Reflection.type<T>().properties")

        self.assertIsInstance(expression, MemberExpression)
        call = expression.receiver
        self.assertIsInstance(call, CallExpression)
        self.assertEqual(call.type_arguments[0].name, "T")

    def test_expression_precedence_is_preserved_in_ast(self) -> None:
        declaration = parse("const value: Int = 2 + 3 * 4").declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        expression = declaration.initializer
        self.assertIsInstance(expression, BinaryExpression)
        self.assertEqual(expression.operator, TokenKind.PLUS)
        self.assertIsInstance(expression.right, BinaryExpression)
        self.assertEqual(expression.right.operator, TokenKind.STAR)

    def test_parses_calls_members_indexes_and_assignment(self) -> None:
        statement = parse('this.items[0] = format("Hello, ", name)').declarations[0]

        self.assertIsInstance(statement.expression, AssignmentExpression)
        self.assertIsInstance(statement.expression.target, IndexExpression)
        target = statement.expression.target
        self.assertIsInstance(target.receiver, MemberExpression)
        self.assertEqual(target.receiver.member, "items")
        self.assertIsInstance(statement.expression.value, CallExpression)

    def test_parses_compound_and_increment_assignments(self) -> None:
        plus_equal = parse("counter += 2").declarations[0].expression
        postfix = parse("counter++").declarations[0].expression
        prefix = parse("--counter").declarations[0].expression

        self.assertIsInstance(plus_equal, AssignmentExpression)
        self.assertEqual(plus_equal.operator, TokenKind.PLUS)
        self.assertIsInstance(postfix, AssignmentExpression)
        self.assertEqual(postfix.operator, TokenKind.PLUS)
        self.assertEqual(postfix.value.value, 1)
        self.assertIsInstance(prefix, AssignmentExpression)
        self.assertEqual(prefix.operator, TokenKind.MINUS)
        self.assertEqual(prefix.value.value, 1)

    def test_parses_short_function_body(self) -> None:
        function = parse("public static square(x: Int): Int => x * x").declarations[0]

        self.assertIsInstance(function, FunctionDeclaration)
        self.assertIsInstance(function.body, BinaryExpression)

    def test_rejects_func_keyword_in_function_declaration(self) -> None:
        with self.assertRaisesRegex(ParserError, "'func' is not allowed"):
            parse("func answer(): Int => 42")

        with self.assertRaisesRegex(ParserError, "'func' is not allowed"):
            parse("class App { public func run(): Void {} }")

    def test_parses_native_function_binding(self) -> None:
        function = parse(
            'public static native answer(): Int = "native_answer"'
        ).declarations[0]

        self.assertIsInstance(function, FunctionDeclaration)
        self.assertEqual(function.modifiers, ("public", "static", "native"))
        self.assertEqual(function.native_name, "native_answer")
        self.assertIsNone(function.body)

    def test_parses_return_statement(self) -> None:
        function = parse("answer(): Int { return 42 }").declarations[0]

        self.assertIsInstance(function.body.statements[0], ReturnStatement)
        expression = function.body.statements[0].expression
        self.assertIsInstance(expression, LiteralExpression)
        self.assertEqual(expression.value, 42)

    def test_parses_for_statement_over_collection(self) -> None:
        statement = parse(
            """
for responses as response {
    print response.status
}
"""
        ).declarations[0]

        self.assertIsInstance(statement, ForStatement)
        self.assertIsInstance(statement.source, IdentifierExpression)
        self.assertEqual(statement.source.name, "responses")
        self.assertEqual(statement.item.name, "response")
        self.assertIsInstance(statement.body.statements[0], PrintStatement)

    def test_parses_switch_statement_without_case_or_break(self) -> None:
        statement = parse(
            """
switch status {
    FeedStatus.Ok => {
        count = count + 1
    }
    FeedStatus.FeedNoContent => count = count + 1
    default => print "unknown"
}
"""
        ).declarations[0]

        self.assertIsInstance(statement, SwitchStatement)
        self.assertIsInstance(statement.expression, IdentifierExpression)
        self.assertEqual(len(statement.arms), 3)
        self.assertIsInstance(statement.arms[0].body, BlockStatement)
        self.assertIsNone(statement.arms[2].pattern)
        self.assertIsInstance(statement.arms[2].body, PrintStatement)

    def test_parses_switch_function_as_returning_if_chain(self) -> None:
        function = parse(
            """
public static switch classify(len: Int): String {
    len == 0 => "empty"
    len < 5 => "short"
    default => "long"
}
"""
        ).declarations[0]

        self.assertIsInstance(function, FunctionDeclaration)
        self.assertEqual(function.kind, "switch")
        self.assertEqual(function.name, "classify")
        self.assertEqual(function.modifiers, ("public", "static"))
        self.assertIsInstance(function.body, BlockStatement)
        first = function.body.statements[0]
        self.assertIsInstance(first, IfStatement)
        self.assertIsInstance(first.then_branch.statements[0], ReturnStatement)
        self.assertIsInstance(first.else_branch, IfStatement)
        self.assertIsInstance(first.else_branch.else_branch, BlockStatement)

    def test_switch_function_requires_default_arm(self) -> None:
        with self.assertRaisesRegex(ParserError, "default arm"):
            parse(
                """
switch classify(len: Int): String {
    len < 5 => "short"
}
"""
            )

    def test_parses_class_fields(self) -> None:
        class_declaration = parse("class App { public args: String[] }").declarations[0]

        self.assertIsInstance(class_declaration, ClassDeclaration)
        field = class_declaration.members[0]
        self.assertIsInstance(field, VariableDeclaration)
        self.assertEqual(field.name, "args")
        self.assertEqual(field.modifiers, ("public",))
        self.assertEqual(field.type.array_depth, 1)

    def test_parses_not_in_expression(self) -> None:
        statement = parse('"x" not in text').declarations[0]

        self.assertIsInstance(statement.expression, BinaryExpression)
        self.assertEqual(statement.expression.operator, TokenKind.NOT)

    def test_parse_accepts_tokens(self) -> None:
        program = parse(lex("const answer = 42"))

        self.assertIsInstance(program.declarations[0], VariableDeclaration)

    def test_parses_program_attributes(self) -> None:
        program = parse("@multidef\nclass App {}")

        self.assertEqual(program.attributes, ("multidef",))
        self.assertEqual(program.declarations[0].name, "App")

    def test_infers_single_type_name_from_source_name(self) -> None:
        program = parse("class {}", source_name="HelloWorld.forge")

        self.assertEqual(program.source_name, "HelloWorld.forge")
        self.assertEqual(program.declarations[0].name, "HelloWorld")

    def test_multidef_disables_single_type_name_inference(self) -> None:
        program = parse("@multidef\nclass {}", source_name="HelloWorld.forge")

        self.assertIsNone(program.declarations[0].name)

    def test_parses_use_declarations(self) -> None:
        program = parse("use app.User\nuse legacy.User")

        first, second = program.declarations
        self.assertIsInstance(first, UseDeclaration)
        self.assertEqual(first.path, ("app", "User"))
        self.assertIsInstance(second, UseDeclaration)
        self.assertEqual(second.path, ("legacy", "User"))

    def test_parses_interface_and_implements_declarations(self) -> None:
        program = parse(
            """
@multidef
interface Stringable {
    public toString(): String
}

class User {
    implements Stringable
}
"""
        )

        interface, class_declaration = program.declarations
        self.assertIsInstance(interface, ClassDeclaration)
        self.assertEqual(interface.kind, "interface")
        self.assertEqual(interface.members[0].body, None)
        self.assertIsInstance(class_declaration, ClassDeclaration)
        self.assertEqual(class_declaration.implements[0].name, "Stringable")

    def test_parses_trait_uses_declarations(self) -> None:
        program = parse(
            """
@multidef
trait RunnableLogic {
    public run(): Void {}
}

class App {
    uses RunnableLogic
}
"""
        )

        _, class_declaration = program.declarations
        self.assertIsInstance(class_declaration, ClassDeclaration)
        self.assertEqual(class_declaration.uses[0].name, "RunnableLogic")

    def test_parses_take_parameters_and_move_arguments(self) -> None:
        program = parse(
            """
setProfile(take profile: Profile): Void {}
setProfile(move profile)
"""
        )

        function, statement = program.declarations
        self.assertIsInstance(function, FunctionDeclaration)
        self.assertEqual(function.parameters[0].ownership, "take")
        self.assertIsInstance(statement.expression, CallExpression)
        self.assertIsInstance(statement.expression.arguments[0], MoveExpression)

    def test_parses_constructor_promoted_parameters(self) -> None:
        constructor = parse("class Point { public new(public x: Int, public y: Int) {} }").declarations[0].members[0]

        self.assertIsInstance(constructor, FunctionDeclaration)
        self.assertEqual(constructor.parameters[0].modifiers, ("public",))
        self.assertEqual(constructor.parameters[0].name, "x")
        self.assertEqual(constructor.parameters[1].modifiers, ("public",))
        self.assertEqual(constructor.parameters[1].name, "y")

    def test_parses_member_block_expression(self) -> None:
        statement = parse(
            """
user.{
    name = "Vasya"
    save()
}
"""
        ).declarations[0]

        self.assertIsInstance(statement.expression, MemberBlockExpression)
        self.assertEqual(len(statement.expression.expressions), 2)
        assignment, call = statement.expression.expressions
        self.assertIsInstance(assignment, AssignmentExpression)
        self.assertIsInstance(assignment.target, MemberExpression)
        self.assertEqual(assignment.target.member, "name")
        self.assertIsInstance(call, CallExpression)
        self.assertIsInstance(call.callee, MemberExpression)
        self.assertEqual(call.callee.member, "save")

    def test_parses_bulk_call_expression(self) -> None:
        declaration = parse(
            "const normalized = Vector2Int.normalize[vectors]"
        ).declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        self.assertIsInstance(declaration.initializer, BulkCallExpression)
        self.assertFalse(declaration.initializer.generator)
        self.assertEqual(len(declaration.initializer.arguments), 1)
        self.assertIsInstance(declaration.initializer.callee, MemberExpression)

    def test_parses_bulk_call_argument_packs(self) -> None:
        declaration = parse(
            "const values = Vector2Int.new[(0, 0), (1, 1)]"
        ).declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        self.assertIsInstance(declaration.initializer, BulkCallExpression)
        first, second = declaration.initializer.arguments
        self.assertIsInstance(first, BulkArgumentPack)
        self.assertIsInstance(second, BulkArgumentPack)
        self.assertEqual(len(first.arguments), 2)

    def test_parses_generator_bulk_call_expression(self) -> None:
        declaration = parse("const parsed = Int.parse generator[values]").declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        self.assertIsInstance(declaration.initializer, BulkCallExpression)
        self.assertTrue(declaration.initializer.generator)

    def test_parses_task_bulk_call_expression(self) -> None:
        declaration = parse("const pages = download task[urls]").declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        self.assertIsInstance(declaration.initializer, BulkCallExpression)
        self.assertTrue(declaration.initializer.task)
        self.assertFalse(declaration.initializer.generator)

    def test_parses_prefixed_function_outcomes_and_forward(self) -> None:
        function = parse(
            """
load(): Void, !AccessDenied, ?AllocFailed {
    forward reserve()
}
"""
        ).declarations[0]

        self.assertIsInstance(function, FunctionDeclaration)
        self.assertEqual(function.return_type.name, "Void")
        self.assertEqual(len(function.outcomes), 2)
        required, optional = function.outcomes
        self.assertIsInstance(required, OutcomeDeclaration)
        self.assertTrue(required.required)
        self.assertEqual(required.type.name, "AccessDenied")
        self.assertFalse(optional.required)
        self.assertEqual(optional.type.name, "AllocFailed")
        statement = function.body.statements[0]
        self.assertIsInstance(statement.expression, ForwardExpression)
        self.assertIsInstance(statement.expression.expression, CallExpression)

    def test_parses_generic_type_reference(self) -> None:
        declaration = parse('const pending: Task<String> = fetch()').declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        self.assertIsInstance(declaration.type, TypeReference)
        self.assertEqual(declaration.type.name, "Task")
        self.assertEqual(len(declaration.type.arguments), 1)
        self.assertEqual(declaration.type.arguments[0].name, "String")

    def test_parses_generic_struct_declaration(self) -> None:
        declaration = parse("struct Definition<T> {}").declarations[0]

        self.assertIsInstance(declaration, ClassDeclaration)
        self.assertEqual(declaration.type_parameters[0].name, "T")

    def test_parses_catch_expression_handlers(self) -> None:
        declaration = parse(
            """
const value = catch Parser.parse() {
    issue: ParseIssue => 0
}
"""
        ).declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        self.assertIsInstance(declaration.initializer, CatchExpression)
        handler = declaration.initializer.handlers[0]
        self.assertEqual(handler.name, "issue")
        self.assertEqual(handler.type.name, "ParseIssue")
        self.assertIsInstance(handler.expression, LiteralExpression)

    def test_parses_catch_handler_block(self) -> None:
        declaration = parse(
            """
const value = catch Parser.parse() {
    issue: ParseIssue => {
        return 1
    }
}
"""
        ).declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        self.assertIsInstance(declaration.initializer, CatchExpression)
        self.assertIsInstance(declaration.initializer.handlers[0].expression, BlockStatement)

    def test_parses_while_statement(self) -> None:
        statement = parse(
            """
while !window.shouldClose() {
    print "tick"
}
"""
        ).declarations[0]

        self.assertIsInstance(statement, WhileStatement)
        self.assertIsInstance(statement.body, BlockStatement)
        self.assertEqual(len(statement.body.statements), 1)

    def test_rejects_multiple_success_types_in_function_signature(self) -> None:
        with self.assertRaises(ParserError) as raised:
            parse("bad(): Int, String {}")

        self.assertEqual(
            raised.exception.message,
            "Function signature can declare only one success type",
        )

    def test_parses_array_literals_and_numeric_indexes(self) -> None:
        array_declaration, index_declaration = parse(
            """
const values = [1, 2]
const first = values[0]
"""
        ).declarations

        self.assertIsInstance(array_declaration, VariableDeclaration)
        self.assertIsInstance(array_declaration.initializer, ArrayLiteralExpression)
        self.assertEqual(len(array_declaration.initializer.elements), 2)
        self.assertIsInstance(index_declaration, VariableDeclaration)
        self.assertIsInstance(index_declaration.initializer, IndexExpression)

    def test_rejects_wildcard_use_declarations(self) -> None:
        with self.assertRaises(ParserError) as raised:
            parse("use legacy.*")

        self.assertEqual(raised.exception.message, "Wildcard imports are not supported")

    def test_reports_location_for_invalid_syntax(self) -> None:
        with self.assertRaises(ParserError) as raised:
            parse("const = 1")

        self.assertEqual(raised.exception.location.line, 1)
        self.assertEqual(raised.exception.location.column, 7)

    def test_source_name_is_attached_to_locations(self) -> None:
        with self.assertRaises(ParserError) as raised:
            parse("const = 1", source_name="src/app.forge")

        self.assertEqual(raised.exception.location.source_name, "src/app.forge")
        self.assertIn("src/app.forge:1:7", str(raised.exception))

    def test_parses_struct_with_inferred_name_and_methods(self) -> None:
        declaration = parse(
            """
public struct

public status: Int
public body: String

public isClientError(): Bool => this.status >= 400 && this.status < 500
""",
            source_name="HttpResponse.forge",
        ).declarations[0]

        self.assertIsInstance(declaration, ClassDeclaration)
        self.assertEqual(declaration.kind, "struct")
        self.assertEqual(declaration.name, "HttpResponse")
        self.assertEqual(len(declaration.members), 3)

    def test_parses_struct_literal_initializer(self) -> None:
        declaration = parse(
            """
var response: HttpResponse = {
    status: 200,
    body: "OK"
}
"""
        ).declarations[0]

        self.assertIsInstance(declaration, VariableDeclaration)
        self.assertIsInstance(declaration.initializer, StructLiteralExpression)
        self.assertEqual(declaration.initializer.fields[0].name, "status")

    def test_parses_typed_enum_and_inline_struct_enum(self) -> None:
        method_enum, status_enum = parse(
            """
@multidef

public enum HttpMethod : String {
    Get => "GET",
    Post => "POST",
}

public enum HttpStatus : struct {
    public code: Int
    public reason: String
    public isError: Bool
} {
    Ok => { 200, "OK", false }
    NotFound => { 404, "Not Found", true }

    public isClientError(): Bool => this.code >= 400 && this.code < 500
}
"""
        ).declarations

        self.assertIsInstance(method_enum, EnumDeclaration)
        self.assertEqual(method_enum.value_type.name, "String")
        self.assertEqual(method_enum.variants[0].name, "Get")
        self.assertIsInstance(status_enum, EnumDeclaration)
        self.assertEqual(len(status_enum.variants), 2)
        self.assertEqual(len(status_enum.members), 1)

    def test_parses_existing_loops_as_expressions_with_break_values(self) -> None:
        for_value, while_value, do_value = parse(
            """
const found: Int? = for [1, 2] as item {
    if item == 2 {
        break item
    }
}
const waited = while false {
    break 1
} else 2
const repeated = do {
    break
} while true else 3
"""
        ).declarations

        self.assertIsInstance(for_value.initializer, ForExpression)
        self.assertIsNone(for_value.initializer.fallback)
        self.assertIsInstance(while_value.initializer, WhileExpression)
        self.assertEqual(while_value.initializer.fallback.value, 2)
        self.assertIsInstance(do_value.initializer, DoWhileExpression)
        self.assertEqual(do_value.initializer.fallback.value, 3)


    def test_parses_const_and_let_array_destructuring(self) -> None:
        program = parse(
            """
main(values: Int[]): Void {
    const [first, second] = values
    var [left, right] = values
}
"""
        )

        const_declaration, let_declaration = program.declarations[0].body.statements
        self.assertIsInstance(const_declaration, ArrayDestructuringDeclaration)
        self.assertEqual(
            [binding.name for binding in const_declaration.bindings],
            ["first", "second"],
        )
        self.assertTrue(
            all(not binding.mutable for binding in const_declaration.bindings)
        )
        self.assertIsInstance(let_declaration, ArrayDestructuringDeclaration)
        self.assertTrue(all(binding.mutable for binding in let_declaration.bindings))

    def test_rejects_empty_or_trailing_array_destructuring_binding(self) -> None:
        with self.assertRaisesRegex(
            ParserError,
            "Array destructuring requires at least one binding",
        ):
            parse("main(values: Int[]): Void { const [] = values }")

        with self.assertRaisesRegex(
            ParserError,
            "Expected binding name after ',' in array destructuring",
        ):
            parse("main(values: Int[]): Void { const [first,] = values }")


if __name__ == "__main__":
    unittest.main()
