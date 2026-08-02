import unittest

from forge_ir import (
    IrArrayDestructuring,
    IrArrayPatternCheck,
    IrBinary,
    IrBlock,
    IrBuiltinRef,
    IrBulkMapCall,
    IrCall,
    IrCatch,
    IrFunction,
    IrLocalRef,
    IrMember,
    IrReturn,
    IrTaskBulkCall,
    IrVariable,
)
from forge_lowering import LoweringError, lower
from forge_parser import parse
from forge_safety import check_safety
from forge_typecheck import INT, STRING


class LoweringTests(unittest.TestCase):
    def test_lowers_short_function_body_to_block_return(self) -> None:
        program = parse("func answer(): Int => 42")

        result = lower(program)
        function = result.ir.declarations[0]

        self.assertIsInstance(function, IrFunction)
        self.assertIsInstance(function.body, IrBlock)
        self.assertIsInstance(function.body.statements[0], IrReturn)
        self.assertEqual(function.return_type, INT)

    def test_lowers_local_references_to_symbols_with_types(self) -> None:
        program = parse(
            """
const answer = 40
const copy = answer + 2
"""
        )

        result = lower(program)
        answer, copy = result.ir.declarations
        expression = copy.initializer

        self.assertIsInstance(answer, IrVariable)
        self.assertIsInstance(copy, IrVariable)
        self.assertIsInstance(expression, IrBinary)
        self.assertIsInstance(expression.left, IrLocalRef)
        self.assertEqual(expression.left.symbol, answer.symbol)
        self.assertEqual(expression.type, INT)

    def test_grouping_expression_disappears_in_ir(self) -> None:
        program = parse("const value = (1 + 2)")

        result = lower(program)
        variable = result.ir.declarations[0]

        self.assertIsInstance(variable.initializer, IrBinary)

    def test_lowers_member_access_with_member_symbol(self) -> None:
        program = parse(
            """
class User {
    public name: String
    func getName(): String => this.name
}
"""
        )

        result = lower(program)
        class_ir = result.ir.declarations[0]
        function = class_ir.members[1]
        returned = function.body.statements[0]
        member = returned.expression

        self.assertIsInstance(member, IrMember)
        self.assertEqual(member.type, STRING)
        self.assertEqual(member.symbol.name, "name")

    def test_lowers_call_with_typed_callee_and_arguments(self) -> None:
        program = parse(
            """
func add(left: Int, right: Int): Int => left + right
const result = add(1, 2)
"""
        )

        result = lower(program)
        variable = result.ir.declarations[1]
        call = variable.initializer

        self.assertIsInstance(call, IrCall)
        self.assertIsInstance(call.callee, IrLocalRef)
        self.assertEqual(call.type, INT)
        self.assertEqual(len(call.arguments), 2)

    def test_lowers_builtin_string_factory_receiver(self) -> None:
        result = lower(parse("const text = String.fromInt(42)"))
        call = result.ir.declarations[0].initializer

        self.assertIsInstance(call, IrCall)
        self.assertIsInstance(call.callee, IrMember)
        self.assertIsInstance(call.callee.receiver, IrBuiltinRef)
        self.assertEqual(call.callee.receiver.name, "String")
        self.assertEqual(call.type, STRING)

    def test_carries_safety_state_on_resource_bindings(self) -> None:
        program = parse(
            """
class File {}
func main(): Void {
    let file: File
    const borrowed: File = file
}
"""
        )

        safety = check_safety(program)
        result = lower(safety)
        function = result.ir.declarations[1]
        owner, borrowed = function.body.statements

        self.assertEqual(owner.safety.ownership, "owner")
        self.assertEqual(borrowed.safety.ownership, "borrow")
        self.assertEqual(borrowed.initializer.safety.ownership, "owner")

    def test_raises_when_previous_phases_have_errors(self) -> None:
        program = parse("const value: Int = \"nope\"")

        with self.assertRaises(LoweringError) as raised:
            lower(program)

        self.assertEqual(
            raised.exception.diagnostics[0].message,
            "Cannot assign String to Int",
        )

    def test_lowers_task_bulk_call(self) -> None:
        program = parse(
            """
async func download(url: String): String => url
const urls = ["a", "b"]
const pending = download task[urls]
"""
        )

        result = lower(program)
        pending = result.ir.declarations[2]

        self.assertIsInstance(pending.initializer, IrTaskBulkCall)

    def test_lowers_array_bulk_map_call(self) -> None:
        program = parse(
            """
func twice(value: Int): Int => value * 2
const values = [1, 2]
const doubled = twice[values]
"""
        )

        result = lower(program)
        doubled = result.ir.declarations[2]

        self.assertIsInstance(doubled.initializer, IrBulkMapCall)
        self.assertEqual(doubled.initializer.mode, "sync")


    def test_lowers_caught_local_array_destructuring_through_borrowed_source_temp(self) -> None:
        result = lower(
            parse(
                """
func main(values: Int[]): Void {
    const [first, second] = catch values {
        issue: PatternMismatch => { return }
    }
}
"""
            )
        )
        declaration = result.ir.declarations[0].body.statements[0]

        self.assertIsInstance(declaration, IrArrayDestructuring)
        self.assertIsNotNone(declaration.source_temp)
        self.assertEqual(declaration.source_temp.safety.ownership, "borrow")
        self.assertIsInstance(declaration.source_temp.initializer, IrCatch)
        self.assertIsInstance(
            declaration.source_temp.initializer.expression,
            IrArrayPatternCheck,
        )
        self.assertEqual(
            [binding.name for binding in declaration.bindings],
            ["first", "second"],
        )
        self.assertEqual(
            [binding.initializer.index.value for binding in declaration.bindings],
            [0, 1],
        )

    def test_lowers_array_destructuring_call_through_single_source_temp(self) -> None:
        result = lower(
            parse(
                """
func values(): Int[] => [1, 2]
func main(): Void {
    const [first, second] = catch values() {
        issue: PatternMismatch => { return }
    }
}
"""
            )
        )
        declaration = result.ir.declarations[1].body.statements[0]

        self.assertIsInstance(declaration, IrArrayDestructuring)
        self.assertIsNotNone(declaration.source_temp)
        self.assertIsInstance(declaration.source_temp.initializer, IrCatch)
        self.assertIsInstance(
            declaration.source_temp.initializer.expression,
            IrArrayPatternCheck,
        )
        self.assertIsInstance(
            declaration.source_temp.initializer.expression.source,
            IrCall,
        )
        self.assertTrue(
            all(
                binding.initializer.receiver.symbol == declaration.source_temp.symbol
                for binding in declaration.bindings
            )
        )


if __name__ == "__main__":
    unittest.main()
