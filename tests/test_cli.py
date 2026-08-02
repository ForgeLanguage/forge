import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORGE = PROJECT_ROOT / "bin" / "forge"


class ForgeCliTests(unittest.TestCase):
    def connect_to_process(self, process: subprocess.Popen[str], port: int) -> socket.socket:
        last_error: OSError | None = None
        for _ in range(100):
            try:
                return socket.create_connection(("127.0.0.1", port), timeout=0.2)
            except OSError as exc:
                last_error = exc
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    self.fail(
                        f"server exited with {process.returncode}: stdout={stdout!r} stderr={stderr!r}"
                    )
                threading.Event().wait(0.05)
        self.fail(f"server did not listen on port {port}: {last_error}")

    def terminate_process(self, process: subprocess.Popen[str]) -> None:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def test_translate_writes_c_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.forge"
            source.write_text("const myVar: Int = 5")

            result = subprocess.run(
                [str(FORGE), "translate", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "int myVar = 5;\n")
        self.assertEqual(result.stderr, "")

    def test_translate_can_write_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.forge"
            output = Path(directory) / "sample.c"
            source.write_text("const value: Int = 7")

            subprocess.run(
                [str(FORGE), "translate", str(source), "-o", str(output)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertEqual(output.read_text(), "int value = 7;\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_compile_generates_c_and_binary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            c_output = Path(directory) / "c"
            binary = Path(directory) / "app"
            source.write_text('func main(): Void { print "compiled" }')

            result = subprocess.run(
                [
                    str(FORGE),
                    "compile",
                    str(source),
                    "-o",
                    str(binary),
                    "--c-out",
                    str(c_output),
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertEqual(result.stdout, f"{binary}\n")
            self.assertTrue((c_output / "app.c").exists())
            self.assertTrue(binary.exists())
            compile_commands = json.loads((c_output / "compile_commands.json").read_text())
            files = {Path(entry["file"]).name for entry in compile_commands}
            self.assertIn("forge_runtime.c", files)
            self.assertIn("app.c", files)
            app_command = next(
                entry["arguments"]
                for entry in compile_commands
                if Path(entry["file"]).name == "app.c"
            )
            self.assertEqual(next(entry["directory"] for entry in compile_commands), ".")
            self.assertFalse(Path(next(entry["file"] for entry in compile_commands)).is_absolute())
            self.assertIn("-D_POSIX_C_SOURCE=200112L", app_command)
            self.assertIn("-D_DARWIN_C_SOURCE", app_command)
            self.assertIn("-O2", app_command)
            self.assertIn("-DNDEBUG", app_command)
            self.assertIn("-c", app_command)

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_compiles_without_optimizations_and_runs_binary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text('func main(): Void { print "Hello from Forge" }')

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "Hello from Forge\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_async_function_with_sync_await_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
async func answer(): Int => 42
func main(): Void {
    print answer().await()
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "42\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_sync_async_twins_select_by_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
func read(path: String): String => "sync"
async func read(path: String): String => "async"
func main(): Void {
    print read("file.txt")
    print read("file.txt").await()
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "sync\nasync\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_async_only_function_generates_sync_call_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
async func read(path: String): String => "async"
func main(): Void {
    const text: String = read("file.txt")
    print text
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "async\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_async_native_await_uses_runtime_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"

[native]
includes = ["stdlib.h"]
"""
            )
            (root / "src" / "main.forge").write_text(
                """
async native func absValue(value: Int): Int = "abs"
func main(): Void {
    print absValue(-7).await()
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "7\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_saved_async_native_task_await_uses_runtime_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"

[native]
includes = ["stdlib.h"]
"""
            )
            (root / "src" / "main.forge").write_text(
                """
async native func absValue(value: Int): Int = "abs"
func main(): Void {
    const pending = absValue(-7)
    print pending.await()
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "7\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_string_methods(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "include").mkdir()
            (root / "native").mkdir()
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"

[native]
includes = ["nul_bytes.h"]
include_dirs = ["include"]
sources = ["native/nul_bytes.c"]

[dependencies]
std = "0.1.0"
"""
            )
            (root / "forge.lock").write_text('std = "0.1.0"\n')
            (root / "include" / "nul_bytes.h").write_text(
                """
#pragma once
#include <stddef.h>
#ifndef FORGEARRAY_BYTE_DEFINED
#define FORGEARRAY_BYTE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    signed char* data;
} ForgeArray_Byte;
#endif
ForgeArray_Byte bytes_with_nul(void);
"""
            )
            (root / "native" / "nul_bytes.c").write_text(
                """
#include "forge_runtime.h"
#include "nul_bytes.h"

ForgeArray_Byte bytes_with_nul(void) {
    ForgeArray_Byte result;
    result.len = 3;
    result.cap = 3;
    result.data = _forge_array_new(3, sizeof(signed char));
    result.data[0] = 'A';
    result.data[1] = 0;
    result.data[2] = 'B';
    return result;
}
"""
            )
            (root / "src" / "main.forge").write_text(
                """
native func bytesWithNul(): Byte[] = "bytes_with_nul"

func chooseStrings(flag: Bool, fallback: String[]): String[] {
    return flag ? "owned-return,x".split(",", 2) : fallback
}

func chooseBorrowed(flag: Bool, left: String[], right: String[]): String[] {
    return flag ? left : right
}

func chooseBytes(flag: Bool, fallback: Byte[]): Byte[] {
    return flag ? "byte-return".toBytes() : fallback
}

func main(): Void {
    print "Forge".length()
    print "".isEmpty()
    print "abc".indexOf("")
    print "abc".contains("")
    print "abc".startsWith("")
    print "abc".endsWith("")
    print "abcdef".substring(-4, -1)
    print "abcdef".substring(-99, 2)
    print "abcdef".substring(4, -1)
    print "abcdef".substring(-1, -4)
    print "\\t  Forge \\r\\n".trim()
    print "ÉA".toLowerCase()
    print "éa".toUpperCase()
    print "aaaa".replace("aa", "b")
    print "abc".replace("", "x")
    const parts = "a,,b,".split(",", 2147483647)
    print parts.len
    print parts[0]
    print parts[1]
    print parts[2]
    print parts[3]
    const limited = "one|two|three|four".split("|", 2)
    print limited.len
    print limited[0]
    print limited[1]
    const zeroLimit = "one|two".split("|", 0)
    print zeroLimit.len
    print zeroLimit[0]
    const negativeLimit = "one|two|three|four".split("|", -2)
    print negativeLimit.len
    print negativeLimit[0]
    print negativeLimit[1]
    const allExcluded = "one|two".split("|", -2)
    print allExcluded.len
    const minimumLimit = "one|two".split("|", -2147483647 - 1)
    print minimumLimit.len
    const unsplit = "a,b".split("", 2)
    print unsplit.len
    print unsplit[0]
    print "a,b".split("", -1).len
    print "  -42tail".parseInt()
    print "no digits".parseInt()
    print "999999999999999999999".parseInt()
    print "-999999999999999999999".parseInt()
    const bytes = "bytes".toBytes()
    print bytes.len
    print String.fromBytes(bytes)
    print String.fromBytes(bytesWithNul())
    print String.fromInt(-17)
    const decoded: String = true ? String.fromBytes("ok".toBytes()) : "bad"
    print decoded
    let decodedAgain = "old"
    decodedAgain = true ? String.fromBytes("next".toBytes()) : "bad"
    print decodedAgain
    const first = "first,second".split(",", 2)[0]
    print first
    const selected = true ? "left,right".split(",", 2) : "wrong".split(",", 2)
    print selected[1]
    const nestedFirst = (true ? "nested,yes".split(",", 2) : "wrong,no".split(",", 2))[0]
    print nestedFirst
    print (true ? "one,two".split(",", 2) : "wrong".split(",", 2)).len
    const fallback = ["fallback"]
    const mixedOwned = true ? "owned,x".split(",", 2) : fallback
    const mixedBorrowed = false ? "wrong,x".split(",", 2) : fallback
    print mixedOwned[0]
    print mixedBorrowed[0]
    const returnedOwned = chooseStrings(true, fallback)
    const returnedBorrowed = chooseStrings(false, fallback)
    const other = ["other"]
    const returnedAllBorrowed = chooseBorrowed(false, fallback, other)
    print returnedOwned[0]
    print returnedBorrowed[0]
    print returnedAllBorrowed[0]
    const fallbackBytes = "fallback-bytes".toBytes()
    const returnedBytesOwned = chooseBytes(true, fallbackBytes)
    const returnedBytesBorrowed = chooseBytes(false, fallbackBytes)
    print String.fromBytes(returnedBytesOwned)
    print String.fromBytes(returnedBytesBorrowed)
    let reassigned = "old".split(",", 2)
    reassigned = "new,value".split(",", 2)
    print reassigned[1]
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "5\n"
            "1\n"
            "0\n"
            "1\n"
            "1\n"
            "1\n"
            "cde\n"
            "ab\n"
            "e\n"
            "\n"
            "Forge\n"
            "Éa\n"
            "éA\n"
            "bb\n"
            "abc\n"
            "4\n"
            "a\n"
            "\n"
            "b\n"
            "\n"
            "2\n"
            "one\n"
            "two|three|four\n"
            "1\n"
            "one|two\n"
            "2\n"
            "one\n"
            "two\n"
            "0\n"
            "0\n"
            "1\n"
            "a,b\n"
            "0\n"
            "-42\n"
            "0\n"
            "2147483647\n"
            "-2147483648\n"
            "5\n"
            "bytes\n"
            "A\n"
            "-17\n"
            "ok\n"
            "next\n"
            "first\n"
            "right\n"
            "nested\n"
            "2\n"
            "owned\n"
            "fallback\n"
            "owned-return\n"
            "fallback\n"
            "other\n"
            "byte-return\n"
            "fallback-bytes\n"
            "value\n",
        )

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_net_connects_to_local_tcp_server(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            server.close()
            self.skipTest(f"Loopback sockets are not available: {exc}")
        server.listen(1)
        port = server.getsockname()[1]
        accepted: list[bool] = []

        def serve() -> None:
            try:
                connection, _ = server.accept()
                with connection:
                    accepted.append(True)
            finally:
                server.close()

        thread = threading.Thread(target=serve)
        thread.start()
        try:
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
                    f"""
use std.Net.Network
use std.Net.NetworkIssue

func main(): Void {{
    const stream = catch Network.connectTcp("127.0.0.1", {port}).await() {{
        issue: NetworkIssue => {{
            print issue.message
            return
        }}
    }}
    Network.close(stream)
    print "connected"
}}
"""
                )

                result = subprocess.run(
                    [str(FORGE), "run", str(root)],
                    cwd=PROJECT_ROOT,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=10,
                )
        finally:
            thread.join(timeout=5)

        self.assertEqual(result.stdout, "connected\n")
        self.assertEqual(accepted, [True])

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_http_gets_from_local_server(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            server.close()
            self.skipTest(f"Loopback sockets are not available: {exc}")
        server.listen(1)
        port = server.getsockname()[1]

        def serve() -> None:
            try:
                connection, _ = server.accept()
                with connection:
                    connection.recv(4096)
                    connection.sendall(
                        b"HTTP/1.0 204 No Content\r\n"
                        b"Content-Length: 5\r\n"
                        b"\r\n"
                        b"hello"
                    )
            finally:
                server.close()

        thread = threading.Thread(target=serve)
        thread.start()
        try:
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
                    f"""
use std.Http.Http
use std.Http.HttpIssue

func main(): Void {{
    const response = catch Http.get("http://127.0.0.1:{port}/test").await() {{
        issue: HttpIssue => {{
            print issue.message
            return
        }}
    }}
    print response.status
    print response.body
}}
"""
                )

                result = subprocess.run(
                    [str(FORGE), "run", str(root)],
                    cwd=PROJECT_ROOT,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=10,
                )
        finally:
            thread.join(timeout=5)

        self.assertEqual(result.stdout, "204\nhello\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_http_server_handles_loopback_request(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            probe.close()
            self.skipTest(f"Loopback sockets are not available: {exc}")
        port = probe.getsockname()[1]
        probe.close()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "server"
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
                f"""
use std.Http.HttpIssue
use std.Http.HttpServer
use std.Http.HttpServerHandler
use std.Http.HttpServerResponse

class EchoHandler {{
    implements HttpServerHandler

    public func handle(path: String, body: String): HttpServerResponse {{
        return HttpServerResponse.new(201, path + ":" + body)
    }}
}}

func main(): Void {{
    const handler: HttpServerHandler = EchoHandler.new()
    catch HttpServer.serve({port}, handler).await() {{
        issue: HttpIssue => {{
            print issue.message
            return
        }}
    }}
}}
"""
            )

            subprocess.run(
                [str(FORGE), "compile", str(root), "-o", str(binary)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )
            process = subprocess.Popen(
                [str(binary)],
                cwd=PROJECT_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                with self.connect_to_process(process, port) as abandoned:
                    abandoned.sendall(b"GET")

                with self.connect_to_process(process, port) as connection:
                    connection.sendall(
                        b"POST /echo HTTP/1.1\r\n"
                        b"Host: 127.0.0.1\r\n"
                        b"Content-Length: 5\r\n"
                        b"Connection: close\r\n"
                        b"\r\n"
                        b"hello"
                    )
                    chunks: list[bytes] = []
                    while True:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
            finally:
                self.terminate_process(process)

        raw = b"".join(chunks)
        head, body = raw.split(b"\r\n\r\n", 1)
        self.assertTrue(head.startswith(b"HTTP/1.1 201 "))
        self.assertIn(b"Content-Type: application/json", head)
        self.assertIn(b"Content-Length: 11", head)
        self.assertEqual(body, b"/echo:hello")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_json_reads_object_fields(self) -> None:
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
use std.Json.Json
use std.Json.JsonIssue

func title(): String, !JsonIssue {
    const value = forward Json.parse("{\\"banners\\":[{\\"title\\":\\"banner\\",\\"priceModel\\":1,\\"active\\":true}]}")
    const banners = forward Json.get(value, "banners")
    const count = forward Json.length(banners)
    const banner = forward Json.at(banners, 0)
    const title = forward Json.asString(forward Json.get(banner, "title"))
    const priceModel = forward Json.asInt(forward Json.get(banner, "priceModel"))
    const active = forward Json.asBool(forward Json.get(banner, "active"))
    if count == 1 && priceModel == 1 && active {
        return title
    }
    return "bad"
}

func main(): Void {
    const value = catch title() {
        issue: JsonIssue => {
            print issue.message
            return
        }
    }
    print value
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        self.assertEqual(result.stdout, "banner\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_json_parses_struct(self) -> None:
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
use std.Json.Json
use std.Json.JsonIssue

struct Banner {
    public title: String
    public priceModel: Int
    public active: Bool
}

func load(): Banner, !JsonIssue {
    return forward Json.parse<Banner>("{\\"title\\":\\"banner\\",\\"priceModel\\":1,\\"active\\":true}")
}

func main(): Void {
    const banner = catch load() {
        issue: JsonIssue => {
            print issue.message
            return
        }
    }
    print banner.title
    print banner.priceModel
    if banner.active {
        print "active"
    }
    else {
        print "inactive"
    }
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        self.assertEqual(result.stdout, "banner\n1\nactive\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_json_parses_nested_struct(self) -> None:
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
@multidef
use std.Json.Json
use std.Json.JsonIssue

struct User {
    public id: String
    public zoneId: Int
}

struct Request {
    public bannerId: Int
    public user: User
}

func load(): Request, !JsonIssue {
    return forward Json.parse<Request>("{\\"bannerId\\":42,\\"user\\":{\\"id\\":\\"u-1\\",\\"zoneId\\":10}}")
}

func main(): Void {
    const request = catch load() {
        issue: JsonIssue => {
            print issue.message
            return
        }
    }
    print request.bannerId
    print request.user.id
    print request.user.zoneId
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        self.assertEqual(result.stdout, "42\nu-1\n10\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_json_parses_int_array_field(self) -> None:
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
use std.Json.Json
use std.Json.JsonIssue

struct Request {
    public bannerIds: Int[]
}

func load(): Request, !JsonIssue {
    return forward Json.parse<Request>("{\\"bannerIds\\":[42,7]}")
}

func main(): Void {
    const request = catch load() {
        issue: JsonIssue => {
            print issue.message
            return
        }
    }
    print request.bannerIds.len
    print request.bannerIds[0]
    print request.bannerIds[1]
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        self.assertEqual(result.stdout, "2\n42\n7\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_json_parses_struct_array_field(self) -> None:
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
@multidef
use std.Json.Json
use std.Json.JsonIssue

struct Header {
    public name: String
    public value: String
}

struct Request {
    public headers: Header[]
}

func load(text: String): Request, !JsonIssue {
    return forward Json.parse<Request>(text)
}

func main(): Void {
    const request = catch load("{\\"headers\\":[{\\"name\\":\\"Accept\\",\\"value\\":\\"text/plain\\"},{\\"name\\":\\"X-Trace\\",\\"value\\":\\"trace-1\\"}]}") {
        issue: JsonIssue => {
            print issue.message
            return
        }
    }
    print request.headers.len
    print request.headers[0].name
    print request.headers[0].value
    print Json.stringify<Request>(request)

    const invalid = catch load("{\\"headers\\":[{\\"name\\":\\"Missing value\\"}]}") {
        issue: JsonIssue => {
            print issue.message
            return
        }
    }
    print invalid.headers.len
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        self.assertEqual(
            result.stdout,
            '2\nAccept\ntext/plain\n{"headers":[{"name":"Accept","value":"text/plain"},{"name":"X-Trace","value":"trace-1"}]}\nJSON field not found\n',
        )

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_json_stringifies_struct(self) -> None:
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
use std.Json.Json

struct Payload {
    public count: Int
    public active: Bool
}

func main(): Void {
    const payload: Payload = {
        count: 2,
        active: true
    }
    print Json.stringify<Payload>(payload)
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        self.assertEqual(result.stdout, '{"count":2,"active":true}\n')

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_json_stringifies_nested_structs_and_arrays(self) -> None:
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
@multidef
use std.Json.Json

struct User {
    public id: String
    public zoneId: Int
}

struct Item {
    public id: Int
}

struct Payload {
    public user: User
    public bannerIds: Int[]
    public items: Item[]
    public flags: Bool[]
}

func main(): Void {
    const user: User = {
        id: "u-1",
        zoneId: 10
    }
    const first: Item = { id: 42 }
    const second: Item = { id: 7 }
    const items: Item[] = [first, second]
    const payload: Payload = {
        user: user,
        bannerIds: [42, 7],
        items: items,
        flags: [true, false]
    }
    print Json.stringify<Payload>(payload)
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        self.assertEqual(
            result.stdout,
            '{"user":{"id":"u-1","zoneId":10},"bannerIds":[42,7],"items":[{"id":42},{"id":7}],"flags":[true,false]}\n',
        )

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_json_escapes_string_values(self) -> None:
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
use std.Json.Json

struct Payload {
    public text: String
}

func main(): Void {
    const payload: Payload = {
        text: "quote: \\" slash: \\\\ line:\\n tab:\\t"
    }
    print Json.writeString(payload.text)
    print Json.stringify<Payload>(payload)
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        escaped = '"quote: \\" slash: \\\\ line:\\n tab:\\t"'
        self.assertEqual(result.stdout, f"{escaped}\n{{\"text\":{escaped}}}\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_json_handles_nullable_struct_fields(self) -> None:
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
@multidef
use std.Json.Json
use std.Json.JsonIssue

struct User {
    public id: String
}

struct Payload {
    public user: User?
}

func load(text: String): Payload, !JsonIssue {
    return forward Json.parse<Payload>(text)
}

func main(): Void {
    const user: User = { id: "u-1" }
    const present: Payload = { user: user }
    const missing: Payload = { user: null }
    print Json.stringify<Payload>(present)
    print Json.stringify<Payload>(missing)

    const parsedPresent = catch load("{\\"user\\":{\\"id\\":\\"u-2\\"}}") {
        issue: JsonIssue => {
            print issue.message
            return
        }
    }
    if parsedPresent.user {
        print parsedPresent.user.id
    }

    const parsedMissing = catch load("{\\"user\\":null}") {
        issue: JsonIssue => {
            print issue.message
            return
        }
    }
    if parsedMissing.user {
        print "bad"
    } else {
        print "none"
    }
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        self.assertEqual(
            result.stdout,
            '{"user":{"id":"u-1"}}\n{"user":null}\nu-2\nnone\n',
        )

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_bundled_std_http_statuses_can_be_aggregated(self) -> None:
        routes = {
            "/ok": 200,
            "/created": 201,
            "/missing": 404,
            "/error": 500,
        }
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            server.close()
            self.skipTest(f"Loopback sockets are not available: {exc}")
        server.listen(len(routes))
        server.settimeout(10)
        port = server.getsockname()[1]

        def serve() -> None:
            try:
                for _ in routes:
                    try:
                        connection, _ = server.accept()
                    except TimeoutError:
                        return
                    with connection:
                        request = connection.recv(4096).decode("ascii", errors="ignore")
                        path = request.split(" ", 2)[1]
                        status = routes[path]
                        connection.sendall(
                            f"HTTP/1.0 {status} Test\r\n"
                            "Content-Length: 0\r\n"
                            "\r\n"
                        .encode("ascii"))
            finally:
                server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
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
                    f"""
use std.Http.Http
use std.Http.HttpIssue

async func safeStatus(url: String): Int {{
    return catch await Http.status(url) {{
        issue: HttpIssue => 0
    }}
}}

func main(): Void {{
    const urls = [
        "http://127.0.0.1:{port}/ok",
        "http://127.0.0.1:{port}/created",
        "http://127.0.0.1:{port}/missing",
        "http://127.0.0.1:{port}/error",
    ]
    const statuses = (safeStatus task[urls]).all().await()
    let ok = 0
    let missing = 0
    let serverError = 0
    let other = 0
    let i = 0
    while i < 4 {{
        const status = statuses[i]
        if status >= 200 && status < 300 {{
            ok = ok + 1
        }}
        if status == 404 {{
            missing = missing + 1
        }}
        if status >= 500 {{
            serverError = serverError + 1
        }}
        if status == 0 {{
            other = other + 1
        }}
        i = i + 1
    }}
    print ok
    print missing
    print serverError
    print other
}}
"""
                )

                result = subprocess.run(
                    [str(FORGE), "run", str(root)],
                    cwd=PROJECT_ROOT,
                    env={**os.environ, "FORGE_ASYNC_THREADS": "128"},
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=60,
                )
        finally:
            thread.join(timeout=12)

        self.assertEqual(result.stdout, "2\n1\n1\n0\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_feedor_http_driver_maps_local_http_statuses(self) -> None:
        statuses = [200, 204, 429, 500]
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            server.close()
            self.skipTest(f"Loopback sockets are not available: {exc}")
        server.listen(len(statuses))
        server.settimeout(10)
        port = server.getsockname()[1]

        def serve() -> None:
            try:
                for status in statuses:
                    try:
                        connection, _ = server.accept()
                    except TimeoutError:
                        return
                    with connection:
                        connection.recv(4096)
                        connection.sendall(
                            f"HTTP/1.0 {status} Test\r\n"
                            "Content-Length: 0\r\n"
                            "\r\n"
                        .encode("ascii"))
            finally:
                server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                package_root = root / "packages" / "Feedor"
                (root / "src").mkdir(parents=True)
                (package_root).mkdir(parents=True)
                shutil.copytree(PROJECT_ROOT / "Feedor" / "src" / "Feedor", package_root / "src")
                (package_root / "forge.toml").write_text(
                    """
[package]
name = "Feedor"
version = "0.1.0"
"""
                )
                (root / "forge.toml").write_text(
                    """
entry_point = "./src/main.forge"
packages_path = "./packages/"

[dependencies]
Feedor = "0.1.0"
std = "0.1.0"
"""
                )
                (root / "forge.lock").write_text('Feedor = "0.1.0"\nstd = "0.1.0"\n')
                (root / "src" / "main.forge").write_text(
                    f"""
use Feedor.ClientHints
use Feedor.FeedorApp
use Feedor.FeedDriver
use Feedor.FeedRequest
use Feedor.HttpFeedDriver
use Feedor.User

func makeUser(): User {{
    const user: User = {{
        userAgent: "Forge HTTP driver",
        ip: "127.0.0.1",
        id: "user-1",
        acceptLang: "en",
        createdTimestamp: 0,
        domain: "example.test",
        geoCode: 1,
        zoneId: 10,
        userActivity: 0,
        osId: 1,
        viewsCount: 0,
        iframeStatus: 0
    }}
    return user
}}

func makeHints(): ClientHints {{
    const hints: ClientHints = {{
        osVersion: "macOS",
        model: "desktop"
    }}
    return hints
}}

func makeRequest(bannerId: Int): FeedRequest {{
    const request: FeedRequest = {{
        bannerId: bannerId,
        sourceSystem: "forge-http-driver",
        traceId: "trace-http",
        user: makeUser(),
        count: 1,
        referrer: "https://example.test",
        zoneId: 10,
        timeoutMs: 1000,
        pubVar: "pub-var",
        subscriptionId: 1,
        siteCategoryId: 0,
        clientHints: makeHints(),
        ruid: "ruid-1",
        batteryLevel: 1.0,
        batteryOnCharge: true,
        var3: ""
    }}
    return request
}}

func main(): Void {{
    const driver: FeedDriver = HttpFeedDriver.new("http://127.0.0.1:{port}/feed")
    const app = FeedorApp.new(driver)
    print app.getFeed(makeRequest(42)).await().status.coden
    print app.getFeed(makeRequest(7)).await().status.coden
    print app.getFeed(makeRequest(13)).await().status.coden
    print app.getFeed(makeRequest(500)).await().status.coden
}}
"""
                )

                result = subprocess.run(
                    [str(FORGE), "run", str(root)],
                    cwd=PROJECT_ROOT,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=30,
                )
        finally:
            thread.join(timeout=12)

        self.assertEqual(result.stdout, "2\n6\n13\n2\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_feedor_forge_server_endpoint(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", 8080))
        except OSError as exc:
            probe.close()
            self.skipTest(f"Feedor development port 8080 is unavailable: {exc}")
        probe.close()

        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "feedor"
            subprocess.run(
                [
                    str(FORGE),
                    "compile",
                    str(PROJECT_ROOT / "Feedor"),
                    "-o",
                    str(binary),
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )
            process = subprocess.Popen(
                [str(binary)],
                cwd=PROJECT_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                with self.connect_to_process(process, 8080) as connection:
                    connection.sendall(
                        b"GET /get_banner_list HTTP/1.1\r\n"
                        b"Host: 127.0.0.1\r\n"
                        b"Connection: close\r\n"
                        b"\r\n"
                    )
                    chunks: list[bytes] = []
                    while True:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
            finally:
                self.terminate_process(process)

        raw = b"".join(chunks)
        head, body = raw.split(b"\r\n\r\n", 1)
        self.assertTrue(head.startswith(b"HTTP/1.1 200 "))
        self.assertIn(b"Content-Type: application/json", head)
        self.assertEqual(body, b'{"count":0}')

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_feedor_http_handler_routes_simple_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_root = root / "packages" / "Feedor"
            (root / "src").mkdir(parents=True)
            package_root.mkdir(parents=True)
            shutil.copytree(PROJECT_ROOT / "Feedor" / "src" / "Feedor", package_root / "src")
            (package_root / "forge.toml").write_text(
                """
[package]
name = "Feedor"
version = "0.1.0"
"""
            )
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"
packages_path = "./packages/"

[dependencies]
Feedor = "0.1.0"
std = "0.1.0"
"""
            )
            (root / "forge.lock").write_text('Feedor = "0.1.0"\nstd = "0.1.0"\n')
            (root / "src" / "main.forge").write_text(
                """
use Feedor.FeedDriver
use Feedor.FeedorApp
use Feedor.HttpContract
use Feedor.HttpHandler
use Feedor.MockFeedDriver

func main(): Void {
    const driver: FeedDriver = MockFeedDriver.new()
    const app = FeedorApp.new(driver)
    const handler = HttpHandler.new(move app)

    const bannerList = handler.handle(HttpContract.getBannerListPath(), "")
    print bannerList.statusCode
    print bannerList.body

    const postback = handler.handle(
        HttpContract.postbackUrlPath(),
        "{\\"encodedPostbacks\\":\\"p\\",\\"traceId\\":\\"t\\",\\"bannerId\\":42,\\"userId\\":\\"u\\",\\"geo\\":\\"US\\",\\"zoneId\\":10,\\"extId\\":\\"e\\",\\"lang\\":\\"en\\",\\"userAgent\\":\\"ua\\",\\"ip\\":\\"127.0.0.1\\",\\"lifeTime\\":1,\\"externalId\\":\\"x\\",\\"subscriptionId\\":1,\\"createdTimestamp\\":0,\\"userActivity\\":0,\\"bidRevenue\\":1.25}"
    )
    print postback.statusCode
    print postback.body

    const winNotice = handler.handle(
        HttpContract.winNoticeUrlPath(),
        "{\\"winNoticeUrl\\":\\"https://example.test/win\\",\\"bannerId\\":-1}"
    )
    print winNotice.statusCode
    print winNotice.body

    const feed = handler.handle(
        HttpContract.getFeedPath(),
        "{\\"bannerId\\":42,\\"sourceSystem\\":\\"forge-handler\\",\\"traceId\\":\\"trace-feed\\",\\"user\\":{\\"userAgent\\":\\"ua\\",\\"ip\\":\\"127.0.0.1\\",\\"id\\":\\"u\\",\\"acceptLang\\":\\"en\\",\\"createdTimestamp\\":0,\\"domain\\":\\"example.test\\",\\"geoCode\\":1,\\"zoneId\\":10,\\"userActivity\\":0,\\"osId\\":1,\\"viewsCount\\":0,\\"iframeStatus\\":0},\\"count\\":1,\\"referrer\\":\\"https://example.test\\",\\"zoneId\\":10,\\"timeoutMs\\":1000,\\"origHeaders\\":[{\\"name\\":\\"X-Trace\\",\\"value\\":\\"trace-feed\\"}],\\"pubVar\\":\\"pub\\",\\"subscriptionId\\":1,\\"siteCategoryId\\":0,\\"clientHints\\":{\\"osVersion\\":\\"macOS\\",\\"model\\":\\"desktop\\"},\\"ruid\\":\\"ruid\\",\\"batteryLevel\\":1.0,\\"batteryOnCharge\\":true,\\"var3\\":\\"\\"}"
    )
    print feed.statusCode
    print feed.body

    const multi = handler.handle(
        HttpContract.getFeedMultiPath(),
        "{\\"bannerIds\\":[42,7],\\"sourceSystem\\":\\"forge-handler\\",\\"traceId\\":\\"trace-multi\\",\\"user\\":{\\"userAgent\\":\\"ua\\",\\"ip\\":\\"127.0.0.1\\",\\"id\\":\\"u\\",\\"acceptLang\\":\\"en\\",\\"createdTimestamp\\":0,\\"domain\\":\\"example.test\\",\\"geoCode\\":1,\\"zoneId\\":10,\\"userActivity\\":0,\\"osId\\":1,\\"viewsCount\\":0,\\"iframeStatus\\":0},\\"count\\":2,\\"referrer\\":\\"https://example.test\\",\\"zoneId\\":10,\\"timeoutMs\\":1000,\\"origHeaders\\":[{\\"name\\":\\"X-Trace\\",\\"value\\":\\"trace-multi\\"}],\\"pubVar\\":\\"pub\\",\\"subscriptionId\\":1,\\"siteCategoryId\\":0,\\"clientHints\\":{\\"osVersion\\":\\"macOS\\",\\"model\\":\\"desktop\\"},\\"ruid\\":\\"ruid\\",\\"batteryLevel\\":1.0,\\"batteryOnCharge\\":true,\\"var3\\":\\"\\"}"
    )
    print multi.statusCode
    print multi.body

    const missing = handler.handle("/missing", "")
    print missing.statusCode
    print missing.body

    const badFeed = handler.handle(HttpContract.getFeedPath(), "not-json")
    print badFeed.statusCode
    print badFeed.body
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )

        self.assertEqual(
            result.stdout,
            '200\n{"count":0}\n'
            '200\n{"accepted":true}\n'
            '200\n{"accepted":false}\n'
            '200\n{"status":{"code":0,"label":"OK","isError":false},"network":"mock","bannerId":42,'
            '"banner":{"title":"banner","text":"Mock banner","icon":"","image":"","url":"https://example.test/click",'
            '"externalId":"mock-42","winNoticeUrl":"","bidRevenue":1.5,"cpcPrice":0.1,"cpcCurrency":"USD",'
            '"priceModel":1,"encodedPostbacks":"","clickExpire":60,"maxBidRevenue":2,"badge":"","htmlAdmarkup":""},'
            '"extendedPostback":false}\n'
            '200\n{"count":2,"okCount":1,"noContentCount":1,"firstStatus":{"code":0,"label":"OK","isError":false}}\n'
            '404\n{"error":"not_found"}\n'
            '400\n{"error":"bad_request","message":"expected value"}\n',
        )

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_task_collection_all_sync_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
async func twice(value: Int): Int => value * 2
func main(): Void {
    const values = [1, 2]
    const doubled = (twice task[values]).all().await()
    print doubled[1]
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "4\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_for_statement_over_array(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
func main(): Void {
    const values = [1, 2, 3]
    let total = 0
    for values as value {
        total = total + value
    }
    print total
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "6\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_array_bulk_map_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
func twice(value: Int): Int => value * 2
func main(): Void {
    const values = [1, 2]
    const doubled = twice[values]
    print doubled[1]
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "4\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_async_native_task_collection_all_uses_runtime_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "forge.toml").write_text(
                """
entry_point = "./src/main.forge"

[native]
includes = ["stdlib.h"]
"""
            )
            (root / "src" / "main.forge").write_text(
                """
async native func absValue(value: Int): Int = "abs"
func main(): Void {
    const values = [-1, -2]
    const pending = absValue task[values]
    const results = pending.all().await()
    print results[1]
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "2\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_task_collection_scalar_methods_sync_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
async func twice(value: Int): Int => value * 2
func main(): Void {
    const values = [1, 2, 3]
    print (twice task[values]).first().await()
    print (twice task[values]).any().await()
    print (twice task[values]).last().await()
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "2\n2\n6\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_project_manifest_with_native_package_include(self) -> None:
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

func main(): Int {
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
"""
            )
            (root / "packages" / "nativepkg" / "include" / "native_math.h").write_text(
                "static inline int native_answer(void) { return 42; }\n"
            )
            (root / "packages" / "nativepkg" / "src" / "Math.forge").write_text(
                """
class

public static native func answer(): Int = "native_answer"
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 42, result.stderr)

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_reports_forge_errors_before_invoking_c_compiler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
class User {}
func main(): Void {
    const user: User = User.new("name")
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Expected 0 arguments for User.new, got 1", result.stderr)
        self.assertIn("app.forge:4:24", result.stderr)
        self.assertNotIn("clang:", result.stderr)

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_resolves_relative_use_inside_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Math").mkdir()
            (root / "Math" / "Vector2Int.forge").write_text(
                """
class

public new(public x: Int, public y: Int) {}
"""
            )
            (root / "Math" / "Figure.forge").write_text(
                """
use Vector2Int

class

public static func sum(point: Vector2Int): Int {
    return point.x + point.y
}
"""
            )
            source = root / "main.forge"
            source.write_text(
                """
use Math.Vector2Int
use Math.Figure

func main(): Int {
    return Figure.sum(Vector2Int.new(20, 22))
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 42, result.stderr)

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_handles_array_destructuring_pattern_mismatch(self) -> None:
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
            source = root / "src" / "main.forge"
            source.write_text(
                """
use std.Http.HttpIssue

func pathOf(requestLine: String): String, !HttpIssue {
    const parts = requestLine.split(" ", 3)
    const [method, path, body] = catch parts {
        issue: PatternMismatch => {
            return HttpIssue.new("Invalid request line")
        }
    }
    return path
}
func main(): Void {
    const valid = catch pathOf("POST /feed payload") {
        issue: HttpIssue => {
            print issue.message
            return
        }
    }
    print valid
    const invalid = catch pathOf("GET") {
        issue: HttpIssue => {
            print issue.message
            return
        }
    }
    print invalid
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(root)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "/feed\nInvalid request line\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_evaluates_caught_array_destructuring_source_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
func values(): Int[] {
    print "source"
    return [20, 22]
}
func main(): Void {
    const [left, right] = catch values() {
        issue: PatternMismatch => { return }
    }
    print left + right
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "source\n42\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_tracks_array_catch_result_ownership_per_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
class File {
    public value: Int

    public new(value: Int) {
        this.value = value
    }
}
func shortFiles(): File[] => [File.new(1)]
func useOwnedFallback(files: File[]): Int {
    const [first] = catch files {
        issue: PatternMismatch => [File.new(7)]
    }
    return first.value
}
func useBorrowedFallback(files: File[]): Int {
    const [first, second] = catch shortFiles() {
        issue: PatternMismatch => files
    }
    return first.value + second.value
}
func main(): Void {
    const empty: File[] = []
    print useOwnedFallback(empty)
    const fallback: File[] = [File.new(20), File.new(22)]
    print useBorrowedFallback(fallback)
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "7\n42\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_handles_declared_outcome_with_catch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
@multidef
class DivisionByZero {}
class Calculator {
    public static func divide(a: Int, b: Int): Int, !DivisionByZero {
        if b == 0 {
            return DivisionByZero.new()
        }
        return a / b
    }
}
func main(): Void {
    const result: Int = catch Calculator.divide(10, 0) {
        issue: DivisionByZero => 42
    }
    print result
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "42\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_handles_catch_handler_block_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
@multidef
class Failed {}
class Work {
    public static func run(): Int, !Failed {
        return Failed.new()
    }
}
func main(): Int {
    const result: Int = catch Work.run() {
        failed: Failed => {
            return 7
        }
    }
    return result
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 7, result.stderr)

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_catch_handler_block_can_reference_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
@multidef
class Failed {
    public new(public code: Int) {}
}
class Work {
    public static func run(): Int, !Failed {
        return Failed.new(-3)
    }
}
func main(): Int {
    const result: Int = catch Work.run() {
        failed: Failed => {
            print "failed (" + failed.code + ")"
            return 7
        }
    }
    return result
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.stdout, "failed (-3)\n")
        self.assertEqual(result.returncode, 7, result.stderr)

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_forwards_partial_catch_remaining_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
@multidef
class ParseIssue {}
class IoIssue {}
class Parser {
    public static func parse(): Int, !ParseIssue, !IoIssue {
        return IoIssue.new()
    }
}
func parseAgain(): Int, !IoIssue {
    return forward catch Parser.parse() {
        issue: ParseIssue => 10
    }
}
func main(): Int {
    const result: Int = catch parseAgain() {
        issue: IoIssue => 7
    }
    return result
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 7, result.stderr)

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_allows_ignored_optional_outcome_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.forge"
            source.write_text(
                """
@multidef
class AllocFailed {}
class Array {
    public static func reserve(size: Int): Void, ?AllocFailed {}
}
func main(): Void {
    Array.reserve(1000)
    print "reserved"
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout, "reserved\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_existing_loops_as_expressions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "main.forge"
            source.write_text(
                """
func main(): Void {
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
    const nested = while true {
        const inner = while true {
            break
        } else 4
        if inner == 4 {
            break 9
        }
    } else 0
    const missing: String? = while false {
        break "hit"
    }
    print fromFor
    print fromWhile
    print fromDo
    print nested
    print missing == null ? "none" : missing
    const selected = while true {
        break 11
    } else fallback()
    const exhausted = while false {
        break 12
    } else fallback()
    print selected
    print exhausted
}

func fallback(): Int {
    print "fallback"
    return 13
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )

        self.assertEqual(result.stdout, "2\n7\n5\n9\nnone\nfallback\n11\n13\n")

    @unittest.skipIf(shutil.which("cc") is None, "C compiler is not available")
    def test_run_expression_loop_conditions_with_per_check_preludes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "loop_condition_preludes.forge"
            source.write_text(
                """
func main(): Void {
    let whileIndex = 0
    const fromWhile = while (while false { break false } else whileIndex < 2) {
        whileIndex++
        if whileIndex > 5 {
            break 99
        }
    } else whileIndex

    let doIndex = 0
    const fromDo = do {
        doIndex++
        if doIndex > 5 {
            break 99
        }
    } while (while false { break false } else doIndex < 2) else doIndex

    print fromWhile
    print fromDo
}
"""
            )

            result = subprocess.run(
                [str(FORGE), "run", str(source)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )

        self.assertEqual(result.stdout, "2\n2\n")


if __name__ == "__main__":
    unittest.main()
