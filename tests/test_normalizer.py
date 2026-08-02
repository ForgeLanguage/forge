import unittest

from forge_ir import IrClass, IrFunction
from forge_lowering import lower
from forge_normalizer import normalize, normalize_program
from forge_parser import (
    AssignmentExpression,
    ClassDeclaration,
    ExpressionStatement,
    FunctionDeclaration,
    MemberExpression,
    parse,
    VariableDeclaration,
)


class NormalizerTests(unittest.TestCase):
    def test_adds_default_constructor_to_class_without_user_constructor(self) -> None:
        program = parse("class App {}")

        normalized = normalize(program)

        original_class = program.declarations[0]
        self.assertIsInstance(original_class, ClassDeclaration)
        self.assertEqual(original_class.members, ())

        normalized_class = normalized.declarations[0]
        self.assertIsInstance(normalized_class, ClassDeclaration)
        constructor = normalized_class.members[0]
        self.assertIsInstance(constructor, FunctionDeclaration)
        self.assertEqual(constructor.name, "new")
        self.assertEqual(constructor.kind, "new")
        self.assertEqual(constructor.modifiers, ("public",))
        self.assertEqual(constructor.parameters, ())
        self.assertIsNone(constructor.return_type)
        self.assertEqual(constructor.body.statements, ())

    def test_keeps_user_constructor_instead_of_adding_default(self) -> None:
        program = parse("class App { public new(name: String) {} }")

        normalized = normalize(program)

        class_declaration = normalized.declarations[0]
        self.assertIsInstance(class_declaration, ClassDeclaration)
        constructors = [
            member
            for member in class_declaration.members
            if isinstance(member, FunctionDeclaration) and member.kind == "new"
        ]
        self.assertEqual(len(constructors), 1)
        self.assertEqual(constructors[0].parameters[0].name, "name")

    def test_promotes_constructor_parameters_to_fields_and_assignments(self) -> None:
        program = parse(
            """
class Point {
    public new(public x: Int, public y: Int) {
        print x
    }
}
"""
        )

        normalized = normalize(program)
        class_declaration = normalized.declarations[0]
        self.assertIsInstance(class_declaration, ClassDeclaration)
        x_field, y_field, constructor = class_declaration.members

        self.assertIsInstance(x_field, VariableDeclaration)
        self.assertEqual(x_field.name, "x")
        self.assertEqual(x_field.modifiers, ("public",))
        self.assertIsInstance(y_field, VariableDeclaration)
        self.assertEqual(y_field.name, "y")
        self.assertEqual(y_field.modifiers, ("public",))

        self.assertIsInstance(constructor, FunctionDeclaration)
        self.assertEqual(constructor.parameters[0].modifiers, ())
        self.assertEqual(constructor.parameters[1].modifiers, ())
        first_statement = constructor.body.statements[0]
        self.assertIsInstance(first_statement, ExpressionStatement)
        self.assertIsInstance(first_statement.expression, AssignmentExpression)
        self.assertIsInstance(first_statement.expression.target, MemberExpression)
        self.assertEqual(first_statement.expression.target.member, "x")

    def test_normalize_program_returns_result_wrapper(self) -> None:
        result = normalize_program(parse("class App {}"))

        self.assertIsInstance(result.program.declarations[0], ClassDeclaration)

    def test_lowering_runs_normalization_for_program_inputs(self) -> None:
        result = lower(parse("class App {}"))

        class_ir = result.ir.declarations[0]
        self.assertIsInstance(class_ir, IrClass)
        constructor = class_ir.members[0]
        self.assertIsInstance(constructor, IrFunction)
        self.assertEqual(constructor.name, "new")
        self.assertEqual(constructor.kind, "new")


if __name__ == "__main__":
    unittest.main()
