Иногда один trait использует поведение другого.

В таком случае зависимость должна быть объявлена явно.

Для этого используется `requires`.

---

# 1. Зависимость одного trait от другого

Пример:

```forge
trait Logger {
    public func log(message: String): Void {
        print "[LOG] " + message
    }
}
```

Теперь создадим trait, который использует `Logger`.

```forge
trait Greeter {
    requires Logger

    public name: String

    public func greet(): Void {
        this.Logger.log("Greeting " + this.name)
        print "Hello, " + this.name + "!"
    }
}
```

Здесь:

- `Greeter` объявляет, что ему нужен `Logger`
- внутри `Greeter` можно безопасно обращаться к `this.Logger`

---

# 2. Подключение зависимостей в классе

Если класс подключает `Greeter`, он обязан подключить и `Logger`.

```forge
class
uses Greeter
uses Logger
```

Если `Logger` не будет подключён — это ошибка компиляции.

---

# 3. Зачем нужен `requires`

`requires`:

- делает зависимости явными
- может требовать как тип, так и конкретную сигнатуру метода
- предотвращает скрытые требования
- делает trait независимыми и переиспользуемыми
- сохраняет порядок и ясность композиции

Граф зависимостей должен быть ацикличным.

Трейт может потребовать конкретный метод у класса:

```forge
trait HttpHandler {
    requires public func HttpHandlerInterface.match(String): Bool
}
```

Класс, который подключает такой трейт через `uses HttpHandler`, обязан объявить совместимый `match`.

---

# 4. Расширим пример

```forge
trait Logger {
    public func log(message: String): Void {
        print "[LOG] " + message
    }
}

trait Greeter {
    requires Logger

    public name: String

    public func greet(): Void {
        this.Logger.log("Greeting " + this.name)
        print "Hello, " + this.name + "!"
    }
}

class
uses Greeter
uses Logger

public static func main(args: String[]): Void {
    const app: App = App.new("Forge")
    app.run()
}

public new(name: String) {
    this.Greeter.name = name
}

public func run(): Void {
    this.Greeter.greet()
}
```

---

# 5. Итог

- Trait может объявлять зависимости через повторяемую инструкцию `requires`.
- Класс обязан удовлетворить все зависимости.
- Внутри trait доступ к зависимым trait осуществляется через `this.TraitName`.
