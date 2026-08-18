Forge supports structs for value-shaped data declarations.

Structs are top-level type declarations and follow the normal visibility and
namespace rules.

In a single-type file the struct name is inferred from the file name:

```forge
public struct

public status: Int
public body: String
```

With `@multidef`, or whenever the declaration must be explicit, the struct name
is written after `struct`:

```forge
public struct HttpResponse {
    public status: Int
    public body: String
}
```

Struct fields use the same visibility modifiers as other type members.
Unlike class fields, struct fields are mutable by default: `public status: Int`
means `public var status: Int`. Use `const` for a struct field that must not be
reassigned after initialization.

```forge
public struct HttpResponse {
    public status: Int
    public const protocol: String
}
```

## Struct literals

A struct value can be initialized with a field literal:

```forge
var response: HttpResponse = {
    status: 200,
    body: "OK"
}
```

The expected type comes from the declared variable type, parameter type, return
type, or another surrounding type context.

Field names in the literal must match fields declared by the struct.

## Methods

Structs may declare methods.

```forge
public struct

public status: Int
public body: String

public isClientError(): Bool => this.status >= 400 && this.status < 500
```

Inside an instance method, `this` refers to the current struct value.
