# forge-lexer

Python packages for lexing and parsing Forge source code.

```python
from forge_lexer import lex

tokens = lex('const name: String = "Forge"')
```

```python
from forge_parser import parse

program = parse('const name: String = "Forge"')
```

The parser builds a syntactic AST. It does not type-check or interpret Forge
programs.

For single-type files, pass `source_name` so an unnamed top-level type can take
its name from the file:

```python
program = parse("class {}", source_name="HelloWorld.forge")
```

Use `@multidef` when a file contains multiple explicitly named top-level types.

```python
from forge_normalizer import normalize

program = normalize(program)
```

The normalizer rewrites AST shape before semantic analysis. It currently adds a
public default constructor to each class that does not declare a user
constructor.

```python
from forge_modules import load_project

project = load_project(".")
```

The modules package loads `src/**/*.forge`, derives namespaces from paths, and
collects top-level symbols plus `use` declarations for multi-file programs. If
`forge.toml` is present, it also validates local dependencies from
`packages_path`, checks `forge.lock`, and prefixes package symbols with the
package name.

```python
from forge_analysis import validate

result = validate(program, raise_on_error=False)
```

The analysis package validates AST structure and returns side-table annotations
without mutating parsed nodes.

```python
from forge_resolution import resolve

resolution = resolve(result, raise_on_error=False)
```

The resolution package resolves lexical identifiers and type references against
validation scopes, including built-in types.

```python
from forge_typecheck import check_types

typed = check_types(resolution, raise_on_error=False)
```

The type checker annotates declarations and expressions with internal types and
reports type mismatches before lowering.

```python
from forge_safety import check_safety

safety = check_safety(typed, raise_on_error=False)
```

The safety package checks Forge ownership and resource rules such as borrowed
handles, exclusive calls, and terminate invalidation.

```python
from forge_lowering import lower

lowered = lower(safety)
```

Lowering builds backend-neutral IR for both the development interpreter and
production compiler backends.

```python
from forge_c import emit_c

c_source = emit_c(lowered)
```

The C backend emits straightforward C directly from IR without an extra C AST.
Classes are emitted as plain `struct` declarations, and methods are emitted as
plain C functions with `Class_method` names.

## CLI

```bash
bin/forge translate app.forge -o app.c
bin/forge compile app.forge -o app --c-out build/c
bin/forge run app.forge
bin/forge run path/to/project
```

On Windows, use the bundled batch launcher:

```bat
bin\forge.bat translate app.forge -o app.c
bin\forge.bat compile app.forge -o app.exe --c-out build\c
bin\forge.bat run app.forge
```

`translate` emits C for one Forge file. `compile` and `run` accept either a Forge
entry file, a project directory, or `forge.toml`. They emit one `.c` file per
project/package `.forge` file plus shared headers and pass native include/link
metadata from package manifests to the C compiler. `compile` builds with
optimizations. `run` builds without optimizations and runs the produced binary.
The CLI implementation is shared Python code behind the macOS/Linux `bin/forge`
wrapper and the Windows `bin\forge.bat` wrapper.

## Bundled standard library

Forge ships a small `std` package that can be used through the regular package
dependency flow:

```toml
[dependencies]
std = "0.1.0"
```

`forge.lock` should contain the same version:

```toml
std = "0.1.0"
```

The first slice intentionally keeps the native boundary low-level:

- `std.Net.Network`
- `std.Net.TcpStream`
- `std.Net.NetworkIssue`
- `std.Http.Http`
- `std.Http.HttpResponse`
- `std.Http.HttpIssue`

`std.Net` is the layer intended to own socket/runtime bindings. `std.Http` is
kept as the higher-level package surface above networking. TCP connect/read/write
use declared outcomes through `!NetworkIssue`; full HTTP behavior, TLS,
redirects, chunked transfer, and text/byte parsing helpers are not implemented
in this initial slice.

Package manifests can also provide native C sources:

```toml
[native]
sources = ["native/package_runtime.c"]
```

These files are compiled alongside generated Forge C sources.
