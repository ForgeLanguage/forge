from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from forge_c import emit_c, emit_c_project
from forge_parser import parse


BUILD_DIR = Path(os.environ.get("FORGE_BUILD_DIR", ".forge-build"))


class ForgeCliError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        usage(sys.stderr)
        return 1

    command = args.pop(0)
    try:
        if command in {"-h", "--help", "help"}:
            usage(sys.stdout)
            return 0
        if command == "translate":
            command_translate(args)
            return 0
        if command == "compile":
            command_compile(args)
            return 0
        if command == "run":
            command_run(args)
            return 0
        raise ForgeCliError(f"unknown command: {command}")
    except ForgeCliError as exc:
        print(f"forge: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode


def usage(stream) -> None:
    stream.write(
        """Usage:
  forge translate <source.forge> [-o output.c]
  forge compile   <source-or-project> [-o output-binary] [--c-out output-dir]
  forge run       <source-or-project> [-- program-args...]

Commands:
  translate  Generate C source.
  compile    Generate one C source per Forge project file and compile with optimizations.
  run        Generate one C source per Forge project file, compile without optimizations, and run.

Environment:
  CC               C compiler, default: cl on Windows when available, otherwise cc
  FORGE_BUILD_DIR  Build output directory, default: .forge-build
"""
    )


def command_translate(args: list[str]) -> None:
    source = ""
    output = ""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-o", "--output"}:
            index += 1
            if index >= len(args):
                raise ForgeCliError("missing value for -o")
            output = args[index]
        elif arg in {"-h", "--help"}:
            usage(sys.stdout)
            return
        elif arg.startswith("-"):
            raise ForgeCliError(f"unknown option for translate: {arg}")
        else:
            if source:
                raise ForgeCliError("translate accepts one source file")
            source = arg
        index += 1

    if not source:
        raise ForgeCliError("translate requires a source file")
    emit_c_file(Path(source), Path(output) if output else None)


def command_compile(args: list[str]) -> None:
    source = ""
    binary = ""
    c_output = ""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-o", "--output"}:
            index += 1
            if index >= len(args):
                raise ForgeCliError("missing value for -o")
            binary = args[index]
        elif arg == "--c-out":
            index += 1
            if index >= len(args):
                raise ForgeCliError("missing value for --c-out")
            c_output = args[index]
        elif arg in {"-h", "--help"}:
            usage(sys.stdout)
            return
        elif arg.startswith("-"):
            raise ForgeCliError(f"unknown option for compile: {arg}")
        else:
            if source:
                raise ForgeCliError("compile accepts one source or project")
            source = arg
        index += 1

    if not source:
        raise ForgeCliError("compile requires a source file")
    source_path = Path(source)
    c_output_path = Path(c_output) if c_output else default_c_output_dir(source_path)
    binary_path = Path(binary) if binary else default_binary_output(source_path)
    compile_project(source_path, binary_path, c_output_path, "release")
    print(binary_path)


def command_run(args: list[str]) -> None:
    source = ""
    program_args: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            program_args = args[index + 1 :]
            break
        if arg in {"-h", "--help"}:
            usage(sys.stdout)
            return
        if arg.startswith("-"):
            raise ForgeCliError(f"unknown option for run: {arg}")
        if source:
            raise ForgeCliError("run accepts one source or project before --")
        source = arg
        index += 1

    if not source:
        raise ForgeCliError("run requires a source file")
    source_path = Path(source)
    c_output = default_c_output_dir(source_path)
    binary = default_binary_output(source_path)
    compile_project(source_path, binary, c_output, "debug")
    subprocess.run([str(binary), *program_args], check=True)


def emit_c_file(source_path: Path, output: Path | None) -> None:
    if not source_path.is_file():
        raise ForgeCliError(f"source file not found: {source_path}")
    c_source = emit_c(parse(source_path.read_text(), source_name=source_path.as_posix()))
    if output is None:
        sys.stdout.write(c_source)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(c_source)


def compile_project(source_path: Path, binary: Path, c_output: Path, mode: str) -> None:
    if not source_path.is_file() and not source_path.is_dir():
        raise ForgeCliError(f"source file or project not found: {source_path}")
    try:
        result = emit_c_project(source_path, c_output)
    except Exception as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc

    c_files = list(result.sources)
    if not c_files:
        raise ForgeCliError("no C files to compile")

    compiler_flags = [f"-I{path}" for path in result.include_dirs]
    link_flags = [
        *(f"-L{path}" for path in result.library_dirs),
        *(f"-l{library}" for library in result.libraries),
        *framework_flags(result.frameworks),
        *pkg_config_flags(result.pkg_config),
        *result.link_flags,
    ]
    cc = compiler()
    if is_msvc(cc):
        link_flags = msvc_link_flags(link_flags)
    write_compile_commands(mode, c_output, cc, compiler_flags, c_files)
    compile_c(binary, mode, cc, compiler_flags, c_files, link_flags)


def compile_c(
    binary: Path,
    mode: str,
    cc: str,
    compiler_flags: list[str],
    c_files: list[Path],
    link_flags: list[str],
) -> None:
    binary.parent.mkdir(parents=True, exist_ok=True)
    if is_msvc(cc):
        command = [
            cc,
            *msvc_mode_flags(mode),
            *msvc_include_flags(compiler_flags),
            *map(str, c_files),
            *link_flags,
            f"/Fe:{binary}",
        ]
    else:
        command = [
            cc,
            *posix_mode_flags(mode),
            "-Wno-unused-variable",
            *compiler_flags,
            *map(str, c_files),
            *link_flags,
            "-o",
            str(binary),
        ]
    subprocess.run(command, check=True)


def write_compile_commands(
    mode: str,
    output_dir: Path,
    cc: str,
    compiler_flags: list[str],
    c_files: list[Path],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_root = output_dir.resolve()
    flags = msvc_mode_flags(mode) if is_msvc(cc) else [*posix_mode_flags(mode), "-Wno-unused-variable"]
    portable_compiler_flags = [portable_flag(flag, output_root) for flag in compiler_flags]
    entries = []
    for c_file in c_files:
        file = portable_path(c_file, output_root)
        object_file = Path(c_file.name + ".obj" if is_msvc(cc) else c_file.name + ".o")
        compile_marker = "/c" if is_msvc(cc) else "-c"
        output_marker = f"/Fo:{object_file.as_posix()}" if is_msvc(cc) else "-o"
        output_argument = [] if is_msvc(cc) else [object_file.as_posix()]
        entries.append(
            {
                "directory": ".",
                "file": file,
                "arguments": [
                    cc,
                    *flags,
                    *portable_compiler_flags,
                    compile_marker,
                    file,
                    output_marker,
                    *output_argument,
                ],
            }
        )
    (output_dir / "compile_commands.json").write_text(json.dumps(entries, indent=2) + "\n")


def compiler() -> str:
    configured = os.environ.get("CC")
    if configured:
        return configured
    if sys.platform == "win32" and shutil.which("cl") is not None:
        return "cl"
    return "cc"


def is_msvc(cc: str) -> bool:
    return Path(cc).name.lower() in {"cl", "cl.exe"}


def posix_mode_flags(mode: str) -> list[str]:
    flags = ["-std=c11", "-Wall", "-Wextra"]
    if sys.platform != "win32":
        flags[1:1] = ["-D_POSIX_C_SOURCE=200112L", "-D_DARWIN_C_SOURCE"]
    if mode == "release":
        return [*flags, "-O2", "-DNDEBUG"]
    return [*flags, "-O0", "-g"]


def msvc_mode_flags(mode: str) -> list[str]:
    flags = ["/std:c11", "/W3"]
    if mode == "release":
        return [*flags, "/O2", "/DNDEBUG"]
    return [*flags, "/Od", "/Zi"]


def msvc_include_flags(flags: list[str]) -> list[str]:
    return [f"/I{flag[2:]}" if flag.startswith("-I") else flag for flag in flags]


def msvc_link_flags(flags: list[str]) -> list[str]:
    converted: list[str] = []
    for flag in flags:
        if flag.startswith("-L"):
            converted.append(f"/LIBPATH:{flag[2:]}")
        elif flag.startswith("-l"):
            converted.append(f"{flag[2:]}.lib")
        else:
            converted.append(flag)
    return converted


def framework_flags(frameworks: tuple[str, ...]) -> list[str]:
    flags: list[str] = []
    for framework in frameworks:
        flags.extend(["-framework", framework])
    return flags


def pkg_config_flags(packages: tuple[str, ...]) -> list[str]:
    if not packages or shutil.which("pkg-config") is None:
        return []
    flags: list[str] = []
    for package in packages:
        exists = subprocess.run(
            ["pkg-config", "--exists", package],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if exists.returncode != 0:
            continue
        result = subprocess.run(
            ["pkg-config", "--cflags", "--libs", package],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            flags.extend(shlex.split(result.stdout))
    return flags


def portable_path(path: Path, output_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(output_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def portable_flag(flag: str, output_root: Path) -> str:
    if not flag.startswith("-I"):
        return flag
    include = Path(flag[2:]).resolve()
    try:
        return "-I" + include.relative_to(output_root).as_posix()
    except ValueError:
        return flag


def default_c_output_dir(source: Path) -> Path:
    return BUILD_DIR / f"{source_basename(source)}-c"


def default_binary_output(source: Path) -> Path:
    binary = BUILD_DIR / source_basename(source)
    if sys.platform == "win32" and binary.suffix.lower() != ".exe":
        return binary.with_suffix(".exe")
    return binary


def source_basename(source: Path) -> str:
    return source.name.rsplit(".", 1)[0]


if __name__ == "__main__":
    raise SystemExit(main())
