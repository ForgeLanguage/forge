Forge supports simple enums without payloads.

```forge
public enum Status {
    Pending,
    Done
}
```

Enum variants are accessed through the enum type:

```forge
const status: Status = Status.Done
```

Enums are top-level type declarations. A file may contain a single enum by
itself, or combine enums with a class when the file starts with `@multidef`.

Enum types follow the normal visibility and namespace rules:

```forge
use app.Status

const status: Status = Status.Pending
```

Fully qualified enum variants can be used without `use`:

```forge
const status: app.Status = app.Status.Done
```

## Typed enums

Besides simple enums, Forge supports typed enums: enums whose variants are
compile-time constants of a declared value type.

```forge
public enum HttpMethod : String {
    Get => "GET",
    Post => "POST",
}
```

```forge
public enum ExitCode : Int {
    Ok => 0,
    ParseError => 7,
}
```

A typed enum variant has the enum type at the type level, and its associated
value has the declared value type.

## Value-object enums

An enum may be declared over a struct, class, or another object-shaped type.

```forge
public enum : HttpResponse {
    Ok => {
        status: 200,
        body: "OK"
    }

    NotFound => {
        status: 404,
        body: "Not Found"
    }
}
```

If the target type has constructors or factory methods, enum variants may use
ordinary expressions:

```forge
public enum : SomeClass {
    FirstValue => SomeClass.new(1),
    SecondValue => SomeClass.new(2)
}
```

As with other top-level types, an unnamed enum in a single-type file gets its
name from the file name. With `@multidef`, the enum name must be written
explicitly.

## Inline struct enums

For enums whose value shape is local to the enum, the enum may declare an inline
struct type:

```forge
public enum HttpStatus : struct {
    public code: Int
    public reason: String
    public isError: Bool
} {
    Ok => { 200, "OK", false }
    NotFound => { 404, "Not Found", true }

    public isClientError(): Bool => this.code >= 400 && this.code < 500
}
```

The inline struct defines the fields available on each variant value. Positional
variant literals are assigned to fields in declaration order.

## Methods

Enums may declare methods.

```forge
public enum HttpStatus : struct {
    public code: Int
    public reason: String
    public isError: Bool
} {
    Ok => { 200, "OK", false }
    NotFound => { 404, "Not Found", true }

    public isClientError(): Bool => this.code >= 400 && this.code < 500
}
```

Inside an enum method, `this` refers to the current enum value.

## Compile-time and runtime enums

A compile-time enum is an enum over values such as `String`, `Int`, or an inline
`struct` value. Its variants are compile-time constants.

A runtime enum is an enum over objects, such as class instances created by
constructor calls or factory expressions. Its variants refer to runtime objects.
