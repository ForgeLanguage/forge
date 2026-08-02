"""Emit multi-file Forge projects as multiple C translation units."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import shutil

from forge_analysis import AnalysisResult, AnnotationTable, Symbol, validate
from forge_lowering import lower
from forge_modules import Project, SourceFile, load_project
from forge_normalizer import normalize
from forge_parser import ClassDeclaration, EnumDeclaration, UseDeclaration
from forge_resolution import ResolutionResult, ResolutionTable, resolve
from forge_safety import check_safety
from forge_typecheck import check_types

from .emitter import CEmissionError, emit_c, emit_c_header


@dataclass(frozen=True, slots=True)
class CProjectOutput:
    header: Path
    runtime_header: Path
    runtime_source: Path
    sources: tuple[Path, ...]
    headers: tuple[Path, ...]
    native_includes: tuple[str, ...] = ()
    include_dirs: tuple[Path, ...] = ()
    native_sources: tuple[Path, ...] = ()
    library_dirs: tuple[Path, ...] = ()
    libraries: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    pkg_config: tuple[str, ...] = ()
    link_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _CompilationProject:
    project: Project
    entry: Path
    source_files: tuple[SourceFile, ...]


def emit_c_project(entry_path: str | Path, output_dir: str | Path) -> CProjectOutput:
    """Emit one C file per Forge source file in a project."""

    compilation = _load_compilation_project(entry_path)
    project = compilation.project
    if project.diagnostics:
        raise CEmissionError(_format_project_diagnostics(project))

    source_files = compilation.source_files
    output_root = Path(output_dir)
    programs = tuple(
        normalize(source_file.program)
        for source_file in source_files
    )
    analyses = tuple(validate(program, raise_on_error=False) for program in programs)
    analyses = _merge_project_annotations(analyses)
    project_symbols = _project_symbols(source_files, analyses)
    resolutions = tuple(
        resolve(
            analysis,
            imports=_imports_for(analysis, project_symbols),
            raise_on_error=False,
        )
        for analysis in analyses
    )
    resolutions = _merge_project_resolutions(resolutions)
    lowered = tuple(
        lower(
            check_safety(
                check_types(
                    resolution,
                    raise_on_error=False,
                ),
                raise_on_error=False,
            )
        )
        for resolution in resolutions
    )
    header = output_root / "forge_project.h"
    header.parent.mkdir(parents=True, exist_ok=True)
    runtime_header = output_root / "forge_runtime.h"
    runtime_source = output_root / "forge_runtime.c"
    runtime_header.write_text(_runtime_header())
    runtime_source.write_text(_runtime_source())

    sources: list[Path] = [runtime_source]
    headers: list[Path] = []
    header_by_symbol = {
        _full_name_for_namespace(source_file.namespace, declaration.name): output_root / _output_relative_path(source_file).with_suffix(".h")
        for source_file, analysis in zip(source_files, analyses)
        for declaration in analysis.program.declarations
        if isinstance(declaration, (ClassDeclaration, EnumDeclaration)) and declaration.name is not None
    }
    native_include_lines = _native_include_lines(project)
    for source_file, analysis, result in zip(source_files, analyses, lowered):
        relative_source = _output_relative_path(source_file).with_suffix(".c")
        relative_header = _output_relative_path(source_file).with_suffix(".h")
        c_path = output_root / relative_source
        h_path = output_root / relative_header
        c_path.parent.mkdir(parents=True, exist_ok=True)
        h_path.parent.mkdir(parents=True, exist_ok=True)
        imported_headers = _import_headers(analysis, header_by_symbol)
        header_import_includes = tuple(
            os.path.relpath(imported_header, h_path.parent)
            for imported_header in imported_headers
            if imported_header != h_path
        )
        header_preamble = "\n".join(
            f'#include "{include}"' for include in header_import_includes
        )
        header_body = emit_c_header(result.ir)
        h_path.write_text(
            f"{header_preamble}\n\n{header_body}" if header_preamble else header_body
        )
        local_header_include = os.path.relpath(h_path, c_path.parent)
        runtime_include = os.path.relpath(runtime_header, c_path.parent)
        import_includes = tuple(
            os.path.relpath(imported_header, c_path.parent)
            for imported_header in imported_headers
            if imported_header != h_path
        )
        include_lines = [
            *native_include_lines,
            f'#include "{local_header_include}"',
            *(f'#include "{include}"' for include in import_includes),
            f'#include "{runtime_include}"',
        ]
        preamble = "\n".join(include_lines)
        c_path.write_text(
            emit_c(
                result.ir,
                preamble=preamble,
                external_helpers=True,
                declarations_in_header=True,
            )
        )
        headers.append(h_path)
        sources.append(c_path)

    header.write_text(_project_header(output_root, headers))
    native_sources = _copy_native_sources(project, output_root)
    sources.extend(native_sources)
    _copy_native_include_dirs(project, output_root)

    return CProjectOutput(
        header,
        runtime_header,
        runtime_source,
        tuple(sources),
        tuple(headers),
        project.native.includes,
        (output_root.resolve(),),
        native_sources,
        project.native.library_dirs,
        project.native.libraries,
        project.native.frameworks,
        project.native.pkg_config,
        ("-pthread",),
    )


def _copy_native_include_dirs(project: Project, output_root: Path) -> None:
    for include_dir in project.native.include_dirs:
        if not include_dir.exists():
            continue
        for source in include_dir.rglob("*"):
            if not source.is_file():
                continue
            destination = output_root / source.relative_to(include_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)


def _copy_native_sources(project: Project, output_root: Path) -> tuple[Path, ...]:
    native_root = output_root / "native"
    copied: list[Path] = []
    used_names: set[str] = set()
    for source in project.native.sources:
        destination = native_root / _unique_native_source_name(source, used_names)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        copied.append(destination)
    return tuple(copied)


def _unique_native_source_name(source: Path, used_names: set[str]) -> str:
    name = source.name
    if name not in used_names:
        used_names.add(name)
        return name
    stem = source.stem
    suffix = source.suffix
    index = 1
    while True:
        candidate = f"{stem}_{index}{suffix}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        index += 1


def _load_compilation_project(entry_path: str | Path) -> _CompilationProject:
    requested = Path(entry_path)
    if requested.name == "forge.toml":
        root = requested.parent.resolve()
        project = load_project(root)
        entry = _manifest_entry(project, root / "main.forge")
        return _CompilationProject(project, entry, _entry_last(project.files, entry))

    if requested.is_dir():
        root = requested.resolve()
        project = load_project(root)
        entry = _manifest_entry(project, root / "main.forge")
        return _CompilationProject(project, entry, _entry_last(project.files, entry))

    entry = requested.resolve()
    manifest_root = _find_manifest_root(entry.parent)
    if manifest_root is not None:
        project = load_project(manifest_root)
    else:
        project = load_project(entry.parent, src_dir=".")
    return _CompilationProject(project, entry, _entry_last(project.files, entry))


def _manifest_entry(project: Project, fallback: Path) -> Path:
    if project.manifest is not None:
        return project.manifest.entry_point
    return fallback.resolve()


def _find_manifest_root(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        if (current / "forge.toml").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _entry_last(source_files: tuple[SourceFile, ...], entry: Path) -> tuple[SourceFile, ...]:
    entry = entry.resolve()
    entry_file = next(
        (source_file for source_file in source_files if source_file.path.resolve() == entry),
        None,
    )
    if entry_file is None:
        return source_files
    return tuple(source_file for source_file in source_files if source_file is not entry_file) + (entry_file,)


def _format_project_diagnostics(project: Project) -> str:
    return "\n".join(
        f"{diagnostic.path}: {diagnostic.message}"
        for diagnostic in project.diagnostics
    )


def _output_relative_path(source_file: SourceFile) -> Path:
    source_name = source_file.program.source_name
    if source_name is not None:
        return Path(source_name)
    return source_file.relative_path


def _native_include_lines(project: Project) -> tuple[str, ...]:
    return tuple(f'#include "{include}"' for include in project.native.includes)


def _project_header(output_root: Path, headers: list[Path]) -> str:
    includes = "\n".join(
        f'#include "{header.relative_to(output_root).as_posix()}"'
        for header in headers
    )
    return f"#pragma once\n\n{includes}\n" if includes else "#pragma once\n"


def _import_headers(
    analysis: AnalysisResult,
    header_by_symbol: dict[str, Path],
) -> tuple[Path, ...]:
    headers: list[Path] = []
    seen: set[Path] = set()
    namespace = _namespace_for_analysis(analysis)
    for declaration in analysis.program.declarations:
        if not isinstance(declaration, UseDeclaration):
            continue
        full_name = ".".join(declaration.path)
        header = header_by_symbol.get(full_name)
        if header is None and namespace:
            header = header_by_symbol.get(_full_name_for_namespace(namespace, full_name))
        if header is not None and header not in seen:
            headers.append(header)
            seen.add(header)
    return tuple(headers)


def _runtime_header() -> str:
    return (
        "#pragma once\n\n"
        "#include <stddef.h>\n\n"
        "typedef struct _ForgeAsyncTask _ForgeAsyncTask;\n"
        "typedef void (*_forge_async_job_fn)(void* context);\n\n"
        "void* _forge_alloc(size_t size);\n"
        "void* _forge_realloc(void* pointer, size_t size);\n"
        "void* _forge_array_new(size_t capacity, size_t element_size);\n"
        "void _forge_array_grow(void** data, size_t* cap, size_t element_size);\n"
        "char* _forge_string_copy(const char* value);\n"
        "char* _forge_string_concat(size_t count, ...);\n"
        "_ForgeAsyncTask* _forge_async_task_new(_forge_async_job_fn run, void* context);\n"
        "void _forge_async_task_start(_ForgeAsyncTask* task);\n"
        "void _forge_async_task_await(_ForgeAsyncTask* task);\n"
        "void _forge_async_task_free(_ForgeAsyncTask* task);\n"
    )


def _runtime_source() -> str:
    return """#include "forge_runtime.h"

#include <pthread.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct _ForgeAsyncTask {
    _forge_async_job_fn run;
    void* context;
    bool complete;
    bool started;
    struct _ForgeAsyncTask* next;
};

static pthread_mutex_t _forge_async_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t _forge_async_work_cond = PTHREAD_COND_INITIALIZER;
static pthread_cond_t _forge_async_complete_cond = PTHREAD_COND_INITIALIZER;
static _ForgeAsyncTask* _forge_async_queue_head = NULL;
static _ForgeAsyncTask* _forge_async_queue_tail = NULL;
static bool _forge_async_workers_started = false;

void* _forge_alloc(size_t size) {
    void* result = malloc(size == 0 ? 1 : size);
    if (result == NULL) {
        abort();
    }
    return result;
}

void* _forge_realloc(void* pointer, size_t size) {
    void* result = realloc(pointer, size == 0 ? 1 : size);
    if (result == NULL) {
        abort();
    }
    return result;
}

void* _forge_array_new(size_t capacity, size_t element_size) {
    return capacity == 0 ? NULL : _forge_alloc(element_size * capacity);
}

void _forge_array_grow(void** data, size_t* cap, size_t element_size) {
    size_t next = *cap == 0 ? 1 : *cap * 2;
    *data = _forge_realloc(*data, element_size * next);
    *cap = next;
}

char* _forge_string_copy(const char* value) {
    size_t len = strlen(value);
    char* result = _forge_alloc(len + 1);
    memcpy(result, value, len + 1);
    return result;
}

char* _forge_string_concat(size_t count, ...) {
    va_list args;
    size_t len = 0;
    va_start(args, count);
    for (size_t i = 0; i < count; i += 1) {
        len += strlen(va_arg(args, const char*));
    }
    va_end(args);

    char* result = _forge_alloc(len + 1);
    char* cursor = result;
    va_start(args, count);
    for (size_t i = 0; i < count; i += 1) {
        const char* part = va_arg(args, const char*);
        size_t part_len = strlen(part);
        memcpy(cursor, part, part_len);
        cursor += part_len;
    }
    va_end(args);
    *cursor = '\\0';
    return result;
}

static void _forge_async_abort_on_error(int status) {
    if (status != 0) {
        abort();
    }
}

static size_t _forge_async_worker_count(void) {
    const char* configured = getenv("FORGE_ASYNC_THREADS");
    if (configured != NULL && configured[0] != '\\0') {
        char* end = NULL;
        unsigned long parsed = strtoul(configured, &end, 10);
        if (parsed > 0 && end != configured && *end == '\\0') {
            return (size_t)parsed;
        }
    }

    long processors = sysconf(_SC_NPROCESSORS_ONLN);
    if (processors > 0) {
        return (size_t)processors;
    }
    return 4;
}

static _ForgeAsyncTask* _forge_async_pop_task(void) {
    _ForgeAsyncTask* task = _forge_async_queue_head;
    if (task == NULL) {
        return NULL;
    }
    _forge_async_queue_head = task->next;
    if (_forge_async_queue_head == NULL) {
        _forge_async_queue_tail = NULL;
    }
    task->next = NULL;
    return task;
}

static void _forge_async_run_task(_ForgeAsyncTask* task) {
    task->run(task->context);

    _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
    task->complete = true;
    _forge_async_abort_on_error(pthread_cond_broadcast(&_forge_async_complete_cond));
    _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
}

static void* _forge_async_worker_run(void* unused) {
    (void)unused;
    for (;;) {
        _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
        while (_forge_async_queue_head == NULL) {
            _forge_async_abort_on_error(
                pthread_cond_wait(&_forge_async_work_cond, &_forge_async_mutex)
            );
        }

        _ForgeAsyncTask* task = _forge_async_pop_task();
        _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
        _forge_async_run_task(task);
    }
    return NULL;
}

static void _forge_async_start_workers(void) {
    if (_forge_async_workers_started) {
        return;
    }

    size_t worker_count = _forge_async_worker_count();
    for (size_t i = 0; i < worker_count; i += 1) {
        pthread_t worker;
        _forge_async_abort_on_error(pthread_create(&worker, NULL, _forge_async_worker_run, NULL));
        _forge_async_abort_on_error(pthread_detach(worker));
    }
    _forge_async_workers_started = true;
}

_ForgeAsyncTask* _forge_async_task_new(_forge_async_job_fn run, void* context) {
    if (run == NULL) {
        abort();
    }
    _ForgeAsyncTask* task = _forge_alloc(sizeof(_ForgeAsyncTask));
    task->run = run;
    task->context = context;
    task->complete = false;
    task->started = false;
    task->next = NULL;
    return task;
}

void _forge_async_task_start(_ForgeAsyncTask* task) {
    if (task == NULL) {
        abort();
    }
    _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
    if (task->started) {
        abort();
    }
    _forge_async_start_workers();
    task->started = true;
    if (_forge_async_queue_tail == NULL) {
        _forge_async_queue_head = task;
        _forge_async_queue_tail = task;
    } else {
        _forge_async_queue_tail->next = task;
        _forge_async_queue_tail = task;
    }
    _forge_async_abort_on_error(pthread_cond_signal(&_forge_async_work_cond));
    _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
}

void _forge_async_task_await(_ForgeAsyncTask* task) {
    if (task == NULL) {
        abort();
    }
    _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
    if (!task->started) {
        abort();
    }
    while (!task->complete) {
        _ForgeAsyncTask* next = _forge_async_pop_task();
        if (next != NULL) {
            _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
            _forge_async_run_task(next);
            _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
        } else {
            _forge_async_abort_on_error(
                pthread_cond_wait(&_forge_async_complete_cond, &_forge_async_mutex)
            );
        }
    }
    _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
}

void _forge_async_task_free(_ForgeAsyncTask* task) {
    if (task == NULL) {
        return;
    }
    if (task->started) {
        _forge_async_task_await(task);
    }
    free(task);
}
"""


def _merge_project_annotations(
    analyses: tuple[AnalysisResult, ...]
) -> tuple[AnalysisResult, ...]:
    node_scopes = {
        node_id: scope
        for analysis in analyses
        for node_id, scope in analysis.annotations.node_scopes.items()
    }
    declaration_symbols = {
        node_id: symbol
        for analysis in analyses
        for node_id, symbol in analysis.annotations.declaration_symbols.items()
    }
    return tuple(
        replace(
            analysis,
            annotations=AnnotationTable(
                analysis.annotations.root_scope,
                dict(node_scopes),
                dict(declaration_symbols),
            ),
        )
        for analysis in analyses
    )


def _project_symbols(
    source_files: tuple[SourceFile, ...],
    analyses: tuple[AnalysisResult, ...],
) -> dict[str, Symbol]:
    symbols: dict[str, Symbol] = {}
    for source_file, analysis in zip(source_files, analyses):
        for declaration in analysis.program.declarations:
            if not isinstance(declaration, (ClassDeclaration, EnumDeclaration)) or declaration.name is None:
                continue
            symbol = analysis.annotations.symbol_for(declaration)
            if symbol is not None:
                full_name = _full_name_for_namespace(source_file.namespace, declaration.name)
                symbols[full_name] = symbol
    return symbols


def _full_name_for_namespace(namespace: tuple[str, ...], name: str) -> str:
    return ".".join((*namespace, name)) if namespace else name


def _imports_for(
    analysis: AnalysisResult,
    project_symbols: dict[str, Symbol],
) -> dict[str, Symbol]:
    imports: dict[str, Symbol] = {}
    namespace = _namespace_for_analysis(analysis)
    for declaration in analysis.program.declarations:
        if not isinstance(declaration, UseDeclaration):
            continue
        path = declaration.path
        full_name = ".".join(path)
        symbol = project_symbols.get(full_name)
        if symbol is None and namespace:
            symbol = project_symbols.get(_full_name_for_namespace(namespace, full_name))
        if symbol is not None:
            imports[path[-1]] = symbol
    return imports


def _namespace_for_analysis(analysis: AnalysisResult) -> tuple[str, ...]:
    source_name = analysis.program.source_name
    if source_name is None:
        return ()
    parent = Path(source_name).parent
    if str(parent) == ".":
        return ()
    return parent.parts


def _merge_project_resolutions(
    resolutions: tuple[ResolutionResult, ...]
) -> tuple[ResolutionResult, ...]:
    identifiers = {
        node_id: symbol
        for resolution in resolutions
        for node_id, symbol in resolution.resolutions.identifiers.items()
    }
    types = {
        node_id: symbol
        for resolution in resolutions
        for node_id, symbol in resolution.resolutions.types.items()
    }
    specials = {
        node_id: symbol
        for resolution in resolutions
        for node_id, symbol in resolution.resolutions.specials.items()
    }
    return tuple(
        replace(
            resolution,
            resolutions=ResolutionTable(
                dict(identifiers),
                dict(types),
                dict(specials),
            ),
        )
        for resolution in resolutions
    )
