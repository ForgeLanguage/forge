import unittest

from forge_resolution import BuiltinSymbol, NameResolutionError, SpecialSymbol, resolve
from forge_parser import (
    CallExpression,
    IdentifierExpression,
    MemberExpression,
    VariableDeclaration,
    parse,
)


class NameResolutionTests(unittest.TestCase):
    def test_resolves_lexical_identifier_to_nearest_symbol(self) -> None:
        program = parse(
            """
const value = 1
main(value: Int): Int {
    const local = value
    return local
}
"""
        )

        result = resolve(program)
        function = program.declarations[1]
        local = function.body.statements[0]
        returned = function.body.statements[1].expression

        self.assertIsInstance(local, VariableDeclaration)
        local_initializer_symbol = result.resolutions.symbol_for(local.initializer)
        parameter_symbol = result.analysis.annotations.symbol_for(function.parameters[0])
        self.assertEqual(local_initializer_symbol, parameter_symbol)

        returned_symbol = result.resolutions.symbol_for(returned)
        local_symbol = result.analysis.annotations.symbol_for(local)
        self.assertEqual(returned_symbol, local_symbol)

    def test_resolves_forward_function_reference(self) -> None:
        program = parse(
            """
main(): Int {
    return answer()
}

answer(): Int => 42
"""
        )

        result = resolve(program)
        call = program.declarations[0].body.statements[0].expression

        self.assertIsInstance(call, CallExpression)
        callee_symbol = result.resolutions.symbol_for(call.callee)
        answer_symbol = result.analysis.annotations.symbol_for(program.declarations[1])
        self.assertEqual(callee_symbol, answer_symbol)

    def test_resolves_builtin_and_user_defined_types(self) -> None:
        program = parse(
            """
class User {}
const name: String = "Forge"
const user: User = null
const pending: Task<User>
"""
        )

        result = resolve(program)
        name_type = program.declarations[1].type
        user_type = program.declarations[2].type
        task_type = program.declarations[3].type

        self.assertIsInstance(result.resolutions.symbol_for(name_type), BuiltinSymbol)
        self.assertEqual(result.resolutions.symbol_for(name_type).name, "String")
        self.assertEqual(
            result.resolutions.symbol_for(user_type),
            result.analysis.annotations.symbol_for(program.declarations[0]),
        )
        self.assertIsInstance(result.resolutions.symbol_for(task_type), BuiltinSymbol)
        self.assertEqual(result.resolutions.symbol_for(task_type).name, "Task")
        self.assertEqual(
            result.resolutions.symbol_for(task_type.arguments[0]),
            result.analysis.annotations.symbol_for(program.declarations[0]),
        )

    def test_resolves_pattern_mismatch_as_builtin_catch_type(self) -> None:
        program = parse(
            """
main(values: Int[]): Void {
    const [first] = catch values {
        issue: PatternMismatch => { return }
    }
}
"""
        )

        result = resolve(program)
        handler_type = program.declarations[0].body.statements[0].initializer.handlers[0].type
        symbol = result.resolutions.symbol_for(handler_type)

        self.assertIsInstance(symbol, BuiltinSymbol)
        self.assertEqual(symbol.name, "PatternMismatch")

    def test_resolves_builtin_type_receiver_in_expression_position(self) -> None:
        program = parse("const text = String.fromInt(42)")

        result = resolve(program)
        receiver = program.declarations[0].initializer.callee.receiver
        symbol = result.resolutions.symbol_for(receiver)

        self.assertIsInstance(symbol, BuiltinSymbol)
        self.assertEqual(symbol.name, "String")

    def test_resolves_this_and_self_to_enclosing_class(self) -> None:
        program = parse(
            """
class App {
    static version(): String => self.name
    rename(name: String): Void {
        this.name = name
    }
}
"""
        )

        result = resolve(program)
        class_declaration = program.declarations[0]
        static_member = class_declaration.members[0].body.receiver
        assignment = class_declaration.members[1].body.statements[0].expression
        instance_member = assignment.target.receiver

        self.assertIsInstance(result.resolutions.symbol_for(static_member), SpecialSymbol)
        self.assertEqual(result.resolutions.symbol_for(static_member).node, class_declaration)
        self.assertIsInstance(result.resolutions.symbol_for(instance_member), SpecialSymbol)
        self.assertEqual(result.resolutions.symbol_for(instance_member).node, class_declaration)

    def test_resolves_self_type_to_enclosing_class(self) -> None:
        program = parse(
            """
class Node {
    same(other: self): self {
        return other
    }
}
"""
        )

        result = resolve(program)
        class_declaration = program.declarations[0]
        function = class_declaration.members[0]

        parameter_type = function.parameters[0].type
        return_type = function.return_type
        self.assertIsInstance(result.resolutions.symbol_for(parameter_type), SpecialSymbol)
        self.assertEqual(result.resolutions.symbol_for(parameter_type).node, class_declaration)
        self.assertIsInstance(result.resolutions.symbol_for(return_type), SpecialSymbol)
        self.assertEqual(result.resolutions.symbol_for(return_type).node, class_declaration)

    def test_reports_self_type_outside_class(self) -> None:
        result = resolve(parse("make(): self => null"), raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Type 'self' can only be used inside a class",
        )

    def test_reports_unknown_names_and_types(self) -> None:
        program = parse("const value: Missing = unknown")

        result = resolve(program, raise_on_error=False)

        self.assertFalse(result.ok)
        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Unknown type 'Missing'", messages)
        self.assertIn("Unknown name 'unknown'", messages)

    def test_builtin_type_name_is_only_a_member_receiver(self) -> None:
        result = resolve(parse("const value = String"), raise_on_error=False)

        self.assertEqual(result.diagnostics[0].message, "Unknown name 'String'")

    def test_raise_on_error_raises_resolution_error(self) -> None:
        program = parse("const value = unknown")

        with self.assertRaises(NameResolutionError) as raised:
            resolve(program)

        self.assertEqual(raised.exception.diagnostics[0].message, "Unknown name 'unknown'")

    def test_raise_on_error_includes_validation_diagnostics(self) -> None:
        program = parse("const value = 1\nconst value = 2")

        with self.assertRaises(NameResolutionError) as raised:
            resolve(program)

        self.assertIn("Duplicate variable 'value'", raised.exception.diagnostics[0].message)

    def test_does_not_resolve_member_names_without_type_information(self) -> None:
        program = parse("const value = user.name")

        result = resolve(program, raise_on_error=False)
        member = program.declarations[0].initializer

        self.assertIsInstance(member, MemberExpression)
        self.assertIsNone(result.resolutions.symbol_for(member))
        self.assertIsInstance(member.receiver, IdentifierExpression)
        self.assertEqual(
            result.diagnostics[0].message,
            "Unknown name 'user'",
        )


if __name__ == "__main__":
    unittest.main()
