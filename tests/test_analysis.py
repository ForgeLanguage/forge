import unittest

from forge_analysis import ValidationError, validate
from forge_parser import (
    ArrayDestructuringDeclaration,
    FunctionDeclaration,
    VariableDeclaration,
    parse,
)


class AnalysisTests(unittest.TestCase):
    def test_builds_scope_annotations_without_mutating_ast(self) -> None:
        program = parse(
            """
class App {
    public args: String[]
    main(name: String): Void {
        const greeting = name
    }
}
"""
        )

        result = validate(program)

        self.assertTrue(result.ok)
        self.assertEqual(result.annotations.root_scope.kind, "module")
        class_declaration = program.declarations[0]
        class_scope = result.annotations.scope_for(class_declaration)
        self.assertIsNotNone(class_scope)
        self.assertIn("main", class_scope.symbols)
        function = class_declaration.members[1]
        self.assertIsInstance(function, FunctionDeclaration)
        function_scope = result.annotations.scope_for(function)
        self.assertIsNotNone(function_scope)
        self.assertIn("name", function_scope.symbols)

        body_scope = result.annotations.scope_for(function.body)
        self.assertIsNotNone(body_scope)
        local = function.body.statements[0]
        self.assertIsInstance(local, VariableDeclaration)
        self.assertEqual(result.annotations.symbol_for(local).scope, body_scope)

    def test_reports_duplicate_names_in_same_scope(self) -> None:
        program = parse(
            """
const answer = 41
const answer = 42
"""
        )

        result = validate(program, raise_on_error=False)

        self.assertFalse(result.ok)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertIn("Duplicate variable 'answer'", result.diagnostics[0].message)

    def test_allows_sync_and_async_function_twins(self) -> None:
        program = parse(
            """
read(path: String): String => "sync"
async read(path: String): String => "async"
"""
        )

        result = validate(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_rejects_duplicate_async_function_twin(self) -> None:
        program = parse(
            """
async read(path: String): String => "one"
async read(path: String): String => "two"
"""
        )

        result = validate(program, raise_on_error=False)

        self.assertFalse(result.ok)
        self.assertIn("Duplicate function 'read'", result.diagnostics[0].message)

    def test_rejects_sync_async_twins_with_different_parameters(self) -> None:
        program = parse(
            """
read(path: String): String => "sync"
async read(path: String, encoding: String): String => "async"
"""
        )

        result = validate(program, raise_on_error=False)

        self.assertFalse(result.ok)
        self.assertIn("Duplicate function 'read'", result.diagnostics[0].message)

    def test_reports_duplicate_parameters(self) -> None:
        program = parse("pick(value: Int, value: Int): Int => value")

        with self.assertRaises(ValidationError) as raised:
            validate(program)

        self.assertIn("Duplicate parameter 'value'", raised.exception.diagnostics[0].message)

    def test_reports_context_sensitive_expression_errors(self) -> None:
        program = parse(
            """
const current = this.name
const value = await fetch()
return value
"""
        )

        result = validate(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("'this' can only be used inside a class", messages)
        self.assertIn("'await' can only be used inside an async function", messages)
        self.assertIn("'return' can only be used inside a function", messages)

    def test_reports_modifier_conflicts(self) -> None:
        program = parse("public private main(): Void {}")

        result = validate(program, raise_on_error=False)

        self.assertFalse(result.ok)
        self.assertEqual(
            result.diagnostics[0].message,
            "Only one visibility modifier is allowed",
        )

    def test_reports_multiple_top_level_types_without_multidef(self) -> None:
        program = parse("class App {}\nclass Helper {}")

        result = validate(program, raise_on_error=False)

        self.assertFalse(result.ok)
        self.assertEqual(
            result.diagnostics[0].message,
            "Multiple top-level types require @multidef",
        )

    def test_multidef_allows_multiple_named_top_level_types(self) -> None:
        program = parse("@multidef\nclass App {}\nclass Helper {}")

        result = validate(program)

        self.assertTrue(result.ok)

    def test_multidef_requires_explicit_top_level_type_names(self) -> None:
        program = parse("@multidef\nclass {}", source_name="App.forge")

        result = validate(program, raise_on_error=False)

        self.assertFalse(result.ok)
        self.assertEqual(
            result.diagnostics[0].message,
            "Top-level types must have explicit names in @multidef files",
        )

    def test_reports_unknown_program_attribute(self) -> None:
        program = parse("@unknown\nclass App {}")

        result = validate(program, raise_on_error=False)

        self.assertFalse(result.ok)
        self.assertEqual(result.diagnostics[0].message, "Unknown program attribute '@unknown'")


    def test_array_destructuring_declares_bindings_and_reports_duplicates(self) -> None:
        program = parse(
            """
main(values: Int[]): Void {
    const [first, first] = values
}
"""
        )

        result = validate(program, raise_on_error=False)
        declaration = program.declarations[0].body.statements[0]

        self.assertIsInstance(declaration, ArrayDestructuringDeclaration)
        self.assertIn("Duplicate variable 'first'", result.diagnostics[0].message)

    def test_array_destructuring_is_local_only(self) -> None:
        result = validate(parse("const [first] = [1]"), raise_on_error=False)

        self.assertIn(
            "Array destructuring is only supported for local declarations",
            result.diagnostics[0].message,
        )


if __name__ == "__main__":
    unittest.main()
