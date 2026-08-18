import unittest

from forge_parser import BinaryExpression, CallExpression, MemberExpression, parse
from forge_normalizer import normalize
from forge_typecheck import (
    ArrayType,
    BOOL,
    INT,
    STRING,
    VOID,
    ClassType,
    EnumType,
    FunctionType,
    NullableType,
    OutcomeType,
    StructType,
    TaskCollectionType,
    TaskType,
    TypeCheckError,
    check_types,
)


class TypeCheckTests(unittest.TestCase):
    def test_infers_variable_and_identifier_types(self) -> None:
        program = parse(
            """
const answer = 42
const copy = answer
"""
        )

        result = check_types(program)
        answer, copy = program.declarations

        self.assertEqual(result.types.type_of(answer), INT)
        self.assertEqual(result.types.type_of(copy), INT)
        self.assertEqual(result.types.type_of(copy.initializer), INT)

    def test_checks_function_signature_return_and_call(self) -> None:
        program = parse(
            """
func add(left: Int, right: Int): Int => left + right
const result: Int = add(1, 2)
"""
        )

        result = check_types(program)
        function = program.declarations[0]
        call = program.declarations[1].initializer

        self.assertIsInstance(result.types.type_of(function), FunctionType)
        self.assertIsInstance(call, CallExpression)
        self.assertEqual(result.types.type_of(call), INT)

    def test_async_function_call_returns_task_of_declared_return_type(self) -> None:
        program = parse(
            """
async func fetch(): String => "ok"
const pending = fetch()
"""
        )

        result = check_types(program)
        pending = program.declarations[1]
        task_type = result.types.type_of(pending)

        self.assertIsInstance(task_type, TaskType)
        self.assertEqual(task_type.result_type, STRING)
        self.assertEqual(task_type.display_name, "Task<String>")

    def test_sync_async_twins_plain_call_prefers_sync_function(self) -> None:
        program = parse(
            """
func read(path: String): String => "sync"
async func read(path: String): String => "async"
const text: String = read("file.txt")
"""
        )

        result = check_types(program)
        call = program.declarations[2].initializer

        self.assertEqual(result.types.type_of(call), STRING)

    def test_sync_async_twins_await_prefers_async_function(self) -> None:
        program = parse(
            """
func read(path: String): String => "sync"
async func read(path: String): String => "async"
async func load(): String {
    return await read("file.txt")
}
"""
        )

        result = check_types(program)
        load = program.declarations[2]
        returned = load.body.statements[0]

        self.assertEqual(result.types.type_of(returned.expression), STRING)

    def test_sync_async_twins_task_context_prefers_async_function(self) -> None:
        program = parse(
            """
func read(path: String): String => "sync"
async func read(path: String): String => "async"
const pending: Task<String> = read("file.txt")
"""
        )

        result = check_types(program)
        pending = program.declarations[2]
        task_type = result.types.type_of(pending)

        self.assertIsInstance(task_type, TaskType)
        self.assertEqual(task_type.result_type, STRING)

    def test_async_only_call_in_sync_value_context_uses_generated_wrapper(self) -> None:
        program = parse(
            """
async func read(path: String): String => "async"
const text: String = read("file.txt")
"""
        )

        result = check_types(program)
        text = program.declarations[1]

        self.assertEqual(result.types.type_of(text.initializer), STRING)

    def test_async_only_call_in_sync_return_context_uses_generated_wrapper(self) -> None:
        program = parse(
            """
async func read(path: String): String => "async"
func load(): String {
    return read("file.txt")
}
"""
        )

        result = check_types(program)
        load = program.declarations[1]
        returned = load.body.statements[0]

        self.assertEqual(result.types.type_of(returned.expression), STRING)

    def test_accepts_explicit_task_type_annotation_for_async_call(self) -> None:
        program = parse(
            """
async func fetch(): String => "ok"
const pending: Task<String> = fetch()
"""
        )

        result = check_types(program)
        pending = program.declarations[1]
        task_type = result.types.type_of(pending.type)

        self.assertIsInstance(task_type, TaskType)
        self.assertEqual(task_type.result_type, STRING)
        self.assertEqual(result.types.type_of(pending), task_type)

    def test_reports_invalid_task_type_argument_count(self) -> None:
        result = check_types(
            parse("const pending: Task = null"),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Task requires exactly one type argument", messages)

    def test_accepts_explicit_task_collection_type_annotation(self) -> None:
        program = parse("const pending: TaskCollection<String>")

        result = check_types(program)
        pending = program.declarations[0]
        collection_type = result.types.type_of(pending.type)

        self.assertIsInstance(collection_type, TaskCollectionType)
        self.assertEqual(collection_type.result_type, STRING)
        self.assertEqual(result.types.type_of(pending), collection_type)

    def test_task_bulk_call_returns_task_collection(self) -> None:
        program = parse(
            """
async func download(url: String): String => url
const urls = ["a", "b"]
const pending = download task[urls]
"""
        )

        result = check_types(program)
        pending = program.declarations[2]
        collection_type = result.types.type_of(pending)

        self.assertIsInstance(collection_type, TaskCollectionType)
        self.assertEqual(collection_type.result_type, STRING)
        self.assertEqual(collection_type.display_name, "TaskCollection<String>")

    def test_task_collection_all_returns_task_of_array(self) -> None:
        program = parse(
            """
async func download(url: String): String => url
async func load(): String[] {
    const urls = ["a", "b"]
    return await (download task[urls]).all()
}
"""
        )

        result = check_types(program)
        load = program.declarations[1]
        returned = load.body.statements[1]
        result_type = result.types.type_of(returned.expression)

        self.assertIsInstance(result_type, ArrayType)
        self.assertEqual(result_type.element_type, STRING)

    def test_task_collection_concurrency_preserves_collection_for_any(self) -> None:
        program = parse(
            """
async func download(url: String): String => url
async func load(): String {
    const urls = ["a", "b"]
    return await (download task[urls]).concurrency(2).any()
}
"""
        )

        result = check_types(program)
        load = program.declarations[1]
        returned = load.body.statements[1]

        self.assertEqual(result.types.type_of(returned.expression), STRING)

    def test_catch_handles_required_task_collection_outcome_at_await(self) -> None:
        program = parse(
            """
@multidef
class NetworkIssue {}
async func download(url: String): String, !NetworkIssue => url
async func load(): String[] {
    const urls = ["a", "b"]
    return catch await (download task[urls]).all() {
        issue: NetworkIssue => ["fallback"]
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_forward_can_propagate_required_task_collection_outcome_at_await(self) -> None:
        program = parse(
            """
@multidef
class NetworkIssue {}
async func download(url: String): String, !NetworkIssue => url
async func load(): String[], !NetworkIssue {
    const urls = ["a", "b"]
    return forward await (download task[urls]).all()
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_await_reports_unhandled_required_task_collection_outcome(self) -> None:
        program = parse(
            """
@multidef
class NetworkIssue {}
async func download(url: String): String, !NetworkIssue => url
async func load(): String[] {
    const urls = ["a", "b"]
    return await (download task[urls]).all()
}
"""
        )

        result = check_types(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Unhandled required outcome NetworkIssue", messages)

    def test_task_collection_method_call_diagnostics(self) -> None:
        result = check_types(
            parse(
                """
async func download(url: String): String => url
async func load(): String {
    const urls = ["a", "b"]
    const pending = download task[urls]
    pending.all(1)
    pending.concurrency("fast")
    return await pending.missing()
}
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Expected 0 arguments for all, got 1", messages)
        self.assertIn("Cannot assign String to Int", messages)
        self.assertIn("Type TaskCollection<String> has no member 'missing'", messages)

    def test_explicit_task_collection_annotation_preserves_deferred_outcomes(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class NetworkIssue {}
async func download(url: String): String, !NetworkIssue => url
async func load(): String[] {
    const urls = ["a", "b"]
    const pending: TaskCollection<String> = download task[urls]
    return await pending.all()
}
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Unhandled required outcome NetworkIssue", messages)

    def test_explicit_task_annotation_preserves_deferred_outcomes(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class NetworkIssue {}
async func fetch(): String, !NetworkIssue => "ok"
async func load(): String {
    const pending: Task<String> = fetch()
    return await pending
}
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Unhandled required outcome NetworkIssue", messages)

    def test_rejects_task_bulk_call_of_sync_function(self) -> None:
        result = check_types(
            parse(
                """
func download(url: String): String => url
const urls = ["a", "b"]
const pending = download task[urls]
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Task bulk calls require an async function", messages)

    def test_await_unwraps_task_inside_async_function(self) -> None:
        program = parse(
            """
async func fetch(): String => "ok"
async func load(): String {
    const value = await fetch()
    return value
}
"""
        )

        result = check_types(program)
        load = program.declarations[1]
        value = load.body.statements[0]
        returned = load.body.statements[1]

        self.assertEqual(result.types.type_of(value), STRING)
        self.assertEqual(result.types.type_of(value.initializer), STRING)
        self.assertEqual(result.types.type_of(returned.expression), STRING)

    def test_task_await_method_unwraps_task_in_sync_function(self) -> None:
        program = parse(
            """
async func fetch(): String => "ok"
func load(): String {
    return fetch().await()
}
"""
        )

        result = check_types(program)
        load = program.declarations[1]
        returned = load.body.statements[0]

        self.assertEqual(result.types.type_of(returned.expression), STRING)

    def test_rejects_task_await_method_inside_async_function(self) -> None:
        result = check_types(
            parse(
                """
async func fetch(): String => "ok"
async func load(): String {
    return fetch().await()
}
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn(
            "Task.await() cannot be used inside an async function; use the await operator",
            messages,
        )

    def test_reports_await_of_non_task_expression(self) -> None:
        program = parse(
            """
async func load(): String {
    const value = await "ready"
    return value
}
"""
        )

        result = check_types(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("'await' requires Task<T>, got String", messages)

    def test_async_call_defers_required_outcome_until_await(self) -> None:
        program = parse(
            """
@multidef
class NetworkIssue {}
async func fetch(): String, !NetworkIssue => "ok"
func main(): Void {
    const pending = fetch()
}
"""
        )

        result = check_types(program, raise_on_error=False)
        pending = program.declarations[2].body.statements[0]
        task_type = result.types.type_of(pending)

        self.assertTrue(result.ok)
        self.assertIsInstance(task_type, TaskType)
        self.assertEqual(len(result.types.task_outcomes_of(pending)), 1)
        self.assertEqual(result.types.task_outcomes_of(pending)[0].type.name, "NetworkIssue")

    def test_await_reports_unhandled_required_async_outcome(self) -> None:
        program = parse(
            """
@multidef
class NetworkIssue {}
async func fetch(): String, !NetworkIssue => "ok"
async func load(): String {
    return await fetch()
}
"""
        )

        result = check_types(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Unhandled required outcome NetworkIssue", messages)

    def test_catch_handles_required_async_outcome_at_await(self) -> None:
        program = parse(
            """
@multidef
class NetworkIssue {}
async func fetch(): String, !NetworkIssue => "ok"
async func load(): String {
    return catch await fetch() {
        issue: NetworkIssue => "guest"
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_forward_can_propagate_required_async_outcome_at_await(self) -> None:
        program = parse(
            """
@multidef
class NetworkIssue {}
async func fetch(): String, !NetworkIssue => "ok"
async func load(): String, !NetworkIssue {
    return forward await fetch()
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_records_nullable_type_and_accepts_null_initializer(self) -> None:
        program = parse("const maybe: String? = null")

        result = check_types(program)
        declaration = program.declarations[0]

        self.assertIsInstance(result.types.type_of(declaration), NullableType)
        self.assertEqual(result.types.type_of(declaration).inner_type, STRING)

    def test_records_dynamic_and_fixed_array_types(self) -> None:
        program = parse(
            """
let dynamic: Int[]
let fixed: Int[2 + 3]
"""
        )

        result = check_types(program)
        dynamic, fixed = program.declarations

        dynamic_type = result.types.type_of(dynamic)
        fixed_type = result.types.type_of(fixed)
        self.assertIsInstance(dynamic_type, ArrayType)
        self.assertIsNone(dynamic_type.size)
        self.assertIsInstance(fixed_type, ArrayType)
        self.assertEqual(fixed_type.size, 5)
        self.assertEqual(fixed_type.display_name, "Int[5]")

    def test_infers_array_literal_type(self) -> None:
        program = parse("const values = [1, 2]")

        result = check_types(program)
        values_type = result.types.type_of(program.declarations[0])

        self.assertIsInstance(values_type, ArrayType)
        self.assertEqual(values_type.element_type, INT)
        self.assertIsNone(values_type.size)

    def test_dynamic_array_index_can_use_variable_index(self) -> None:
        program = parse(
            """
const values = [1, 2]
const index = 1
const value = values[index]
"""
        )

        result = check_types(program)

        self.assertEqual(result.types.type_of(program.declarations[2]), INT)

    def test_logical_operators_accept_boolean_comparisons(self) -> None:
        program = parse("const ok = 200 >= 200 && 200 < 300")

        result = check_types(program)

        self.assertEqual(result.types.type_of(program.declarations[0]), BOOL)

    def test_empty_array_literal_requires_declared_type(self) -> None:
        result = check_types(parse("const values = []"), raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot infer element type of empty array literal",
        )

    def test_empty_array_literal_uses_declared_dynamic_array_type(self) -> None:
        program = parse("const values: Int[] = []")

        result = check_types(program)

        self.assertEqual(result.types.type_of(program.declarations[0]).element_type, INT)

    def test_struct_literal_uses_block_return_type(self) -> None:
        program = parse(
            """
struct FeedMultiResponse {
    const count: Int
    const okCount: Int
}

func empty(): FeedMultiResponse {
    return {
        count: 0,
        okCount: 0
    }
}
"""
        )

        result = check_types(program)
        function = program.declarations[1]
        returned = function.body.statements[0]

        self.assertEqual(result.types.type_of(returned.expression).display_name, "FeedMultiResponse")

    def test_struct_literal_uses_expression_body_return_type(self) -> None:
        program = parse(
            """
struct FeedMultiResponse {
    const count: Int
    const okCount: Int
}

func empty(): FeedMultiResponse => {
    count: 0,
    okCount: 0
}
"""
        )

        result = check_types(program)
        function = program.declarations[1]

        self.assertEqual(result.types.type_of(function.body).display_name, "FeedMultiResponse")

    def test_struct_literal_uses_call_parameter_type(self) -> None:
        program = parse(
            """
@multidef

struct DriverFetchResult {
    const network: String
    const statusCode: Int
}

struct FeedResponse {
    const status: Int
}

func fromDriverResult(result: DriverFetchResult): FeedResponse => {
    status: result.statusCode
}

func get(): FeedResponse {
    return fromDriverResult({
        network: "http",
        statusCode: 200
    })
}
"""
        )

        result = check_types(program)
        function = program.declarations[3]
        returned = function.body.statements[0]
        call = returned.expression
        argument = call.arguments[0]

        self.assertEqual(result.types.type_of(argument).display_name, "DriverFetchResult")

    def test_member_block_returns_receiver_type(self) -> None:
        program = parse(
            """
struct DriverFetchResult {
    const network: String
    public statusCode: Int
}

func accept(result: DriverFetchResult): DriverFetchResult => result

func get(): DriverFetchResult {
    let result: DriverFetchResult = {
        network: "http",
        statusCode: 0
    }
    return accept(result.{
        statusCode = 200
    })
}
"""
        )

        result = check_types(program)
        function = program.declarations[2]
        returned = function.body.statements[1]
        argument = returned.expression.arguments[0]

        self.assertEqual(result.types.type_of(argument).display_name, "DriverFetchResult")

    def test_rejects_mixed_array_literal_elements(self) -> None:
        result = check_types(parse('const values = [1, "two"]'), raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Array literal element has type String, expected Int",
        )

    def test_checks_fixed_array_literal_length(self) -> None:
        result = check_types(parse("const values: Int[3] = [1, 2]"), raise_on_error=False)

        self.assertEqual(result.diagnostics[0].message, "Expected 3 array elements, got 2")

    def test_dynamic_array_len_member_is_int(self) -> None:
        program = parse("const values: Int[] = [1, 2]\nconst count: Int = values.len")

        result = check_types(program)

        count = program.declarations[1]
        self.assertEqual(result.types.type_of(count.initializer), INT)

    def test_rejects_unknown_dynamic_array_member(self) -> None:
        result = check_types(
            parse("const values: Int[] = [1, 2]\nconst count: Int = values.length"),
            raise_on_error=False,
        )

        self.assertEqual(result.diagnostics[0].message, "Type Int[] has no member 'length'")

    def test_rejects_fixed_array_len_member(self) -> None:
        result = check_types(
            parse("const values: Int[2] = [1, 2]\nconst count: Int = values.len"),
            raise_on_error=False,
        )

        self.assertEqual(result.diagnostics[0].message, "Type Int[2] has no member 'len'")

    def test_reports_non_constant_fixed_array_size(self) -> None:
        program = parse("let values: Int[count]")

        result = check_types(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Array size must be a compile-time integer constant",
        )

    def test_reports_negative_fixed_array_size(self) -> None:
        program = parse("let values: Int[-1]")

        result = check_types(program, raise_on_error=False)

        self.assertEqual(result.diagnostics[0].message, "Array size cannot be negative")

    def test_checks_basic_operators(self) -> None:
        program = parse(
            """
const sum = 1 + 2
const label = "a" + "b"
const valid = sum > 0
"""
        )

        result = check_types(program)

        self.assertEqual(result.types.type_of(program.declarations[0]), INT)
        self.assertEqual(result.types.type_of(program.declarations[1]), STRING)
        self.assertEqual(result.types.type_of(program.declarations[2]), BOOL)

    def test_primitive_to_string_returns_string(self) -> None:
        program = parse(
            """
func stringify(value: Int, enabled: Bool, label: String): String {
    return value.toString() + enabled.toString() + label.toString()
}
"""
        )

        result = check_types(program)
        returned = program.declarations[0].body.statements[0].expression

        self.assertEqual(result.types.type_of(returned), STRING)

    def test_resolves_class_member_types(self) -> None:
        program = parse(
            """
class User {
    public name: String
    func rename(name: String): Void {
        this.name = name
    }
}
"""
        )

        result = check_types(program)
        function = program.declarations[0].members[1]
        assignment = function.body.statements[0].expression
        member = assignment.target

        self.assertIsInstance(member, MemberExpression)
        self.assertEqual(result.types.type_of(member), STRING)
        self.assertIsInstance(result.types.type_of(function), FunctionType)
        self.assertEqual(result.types.type_of(function).return_type, VOID)

    def test_self_type_resolves_to_enclosing_class_type(self) -> None:
        program = parse(
            """
class Node {
    func same(other: self): self {
        return other
    }
}
"""
        )

        result = check_types(program)
        class_declaration = program.declarations[0]
        function = class_declaration.members[0]
        function_type = result.types.type_of(function)

        self.assertIsInstance(function_type, FunctionType)
        self.assertIsInstance(function_type.return_type, ClassType)
        self.assertEqual(function_type.return_type.name, "Node")
        self.assertEqual(function_type.parameter_types[0], function_type.return_type)

    def test_checks_builtin_stringable_interface(self) -> None:
        program = parse(
            """
class User {
    implements Stringable

    public func toString(): String {
        return "User"
    }
}
"""
        )

        result = check_types(program)

        self.assertTrue(result.ok)

    def test_reports_missing_stringable_method(self) -> None:
        result = check_types(
            parse("class User { implements Stringable }"),
            raise_on_error=False,
        )

        self.assertEqual(
            result.diagnostics[0].message,
            "Type User implements Stringable but is missing method 'toString'",
        )

    def test_checks_user_defined_interface_contract(self) -> None:
        program = parse(
            """
@multidef
interface Printable {
    public func print(): Void
}

class User {
    implements Printable

    public func print(): Void {}
}
"""
        )

        result = check_types(program)

        self.assertTrue(result.ok)

    def test_trait_can_satisfy_class_interface_contract(self) -> None:
        program = parse(
            """
@multidef
interface Runnable {
    public func run(): Void
}

trait AppLogic {
    implements Runnable

    public func run(): Void {}
}

class App {
    uses AppLogic
    implements Runnable
}
"""
        )

        result = check_types(program)

        self.assertTrue(result.ok)

    def test_class_value_can_be_assigned_to_implemented_interface(self) -> None:
        program = parse(
            """
@multidef
interface Runnable {
    public async func run(): Int
}

class App {
    implements Runnable

    public new() {}

    public async func run(): Int => 1
}

const runnable: Runnable = App.new()
"""
        )

        result = check_types(program)

        self.assertTrue(result.ok)

    def test_array_literal_uses_contextual_interface_element_type(self) -> None:
        program = parse(
            """
@multidef
interface Runnable {
    public func run(): Int
}

class One {
    implements Runnable
    public new() {}
    public func run(): Int => 1
}

class Two {
    implements Runnable
    public new() {}
    public func run(): Int => 2
}

const values: Runnable[] = [One.new(), Two.new()]
"""
        )

        result = check_types(program)

        self.assertTrue(result.ok)

    def test_array_literal_uses_contextual_struct_element_type(self) -> None:
        program = parse(
            """
struct Pair {
    public name: String
    public value: Int
}

const values: Pair[] = [{ name: "one", value: 1 }]
"""
        )

        result = check_types(program)

        self.assertTrue(result.ok)

    def test_allows_type_arguments_for_user_generic_structs(self) -> None:
        program = parse(
            """
@multidef
struct Definition<T> {
    public asSingle: Bool
}

class Logger {
    public new() {}
}

struct Defs {
    public logger: Definition<Logger>
}
"""
        )

        result = check_types(program)

        self.assertTrue(result.ok)

    def test_specializes_nullable_generic_struct_field(self) -> None:
        program = parse(
            """
@multidef
struct Definition<T> {
    public instance: T?
}

class Logger {
    public new() {}
}

struct Defs {
    public logger: Definition<Logger>
}

const defs: Defs = {
    logger: {
        instance: Logger.new()
    }
}
"""
        )

        result = check_types(program)

        self.assertTrue(result.ok)

    def test_uses_requires_trait(self) -> None:
        result = check_types(
            parse(
                """
@multidef
interface Runnable {
    public func run(): Void
}

class App {
    uses Runnable
}
"""
            ),
            raise_on_error=False,
        )

        self.assertEqual(result.diagnostics[0].message, "uses expects a trait, got Runnable")

    def test_reports_type_mismatch(self) -> None:
        program = parse("const value: Int = \"nope\"")

        result = check_types(program, raise_on_error=False)

        self.assertFalse(result.ok)
        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot assign String to Int",
        )

    def test_reports_return_type_mismatch(self) -> None:
        program = parse("func answer(): Int { return \"nope\" }")

        with self.assertRaises(TypeCheckError) as raised:
            check_types(program)

        self.assertEqual(
            raised.exception.diagnostics[0].message,
            "Cannot assign String to Int",
        )

    def test_reports_call_argument_errors(self) -> None:
        program = parse(
            """
func takesInt(value: Int): Void {}
takesInt("nope")
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertEqual(result.diagnostics[0].message, "Cannot assign String to Int")

    def test_reports_called_function_name_on_arity_mismatch(self) -> None:
        program = parse("func takesInt(value: Int): Void {}\ntakesInt()")

        result = check_types(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Expected 1 arguments for takesInt, got 0",
        )

    def test_reports_member_name_on_constructor_arity_mismatch(self) -> None:
        program = normalize(parse("class User {}\nconst user: User = User.new(\"name\")"))

        result = check_types(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Expected 0 arguments for User.new, got 1",
        )

    def test_rejects_instance_member_access_through_class(self) -> None:
        result = check_types(
            parse("class User { func name(): String => \"\" }\nconst name = User.name()"),
            raise_on_error=False,
        )

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot access instance member 'name' through class",
        )

    def test_rejects_static_member_access_through_instance(self) -> None:
        result = check_types(
            parse(
                """
class User {
    static func name(): String => ""
}
func main(user: User): String {
    return user.name()
}
"""
            ),
            raise_on_error=False,
        )

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot access static member 'name' through instance",
        )

    def test_requires_move_for_take_parameter(self) -> None:
        program = parse(
            """
class Profile {}
func consume(take profile: Profile): Void {}
func main(): Void {
    let profile: Profile
    consume(profile)
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Parameter 1 of consume takes ownership; pass it with 'move'",
        )

    def test_rejects_move_for_borrow_parameter(self) -> None:
        program = parse(
            """
class Profile {}
func inspect(profile: Profile): Void {}
func main(): Void {
    let profile: Profile
    inspect(move profile)
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Parameter 1 of inspect does not take ownership; remove 'move'",
        )

    def test_reports_immutable_assignment(self) -> None:
        program = parse(
            """
const value = 1
value = 2
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertEqual(result.diagnostics[0].message, "Cannot assign to immutable 'value'")

    def test_reports_invalid_binary_operator(self) -> None:
        program = parse('const value = "x" - "y"')

        result = check_types(program, raise_on_error=False)

        initializer = program.declarations[0].initializer
        self.assertIsInstance(initializer, BinaryExpression)
        self.assertIn("Operator 'minus' cannot be applied", result.diagnostics[0].message)

    def test_class_type_reference_becomes_class_type(self) -> None:
        program = parse(
            """
class User {}
const user: User? = null
"""
        )

        result = check_types(program)
        user_type = result.types.type_of(program.declarations[1])

        self.assertIsInstance(user_type, NullableType)
        self.assertIsInstance(user_type.inner_type, ClassType)
        self.assertEqual(user_type.inner_type.name, "User")

    def test_assigns_non_nullable_class_to_nullable_class_field(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public profile: Profile?
    public func setProfile(take profile: Profile): Void {
        this.profile = profile
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_accepts_nullable_condition(self) -> None:
        program = parse(
            """
class User {
    public profile: String?
    public func name(): String {
        return this.profile ? "set" : ""
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_allows_member_access_through_nullable_class_receiver(self) -> None:
        program = parse(
            """
@multidef
class Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public func name(): String {
        return this.profile ? this.profile.firstName : ""
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_allows_passing_narrowed_nullable_struct_as_non_nullable(self) -> None:
        program = parse(
            """
@multidef
struct Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public func render(profile: Profile): String {
        return profile.firstName
    }
    public func name(): String {
        return this.profile ? this.render(this.profile) : ""
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_allows_member_access_after_not_null_comparison(self) -> None:
        program = parse(
            """
@multidef
class Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public func name(): String {
        return this.profile != null ? this.profile.firstName : ""
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertTrue(result.ok)

    def test_null_safe_member_access_returns_nullable_type(self) -> None:
        program = parse(
            """
@multidef
class Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public func name(): String? {
        return this.profile?.firstName
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)
        return_statement = program.declarations[1].members[1].body.statements[0]

        self.assertTrue(result.ok)
        self.assertIsInstance(result.types.type_of(return_statement.expression), NullableType)

    def test_rejects_member_access_through_unguarded_nullable_receiver(self) -> None:
        program = parse(
            """
@multidef
class Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public func name(): String {
        return this.profile.firstName
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot access member 'firstName' on nullable Profile? without a non-null check",
        )

    def test_nullable_narrowing_does_not_escape_if_statement(self) -> None:
        program = parse(
            """
@multidef
class Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public func name(flag: Bool): String {
        if this.profile {
            print this.profile.firstName
        }
        return this.profile.firstName
    }
}
"""
        )

        result = check_types(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn(
            "Cannot access member 'firstName' on nullable Profile? without a non-null check",
            messages,
        )

    def test_constructor_call_returns_enclosing_class_type(self) -> None:
        program = normalize(
            parse(
                """
class User {}
const user: User = User.new()
"""
            )
        )

        result = check_types(program)
        initializer = program.declarations[1].initializer

        self.assertIsInstance(initializer, CallExpression)
        self.assertIsInstance(result.types.type_of(initializer), ClassType)
        self.assertEqual(result.types.type_of(initializer).name, "User")

    def test_records_required_and_optional_outcomes_on_function_type(self) -> None:
        program = parse(
            """
@multidef
class ParseIssue {}
class AllocFailed {}
func parse(): Int, !ParseIssue, ?AllocFailed {
    return 1
}
"""
        )

        result = check_types(program)
        function_type = result.types.type_of(program.declarations[2])

        self.assertIsInstance(function_type, FunctionType)
        self.assertEqual(len(function_type.outcomes), 2)
        self.assertIsInstance(function_type.outcomes[0], OutcomeType)
        self.assertTrue(function_type.outcomes[0].required)
        self.assertEqual(function_type.outcomes[0].type.name, "ParseIssue")
        self.assertFalse(function_type.outcomes[1].required)
        self.assertEqual(function_type.outcomes[1].type.name, "AllocFailed")

    def test_reports_unhandled_required_outcome(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class ParseIssue {}
class Parser {
    static func parse(): Int, !ParseIssue {
        return 1
    }
}
func main(): Void {
    const value = Parser.parse()
}
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Unhandled required outcome ParseIssue", messages)

    def test_allows_ignored_optional_outcome(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class AllocFailed {}
class Array {
    static func reserve(size: Int): Void, ?AllocFailed {}
}
func main(): Void {
    Array.reserve(1000)
}
"""
            ),
            raise_on_error=False,
        )

        self.assertTrue(result.ok)

    def test_catch_handles_required_outcome(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class ParseIssue {}
class Parser {
    static func parse(): Int, !ParseIssue {
        return 1
    }
}
func main(): Void {
    const value = catch Parser.parse() {
        issue: ParseIssue => 0
    }
}
"""
            ),
            raise_on_error=False,
        )

        self.assertTrue(result.ok)

    def test_allows_returning_declared_outcome(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class ParseIssue {
    public new() {}
}
class Parser {
    static func parse(): Int, !ParseIssue {
        return ParseIssue.new()
    }
}
"""
            ),
            raise_on_error=False,
        )

        self.assertTrue(result.ok)

    def test_catch_handler_must_match_success_type(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class ParseIssue {}
class Parser {
    static func parse(): Int, !ParseIssue {
        return 1
    }
}
func main(): Void {
    const value = catch Parser.parse() {
        issue: ParseIssue => "nope"
    }
}
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Cannot assign String to Int", messages)

    def test_forwards_optional_outcome_as_optional(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class AllocFailed {}
class Array {
    static func reserve(size: Int): Void, ?AllocFailed {}
}
func prepare(): Void, ?AllocFailed {
    forward Array.reserve(1000)
}
"""
            ),
            raise_on_error=False,
        )

        self.assertTrue(result.ok)

    def test_forward_promotes_optional_outcome_to_required(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class AllocFailed {}
class Array {
    static func reserve(size: Int): Void, ?AllocFailed {}
}
func load(): Void, !AllocFailed {
    forward Array.reserve(1000)
}
"""
            ),
            raise_on_error=False,
        )

        self.assertTrue(result.ok)

    def test_rejects_forward_of_undeclared_outcome(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class AllocFailed {}
class Array {
    static func reserve(size: Int): Void, ?AllocFailed {}
}
func load(): Void {
    forward Array.reserve(1000)
}
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Cannot forward undeclared outcome AllocFailed", messages)

    def test_rejects_downgrading_required_outcome_to_optional(self) -> None:
        result = check_types(
            parse(
                """
@multidef
class ParseIssue {}
class Parser {
    static func parse(): Int, !ParseIssue {
        return 1
    }
}
func parseMaybe(): Int, ?ParseIssue {
    return forward Parser.parse()
}
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Cannot forward required outcome ParseIssue as optional", messages)

    def test_checks_struct_literal_against_declared_type(self) -> None:
        program = parse(
            """
@multidef

public struct HttpResponse {
    public status: Int
    public body: String
}

let response: HttpResponse = {
    status: 200,
    body: "OK"
}
"""
        )

        result = check_types(program)
        declaration = program.declarations[1]

        self.assertIsInstance(result.types.type_of(declaration), StructType)
        self.assertIsInstance(result.types.type_of(declaration.initializer), StructType)

    def test_rejects_struct_literal_field_type_mismatch(self) -> None:
        result = check_types(
            parse(
                """
@multidef

public struct HttpResponse {
    public status: Int
    public body: String
}

let response: HttpResponse = {
    status: "bad",
    body: "OK"
}
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Cannot assign String to Int", messages)

    def test_checks_inline_struct_enum_methods(self) -> None:
        program = parse(
            """
public enum HttpStatus : struct {
    public code: Int
    public reason: String
    public isError: Bool
} {
    Ok => { 200, "OK", false }
    NotFound => { 404, "Not Found", true }

    public func isClientError(): Bool => this.code >= 400 && this.code < 500
}
""",
            source_name="HttpStatus.forge",
        )

        result = check_types(program)
        enum_type = result.types.type_of(program.declarations[0])

        self.assertIsInstance(enum_type, EnumType)
        self.assertTrue(result.ok)

    def test_types_loop_expressions_and_contextual_nullable_fallback(self) -> None:
        program = parse(
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
        )

        result = check_types(program)

        self.assertTrue(result.ok)
        self.assertEqual(result.types.type_of(program.declarations[0]).display_name, "Int?")
        self.assertEqual(result.types.type_of(program.declarations[1]).display_name, "Int")
        self.assertEqual(result.types.type_of(program.declarations[2]).display_name, "Int")

    def test_rejects_loop_expression_without_fallback_or_nullable_context(self) -> None:
        result = check_types(
            parse(
                """
const value = while false {
    break 1
}
"""
            ),
            raise_on_error=False,
        )

        self.assertIn(
            "Loop expression requires an else fallback or a contextual nullable type",
            [diagnostic.message for diagnostic in result.diagnostics],
        )

    def test_rejects_valued_break_in_statement_loop(self) -> None:
        result = check_types(
            parse(
                """
while true {
    break 1
}
"""
            ),
            raise_on_error=False,
        )

        self.assertIn(
            "A valued break requires an expression loop",
            [diagnostic.message for diagnostic in result.diagnostics],
        )

    def test_contextual_nullable_loop_fallback_flows_through_typed_positions(self) -> None:
        result = check_types(
            parse(
                """
struct Box {
    public value: Int?
}

func consume(value: Int?): Void {}

func main(): Void {
    let assigned: Int? = null
    assigned = while false { break 1 }
    consume(while false { break 2 })
    const box: Box = { value: while false { break 3 } }
}
"""
            )
        )

        self.assertTrue(result.ok)

    def test_types_builtin_string_instance_methods_and_static_factories(self) -> None:
        program = parse(
            """
const text = " Forge "
const length: Int = text.length()
const empty: Bool = text.isEmpty()
const bytes: Byte[] = text.toBytes()
const equals: Bool = text.equals(" Forge ")
const index: Int = text.indexOf("or")
const contains: Bool = text.contains("or")
const starts: Bool = text.startsWith(" ")
const ends: Bool = text.endsWith(" ")
const part: String = text.substring(-5, -1)
const trimmed: String = text.trim()
const lower: String = text.toLowerCase()
const upper: String = text.toUpperCase()
const replaced: String = text.replace("o", "0")
const parts: String[] = text.split(" ", 3)
const number: Int = "42".parseInt()
const decoded: String = String.fromBytes(bytes)
const encoded: String = String.fromInt(42)
"""
        )

        result = check_types(program)

        self.assertTrue(result.ok)

    def test_rejects_wrong_string_intrinsic_receiver_arity_and_types(self) -> None:
        result = check_types(
            parse(
                """
const classReceiver = String.length()
const instanceReceiver = "x".fromInt(1)
const staticToString = Int.toString()
const arity = "x".substring(0)
const argument = "x".contains(1)
const splitArity = "x".split(",")
const splitLimit = "x".split(",", "2")
"""
            ),
            raise_on_error=False,
        )

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Cannot access instance member 'length' through class", messages)
        self.assertIn("Cannot access static member 'fromInt' through instance", messages)
        self.assertIn("Cannot access instance member 'toString' through class", messages)
        self.assertIn("Expected 2 arguments for substring, got 1", messages)
        self.assertIn("Expected 2 arguments for split, got 1", messages)
        self.assertIn("Cannot assign Int to String", messages)
        self.assertIn("Cannot assign String to Int", messages)


    def test_array_destructuring_infers_element_type_for_each_binding(self) -> None:
        program = parse(
            """
func main(values: Int[]): Void {
    const [first, second] = catch values {
        issue: PatternMismatch => { return }
    }
}
"""
        )

        result = check_types(program)
        declaration = program.declarations[0].body.statements[0]

        self.assertEqual(result.types.type_of(declaration.bindings[0]), INT)
        self.assertEqual(result.types.type_of(declaration.bindings[1]), INT)

    def test_array_destructuring_requires_catch_for_unknown_length(self) -> None:
        result = check_types(
            parse(
                """
func main(values: Int[]): Void {
    const [first] = values
}
"""
            ),
            raise_on_error=False,
        )

        self.assertIn(
            "Array destructuring of unknown length requires "
            "'catch ... { issue: PatternMismatch => ... }'",
            [diagnostic.message for diagnostic in result.diagnostics],
        )

    def test_array_destructuring_allows_known_sufficient_length_without_catch(self) -> None:
        result = check_types(
            parse(
                """
func main(values: Int[2]): Void {
    const [first, second] = values
    const [one, two] = [1, 2]
}
"""
            )
        )

        self.assertTrue(result.ok)

    def test_array_destructuring_rejects_known_short_source(self) -> None:
        result = check_types(
            parse(
                """
func main(values: Int[1]): Void {
    const [first, second] = values
}
"""
            ),
            raise_on_error=False,
        )

        self.assertIn(
            "Array destructuring requires 2 elements, but source has 1",
            [diagnostic.message for diagnostic in result.diagnostics],
        )

        caught = check_types(
            parse(
                """
func main(values: Int[1]): Void {
    const [first, second] = catch values {
        issue: PatternMismatch => { return }
    }
}
"""
            ),
            raise_on_error=False,
        )
        self.assertIn(
            "Array destructuring requires 2 elements, but source has 1",
            [diagnostic.message for diagnostic in caught.diagnostics],
        )

    def test_array_destructuring_allows_redundant_catch_for_known_length(self) -> None:
        result = check_types(
            parse(
                """
func main(values: Int[2]): Void {
    const [first, second] = catch values {
        issue: PatternMismatch => { return }
    }
}
"""
            )
        )

        self.assertTrue(result.ok)

    def test_pattern_mismatch_catch_is_contextual_to_destructuring(self) -> None:
        result = check_types(
            parse(
                """
func main(values: Int[]): Void {
    const same = catch values {
        issue: PatternMismatch => values
    }
}
"""
            ),
            raise_on_error=False,
        )

        self.assertIn(
            "Cannot catch undeclared outcome PatternMismatch",
            [diagnostic.message for diagnostic in result.diagnostics],
        )

    def test_array_destructuring_rejects_non_array_source(self) -> None:
        result = check_types(
            parse("func main(): Void { const [value] = 42 }"),
            raise_on_error=False,
        )

        self.assertIn(
            "Array destructuring requires an array, got Int",
            [diagnostic.message for diagnostic in result.diagnostics],
        )


if __name__ == "__main__":
    unittest.main()
