import tempfile
import unittest
from pathlib import Path

from forge_c import emit_c_project
from forge_templates import expand_template_sources, expand_templates


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
