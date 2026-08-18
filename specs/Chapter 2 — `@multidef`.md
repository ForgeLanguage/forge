По умолчанию файл содержит **ровно один** верхнеуровневый тип.

Это правило применяется ко всем верхнеуровневым определениям:

- `class`
- `trait`
- `interface`
- `struct`
- `enum`
- `compose`

Если нужно явно объявить имя верхнеуровневого типа или разместить несколько типов в одном файле, используется `@multidef`.

Файл: `HelloWorld.forge`

```forge
@multidef

class HelloWorld
{
    public static main(args: String[]): Void
    {
        print "Hello, World!"
    }
}
```

В этом режиме:

- имена верхнеуровневых типов указываются явно,
- в файле может быть несколько типов,
- `single-type-per-file` правило отключается.

Например, trait и class в одном файле тоже требуют `@multidef`:

```forge
@multidef

trait Greeter {
    public greet(): Void {
        print "Hello"
    }
}

class App
uses Greeter

public static main(args: String[]): Void {
    const app: App = App.new()
    app.greet()
}
```
