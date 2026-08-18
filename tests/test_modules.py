import tempfile
import unittest
from pathlib import Path

from forge_modules import load_project


class ModuleTests(unittest.TestCase):
    def test_loads_project_files_with_namespaces_and_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src" / "app").mkdir(parents=True)
            (root / "src" / "utils").mkdir(parents=True)
            (root / "src" / "app" / "User.forge").write_text("class {}")
            (root / "src" / "utils" / "StringUtils.forge").write_text("class {}")

            project = load_project(root)

        self.assertTrue(project.ok)
        self.assertEqual(len(project.files), 2)
        self.assertEqual(set(project.symbols), {"app.User", "utils.StringUtils"})
        self.assertEqual(project.symbols["app.User"].short_name, "User")
        self.assertEqual(project.symbols["app.User"].namespace, ("app",))

    def test_loads_project_enum_symbols_with_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src" / "app").mkdir(parents=True)
            (root / "src" / "app" / "Status.forge").write_text(
                "public enum Status : Int { Ok => 0 }"
            )

            project = load_project(root)

        self.assertTrue(project.ok)
        self.assertIn("app.Status", project.symbols)
        self.assertEqual(project.symbols["app.Status"].short_name, "Status")
        self.assertEqual(project.symbols["app.Status"].namespace, ("app",))

    def test_collects_use_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src" / "app").mkdir(parents=True)
            (root / "src" / "app" / "App.forge").write_text(
                "use utils.StringUtils\nuse legacy.User\nclass {}"
            )

            project = load_project(root)

        source_file = project.files[0]
        self.assertEqual(source_file.namespace, ("app",))
        self.assertEqual(len(source_file.imports), 2)
        self.assertEqual(source_file.imports[0].path, ("utils", "StringUtils"))
        self.assertEqual(source_file.imports[1].path, ("legacy", "User"))

    def test_reports_duplicate_full_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src" / "app").mkdir(parents=True)
            (root / "src" / "app" / "One.forge").write_text("@multidef\nclass User {}")
            (root / "src" / "app" / "Two.forge").write_text("@multidef\nclass User {}")

            project = load_project(root)

        self.assertFalse(project.ok)
        self.assertEqual(
            project.diagnostics[0].message,
            "Duplicate top-level symbol 'app.User'",
        )

    def test_loads_manifest_dependencies_and_package_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "packages" / "http" / "src" / "client").mkdir(parents=True)
            (root / "packages" / "http" / "include").mkdir(parents=True)
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"
packages_path = "./packages/"

[dependencies]
http = "1.2.0"
"""
            )
            (root / "forge.lock").write_text('http = "1.2.0"\n')
            (root / "src" / "main.forge").write_text(
                "use http.client.Request\nmain(): Void {}"
            )
            (root / "packages" / "http" / "forge.toml").write_text(
                """
[package]
name = "http"
version = "1.2.0"

[native]
includes = ["http_native.h"]
include_dirs = ["include"]
libraries = ["http_native"]
"""
            )
            (root / "packages" / "http" / "src" / "client" / "Request.forge").write_text("class {}")

            project = load_project(root)

        self.assertTrue(project.ok, project.diagnostics)
        self.assertEqual(project.dependencies, {"http": "1.2.0"})
        self.assertEqual(project.lock, {"http": "1.2.0"})
        self.assertEqual(project.packages[0].name, "http")
        self.assertEqual(project.packages[0].version, "1.2.0")
        self.assertIn("http.client.Request", project.symbols)
        package_file = next(source for source in project.files if source.package == "http")
        self.assertEqual(package_file.namespace, ("http", "client"))
        self.assertEqual(package_file.program.source_name, "http/client/Request.forge")
        self.assertEqual(project.native.includes, ("http_native.h",))
        self.assertIn((root / "packages" / "http" / "include").resolve(), project.native.include_dirs)
        self.assertEqual(project.native.sources, ())
        self.assertEqual(project.native.libraries, ("http_native",))

    def test_loads_bundled_std_dependency_when_local_package_is_absent(self) -> None:
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
use std.Net.Network
use std.Net.TcpStream
use std.Http.Http
use std.Json.Json

main(): Bool {
    return true
}
"""
            )

            project = load_project(root)

        self.assertTrue(project.ok, project.diagnostics)
        self.assertEqual(project.dependencies, {"std": "0.1.0"})
        self.assertEqual(project.packages[0].name, "std")
        self.assertIn("std.Net.Network", project.symbols)
        self.assertIn("std.Net.TcpStream", project.symbols)
        self.assertIn("std.Http.Http", project.symbols)
        self.assertIn("std.Json.Json", project.symbols)
        self.assertEqual(
            project.native.includes,
            ("forge_std_net.h", "forge_std_string.h"),
        )
        self.assertIn(project.packages[0].root / "include", project.native.include_dirs)
        self.assertIn(project.packages[0].root / "native" / "forge_std_net.c", project.native.sources)
        self.assertIn(project.packages[0].root / "native" / "forge_std_string.c", project.native.sources)
        self.assertIn(project.packages[0].root / "native" / "forge_std_json.c", project.native.sources)

    def test_loads_native_package_sources_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "packages" / "nativepkg" / "src").mkdir(parents=True)
            (root / "packages" / "nativepkg" / "native").mkdir(parents=True)
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"

[dependencies]
nativepkg = "1.0.0"
"""
            )
            (root / "forge.lock").write_text('nativepkg = "1.0.0"\n')
            (root / "src" / "main.forge").write_text("main(): Void {}")
            (root / "packages" / "nativepkg" / "forge.toml").write_text(
                """
[package]
name = "nativepkg"
version = "1.0.0"

[native]
sources = ["native/nativepkg.c"]
"""
            )

            project = load_project(root)

        self.assertTrue(project.ok, project.diagnostics)
        self.assertEqual(
            project.native.sources,
            ((root / "packages" / "nativepkg" / "native" / "nativepkg.c").resolve(),),
        )

    def test_reports_lock_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "packages" / "http" / "src").mkdir(parents=True)
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"

[dependencies]
http = "1.2.0"
"""
            )
            (root / "forge.lock").write_text('http = "2.0.0"\n')
            (root / "src" / "main.forge").write_text("main(): Void {}")
            (root / "packages" / "http" / "forge.toml").write_text(
                """
[package]
name = "http"
version = "1.2.0"
"""
            )

            project = load_project(root)

        self.assertFalse(project.ok)
        self.assertIn(
            "forge.lock version for 'http' is '2.0.0', expected '1.2.0'",
            [diagnostic.message for diagnostic in project.diagnostics],
        )


if __name__ == "__main__":
    unittest.main()
