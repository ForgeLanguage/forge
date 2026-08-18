import tempfile
import unittest
from pathlib import Path

from forge_c import emit_c_project
from forge_templates import expand_template_sources, expand_templates
from forge_templates.expander import TemplateExpansionError

DI_CONTAINER_SOURCE = (Path(__file__).resolve().parents[1] / "stdlib" / "std" / "src" / "Di" / "DiContainer.forge").read_text()


class TemplateExpansionTests(unittest.TestCase):
    def test_expands_nongeneric_template_function_in_place(self) -> None:
        expanded = expand_templates(
            """
public template func answer(): Int {
    return 42
}

const value = answer()
""",
            source_name="main.forge",
        )

        self.assertNotIn("template func", expanded)
        self.assertIn("public func answer(): Int", expanded)
        self.assertIn("const value = answer()", expanded)

    def test_expands_struct_property_loop_into_specialized_function(self) -> None:
        expanded = expand_templates(
            """
struct User {
    public name: String
    public age: Int
}

public template func parse<T:struct>(reader: Reader): T {
    let result: T = {}
    #for Reflection.type<T>().properties as property {
        result.#{property.name} = Reader.get#{property.type}(reader, "#{property.name}")
    #}
    return result
}

const user = parse<User>(Reader.new())
const other = parse<User>(Reader.new())
""",
            source_name="main.forge",
        )

        self.assertNotIn("template func", expanded)
        self.assertEqual(expanded.count("public func parse__User(reader: Reader): User"), 1)
        self.assertIn('result.name = Reader.getString(reader, "name")', expanded)
        self.assertIn('result.age = Reader.getInt(reader, "age")', expanded)
        self.assertIn("const user = parse__User(Reader.new())", expanded)
        self.assertIn("const other = parse__User(Reader.new())", expanded)

    def test_expands_member_template_from_another_source(self) -> None:
        expanded = expand_template_sources(
            (
                (
                    "lib/Box.forge",
                    """
class

public static template func make<T:struct>(reader: Reader): T {
    let result: T = {}
    #for Reflection.type<T>().properties as property {
        result.#{property.name} = Reader.get#{property.type}(reader, "#{property.name}")
    #}
    return result
}
""",
                ),
                (
                    "main.forge",
                    """
struct User {
    public name: String
    public age: Int
}

const user = Box.make<User>(Reader.new())
""",
                ),
            )
        )

        self.assertNotIn("template func", expanded["lib/Box.forge"])
        self.assertIn("Box_make__User", expanded["main.forge"])
        self.assertIn("const user = Box_make__User(Reader.new())", expanded["main.forge"])
        self.assertIn("func Box_make__User(reader: Reader): User", expanded["main.forge"])
        self.assertIn('result.name = Reader.getString(reader, "name")', expanded["main.forge"])

    def test_expands_class_constructor_parameter_loop(self) -> None:
        expanded = expand_templates(
            """
class Foo {}

class Bar {
    public new(public take foo: Foo, public name: String) {}
}

template func create<T:class>(container: DiContainer): T {
    return T.new(
    #for Reflection.type<T>().constructor.parameters as parameter {
        #{parameter.separator}#{parameter.movePrefix}container.resolve#{parameter.type}()
    #}
    )
}

const bar = create<Bar>(DiContainer.new())
""",
            source_name="main.forge",
        )

        self.assertIn("func create__Bar(container: DiContainer): Bar", expanded)
        self.assertIn("move container.resolveFoo()", expanded)
        self.assertIn(",container.resolveString()", expanded)
        self.assertIn("const bar = create__Bar(DiContainer.new())", expanded)

    def test_class_template_rejects_struct_argument(self) -> None:
        with self.assertRaisesRegex(Exception, "Template expected class 'User'"):
            expand_templates(
                """
struct User {
    public name: String
}

template func create<T:class>(): T {
    return T.new()
}

const user = create<User>()
""",
                source_name="main.forge",
            )

    def test_template_panic_stops_expansion_with_message(self) -> None:
        with self.assertRaisesRegex(
            TemplateExpansionError,
            "Cannot build A",
        ):
            expand_templates(
                """
class A {
    public new() {}
}

template func create<T:class>(): T {
    #panic "Cannot build #{Reflection.type<T>().name}"
    return T.new()
}

const value = create<A>()
""",
                source_name="main.forge",
            )

    def test_expands_interface_implementation_loop(self) -> None:
        expanded = expand_templates(
            """
@multidef
interface Service {
    public func name(): String
}

class First {
    implements Service
    public func name(): String => "first"
}

class Second {
    implements Service
    public func name(): String => "second"
}

template func all<T:interface>(): T[] {
    return [
    #for Reflection.type<T>().implementations as implementation {
        #{implementation.separator}make#{implementation.type}()
    #}
    ]
}

const services = all<Service>()
""",
            source_name="main.forge",
        )

        self.assertIn("func all__Service(): Service[]", expanded)
        self.assertIn("makeFirst()", expanded)
        self.assertIn(",makeSecond()", expanded)
        self.assertIn("const services = all__Service()", expanded)

    def test_reflects_type_arguments_on_struct_fields(self) -> None:
        expanded = expand_templates(
            """
@multidef
struct Definition<T> {}
struct Defs {
    public logger: Definition<Logger>
}
class Logger {}
template func services<T:struct>(): String {
    return ""
    #for Reflection.type<T>().properties as field {
    const #{field.name}Name = "#{field.type.arguments[0].name}"
    #}
}
const names = services<Defs>()
""",
            source_name="main.forge",
        )

        self.assertIn('const loggerName = "Logger"', expanded)

    def test_expands_template_used_as_bulk_map(self) -> None:
        expanded = expand_templates(
            """
struct User {
    public name: String
}

template func decode<T:struct>(value: String): T {
    const result: T = {}
    return result
}

const values = ["first", "second"]
const users = decode<User>[values]
""",
            source_name="main.forge",
        )

        self.assertIn("func decode__User(value: String): User", expanded)
        self.assertIn("const users = decode__User[values]", expanded)
        self.assertNotIn("decode<User>", expanded)

    def test_stateful_template_shares_state_per_receiver_config(self) -> None:
        expanded = expand_templates(
            """
class Builder {
    public new() {}

    #state compiled: Bool = false

    public template func apply<T:struct>(): Void {
        #{
            if state.compiled {
                Compiler.error("already compiled")
            }
        #}
    }

    public template func compile(): Void {
        #{
            state.compiled = true
        #}
    }
}

struct Core {}
struct Http {}

const app = Builder.new()
app.apply<Core>()
app.compile()
""",
            source_name="main.forge",
        )

        self.assertIn("Builder_apply__Core__Config_1()", expanded)
        self.assertIn("Builder_compile__nongeneric__Config_1()", expanded)
        self.assertIn("Builder_apply__Core__Config_1()", expanded)

    def test_stateful_template_rejects_apply_after_compile_same_receiver(self) -> None:
        with self.assertRaisesRegex(TemplateExpansionError, "already compiled"):
            expand_templates(
                """
class Builder {
    public new() {}

    #state compiled: Bool = false

    public template func apply<T:struct>(): Void {
        #{
            if state.compiled {
                Compiler.error("already compiled")
            }
        #}
    }

    public template func compile(): Void {
        #{
            state.compiled = true
        #}
    }
}

struct Core {}

const app = Builder.new()
app.compile()
app.apply<Core>()
""",
                source_name="main.forge",
            )

    def test_stateful_template_uses_separate_state_for_separate_receivers(self) -> None:
        expanded = expand_templates(
            """
class Builder {
    public new() {}

    #state compiled: Bool = false

    public template func apply<T:struct>(): Void {
        #{
            if state.compiled {
                Compiler.error("already compiled")
            }
        #}
    }

    public template func compile(): Void {
        #{
            state.compiled = true
        #}
    }
}

struct Core {}

const app = Builder.new()
const worker = Builder.new()
app.compile()
worker.apply<Core>()
""",
            source_name="main.forge",
        )

        self.assertIn("Builder_compile__nongeneric__Config_1", expanded)
        self.assertIn("Builder_apply__Core__Config_2", expanded)

    def test_stateful_template_alias_shares_receiver_state(self) -> None:
        with self.assertRaisesRegex(TemplateExpansionError, "already compiled"):
            expand_templates(
                """
class Builder {
    public new() {}

    #state compiled: Bool = false

    public template func apply<T:struct>(): Void {
        #{
            if state.compiled {
                Compiler.error("already compiled")
            }
        #}
    }

    public template func compile(): Void {
        #{
            state.compiled = true
        #}
    }
}

struct Core {}

const app = Builder.new()
const alias = app
app.compile()
alias.apply<Core>()
""",
                source_name="main.forge",
            )

    def test_stateful_template_rejects_unknown_receiver_config(self) -> None:
        with self.assertRaisesRegex(
            TemplateExpansionError,
            "Stateful template invocation requires a compile-time-resolvable receiver configuration",
        ):
            expand_templates(
                """
class Builder {
    #state compiled: Bool = false
    public template func compile(): Void {
        #{
            state.compiled = true
        #}
    }
}

const app = createBuilder()
app.compile()
""",
                source_name="main.forge",
            )

    def test_stateful_template_rejects_runtime_control_flow(self) -> None:
        with self.assertRaisesRegex(
            TemplateExpansionError,
            "compile-time deterministic control flow",
        ):
            expand_templates(
                """
class Builder {
    public new() {}
    #state compiled: Bool = false
    public template func compile(): Void {
        #{
            state.compiled = true
        #}
    }
}

const app = Builder.new()
if runtimeFlag {
    app.compile()
}
""",
                source_name="main.forge",
            )

    def test_stateful_template_graph_find_cycle_reports_compiler_error(self) -> None:
        with self.assertRaisesRegex(TemplateExpansionError, "Circular dependency: A -> B -> A"):
            expand_templates(
                """
class Builder {
    public new() {}
    #state graph: Dict<String, String[]> = {}

    public template func registerCycle(): Void {
        #{
            state.graph["A"] = ["B"]
            state.graph["B"] = ["A"]
        #}
    }

    public template func compile(): Void {
        #{
            const cycle = Graph.findCycle(state.graph)
            if cycle != null {
                const path = cycle.join(" -> ")
                Compiler.error("Circular dependency: #{path}")
            }
        #}
    }
}

const app = Builder.new()
app.registerCycle()
app.compile()
""",
                source_name="main.forge",
            )

    def test_di_container_apply_build_resolve_uses_independent_receiver_state(self) -> None:
        expanded = expand_template_sources(
            (
                ("stdlib/std/src/Di/DiContainer.forge", DI_CONTAINER_SOURCE),
                (
                    "main.forge",
                    """
@multidef
struct Definition<T> {}

struct AppDefs {
    public logger: Definition<Logger>
    public service: Definition<Service>
}

struct WorkerDefs {
    public workerLogger: Definition<WorkerLogger>
}

class Logger {}
class Service {
    public new(public take logger: Logger) {}
}
class WorkerLogger {}

const app = DiContainer.new()
const appDefs: AppDefs = {}
app.apply<AppDefs>(appDefs)
app.build()
const logger = app.resolve<Logger>()
const service = app.resolve<Service>()

const worker = DiContainer.new()
const workerDefs: WorkerDefs = {}
worker.apply<WorkerDefs>(workerDefs)
worker.build()
const workerLogger = worker.resolve<WorkerLogger>()
""",
                ),
            )
        )

        main = expanded["main.forge"]
        self.assertIn("DiContainer_apply__AppDefs__Config_1(appDefs)", main)
        self.assertIn("DiContainer_build__nongeneric__Config_1()", main)
        self.assertIn("DiContainer_resolve__Logger__Config_1()", main)
        self.assertIn("DiContainer_resolve__Service__Config_1()", main)
        self.assertIn("DiContainer_apply__WorkerDefs__Config_2(workerDefs)", main)
        self.assertIn("DiContainer_build__nongeneric__Config_2()", main)
        self.assertIn("DiContainer_resolve__WorkerLogger__Config_2()", main)
        self.assertIn("func DiContainer_resolve__Logger__Config_1(): Logger", main)
        self.assertIn("return Logger.new(", main)
        self.assertIn("return Service.new(move Logger.new())", main)

    def test_di_container_build_reports_missing_dependency(self) -> None:
        with self.assertRaisesRegex(TemplateExpansionError, "Missing dependency for Service: Logger"):
            expand_template_sources(
                (
                    ("stdlib/std/src/Di/DiContainer.forge", DI_CONTAINER_SOURCE),
                    (
                        "main.forge",
                        """
@multidef
struct Definition<T> {}

struct AppDefs {
    public service: Definition<Service>
}

class Logger {}
class Service {
    public new(public take logger: Logger) {}
}

const app = DiContainer.new()
const defs: AppDefs = {}
app.apply<AppDefs>(defs)
app.build()
""",
                    ),
                )
            )

    def test_di_container_build_reports_circular_dependency(self) -> None:
        with self.assertRaisesRegex(TemplateExpansionError, "Circular dependency: A -> B -> A"):
            expand_template_sources(
                (
                    ("stdlib/std/src/Di/DiContainer.forge", DI_CONTAINER_SOURCE),
                    (
                        "main.forge",
                        """
@multidef
struct Definition<T> {}

struct AppDefs {
    public a: Definition<A>
    public b: Definition<B>
}

class A {
    public new(public take b: B) {}
}

class B {
    public new(public take a: A) {}
}

const app = DiContainer.new()
const defs: AppDefs = {}
app.apply<AppDefs>(defs)
app.build()
""",
                    ),
                )
            )

    def test_di_container_rejects_apply_after_build(self) -> None:
        with self.assertRaisesRegex(TemplateExpansionError, "Cannot register services after DI build"):
            expand_template_sources(
                (
                    ("stdlib/std/src/Di/DiContainer.forge", DI_CONTAINER_SOURCE),
                    (
                        "main.forge",
                        """
@multidef
struct Definition<T> {}

struct AppDefs {
    public logger: Definition<Logger>
}

class Logger {}

const app = DiContainer.new()
const defs: AppDefs = {}
app.apply<AppDefs>(defs)
app.build()
app.apply<AppDefs>(defs)
""",
                    ),
                )
            )

    def test_project_compiles_template_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "main.forge").write_text(
                """
@multidef
class Reader {
    public new() {}

    public static func getString(reader: Reader, name: String): String => name
    public static func getInt(reader: Reader, name: String): Int => 42
}

struct User {
    public name: String
    public age: Int
}

template func parse<T:struct>(reader: Reader): T {
    let result: T = {}
    #for Reflection.type<T>().properties as property {
        result.#{property.name} = Reader.get#{property.type}(reader, "#{property.name}")
    #}
    return result
}

func main(): Void {
    const reader = Reader.new()
    const user = parse<User>(reader)
    print user.name
    print user.age
}
"""
            )

            result = emit_c_project(root / "src" / "main.forge", root / "c")
            main_c = (root / "c" / "main.c").read_text()

        self.assertIn("parse__User", main_c)
        self.assertTrue(result.sources)

    def test_project_compiles_nongeneric_template_function(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "main.forge").write_text(
                """
template func answer(): Int {
    return 42
}

func main(): Void {
    print answer()
}
"""
            )

            result = emit_c_project(root / "src" / "main.forge", root / "c")
            main_c = (root / "c" / "main.c").read_text()

        self.assertIn("int answer(void)", main_c)
        self.assertTrue(result.sources)


if __name__ == "__main__":
    unittest.main()
