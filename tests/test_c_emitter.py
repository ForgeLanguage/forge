import re
import sys
import unittest
import tempfile
from pathlib import Path

from forge_c import CEmissionError, emit_c, emit_c_header, emit_c_project
from forge_lowering import lower
from forge_parser import parse


class CEmitterTests(unittest.TestCase):
    def test_emits_plain_int_variable(self) -> None:
        source = emit_c(parse("const myVar: Int = 5"))

        self.assertEqual(source, "int myVar = 5;\n")

    def test_emits_function_and_call_without_extra_abstractions(self) -> None:
        source = emit_c(
            parse(
                """
add(left: Int, right: Int): Int => left + right
const result: Int = add(1, 2)
"""
            )
        )

        self.assertEqual(
            source,
            """int add(int left, int right) {
    return left + right;
}

int result = add(1, 2);
""",
        )

    def test_emits_print_with_stdio_include(self) -> None:
        source = emit_c(parse('main(): Void { print "Hello" }'))

        self.assertEqual(
            source,
            """#include <stdio.h>

int main(void) {
    printf("%s\\n", "Hello");
    return 0;
}
""",
        )

    def test_emits_bool_with_stdbool_include(self) -> None:
        source = emit_c(parse("const enabled: Bool = true"))

        self.assertEqual(
            source,
            """#include <stdbool.h>

bool enabled = true;
""",
        )

    def test_emits_lazy_local_force_on_first_read(self) -> None:
        source = emit_c(
            parse(
                """
value(): Int {
    lazy delayed = 1 + 2
    print delayed
    return delayed
}
"""
            )
        )

        self.assertIn("bool delayed__ready = false;", source)
        self.assertIn("int delayed;", source)
        self.assertNotIn("int delayed = 1 + 2;", source)
        self.assertLess(source.index("if (!delayed__ready)"), source.index('printf("%d\\n", delayed);'))
        self.assertLess(source.index('printf("%d\\n", delayed);'), source.index("return delayed;"))

    def test_emits_if_else_and_assignment(self) -> None:
        source = emit_c(
            parse(
                """
pick(flag: Bool): Int {
    var value: Int = 0
    if flag {
        value = 1
    } else {
        value = 2
    }
    return value
}
"""
            )
        )

        self.assertEqual(
            source,
            """#include <stdbool.h>

int pick(bool flag) {
    int value = 0;
    if (flag) {
        value = 1;
    } else {
        value = 2;
    }
    return value;
}
""",
        )

    def test_emits_compound_assignment_and_increment(self) -> None:
        source = emit_c(
            parse(
                """
count(): Int {
    var value: Int = 1
    value += 2
    value++;
    --value
    return value
}
"""
            )
        )

        self.assertIn("value += 2;", source)
        self.assertIn("value++;", source)
        self.assertIn("value--;", source)

    def test_emits_switch_statement_as_single_selector_if_chain(self) -> None:
        source = emit_c(
            parse(
                """
pick(status: Int): Int {
    var value: Int = 0
    switch status {
        1 => {
            value = 10
        }
        2 => value = 20
        default => value = 30
    }
    return value
}
"""
            )
        )

        self.assertIn("int forge_tmp_switch0 = status;", source)
        self.assertIn("if (forge_tmp_switch0 == 1) {", source)
        self.assertIn("} else if (forge_tmp_switch0 == 2) {", source)
        self.assertIn("} else {", source)

    def test_emits_switch_function_as_if_chain_with_returns(self) -> None:
        source = emit_c(
            parse(
                """
switch classify(len: Int): String {
    len == 0 => "empty"
    len < 5 => "short"
    default => "long"
}
"""
            )
        )

        self.assertIn("char* classify(int len) {", source)
        self.assertIn("if (len == 0) {", source)
        self.assertIn('_forge_string_copy("empty");', source)
        self.assertIn("} else if (len < 5) {", source)
        self.assertIn('_forge_string_copy("short");', source)
        self.assertIn("} else {", source)
        self.assertIn('_forge_string_copy("long");', source)
        self.assertIn("return forge_tmp_string", source)

    def test_emits_while_loop(self) -> None:
        source = emit_c(
            parse(
                """
count(): Int {
    var value: Int = 0
    while value < 3 {
        value = value + 1
    }
    return value
}
"""
            )
        )

        self.assertIn("while (true) {", source)
        self.assertIn("bool forge_tmp_loop_condition0 = value < 3;", source)
        self.assertIn("if (!forge_tmp_loop_condition0) break;", source)
        self.assertIn("value = value + 1;", source)

    def test_emits_dynamic_array_literal_and_indexing(self) -> None:
        source = emit_c(
            parse(
                """
first(): Int {
    const values: Int[] = [1, 2]
    const index = 1
    return values[index]
}
"""
            )
        )

        self.assertIn("static void* _forge_alloc(size_t size)", source)
        self.assertIn("static void* _forge_realloc(void* pointer, size_t size)", source)
        self.assertIn("static void* _forge_array_new(size_t capacity, size_t element_size)", source)
        self.assertIn("static void _forge_array_grow(void** data, size_t* cap, size_t element_size)", source)
        self.assertIn("array.data = _forge_array_new(capacity, sizeof(int));", source)
        self.assertIn("_forge_array_grow((void**)&array->data, &array->cap, sizeof(int));", source)
        self.assertIn("forge_tmp_return1 = values.data[index];", source)
        self.assertIn("return forge_tmp_return1;", source)

    def test_emits_dynamic_array_len_as_int_cast(self) -> None:
        source = emit_c(
            parse(
                """
count(): Int {
    const values: Int[] = [1, 2]
    return values.len
}
"""
            )
        )

        self.assertIn("forge_tmp_return1 = (int)values.len;", source)

    def test_emits_fixed_array_literal_and_indexing(self) -> None:
        source = emit_c(
            parse(
                """
first(): Int {
    const values: Int[2] = [1, 2]
    return values[0]
}
"""
            )
        )

        self.assertEqual(
            source,
            """int first(void) {
    int values[2] = {1, 2};
    return values[0];
}
""",
        )

    def test_emits_top_level_dynamic_array_literal(self) -> None:
        source = emit_c(parse("const values: Int[] = [1, 2]"))

        self.assertIn("ForgeArray_Int values = {2, 2, (int[]){1, 2}};", source)

    def test_emits_array_destructuring_from_local_dynamic_array(self) -> None:
        source = emit_c(
            parse(
                """
main(values: Int[]): Void {
    const [first, second] = catch values {
        issue: PatternMismatch => { return }
    }
}
"""
            )
        )

        self.assertRegex(source, r"if \(forge_tmp_array_pattern\d+\.len >= 2\)")
        self.assertRegex(
            source,
            r"int first = forge_destructure_source\d+\.data\[0\];",
        )
        self.assertRegex(
            source,
            r"int second = forge_destructure_source\d+\.data\[1\];",
        )

    def test_emits_array_destructuring_source_call_once(self) -> None:
        source = emit_c(
            parse(
                """
values(): Int[] => [1, 2]
main(): Void {
    const [first, second] = catch values() {
        issue: PatternMismatch => { return }
    }
}
"""
            )
        )
        main_source = source[source.index("int main") :]

        self.assertEqual(main_source.count("values()"), 1)
        self.assertRegex(
            main_source,
            r"ForgeArray_Int forge_tmp_array_pattern\d+ = values\(\);",
        )
        self.assertRegex(
            main_source,
            r"int first = forge_destructure_source\d+\.data\[0\];",
        )
        self.assertLess(
            main_source.index(".len >= 2"),
            main_source.index(".data[0]"),
        )

    def test_caught_borrowed_dynamic_array_is_not_freed(self) -> None:
        source = emit_c(
            parse(
                """
read(values: Int[]): Int {
    const [first] = catch values {
        issue: PatternMismatch => { return 0 }
    }
    return first
}
"""
            )
        )
        function = source[source.index("int read") :]

        self.assertNotIn("free(values.data);", function)
        self.assertEqual(function.count(".data[0]"), 1)

    def test_caught_array_tracks_owned_expression_handler_result(self) -> None:
        source = emit_c(
            parse(
                """
class File {
    public new() {}
    public ping(): Void { print 1 }
}
read(files: File[]): Void {
    const [first] = catch files {
        issue: PatternMismatch => [File.new()]
    }
    first.ping()
}
"""
            )
        )
        function = source[source.index("void read") :]

        owner_flag = re.search(
            r"int (forge_tmp_array_owned\d+) = 0;",
            function,
        )
        self.assertIsNotNone(owner_flag)
        flag = owner_flag.group(1)
        self.assertIn(f"{flag} = 0;", function)
        self.assertIn(f"{flag} = 1;", function)
        self.assertRegex(
            function,
            rf"(?s)if \({flag}\) \{{.*_forge_free_File\(forge_destructure_source\d+"
            rf"\.data\[_forge_i\]\);.*free\(forge_destructure_source\d+\.data\);.*\}}",
        )

    def test_caught_array_does_not_own_borrowed_expression_handler_result(self) -> None:
        source = emit_c(
            parse(
                """
class File {
    public new() {}
}
load(): File[] => [File.new()]
read(fallback: File[]): Void {
    const [first, second] = catch load() {
        issue: PatternMismatch => fallback
    }
}
"""
            )
        )
        function = source[source.index("void read") :]

        owner_flag = re.search(
            r"int (forge_tmp_array_owned\d+) = 0;",
            function,
        )
        self.assertIsNotNone(owner_flag)
        flag = owner_flag.group(1)
        self.assertIn(f"{flag} = 1;", function)
        self.assertGreaterEqual(function.count(f"{flag} = 0;"), 2)
        self.assertNotIn("free(fallback.data);", function)
        self.assertRegex(
            function,
            rf"(?s)if \({flag}\) \{{.*free\(forge_destructure_source\d+\.data\);.*\}}",
        )

    def test_owned_string_array_pattern_cleans_mismatch_and_success_paths(self) -> None:
        source = emit_c(
            parse(
                """
read(text: String): String {
    const [first, second] = catch text.split(",", 2) {
        issue: PatternMismatch => { return "invalid" }
    }
    return first + second
}
"""
            )
        )
        function = source[source.index("char* read") :]

        guard = function.index(".len >= 2")
        first_index = function.index(".data[0]")
        self.assertLess(guard, first_index)
        self.assertRegex(
            function,
            r"free\(forge_tmp_array_pattern\d+\.data\);",
        )
        self.assertRegex(
            function,
            r"free\(forge_destructure_source\d+\.data\);",
        )
        self.assertRegex(
            function,
            r"_forge_string_copy\(forge_destructure_source\d+\.data\[0\]\)",
        )
        self.assertRegex(
            function,
            r"_forge_string_copy\(forge_destructure_source\d+\.data\[1\]\)",
        )

    def test_emits_array_destructuring_from_local_fixed_array(self) -> None:
        source = emit_c(
            parse(
                """
main(): Void {
    const values: Int[2] = [1, 2]
    const [first, second] = values
}
"""
            )
        )

        self.assertIn("int first = values[0];", source)
        self.assertIn("int second = values[1];", source)

    def test_emits_array_destructuring_from_fixed_array_member_alias(self) -> None:
        source = emit_c(
            parse(
                """
class Box {
    public values: Int[2]
}
main(box: Box): Void {
    const [first, second] = box.values
}
"""
            )
        )

        self.assertRegex(
            source,
            r"int\* forge_destructure_source\d+ = box->values;",
        )
        self.assertRegex(
            source,
            r"int first = forge_destructure_source\d+\[0\];",
        )
        self.assertNotRegex(source, r"free\(forge_destructure_source\d+\)")

    def test_emits_array_destructuring_from_indexed_fixed_array_alias(self) -> None:
        source = emit_c(
            parse(
                """
read(rows: Int[2][2]): Int {
    const [first] = rows[0]
    return first
}
"""
            )
        )

        self.assertRegex(
            source,
            r"int\* forge_destructure_source\d+ = rows\[0\];",
        )
        self.assertRegex(
            source,
            r"int first = forge_destructure_source\d+\[0\];",
        )

    def test_emits_array_destructuring_from_conditional_fixed_array_alias(self) -> None:
        source = emit_c(
            parse(
                """
read(flag: Bool, left: Int[2], right: Int[2]): Int {
    const [first] = flag ? left : right
    return first
}
"""
            )
        )

        self.assertRegex(
            source,
            r"int\* forge_destructure_source\d+ = flag \? left : right;",
        )
        self.assertRegex(
            source,
            r"int first = forge_destructure_source\d+\[0\];",
        )
        self.assertEqual(source.count("flag ? left : right"), 1)

    def test_fixed_resource_array_destructuring_alias_does_not_double_free(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class File {}
class Box {
    public files: File[1]
}
main(box: Box): Void {
    const [first] = box.files
}
"""
            )
        )
        main_source = source[source.index("int main") :]

        self.assertRegex(
            main_source,
            r"struct File\*\* forge_destructure_source\d+ = box->files;",
        )
        self.assertEqual(main_source.count("_forge_free_File(first);"), 0)
        self.assertEqual(main_source.count("_forge_free_Box(box);"), 0)

    def test_caught_fixed_resource_array_remains_borrowed(self) -> None:
        source = emit_c(
            parse(
                """
class File {}
read(files: File[1]): Void {
    const [first] = catch files {
        issue: PatternMismatch => { return }
    }
}
"""
            )
        )
        function = source[source.index("void read") :]

        self.assertNotIn(".len >=", function)
        self.assertEqual(function.count("_forge_free_File(first);"), 0)
        self.assertNotIn("free(files);", function)

    def test_emits_owned_dynamic_array_cleanup(self) -> None:
        source = emit_c(
            parse(
                """
class User {}
make(): Void {
    const users: User[] = [User.new(), User.new()]
}
"""
            )
        )

        self.assertIn(
            "for (size_t _forge_i = 0; _forge_i < users.len; _forge_i += 1)",
            source,
        )
        self.assertIn("_forge_free_User(users.data[_forge_i]);", source)
        self.assertIn("free(users.data);", source)

    def test_emits_bulk_call_argument_packs_as_array_literal(self) -> None:
        source = emit_c(
            parse(
                """
class Point {
    public new(public x: Int, public y: Int) {}
}

make(): Point[] {
    return Point.new[(1, 2), (3, 4)]
}
"""
            )
        )

        self.assertIn("ForgeArray_Point_new(2);", source)
        self.assertIn("ForgeArray_Point_push(&forge_tmp_array0, Point_new(1, 2));", source)
        self.assertIn("ForgeArray_Point_push(&forge_tmp_array0, Point_new(3, 4));", source)

    def test_emits_scalar_bracket_call_as_plain_call(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Console {
    public static write(str: String): Void {
        print str
    }
}

main(): Void {
    Console.write["a"]
}
"""
            )
        )

        self.assertIn('Console_write("a");', source)

    def test_emits_scalar_list_bracket_call_as_sequence(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Console {
    public static write(str: String): Void {
        print str
    }
}

main(): Void {
    Console.write["a", "b"]
}
"""
            )
        )

        self.assertIn('Console_write("a");\n    Console_write("b");', source)

    def test_emits_array_bulk_map_call_as_result_array(self) -> None:
        source = emit_c(
            parse(
                """
twice(value: Int): Int => value * 2
load(): Int[] {
    const values = [1, 2]
    return twice[values]
}
"""
            )
        )

        self.assertIn("ForgeArray_Int forge_tmp_bulk", source)
        self.assertIn(
            "for (size_t _forge_i = 0; _forge_i < values.len; _forge_i += 1)",
            source,
        )
        self.assertIn(
            "ForgeArray_Int_push(&forge_tmp_bulk1, twice(values.data[_forge_i]));",
            source,
        )
        self.assertIn("return forge_tmp_return", source)

    def test_emits_array_bulk_map_call_for_instance_method(self) -> None:
        source = emit_c(
            parse(
                """
class Doubler {
    public new() {}

    public twice(value: Int): Int => value * 2
}

load(): Int[] {
    const values = [1, 2]
    const doubler = Doubler.new()
    return doubler.twice[values]
}
"""
            )
        )

        self.assertIn("ForgeArray_Int_push(&forge_tmp_bulk", source)
        self.assertIn("Doubler_twice(doubler, values.data[_forge_i])", source)

    def test_emits_stringable_array_bulk_call_to_string(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Console {
    public static write(str: String): Void {
        print str
    }
}

class Point {
    implements Stringable

    public toString(): String {
        return "Point"
    }
}

main(points: Point[]): Void {
    Console.write[points]
}
"""
            )
        )

        self.assertIn("for (size_t _forge_i = 0; _forge_i < points.len; _forge_i += 1)", source)
        self.assertIn("char* forge_tmp_string1 = Point_toString(points.data[_forge_i]);", source)
        self.assertIn("Console_write(forge_tmp_string1);", source)
        self.assertIn("free(forge_tmp_string1);", source)

    def test_emits_class_method_from_used_trait(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
interface Runnable {
    public run(): Void
}

trait AppLogic {
    implements Runnable

    public run(): Void {
        print "running"
    }
}

class App {
    uses AppLogic
    implements Runnable
}

main(): Void {
    const app = App.new()
    app.run()
}
"""
            )
        )

        self.assertIn("void App_run(struct App* this)", source)
        self.assertIn("App_run(app);", source)

    def test_accepts_lowering_result(self) -> None:
        lowered = lower(parse("const value: Int = 1"))

        self.assertEqual(emit_c(lowered), "int value = 1;\n")

    def test_rejects_nullable_value_type_until_representation_exists(self) -> None:
        with self.assertRaises(CEmissionError):
            emit_c(parse("const value: Int? = null"))

    def test_emits_nullable_struct_as_boxed_value(self) -> None:
        source = emit_c(
            parse(
                """
struct Item {
    public name: String
}

main(): Void {
    var item: Item? = null
    item = { name: "one" }
}
"""
            )
        )

        self.assertIn("struct Item* item = NULL;", source)
        self.assertIn("struct Item* forge_tmp_nullable0 = _forge_alloc(sizeof(struct Item));", source)
        self.assertIn('char* forge_tmp_string1 = _forge_string_copy("one");', source)
        self.assertIn("*forge_tmp_nullable0 = (struct Item){.name = forge_tmp_string1};", source)
        self.assertIn("item = forge_tmp_nullable0;", source)

    def test_emits_async_function_as_sync_backend_mvp(self) -> None:
        source = emit_c(parse("async answer(): Int => 42"))

        self.assertIn("int answer(void)", source)
        self.assertIn("return 42;", source)

    def test_emits_direct_async_native_await_through_runtime_task(self) -> None:
        source = emit_c(
            parse(
                """
async native absValue(value: Int): Int = "abs"
main(): Void {
    print absValue(-7).await()
}
"""
            ),
            preamble='#include "forge_runtime.h"',
            external_helpers=True,
        )

        self.assertIn("typedef struct {\n    int arg0;\n    int result;\n}", source)
        self.assertIn("static void ForgeAsyncNative_abs_Int_Int_run(void* raw_context)", source)
        self.assertIn("context->result = abs(context->arg0);", source)
        self.assertIn("_ForgeAsyncTask* forge_tmp_async_task", source)
        self.assertIn("_forge_async_task_new(ForgeAsyncNative_abs_Int_Int_run, &forge_tmp_async_context", source)
        self.assertIn("_forge_async_task_start(forge_tmp_async_task", source)
        self.assertIn("_forge_async_task_await(forge_tmp_async_task", source)
        self.assertIn("_forge_async_task_free(forge_tmp_async_task", source)
        self.assertIn('printf("%d\\n", forge_tmp_async_context', source)

    def test_emits_saved_async_native_task_through_runtime_task(self) -> None:
        source = emit_c(
            parse(
                """
async native absValue(value: Int): Int = "abs"
main(): Void {
    const pending = absValue(-7)
    print pending.await()
}
"""
            ),
            preamble='#include "forge_runtime.h"',
            external_helpers=True,
        )

        self.assertIn("ForgeAsyncNative_abs_Int_Int_Context pending_context;", source)
        self.assertIn("pending_context.arg0 = -7;", source)
        self.assertIn("_ForgeAsyncTask* pending = _forge_async_task_new(ForgeAsyncNative_abs_Int_Int_run, &pending_context);", source)
        self.assertIn("_forge_async_task_start(pending);", source)
        self.assertIn("_forge_async_task_await(pending);", source)
        self.assertIn("_forge_async_task_free(pending);", source)
        self.assertIn('printf("%d\\n", pending_context.result);', source)

    def test_emits_await_through_runtime_task_for_forge_async_function(self) -> None:
        source = emit_c(
            parse(
                """
async answer(): Int => 42
async load(): Int {
    return await answer()
}
"""
            )
        )

        self.assertIn("int answer(void);", source)
        self.assertIn("context->result = answer();", source)
        self.assertIn("_forge_async_task_new(ForgeAsyncNative_answer_Int_run, &forge_tmp_async_context", source)
        self.assertIn("_forge_async_task_start(forge_tmp_async_task", source)
        self.assertIn("_forge_async_task_await(forge_tmp_async_task", source)
        self.assertIn("_forge_async_task_free(forge_tmp_async_task", source)
        self.assertIn("return forge_tmp_async_context", source)

    def test_emits_task_await_method_as_runtime_task_for_forge_async_function(self) -> None:
        source = emit_c(
            parse(
                """
async answer(): Int => 42
load(): Int {
    return answer().await()
}
"""
            )
        )

        self.assertIn("int answer(void);", source)
        self.assertIn("context->result = answer();", source)
        self.assertIn("_forge_async_task_new(ForgeAsyncNative_answer_Int_run, &forge_tmp_async_context", source)
        self.assertIn("_forge_async_task_start(forge_tmp_async_task", source)
        self.assertIn("_forge_async_task_await(forge_tmp_async_task", source)
        self.assertIn("_forge_async_task_free(forge_tmp_async_task", source)
        self.assertIn("return forge_tmp_async_context", source)

    def test_emits_awaited_async_instance_method_call(self) -> None:
        source = emit_c(
            parse(
                """
class App {
    public new() {}

    public async run(value: Int): Int {
        return value + 1
    }
}

main(): Void {
    const app = App.new()
    print app.run(41).await()
}
"""
            )
        )

        self.assertIn("struct App* receiver;", source)
        self.assertIn(".receiver = app;", source)
        self.assertIn("context->result = App_run(context->receiver, context->arg0);", source)
        self.assertIn("_forge_async_task_new(ForgeAsyncNative_App_run_App_Int_Int_run, &forge_tmp_async_context", source)
        self.assertIn("_forge_async_task_start(forge_tmp_async_task", source)

    def test_emits_interface_value_and_dynamic_async_method_call(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
interface Runner {
    public async run(value: Int): Int
}

class App {
    implements Runner

    public new() {}

    public async run(value: Int): Int {
        return value + 1
    }
}

main(): Void {
    const runner: Runner = App.new()
    print runner.run(41).await()
}
"""
            )
        )

        self.assertIn("struct Runner_vtable", source)
        self.assertIn("struct Runner runner = (struct Runner){.object = App_new(), .vtable = &App_as_Runner_vtable};", source)
        self.assertIn("static int App_as_Runner_run(void* object, int arg0)", source)
        self.assertIn("runner.vtable->run(runner.object, 41)", source)

    def test_emits_operator_await_for_dynamic_async_interface_method_call(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
interface Runner {
    public async run(value: Int): Int
}

class App {
    implements Runner

    public new() {}

    public async run(value: Int): Int {
        return value + 1
    }
}

async mainAsync(runner: Runner): Int {
    return await runner.run(41)
}
"""
            )
        )

        self.assertIn("runner.vtable->run(runner.object, 41)", source)

    def test_emits_catch_for_awaited_async_outcome(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class NetworkIssue {}
async fetch(): String, !NetworkIssue {
    return NetworkIssue.new()
}
async load(): String {
    return catch await fetch() {
        issue: NetworkIssue => "fallback"
    }
}
"""
            )
        )

        self.assertIn("ForgeResult_String_NetworkIssue fetch(void);", source)
        self.assertIn("ForgeResult_String_NetworkIssue result;", source)
        self.assertIn("context->result = fetch();", source)
        self.assertIn("ForgeResult_String_NetworkIssue forge_tmp_outcome", source)
        self.assertIn('forge_tmp_catch', source)
        self.assertIn('= "fallback";', source)
        self.assertIn("_forge_string_copy(forge_tmp_catch", source)

    def test_emits_catch_for_saved_async_outcome_task_await(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class NetworkIssue {}
async fetch(): String, !NetworkIssue {
    return NetworkIssue.new()
}
load(): String {
    const pending = fetch()
    return catch pending.await() {
        issue: NetworkIssue => "fallback"
    }
}
"""
            )
        )

        self.assertIn("ForgeAsyncNative_fetch_String_Context pending_context;", source)
        self.assertIn("ForgeResult_String_NetworkIssue result;", source)
        self.assertIn("ForgeResult_String_NetworkIssue forge_tmp_outcome", source)
        self.assertIn("_forge_async_task_await(pending);", source)
        self.assertIn("_forge_async_task_free(pending);", source)

    def test_emits_catch_for_task_collection_all_async_outcome(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class NetworkIssue {}
async download(url: String): String, !NetworkIssue {
    return url
}
async load(): String[] {
    const urls = ["a", "b"]
    return catch await (download task[urls]).all() {
        issue: NetworkIssue => ["fallback"]
    }
}
"""
            )
        )

        self.assertIn("context->result = download(context->arg0);", source)
        self.assertIn("_forge_async_task_await(forge_tmp_async_tasks", source)
        self.assertIn(".tag == ForgeResult_String_NetworkIssue_SUCCESS", source)
        self.assertIn("ForgeArray_String_push(&forge_tmp_tasks", source)
        self.assertIn("ForgeResult_String___NetworkIssue forge_tmp_outcome", source)

    def test_emits_sync_async_twins_with_distinct_c_names(self) -> None:
        source = emit_c(
            parse(
                """
read(path: String): String => "sync"
async read(path: String): String => "async"
syncLoad(): String {
    return read("file.txt")
}
asyncLoad(): String {
    return read("file.txt").await()
}
"""
            )
        )

        self.assertIn("char* read(const char* path)", source)
        self.assertIn("char* read_async(const char* path)", source)
        self.assertIn('char* forge_tmp_string0 = _forge_string_copy("sync");', source)
        self.assertIn('char* forge_tmp_string1 = _forge_string_copy("async");', source)
        self.assertIn('return read("file.txt");', source)
        self.assertIn("context->result = read_async(context->arg0);", source)
        self.assertIn("_forge_async_task_new(ForgeAsyncNative_read_async_String_String_run, &forge_tmp_async_context", source)
        self.assertIn("_forge_async_task_start(forge_tmp_async_task", source)
        self.assertIn("return forge_tmp_async_context", source)

    def test_emits_task_bulk_all_as_runtime_tasks_for_forge_async_function(self) -> None:
        source = emit_c(
            parse(
                """
async twice(value: Int): Int => value * 2
load(): Int[] {
    const values = [1, 2]
    return (twice task[values]).all().await()
}
"""
            )
        )

        self.assertIn("ForgeArray_Int forge_tmp_tasks", source)
        self.assertIn("ForgeAsyncNative_twice_Int_Int_Context* forge_tmp_async_contexts", source)
        self.assertIn("_ForgeAsyncTask** forge_tmp_async_tasks", source)
        self.assertIn(
            "for (size_t _forge_i = 0; _forge_i < values.len; _forge_i += 1)",
            source,
        )
        self.assertIn("_forge_async_task_start(forge_tmp_async_tasks", source)
        self.assertIn("_forge_async_task_await(forge_tmp_async_tasks", source)
        self.assertIn("ForgeArray_Int_push(&forge_tmp_tasks", source)
        self.assertIn("return forge_tmp_return", source)

    def test_emits_saved_async_native_task_collection_all_through_runtime_tasks(self) -> None:
        source = emit_c(
            parse(
                """
async native absValue(value: Int): Int = "abs"
load(): Int[] {
    const values = [-1, -2]
    const pending = absValue task[values]
    return pending.all().await()
}
"""
            ),
            preamble='#include "forge_runtime.h"',
            external_helpers=True,
        )

        self.assertIn("ForgeArray_Int pending = ForgeArray_Int_new(values.len);", source)
        self.assertIn("ForgeAsyncNative_abs_Int_Int_Context* forge_tmp_async_contexts", source)
        self.assertIn("_ForgeAsyncTask** forge_tmp_async_tasks", source)
        self.assertIn("forge_tmp_async_contexts", source)
        self.assertIn(".arg0 = values.data[_forge_i];", source)
        self.assertIn("_forge_async_task_start(forge_tmp_async_tasks", source)
        self.assertIn("_forge_async_task_await(forge_tmp_async_tasks", source)
        self.assertIn("ForgeArray_Int_push(&pending, forge_tmp_async_contexts", source)
        self.assertIn("_forge_async_task_free(forge_tmp_async_tasks", source)
        self.assertIn("forge_tmp_return", source)
        self.assertIn("= pending;", source)

    def test_emits_task_bulk_call_for_async_instance_method(self) -> None:
        source = emit_c(
            parse(
                """
class Doubler {
    public new() {}

    public async twice(value: Int): Int => value * 2
}

load(): Int[] {
    const values = [1, 2]
    const doubler = Doubler.new()
    return (doubler.twice task[values]).all().await()
}
"""
            )
        )

        self.assertIn("struct Doubler* receiver;", source)
        self.assertIn(".receiver = doubler;", source)
        self.assertIn("context->result = Doubler_twice(context->receiver, context->arg0);", source)
        self.assertIn("_forge_async_task_start(forge_tmp_async_tasks", source)

    def test_emits_task_collection_scalar_methods_as_runtime_task_awaits(self) -> None:
        source = emit_c(
            parse(
                """
async twice(value: Int): Int => value * 2
pickFirst(): Int {
    const values = [1, 2]
    return (twice task[values]).first().await()
}
pickAny(): Int {
    const values = [1, 2]
    return (twice task[values]).any().await()
}
pickLast(): Int {
    const values = [1, 2]
    return (twice task[values]).last().await()
}
"""
            )
        )

        self.assertIn("_forge_async_task_await(forge_tmp_async_tasks", source)
        self.assertIn("ForgeArray_Int_push(&forge_tmp_tasks", source)
        self.assertIn("forge_tmp_return4 = forge_tmp_tasks1.data[0];", source)
        self.assertIn("free(forge_tmp_tasks1.data);", source)
        self.assertIn("forge_tmp_return9 = forge_tmp_tasks6.data[0];", source)
        self.assertIn("free(forge_tmp_tasks6.data);", source)
        self.assertIn("forge_tmp_return14 = forge_tmp_tasks11.data[forge_tmp_tasks11.len - 1];", source)
        self.assertIn("free(forge_tmp_tasks11.data);", source)

    def test_emits_class_struct_with_fields(self) -> None:
        source = emit_c(
            parse(
                """
class User {
    public name: String
    public age: Int
}
"""
            )
        )

        self.assertIn("struct User {\n    const char* name;\n    int age;\n};", source)
        self.assertIn("struct User* User_new(void)", source)
        self.assertIn("struct User* this = _forge_alloc(sizeof(struct User));", source)
        self.assertIn("void _forge_free_User(struct User* value)", source)

    def test_emits_nullable_generic_struct_field_after_specialization(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
struct Definition<T> {
    public asSingle: Bool
    public instance: T?
}

class Logger {}

struct Defs {
    public logger: Definition<Logger>
}

const defs: Defs = {
    logger: {
        asSingle: true,
        instance: Logger.new()
    }
}
"""
            )
        )

        self.assertIn("struct Definition_Logger {", source)
        self.assertIn("struct Logger* instance;", source)

    def test_emits_instance_method_with_hidden_this_parameter(self) -> None:
        source = emit_c(
            parse(
                """
class Counter {
    public value: Int
    inc(): Void {
        this.value = this.value + 1
    }
}
"""
            )
        )

        self.assertIn("struct Counter {\n    int value;\n};", source)
        self.assertIn("void Counter_inc(struct Counter* this)", source)
        self.assertIn("this->value = this->value + 1;", source)
        self.assertIn("struct Counter* this = _forge_alloc(sizeof(struct Counter));", source)

    def test_emits_constructor_promoted_parameter_assignments_first(self) -> None:
        source = emit_c(
            parse(
                """
class Point {
    public new(public x: Int, public y: Int) {
        print x
    }
}
"""
            )
        )

        constructor_body = source[source.index("struct Point* Point_new") :]
        self.assertLess(
            constructor_body.index("this->x = x;"),
            constructor_body.index('printf("%d\\n", x);'),
        )
        self.assertLess(
            constructor_body.index("this->y = y;"),
            constructor_body.index('printf("%d\\n", x);'),
        )

    def test_constructor_copies_borrowed_string_into_owned_field(self) -> None:
        source = emit_c(
            parse(
                """
class Response {
    public new(public status: Int, public body: String) {}
}
"""
            )
        )

        self.assertIn("this->body = _forge_string_copy(body);", source)

    def test_constructor_transfers_taken_string_into_owned_field(self) -> None:
        source = emit_c(
            parse(
                """
class Response {
    public new(public take body: String) {}
}
"""
            )
        )

        self.assertIn("this->body = body;", source)
        self.assertNotIn("this->body = _forge_string_copy(body);", source)

    def test_constructor_does_not_free_uninitialized_promoted_class_field(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Handler {}
class Server {
    public new(public take handler: Handler) {}
}
"""
            )
        )

        constructor = source[source.index("struct Server* Server_new") :]
        self.assertIn("this->handler = handler;", constructor)
        self.assertNotIn("_forge_free_Handler(this->handler);", constructor)

    def test_dynamic_string_array_owns_literal_elements(self) -> None:
        source = emit_c(
            parse(
                """
main(): Void {
    const values = ["one", "two"]
    print values[0]
}
"""
            )
        )

        self.assertIn('char* forge_tmp_string1 = _forge_string_copy("one");', source)
        self.assertIn(
            "ForgeArray_String_push(&forge_tmp_array0, forge_tmp_string1);",
            source,
        )
        self.assertIn("free((void*)values.data[_forge_i]);", source)

    def test_emits_instance_method_calls_as_plain_c_functions(self) -> None:
        source = emit_c(
            parse(
                """
class Counter {
    public value: Int
    inc(): Void {
        this.value = this.value + 1
    }
}

tick(counter: Counter): Void {
    counter.inc()
}
"""
            )
        )

        self.assertIn("void Counter_inc(struct Counter* this)", source)
        self.assertIn("struct Counter* this = _forge_alloc(sizeof(struct Counter));", source)
        self.assertIn("void tick(struct Counter* counter)", source)
        self.assertIn("Counter_inc(counter);", source)

    def test_emits_move_as_plain_argument_and_skips_caller_cleanup(self) -> None:
        source = emit_c(
            parse(
                """
class Profile {}
consume(take profile: Profile): Void {}

main(): Void {
    var profile: Profile = Profile.new()
    consume(move profile)
}
"""
            )
        )

        self.assertIn("consume(profile);", source)
        main_body = source[source.index("int main(void)") :]
        self.assertNotIn("_forge_free_Profile(profile);", main_body)

    def test_return_keeps_owned_string_from_conditional_branch_alive(self) -> None:
        source = emit_c(
            parse(
                """
name(flag: Bool): String {
    return flag ? "Hello, " + "World" : ""
}
"""
            )
        )

        self.assertIn('char* forge_tmp_string0 = _forge_string_concat(2, "Hello, ", "World");', source)
        self.assertIn("if (flag) {", source)
        self.assertIn("return forge_tmp_string0;", source)
        self.assertIn('char* forge_tmp_string1 = _forge_string_copy("");', source)
        self.assertIn("return forge_tmp_string1;", source)
        self.assertNotIn("free(forge_tmp_string0);\n    return", source)

    def test_string_return_copies_borrowed_values(self) -> None:
        source = emit_c(
            parse(
                """
empty(): String {
    return ""
}

echo(name: String): String {
    return name
}
"""
            )
        )

        self.assertIn("char* empty(void)", source)
        self.assertIn('char* forge_tmp_string0 = _forge_string_copy("");', source)
        self.assertIn("return forge_tmp_string0;", source)
        self.assertIn("char* echo(const char* name)", source)
        self.assertIn("char* forge_tmp_string1 = _forge_string_copy(name);", source)
        self.assertIn("return forge_tmp_string1;", source)

    def test_string_conditional_local_owns_all_branches(self) -> None:
        source = emit_c(
            parse(
                """
name(flag: Bool): String {
    const result: String = flag ? "Hello, " + "World" : ""
    return result
}
"""
            )
        )

        self.assertIn("char* result;", source)
        self.assertIn('char* forge_tmp_string0 = _forge_string_concat(2, "Hello, ", "World");', source)
        self.assertIn("result = forge_tmp_string0;", source)
        self.assertIn('char* forge_tmp_string1 = _forge_string_copy("");', source)
        self.assertIn("result = forge_tmp_string1;", source)
        self.assertIn("return result;", source)
        self.assertNotIn("free((void*)result);\n    return result;", source)

    def test_frees_owned_string_function_call_after_print(self) -> None:
        source = emit_c(
            parse(
                """
class Helper {
    public static hello(name: String): String {
        return "Hello, " + name
    }
}

main(): Void {
    print Helper.hello("World")
}
"""
            )
        )

        self.assertIn("char* Helper_hello(const char* name)", source)
        self.assertIn('char* forge_tmp_string1 = Helper_hello("World");', source)
        self.assertIn('printf("%s\\n", forge_tmp_string1);', source)
        self.assertIn("free(forge_tmp_string1);", source)

    def test_conditional_return_does_not_evaluate_string_branch_before_guard(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public name(): String {
        return this.profile ? this.profile.firstName + "!" : ""
    }
}
"""
            )
        )

        guard_index = source.index("if (this->profile)")
        access_index = source.index("this->profile->firstName")
        self.assertLess(guard_index, access_index)

    def test_emits_null_safe_member_access_as_null_checked_expression(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public name(): String? {
        return this.profile?.firstName
    }
}
"""
            )
        )

        self.assertIn(
            "return (this->profile != NULL ? this->profile->firstName : NULL);",
            source,
        )

    def test_emits_nullable_struct_member_access_through_pointer(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
struct Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public name(): String {
        return this.profile ? this.profile.firstName : ""
    }
}
"""
            )
        )

        guard_index = source.index("if (this->profile)")
        access_index = source.index("(*this->profile).firstName")
        self.assertLess(guard_index, access_index)

    def test_emits_narrowed_nullable_struct_as_call_argument(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
struct Profile {
    public firstName: String
}
class User {
    public profile: Profile?
    public render(profile: Profile): String {
        return profile.firstName
    }
    public name(): String {
        return this.profile ? this.render(this.profile) : ""
    }
}
"""
            )
        )

        self.assertIn("User_render(this, (*this->profile))", source)

    def test_owned_field_assignment_frees_old_value_and_consumes_local(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Profile {}
class User {
    public profile: Profile?
    public setProfile(take profile: Profile): Void {
        this.profile = profile
    }
}
"""
            )
        )

        self.assertIn(
            "_forge_free_Profile(this->profile);\n    this->profile = profile;",
            source,
        )

    def test_unused_owned_take_parameter_is_cleaned_up(self) -> None:
        source = emit_c(
            parse(
                """
class Profile {}
consume(take profile: Profile): Void {
}
"""
            )
        )

        self.assertIn("_forge_free_Profile(profile);", source)

    def test_transferred_take_parameter_is_not_cleaned_up(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Profile {}
class User {
    public profile: Profile?
    public setProfile(take profile: Profile): Void {
        this.profile = profile
    }
}
"""
            )
        )

        self.assertIn("this->profile = profile;", source)
        self.assertNotIn("_forge_free_Profile(profile);", source)

    def test_returned_take_parameter_is_not_cleaned_up(self) -> None:
        source = emit_c(
            parse(
                """
class Profile {}
identity(take profile: Profile): Profile {
    return profile
}
"""
            )
        )

        self.assertIn("return profile;", source)
        self.assertNotIn("_forge_free_Profile(profile);\n    return profile;", source)

    def test_nullable_owned_field_null_assignment_frees_old_value(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Profile {}
class User {
    public profile: Profile?
    public clear(): Void {
        this.profile = null
    }
}
"""
            )
        )

        self.assertIn(
            "_forge_free_Profile(this->profile);\n    this->profile = NULL;",
            source,
        )

    def test_owned_field_assignment_disables_consumed_local_cleanup(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Profile {}
class User {
    public profile: Profile?
}

main(): Void {
    var user: User = User.new()
    var profile: Profile = Profile.new()
    user.profile = move profile
}
"""
            )
        )

        self.assertIn(
            "_forge_free_Profile(user->profile);\n    user->profile = profile;",
            source,
        )
        self.assertNotIn("_forge_free_Profile(profile);", source)

    def test_owned_local_reassignment_frees_old_value_and_consumes_source(self) -> None:
        source = emit_c(
            parse(
                """
class Profile {}
main(): Void {
    var first: Profile = Profile.new()
    var second: Profile = Profile.new()
    first = move second
}
"""
            )
        )

        self.assertIn(
            "_forge_free_Profile(first);\n    first = second;",
            source,
        )
        self.assertNotIn("_forge_free_Profile(second);", source)

    def test_nullable_owned_local_null_assignment_frees_old_value(self) -> None:
        source = emit_c(
            parse(
                """
class Profile {}
main(): Void {
    var profile: Profile? = Profile.new()
    profile = null
}
"""
            )
        )

        self.assertIn(
            "_forge_free_Profile(profile);\n    profile = NULL;",
            source,
        )

    def test_member_block_emits_field_assignments_and_method_calls(self) -> None:
        source = emit_c(
            parse(
                """
class User {
    public age: Int
    save(): Void {}
}

main(): Void {
    var user: User = User.new()
    user.{
        age = 42
        save()
    }
}
"""
            )
        )

        self.assertIn("user->age = 42;\n    User_save(user);", source)

    def test_member_block_expression_emits_updates_and_returns_receiver(self) -> None:
        source = emit_c(
            parse(
                """
struct Result {
    public statusCode: Int
}

accept(result: Result): Result => result

main(): Void {
    var result: Result = {
        statusCode: 0
    }
    accept(result.{
        statusCode = 200
    })
}
"""
            )
        )

        self.assertIn("result.statusCode = 200;\n    accept(result);", source)

    def test_owned_return_does_not_cleanup_returned_local(self) -> None:
        source = emit_c(
            parse(
                """
class Profile {}
makeProfile(): Profile {
    var profile: Profile = Profile.new()
    return move profile
}
"""
            )
        )

        self.assertIn("return profile;", source)
        self.assertNotIn("_forge_free_Profile(profile);\n    return profile;", source)

    def test_emits_static_method_calls_without_receiver_argument(self) -> None:
        source = emit_c(
            parse(
                """
class Math {
    static one(): Int => 1
}

const value: Int = Math.one()
"""
            )
        )

        self.assertIn("int Math_one(void)", source)
        self.assertIn("return 1;", source)
        self.assertIn("struct Math* this = _forge_alloc(sizeof(struct Math));", source)
        self.assertIn("int value = Math_one();", source)

    def test_emits_self_type_and_self_constructor_call(self) -> None:
        source = emit_c(
            parse(
                """
class Point {
    public new(public x: Int, public y: Int) {}

    public static origin(): self {
        return self.new(0, 0)
    }
}
"""
            )
        )

        self.assertIn("struct Point* Point_origin(void)", source)
        self.assertIn("return Point_new(0, 0);", source)

    def test_emits_static_fields_as_class_globals(self) -> None:
        source = emit_c(
            parse(
                """
class Counter {
    public static count: Int = 0
    public value: Int
    public new() {
        self.count = self.count + 1
    }
}
"""
            )
        )

        self.assertIn("int Counter_count = 0;", source)
        self.assertIn("struct Counter* this = _forge_alloc(sizeof(struct Counter));", source)
        self.assertIn("Counter_count = Counter_count + 1;", source)

    def test_emits_static_fields_in_headers_as_externs(self) -> None:
        header = emit_c_header(
            parse(
                """
class Counter {
    public static count: Int = 0
}
"""
            )
        )

        self.assertIn("extern int Counter_count;", header)

    def test_emits_class_variables_as_struct_pointers(self) -> None:
        source = emit_c(
            parse(
                """
class User {}
var user: User
"""
            )
        )

        self.assertIn("struct User* this = _forge_alloc(sizeof(struct User));", source)
        self.assertIn("struct User* user;", source)

    def test_emits_struct_variables_as_values(self) -> None:
        source = emit_c(
            parse(
                """
@multidef

public struct HttpResponse {
    public status: Int
    public body: String
}

const response: HttpResponse = {
    status: 200,
    body: "OK"
}
"""
            )
        )

        self.assertIn("struct HttpResponse {\n    int status;\n    const char* body;\n};", source)
        self.assertIn(
            'struct HttpResponse response = (struct HttpResponse){.status = 200, .body = "OK"};',
            source,
        )
        self.assertNotIn("struct HttpResponse* response", source)

    def test_emits_typed_enum_variants_as_values(self) -> None:
        source = emit_c(
            parse(
                """
@multidef

public enum HttpMethod : String {
    Get => "GET",
    Post => "POST",
}

const method: HttpMethod = HttpMethod.Get
"""
            )
        )

        self.assertIn('static const char* const HttpMethod_Get = "GET";', source)
        self.assertIn("const char* method = HttpMethod_Get;", source)

    def test_emits_inline_struct_enum_variants_as_values(self) -> None:
        source = emit_c(
            parse(
                """
@multidef

public enum FeedStatus : struct {
    public code: Int
    public label: String
    public isError: Bool
} {
    Ok => { 0, "OK", false }
    NoBannerConfig => { 1, "NoBannerConfig", true }
}

const status: FeedStatus = FeedStatus.NoBannerConfig
const code = status.code
"""
            )
        )

        self.assertIn(
            "struct FeedStatus_Value {\n"
            "    int _forge_variant_id;\n"
            "    int code;\n"
            "    const char* label;\n"
            "    bool isError;\n"
            "};",
            source,
        )
        self.assertIn(
            'static const struct FeedStatus_Value FeedStatus_NoBannerConfig = '
            '(struct FeedStatus_Value){._forge_variant_id = 1, 1, "NoBannerConfig", true};',
            source,
        )
        self.assertIn("struct FeedStatus_Value status = FeedStatus_NoBannerConfig;", source)
        self.assertIn("int code = status.code;", source)

    def test_emits_inline_struct_enum_equality_by_variant_id(self) -> None:
        source = emit_c(
            parse(
                """
@multidef

public enum FeedStatus : struct {
    public code: Int
    public label: String
    public isError: Bool
} {
    Ok => { 0, "OK", false }
    AlsoOk => { 0, "OK", false }
}

const status: FeedStatus = FeedStatus.AlsoOk
const matches = status == FeedStatus.Ok
"""
            )
        )

        self.assertIn(
            "bool matches = status._forge_variant_id == FeedStatus_Ok._forge_variant_id;",
            source,
        )

    def test_emits_default_constructor_call_as_allocation(self) -> None:
        source = emit_c(
            parse(
                """
class User {}
const user: User = User.new()
"""
            )
        )

        self.assertIn("struct User* this = _forge_alloc(sizeof(struct User));", source)
        self.assertIn("struct User* user = User_new();", source)

    def test_frees_owned_class_locals_at_block_exit(self) -> None:
        source = emit_c(
            parse(
                """
class User {}
main(): Void {
    const user: User = User.new()
    print "done"
}
"""
            )
        )

        self.assertIn("_forge_free_User(user);\n    return 0;", source)

    def test_early_return_uses_function_cleanup_label(self) -> None:
        source = emit_c(
            parse(
                """
class User {}
main(): Int {
    const user: User = User.new()
    return 7
}
"""
            )
        )

        self.assertIn("int forge_tmp_return0;", source)
        self.assertIn("forge_tmp_return0 = 7;\n    goto cleanup;", source)
        self.assertIn("cleanup:\n    _forge_free_User(user);\n    return forge_tmp_return0;", source)

    def test_catch_handler_return_keeps_inline_cleanup(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Issue {}
class User {}
class Work {
    public static run(): Int, !Issue {
        return Issue.new()
    }
}
main(): Int {
    const user: User = User.new()
    const value: Int = catch Work.run() {
        issue: Issue => {
            return 1
        }
    }
    const later: User = User.new()
    return value
}
"""
            )
        )

        self.assertIn("_forge_free_User(user);\n        return forge_tmp_return", source)
        self.assertNotIn("return 1;\n    }\n    struct User* later", source)

    def test_backend_destructor_does_not_conflict_with_user_free_method(self) -> None:
        source = emit_c(
            parse(
                """
class User {
    public free(): Void {}
}
"""
            )
        )

        self.assertIn("void User_free(struct User* this) {}", source)
        self.assertIn("void _forge_free_User(struct User* value)", source)

    def test_backend_destructor_recursively_frees_class_fields(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Profile {}
class User {
    public profile: Profile?
}
"""
            )
        )

        self.assertIn("this->profile = NULL;", source)
        self.assertIn("_forge_free_Profile(value->profile);", source)
        self.assertIn("free(value);", source)

    def test_backend_destructor_recursively_frees_dynamic_array_fields(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Point {}

class Figure {
    public new(public points: Point[]) {}
}
"""
            )
        )

        self.assertNotIn("this->points = (ForgeArray_Point){0, 0, NULL};", source)
        self.assertIn("this->points = points;", source)
        self.assertIn(
            "for (size_t _forge_i = 0; _forge_i < value->points.len; _forge_i += 1)",
            source,
        )
        self.assertIn("_forge_free_Point(value->points.data[_forge_i]);", source)
        self.assertIn("free(value->points.data);", source)

    def test_backend_emits_destructor_for_struct_declarations(self) -> None:
        source = emit_c(
            parse(
                """
struct Banner {
    public title: String
}
"""
            )
        )

        self.assertIn("void _forge_free_Banner(struct Banner* value)", source)
        self.assertIn("free(value);", source)

    def test_backend_destructor_frees_struct_string_fields_and_arrays(self) -> None:
        source = emit_c(
            parse(
                """
struct User {
    public name: String
    public tags: String[]
}
"""
            )
        )

        self.assertIn("free((void*)value->name);", source)
        self.assertIn("for (size_t _forge_i = 0; _forge_i < value->tags.len; _forge_i += 1)", source)
        self.assertIn("free((void*)value->tags.data[_forge_i]);", source)
        self.assertIn("free(value->tags.data);", source)

    def test_frees_temporary_string_concat_after_statement(self) -> None:
        source = emit_c(parse('main(): Void { print "a" + "b" + "c" }'))

        self.assertIn('char* forge_tmp_string0 = _forge_string_concat(3, "a", "b", "c");', source)
        self.assertIn('printf("%s\\n", forge_tmp_string0);', source)
        self.assertIn("free(forge_tmp_string0);", source)

    def test_frees_owned_string_local_initialized_from_concat(self) -> None:
        source = emit_c(
            parse(
                """
main(): Void {
    const text: String = "a" + "b"
    print text
}
"""
            )
        )

        self.assertIn('char* text = forge_tmp_string0;', source)
        self.assertIn("free((void*)text);\n    return 0;", source)

    def test_struct_literal_string_field_consumes_owned_value(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
struct Response {
    public body: String
}

class Helper {
    public static render(): String {
        return "ok" + ""
    }
}

make(): Response {
    const response: Response = {
        body: Helper.render()
    }
    return response
}
"""
            )
        )

        make_source = source[source.index("struct Response make(void)") :]
        self.assertIn(
            "struct Response response = (struct Response){.body = Helper_render()};",
            make_source,
        )
        self.assertNotIn("free(", make_source)

    def test_emits_primitive_to_string_helpers_and_cleanup(self) -> None:
        source = emit_c(
            parse(
                """
main(value: Int, enabled: Bool): Void {
    print value.toString()
    print enabled.toString()
}
"""
            )
        )

        self.assertIn("static char* _forge_Int_to_string(int value)", source)
        self.assertIn("static char* _forge_bool_to_string(bool value)", source)
        self.assertIn("char* forge_tmp_string0 = _forge_Int_to_string(value);", source)
        self.assertIn('printf("%s\\n", forge_tmp_string0);', source)
        self.assertIn("free(forge_tmp_string0);", source)
        self.assertIn("free(forge_tmp_string1);", source)

    def test_does_not_free_owned_class_local_returned_from_function(self) -> None:
        source = emit_c(
            parse(
                """
class User {}
make(): User {
    const user: User = User.new()
    return move user
}
"""
            )
        )

        self.assertIn(
            """struct User* make(void) {
    struct User* user = User_new();
    return user;
}""",
            source,
        )

    def test_emits_native_static_method_call_without_wrapper(self) -> None:
        source = emit_c(
            parse(
                """
class Native {
    public static native answer(): Int = "native_answer"
}

main(): Int {
    return Native.answer()
}
"""
            )
        )

        self.assertIn("return native_answer();", source)
        self.assertNotIn("Native_answer", source)

    def test_emits_awaited_async_native_static_method_call(self) -> None:
        source = emit_c(
            parse(
                """
class Native {
    public static async native answer(value: Int): Int = "native_answer"
}

async mainAsync(): Int {
    return await Native.answer(41)
}

main(): Int {
    return mainAsync().await()
}
"""
            )
        )

        self.assertIn("int native_answer(int);", source)
        self.assertIn(".arg0 = 41;", source)
        self.assertIn("return forge_tmp_async_context", source)
        self.assertIn(".result;", source)

    def test_emits_task_bulk_call_for_async_native_static_method(self) -> None:
        source = emit_c(
            parse(
                """
class Native {
    public static async native answer(value: Int): Int = "native_answer"
}

async mainAsync(): Int {
    const values = [1, 2]
    const results = await (Native.answer task[values]).all()
    return results[0] + results[1]
}

main(): Int {
    return mainAsync().await()
}
"""
            )
        )

        self.assertIn(".arg0 = values.data[_forge_i];", source)
        self.assertIn("ForgeArray_Int_push(&forge_tmp_tasks", source)

    def test_emits_multi_file_project_as_separate_c_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Helper").mkdir()
            (root / "Helper" / "StringHelper.forge").write_text(
                """
class

public static hello(name: String): String {
    return "Hello, " + name
}
"""
            )
            (root / "main.forge").write_text(
                """
use Helper.StringHelper

main(): Void {
    print StringHelper.hello("World")
}
"""
            )
            output = root / "c"

            result = emit_c_project(root / "main.forge", output)

            self.assertEqual(
                {path.relative_to(output).as_posix() for path in result.sources},
                {"forge_runtime.c", "Helper/StringHelper.c", "main.c"},
            )
            self.assertEqual(
                {path.relative_to(output).as_posix() for path in result.headers},
                {"Helper/StringHelper.h", "main.h"},
            )
            self.assertTrue(result.runtime_header.exists())
            self.assertTrue(result.runtime_source.exists())
            self.assertIn(
                "char* _forge_string_concat(size_t count, ...);",
                result.runtime_header.read_text(),
            )
            self.assertIn(
                "void* _forge_array_new(size_t capacity, size_t element_size);",
                result.runtime_header.read_text(),
            )
            self.assertIn(
                "void _forge_array_grow(void** data, size_t* cap, size_t element_size);",
                result.runtime_header.read_text(),
            )
            self.assertIn(
                "typedef struct _ForgeAsyncTask _ForgeAsyncTask;",
                result.runtime_header.read_text(),
            )
            self.assertIn(
                "_ForgeAsyncTask* _forge_async_task_new(_forge_async_job_fn run, void* context);",
                result.runtime_header.read_text(),
            )
            self.assertEqual(result.link_flags, () if sys.platform == "win32" else ("-pthread",))
            self.assertIn(
                "char* _forge_string_concat(size_t count, ...)",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                "void* _forge_array_new(size_t capacity, size_t element_size)",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                "void _forge_array_grow(void** data, size_t* cap, size_t element_size)",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                "static void* _forge_async_worker_run(void* unused)",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                "#ifdef _WIN32",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                "CreateThread(NULL, 0, _forge_async_worker_run, NULL, 0, NULL)",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                "SleepConditionVariableCS(&_forge_async_work_cond",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                "pthread_create(&worker, NULL, _forge_async_worker_run, NULL)",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                "pthread_cond_wait(&_forge_async_work_cond",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                "void _forge_async_task_await(_ForgeAsyncTask* task)",
                result.runtime_source.read_text(),
            )
            self.assertIn(
                'char* Helper_StringHelper_hello(const char* name);',
                (output / "Helper" / "StringHelper.h").read_text(),
            )
            self.assertIn(
                '#include "Helper/StringHelper.h"',
                result.header.read_text(),
            )
            self.assertIn(
                '#include "StringHelper.h"',
                (output / "Helper" / "StringHelper.c").read_text(),
            )
            self.assertNotIn(
                '#include "../forge_project.h"',
                (output / "Helper" / "StringHelper.c").read_text(),
            )
            self.assertIn(
                '#include "../forge_runtime.h"',
                (output / "Helper" / "StringHelper.c").read_text(),
            )
            self.assertNotIn(
                "char* _forge_string_concat(size_t count, ...)",
                (output / "Helper" / "StringHelper.c").read_text(),
            )
            self.assertIn(
                "Helper_StringHelper_hello(\"World\")",
                (output / "main.c").read_text(),
            )
            self.assertIn(
                '#include "Helper/StringHelper.h"',
                (output / "main.c").read_text(),
            )
            self.assertNotIn(
                '#include "forge_project.h"',
                (output / "main.c").read_text(),
            )

    def test_project_c_names_include_namespace_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app").mkdir()
            (root / "legacy").mkdir()
            (root / "app" / "User.forge").write_text("class {}")
            (root / "legacy" / "User.forge").write_text("class {}")
            (root / "main.forge").write_text("main(): Void {}")

            result = emit_c_project(root / "main.forge", root / "c")
            header = result.header.read_text()

            self.assertIn('#include "app/User.h"', header)
            self.assertIn('#include "legacy/User.h"', header)
            self.assertIn("struct app_User {", (root / "c" / "app" / "User.h").read_text())
            self.assertIn(
                "struct legacy_User {",
                (root / "c" / "legacy" / "User.h").read_text(),
            )
            self.assertNotIn("struct app_User {", (root / "c" / "app" / "User.c").read_text())
            self.assertNotIn(
                "struct legacy_User {",
                (root / "c" / "legacy" / "User.c").read_text(),
            )

    def test_project_headers_include_imported_class_headers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Profile.forge").write_text("class\npublic name: String\n")
            (root / "User.forge").write_text(
                """
use Profile

class

public profile: Profile?
public setProfile(take profile: Profile): Void {
    this.profile = profile
}
"""
            )
            (root / "main.forge").write_text(
                """
use Profile
use User

main(): Void {
    var profile: Profile = Profile.new()
    var user: User = User.new()
    user.setProfile(move profile)
}
"""
            )

            emit_c_project(root / "main.forge", root / "c")

            self.assertIn('#include "Profile.h"', (root / "c" / "User.h").read_text())

    def test_project_emits_dependency_package_sources_and_native_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "packages" / "nativepkg" / "src").mkdir(parents=True)
            (root / "packages" / "nativepkg" / "include").mkdir(parents=True)
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"

[dependencies]
nativepkg = "1.0.0"
"""
            )
            (root / "forge.lock").write_text('nativepkg = "1.0.0"\n')
            (root / "src" / "main.forge").write_text(
                """
use nativepkg.Math

main(): Int {
    return Math.answer()
}
"""
            )
            (root / "packages" / "nativepkg" / "forge.toml").write_text(
                """
[package]
name = "nativepkg"
version = "1.0.0"

[native]
includes = ["native_math.h"]
include_dirs = ["include"]
libraries = ["native_math"]
"""
            )
            (root / "packages" / "nativepkg" / "include" / "native_math.h").write_text(
                "int native_answer(void);\n"
            )
            (root / "packages" / "nativepkg" / "src" / "Math.forge").write_text(
                """
class

public static native answer(): Int = "native_answer"
"""
            )

            result = emit_c_project(root, root / "c")

            self.assertEqual(result.native_includes, ("native_math.h",))
            self.assertEqual(result.include_dirs, ((root / "c").resolve(),))
            self.assertTrue((root / "c" / "native_math.h").exists())
            self.assertEqual(result.libraries, ("native_math",))
            self.assertEqual(
                {path.relative_to(root / "c").as_posix() for path in result.sources},
                {"forge_runtime.c", "main.c", "nativepkg/Math.c"},
            )
            self.assertIn('#include "native_math.h"', (root / "c" / "main.c").read_text())
            self.assertIn('#include "nativepkg/Math.h"', (root / "c" / "main.c").read_text())
            self.assertIn("return native_answer();", (root / "c" / "main.c").read_text())
            self.assertIn('#include "nativepkg/Math.h"', result.header.read_text())

    def test_project_emits_bundled_std_package_sources_and_native_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"

[dependencies]
std = "0.1.0"
"""
            )
            (root / "forge.lock").write_text('std = "0.1.0"\n')
            (root / "src" / "main.forge").write_text(
                """
use std.Http.Http

main(): Bool {
    return true
}
"""
            )

            result = emit_c_project(root, root / "c")

            self.assertEqual(
                result.native_includes,
                ("forge_std_net.h", "forge_std_string.h"),
            )
            self.assertEqual(result.include_dirs, ((root / "c").resolve(),))
            self.assertTrue((root / "c" / "forge_std_net.h").exists())
            self.assertTrue((root / "c" / "forge_std_string.h").exists())
            self.assertTrue(any(path == root / "c" / "native" / "forge_std_net.c" for path in result.sources))
            self.assertTrue(any(path == root / "c" / "native" / "forge_std_string.c" for path in result.sources))
            self.assertTrue(any(path == root / "c" / "native" / "forge_std_json.c" for path in result.sources))
            generated_sources = {
                path.relative_to(root / "c").as_posix()
                for path in result.sources
                if path.is_relative_to(root / "c")
            }
            self.assertIn("std/Http/Http.c", generated_sources)
            self.assertIn("std/Http/HttpServer.c", generated_sources)
            self.assertIn('#include "forge_std_net.h"', (root / "c" / "main.c").read_text())
            self.assertIn('#include "forge_std_string.h"', (root / "c" / "main.c").read_text())
            self.assertIn('#include "std/Http/Http.h"', result.header.read_text())
            http_server_source = (root / "c" / "std" / "Http" / "HttpServer.c").read_text()
            self.assertIn("free((void*)request);", http_server_source)

    def test_emits_declared_outcome_result_abi_and_catch(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class DivisionByZero {}
class Calculator {
    public static divide(a: Int, b: Int): Int, !DivisionByZero {
        if b == 0 {
            return DivisionByZero.new()
        }
        return a / b
    }
}
main(): Void {
    const result: Int = catch Calculator.divide(10, 0) {
        issue: DivisionByZero => 42
    }
    print result
}
"""
            )
        )

        self.assertIn("typedef enum {\n    ForgeResult_Int_DivisionByZero_SUCCESS = 0,", source)
        self.assertIn("typedef struct {\n    uint8_t tag;\n    int success;", source)
        self.assertIn("struct DivisionByZero* outcome_DivisionByZero;", source)
        self.assertIn("ForgeResult_Int_DivisionByZero Calculator_divide", source)
        self.assertIn(
            "return (ForgeResult_Int_DivisionByZero){.tag = "
            "ForgeResult_Int_DivisionByZero_OUTCOME_DIVISIONBYZERO",
            source,
        )
        self.assertIn("ForgeResult_Int_DivisionByZero forge_tmp_outcome0 = Calculator_divide(10, 0);", source)

    def test_outcome_return_reads_owned_local_before_cleanup(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Issue {}
class Response {
    public new(public status: Int) {}
}
status(): Int, !Issue {
    const response = Response.new(204)
    return response.status
}
"""
            )
        )

        self.assertIn("ForgeResult_Int_Issue forge_tmp_return", source)
        self.assertIn("forge_tmp_return", source)
        self.assertIn("= (ForgeResult_Int_Issue){.tag = ForgeResult_Int_Issue_SUCCESS, .success = response->status};", source)
        self.assertLess(source.index("response->status"), source.index("_forge_free_Response(response);"))

    def test_string_local_assignment_keeps_owned_result_alive(self) -> None:
        source = emit_c(
            parse(
                """
append(): Void {
    var raw = ""
    raw = raw + "x"
    raw = raw + "y"
    print raw
}
"""
            )
        )

        self.assertIn('char* forge_tmp_string0 = _forge_string_copy("");', source)
        self.assertIn("char* raw = forge_tmp_string0;", source)
        first_concat = source.index('char* forge_tmp_string1 = _forge_string_concat(2, raw, "x");')
        first_free = source.index("free((void*)raw);")
        first_assign = source.index("raw = forge_tmp_string1;")
        second_concat = source.index('char* forge_tmp_string2 = _forge_string_concat(2, raw, "y");')
        second_free = source.index("free((void*)raw);", first_free + 1)
        second_assign = source.index("raw = forge_tmp_string2;")
        final_free = source.rindex("free((void*)raw);")
        self.assertLess(first_concat, first_free)
        self.assertLess(first_free, first_assign)
        self.assertLess(first_assign, second_concat)
        self.assertLess(second_concat, second_free)
        self.assertLess(second_free, second_assign)
        self.assertLess(second_assign, final_free)
        self.assertNotIn("free(forge_tmp_string1);", source)
        self.assertNotIn("free(forge_tmp_string2);", source)

    def test_emits_forward_for_declared_outcome_call(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class ParseIssue {}
class Parser {
    public static parse(): Int, !ParseIssue {
        return 1
    }
}
parseAgain(): Int, !ParseIssue {
    return forward Parser.parse()
}
"""
            )
        )

        self.assertIn("ForgeResult_Int_ParseIssue parseAgain(void)", source)
        self.assertIn("ForgeResult_Int_ParseIssue forge_tmp_outcome0 = Parser_parse();", source)
        self.assertIn("if (forge_tmp_outcome0.tag == ForgeResult_Int_ParseIssue_OUTCOME_PARSEISSUE)", source)
        self.assertIn(
            "return (ForgeResult_Int_ParseIssue){.tag = "
            "ForgeResult_Int_ParseIssue_OUTCOME_PARSEISSUE",
            source,
        )
        self.assertIn(".success = forge_tmp_outcome0.success", source)

    def test_emits_default_policy_for_ignored_optional_outcome(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class AllocFailed {}
class Array {
    public static reserve(size: Int): Void, ?AllocFailed {}
}
main(): Void {
    Array.reserve(1000)
}
"""
            )
        )

        self.assertIn("ForgeResult_Void_AllocFailed forge_tmp_outcome0 = Array_reserve(1000);", source)
        self.assertIn("return (ForgeResult_Void_AllocFailed){.tag = ForgeResult_Void_AllocFailed_SUCCESS};", source)
        self.assertIn("if (forge_tmp_outcome0.tag != ForgeResult_Void_AllocFailed_SUCCESS)", source)
        self.assertIn("abort();", source)

    def test_forward_maps_outcome_into_current_superset_signature(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class ParseIssue {}
class IoIssue {}
class Parser {
    public static parse(): Int, !ParseIssue {
        return 1
    }
}
parseAgain(): Int, !ParseIssue, !IoIssue {
    return forward Parser.parse()
}
"""
            )
        )

        self.assertIn("ForgeResult_Int_ParseIssue forge_tmp_outcome0 = Parser_parse();", source)
        self.assertIn("ForgeResult_Int_ParseIssue_IoIssue parseAgain(void)", source)
        self.assertIn(
            "return (ForgeResult_Int_ParseIssue_IoIssue){.tag = "
            "ForgeResult_Int_ParseIssue_IoIssue_OUTCOME_PARSEISSUE",
            source,
        )

    def test_emits_forward_partial_catch(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class ParseIssue {}
class IoIssue {}
class Parser {
    public static parse(): Int, !ParseIssue, !IoIssue {
        return IoIssue.new()
    }
}
parseAgain(): Int, !IoIssue {
    return forward catch Parser.parse() {
        issue: ParseIssue => 10
    }
}
"""
            )
        )

        self.assertIn("ForgeResult_Int_ParseIssue_IoIssue forge_tmp_outcome", source)
        self.assertIn(" = Parser_parse();", source)
        self.assertIn("ForgeResult_Int_IoIssue forge_tmp_outcome", source)
        self.assertIn("= (ForgeResult_Int_IoIssue){.tag = ForgeResult_Int_IoIssue_SUCCESS, .success = 10};", source)
        self.assertIn(
            "= (ForgeResult_Int_IoIssue){.tag = "
            "ForgeResult_Int_IoIssue_OUTCOME_IOISSUE",
            source,
        )
        self.assertIn("return (ForgeResult_Int_IoIssue){.tag = ForgeResult_Int_IoIssue_OUTCOME_IOISSUE", source)

    def test_forwarded_outcome_cleans_owned_locals_before_return(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Issue {}
class Resource {}
class Parser {
    public static fail(): Int, !Issue {
        return Issue.new()
    }
}
load(): Int, !Issue {
    const resource = Resource.new()
    return forward Parser.fail()
}
"""
            )
        )

        return_index = source.index("return forge_tmp_return")
        self.assertIn("_forge_free_Resource(resource);", source[:return_index])
        self.assertLess(source.index("_forge_free_Resource(resource);"), return_index)

    def test_forwarded_outcome_cleans_owned_struct_string_fields_before_return(self) -> None:
        source = emit_c(
            parse(
                """
@multidef
class Issue {}
class Parser {
    public static parse(): String, !Issue {
        return Issue.new()
    }
}
struct Banner {
    public title: String
    public text: String
}
load(): Banner, !Issue {
    var result: Banner = {}
    result.title = forward Parser.parse()
    result.text = forward Parser.parse()
    return result
}
"""
            )
        )

        second_return = source.index("return forge_tmp_return", source.index("result.title"))
        before_second_return = source[:second_return]
        self.assertIn("free((void*)result.title);", before_second_return)
        self.assertNotIn("free((void*)result.text);", before_second_return)

    def test_project_emits_outcome_result_abi_only_in_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Issue.forge").write_text("class {}")
            (root / "Parser.forge").write_text(
                """
use Issue

class

public static parse(): Int, !Issue {
    return 1
}
"""
            )
            (root / "main.forge").write_text(
                """
use Issue
use Parser

main(): Int {
    return catch Parser.parse() {
        issue: Issue => 2
    }
}
"""
            )

            emit_c_project(root / "main.forge", root / "c")

            parser_h = (root / "c" / "Parser.h").read_text()
            parser_c = (root / "c" / "Parser.c").read_text()
            main_c = (root / "c" / "main.c").read_text()

        self.assertIn("typedef enum {\n    ForgeResult_Int_Issue_SUCCESS = 0,", parser_h)
        self.assertIn("typedef struct {\n    uint8_t tag;", parser_h)
        self.assertIn("ForgeResult_Int_Issue Parser_parse(void);", parser_h)
        self.assertNotIn("typedef struct {\n    uint8_t tag;", parser_c)
        self.assertNotIn("typedef struct {\n    uint8_t tag;", main_c)
        self.assertIn("ForgeResult_Int_Issue forge_tmp_outcome0 = Parser_parse();", main_c)

    def test_emits_existing_loops_as_value_producing_expressions(self) -> None:
        source = emit_c(
            parse(
                """
main(): Int {
    const fromFor = for [1, 2] as item {
        if item == 2 {
            break item
        }
    } else 0
    const fromWhile = while true {
        break 7
    } else 0
    const fromDo = do {
        break
    } while true else 5
    return fromFor + fromWhile + fromDo
}
"""
            )
        )

        self.assertIn("bool forge_tmp_loop_has_value", source)
        self.assertIn("for (int forge_tmp_loop_index", source)
        self.assertIn("while (true)", source)
        self.assertIn("do {", source)
        self.assertIn("if (!forge_tmp_loop_has_value", source)

    def test_emits_loop_fallback_prelude_inside_fallback_branch(self) -> None:
        source = emit_c(
            parse(
                """
value(): String {
    return while true {
        break "selected"
    } else ("a" + "b")
}
"""
            )
        )

        function = source[source.index("char* value(void)") :]
        fallback_branch = function.index("if (!forge_tmp_loop_has_value")
        fallback_concat = function.index("_forge_string_concat")
        self.assertLess(fallback_branch, fallback_concat)

    def test_returned_loop_result_preserves_take_owned_source(self) -> None:
        source = emit_c(
            parse(
                """
class File {}

pick(take file: File): File? {
    return while true {
        break file
    }
}
"""
            )
        )

        function = source[source.index("struct File* pick(") :]
        transfer = function.index("file = NULL;")
        cleanup = function.index("_forge_free_File(file);")
        self.assertLess(transfer, cleanup)

    def test_returned_loop_result_transfers_each_possible_owned_source(self) -> None:
        source = emit_c(
            parse(
                """
class File {}

pick(flag: Bool, take first: File, take second: File): File? {
    return while flag {
        switch flag {
            true => {
                break first
            }
            default => {
                break second
            }
        }
    } else second
}
"""
            )
        )

        function = source[source.index("struct File* pick(") :]
        self.assertRegex(function, r"forge_tmp_loop_result\d+ = first;\s+first = NULL;")
        self.assertEqual(function.count(" = second;"), 2)
        self.assertEqual(function.count("second = NULL;"), 2)
        self.assertIn("_forge_free_File(first);", function)
        self.assertIn("_forge_free_File(second);", function)

    def test_conditional_loop_result_transfers_only_selected_owned_source(self) -> None:
        source = emit_c(
            parse(
                """
class File {}

pick(flag: Bool, take first: File, take second: File): File? {
    return while false {
        break null
    } else (flag ? first : second)
}
"""
            )
        )

        function = source[source.index("struct File* pick(") :]
        self.assertIn("bool forge_tmp_loop_choice", function)
        self.assertRegex(function, r"forge_tmp_loop_result\d+ = first;\s+first = NULL;")
        self.assertRegex(function, r"forge_tmp_loop_result\d+ = second;\s+second = NULL;")
        self.assertLess(function.index("first = NULL;"), function.index("_forge_free_File(first);"))
        self.assertLess(function.index("second = NULL;"), function.index("_forge_free_File(second);"))

    def test_loop_condition_prelude_is_emitted_inside_each_condition_check(self) -> None:
        source = emit_c(
            parse(
                """
value(): Int {
    var index = 0
    return while (while false { break false } else index < 2) {
        index++
    } else index
}
"""
            )
        )

        function = source[source.index("int value(void)") :]
        loop = function.index("while (true)")
        nested_condition = function.index("bool forge_tmp_loop_has_value", loop)
        body = function.index("index++;")
        self.assertLess(loop, nested_condition)
        self.assertLess(nested_condition, body)

    def test_nullable_string_loop_local_is_cleaned_up(self) -> None:
        source = emit_c(
            parse(
                """
value(): Void {
    const result: String? = while true {
        break "selected"
    }
    print result
}
"""
            )
        )

        function = source[source.index("void value(void)") :]
        self.assertIn("char* result = forge_tmp_loop_result", function)
        self.assertIn("free((void*)result);", function)

    def test_loop_fallback_cleans_temporary_values_inside_guard(self) -> None:
        source = emit_c(
            parse(
                """
value(): String {
    return while false {
        break "selected"
    } else ("n=" + 42)
}
"""
            )
        )

        function = source[source.index("char* value(void)") :]
        guard = function.index("if (!forge_tmp_loop_has_value")
        conversion = function.index("_forge_Int_to_string")
        assignment = function.index("forge_tmp_loop_result", conversion)
        cleanup = function.index("free(forge_tmp_string", assignment)
        self.assertLess(guard, conversion)
        self.assertLess(conversion, assignment)
        self.assertLess(assignment, cleanup)

    def test_emits_builtin_string_intrinsics_and_array_result_cleanup(self) -> None:
        source = emit_c(
            parse(
                """
parts(): String[] {
    return "a,b".split(",", 2)
}

exercise(): Void {
    const local = "a,b".split(",", 2)
    print "a,b".split(",", 2).len
    "abc".toBytes()
    print String.fromInt("42".parseInt())
}
"""
            )
        )

        self.assertIn('return forge_string_split("a,b", ",", 2);', source)
        self.assertIn('ForgeArray_String local = forge_string_split("a,b", ",", 2);', source)
        self.assertIn('forge_string_from_int(forge_string_parse_int("42"))', source)
        self.assertRegex(
            source,
            r'ForgeArray_String forge_tmp_array\d+ = forge_string_split\("a,b", ",", 2\);',
        )
        self.assertRegex(
            source,
            r'ForgeArray_Byte forge_tmp_array\d+ = forge_string_to_bytes\("abc"\);',
        )
        self.assertIn("free((void*)local.data[_forge_i]);", source)
        self.assertIn("free(local.data);", source)
        self.assertRegex(source, r"free\(forge_tmp_array\d+\.data\);")

    def test_string_array_temporaries_transfer_before_cleanup(self) -> None:
        source = emit_c(
            parse(
                """
exercise(flag: Bool): Void {
    const decoded: String = flag ? String.fromBytes("abc".toBytes()) : ""
    var decodedAgain = "old"
    decodedAgain = flag ? String.fromBytes("next".toBytes()) : "fallback"
    const first = "a,b".split(",", 2)[0]
    const selected = flag ? "a,b".split(",", 2) : "c,d".split(",", 2)
    const nestedFirst = (flag ? "nested-left,x".split(",", 2) : "nested-right,y".split(",", 2))[0]
    print (flag ? "one,two".split(",", 2) : "three".split(",", 2)).len
    const fallback = ["fallback"]
    const mixed = flag ? "owned,x".split(",", 2) : fallback
    var reassigned = "old".split(",", 2)
    reassigned = "new,value".split(",", 2)
    print decoded
    print first
    print selected[0]
    print nestedFirst
    print mixed[0]
    print reassigned[0]
}

chooseMixed(flag: Bool, fallback: String[]): String[] {
    return flag ? "return-owned,x".split(",", 2) : fallback
}

chooseBorrowed(flag: Bool, left: String[], right: String[]): String[] {
    return flag ? left : right
}

chooseBytes(flag: Bool, fallback: Byte[]): Byte[] {
    return flag ? "bytes".toBytes() : fallback
}
"""
            )
        )

        decoded_create = source.index('forge_string_to_bytes("abc")')
        decoded_consume = source.index("forge_string_from_bytes(", decoded_create)
        decoded_cleanup = source.index(".data);", decoded_consume)
        self.assertLess(decoded_create, decoded_consume)
        self.assertLess(decoded_consume, decoded_cleanup)

        reassigned_string_create = source.index('forge_string_to_bytes("next")')
        reassigned_string_consume = source.index(
            "forge_string_from_bytes(",
            reassigned_string_create,
        )
        old_string_cleanup = source.index(
            "free((void*)decodedAgain);",
            reassigned_string_consume,
        )
        reassigned_string_store = source.index(
            "decodedAgain = forge_tmp_string",
            old_string_cleanup,
        )
        self.assertLess(reassigned_string_create, reassigned_string_consume)
        self.assertLess(reassigned_string_consume, old_string_cleanup)
        self.assertLess(old_string_cleanup, reassigned_string_store)

        indexed_array = source.index('forge_string_split("a,b", ",", 2)')
        indexed_copy = source.index("_forge_string_copy(", indexed_array)
        indexed_cleanup = source.index("free((void*)forge_tmp_array", indexed_copy)
        self.assertLess(indexed_array, indexed_copy)
        self.assertLess(indexed_copy, indexed_cleanup)

        selected_declaration = source.index("ForgeArray_String selected;")
        selected_branch = source.index("selected = forge_string_split", selected_declaration)
        selected_cleanup = source.index("free(selected.data);", selected_branch)
        self.assertLess(selected_branch, selected_cleanup)

        nested_left = source.index('forge_string_split("nested-left,x", ",", 2)')
        nested_right = source.index('forge_string_split("nested-right,y", ",", 2)')
        nested_copy = source.index("_forge_string_copy(", nested_right)
        self.assertIn("if (flag) {", source[:nested_left])
        self.assertIn("} else {", source[nested_left:nested_right])
        self.assertLess(nested_right, nested_copy)
        self.assertNotIn(" ? ", source[nested_left:nested_copy])
        self.assertRegex(
            source,
            r'printf\("%d\\n", \(int\)forge_tmp_array\d+\.len\);',
        )

        mixed_if = source.index("if (flag) {", nested_copy)
        mixed_owned = source.index('forge_string_split("owned,x", ",", 2)', mixed_if)
        mixed_else = source.index("} else {", mixed_owned)
        mixed_copy = source.index("_forge_string_copy(", mixed_else)
        self.assertLess(mixed_if, mixed_owned)
        self.assertLess(mixed_owned, mixed_else)
        self.assertLess(mixed_else, mixed_copy)
        self.assertNotIn('forge_string_split("owned,x", ",", 2)', source[:mixed_if])

        replacement_create = source.index(
            'forge_string_split("new,value", ",", 2)'
        )
        old_cleanup = source.index("free(reassigned.data);", replacement_create)
        replacement_assign = source.index("reassigned = forge_tmp_array_replacement", old_cleanup)
        self.assertLess(replacement_create, old_cleanup)
        self.assertLess(old_cleanup, replacement_assign)

        mixed_return = source[source.index("ForgeArray_String chooseMixed") :]
        self.assertNotIn("return fallback;", mixed_return.split("}", 1)[0])
        self.assertIn("ForgeArray_String forge_tmp_array", mixed_return)
        self.assertIn("_forge_string_copy(", mixed_return)

        borrowed_return = source[source.index("ForgeArray_String chooseBorrowed") :]
        self.assertIn("_forge_string_copy(", borrowed_return)
        self.assertNotIn("return left;", borrowed_return.split("}", 1)[0])
        self.assertNotIn("return right;", borrowed_return.split("}", 1)[0])

        byte_return = source[source.index("ForgeArray_Byte chooseBytes") :]
        self.assertIn("ForgeArray_Byte_push", byte_return)
        self.assertNotIn("return fallback;", byte_return.split("}", 1)[0])


if __name__ == "__main__":
    unittest.main()
