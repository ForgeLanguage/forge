import unittest

from forge_lowering import lower
from forge_ownership import analyze_ownership
from forge_parser import parse
from forge_ir import IrArrayPatternCheck, IrCatch
from forge_typecheck import ArrayType


class OwnershipPlanTests(unittest.TestCase):
    def test_marks_owned_string_struct_field_assignment(self) -> None:
        result = lower(
            parse(
                """
@multidef
class Issue {}
class Parser {
    public static func parse(): String, !Issue {
        return Issue.new()
    }
}
struct Banner {
    public title: String
}
func load(): Banner, !Issue {
    let result: Banner = {}
    result.title = forward Parser.parse()
    return result
}
"""
            )
        )
        plan = analyze_ownership(result.ir)
        function = result.ir.declarations[-1]
        assignment = function.body.statements[1].expression

        self.assertTrue(plan.tracks_struct_string_field_assignment(assignment))

    def test_reports_string_array_element_cleanup(self) -> None:
        result = lower(parse("const tags: String[] = [\"a\"]"))
        plan = analyze_ownership(result.ir)
        variable = result.ir.declarations[0]

        self.assertEqual(plan.local_cleanup_kind(variable), "array")
        self.assertIsInstance(variable.type, ArrayType)
        self.assertEqual(plan.array_element_cleanup_kind(variable.type), "string")

    def test_marks_string_intrinsic_array_call_as_allocating(self) -> None:
        result = lower(parse('const parts = "a,b".split(",", 2)'))
        plan = analyze_ownership(result.ir)
        call = result.ir.declarations[0].initializer

        self.assertTrue(plan.allocating_array_call(call))

    def test_nullable_string_loop_result_is_owned_by_local(self) -> None:
        result = lower(
            parse(
                """
func value(): Void {
    const result: String? = while true {
        break "selected"
    }
}
"""
            )
        )
        plan = analyze_ownership(result.ir)
        function = result.ir.declarations[0]
        variable = function.body.statements[0]

        self.assertEqual(plan.local_cleanup_kind(variable), "string")


    def test_borrowed_destructuring_source_alias_does_not_need_cleanup(self) -> None:
        result = lower(
            parse(
                """
class Box {
    public values: Int[]
}
func main(box: Box): Void {
    const [first] = catch box.values {
        issue: PatternMismatch => { return }
    }
}
"""
            )
        )
        plan = analyze_ownership(result.ir)
        declaration = result.ir.declarations[1].body.statements[0]

        self.assertIsNotNone(declaration.source_temp)
        self.assertEqual(declaration.source_temp.safety.ownership, "borrow")
        self.assertEqual(plan.local_cleanup_kind(declaration.source_temp), "none")

    def test_owned_caught_destructuring_source_transfers_to_cleanup_temp(self) -> None:
        result = lower(
            parse(
                """
func read(text: String): Void {
    const [first] = catch text.split(",", 1) {
        issue: PatternMismatch => { return }
    }
}
"""
            )
        )
        plan = analyze_ownership(result.ir)
        declaration = result.ir.declarations[0].body.statements[0]

        self.assertEqual(declaration.source_temp.safety.ownership, "owner")
        self.assertEqual(plan.local_cleanup_kind(declaration.source_temp), "array")
        self.assertIsInstance(declaration.source_temp.initializer, IrCatch)
        checked = declaration.source_temp.initializer.expression
        self.assertIsInstance(checked, IrArrayPatternCheck)
        self.assertTrue(plan.owned_array_expression(checked))


if __name__ == "__main__":
    unittest.main()
