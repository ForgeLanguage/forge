В Forge поведение не наследуется. Оно компонуется через `trait`.

Трейт может содержать:

- поля (состояние)
- методы (поведение)

Класс подключает трейты и получает доступ к ним через **явное имя трейта**.

Если `trait` и `class` показаны в одном файле, такой файл должен начинаться с `@multidef`.
Без `@multidef` файл содержит ровно один верхнеуровневый тип.

---

# 1. Trait

```forge
trait Greeter {
    public name: String

    public func greet(): Void {
        print "Hello, " + this.name + "!"
    }
}
```

---

# 2. Подключение trait к классу

Класс подключает трейты через повторяемую инструкцию `uses` на уровне объявления членов:

```forge
class
uses Greeter
```

---

# 3. Доступ к членам трейта

Если к классу подключены несколько трейтов с одним и тем же именем членов, доступ из класса к членам трейта осуществляется  **через имя трейта**:

```forge
this.Greeter.greet()
print this.Greeter.name
```

Если неоднозначностей нет, имя трейта можно опустить:
```forge
this.greet()
print this.name
```
---

# 4. Инициализация полей трейта

Если в трейте объявлены поля **без значения по умолчанию**, их обязан инициализировать:

- либо конструктор класса (`new`)
    
- либо вызывающий код (если объект создаётся без конструктора/через фабрику — зависит от модели, но обязанность должна быть закрыта)
    

Пример: поле `name` в `Greeter` не имеет значения по умолчанию, значит класс обязан его установить.

```forge
trait Greeter {
    public name: String

    public func greet(): Void {
        print "Hello, " + this.name + "!"
    }
}

class
uses Greeter

public new(name: String) {
    this.Greeter.name = name
}
```

Если класс этого не сделает, объект считается неинициализированным (и это ошибка — детали проверки фиксируются в правилах инициализации).

---

# 5. Несколько трейтов

```forge
trait Greeter {
    public name: String

    public func greet(): Void {
        print "Hello, " + this.name + "!"
    }
}

trait Logger {
    public func log(message: String): Void {
        print "[LOG] " + message
    }
}

class
uses Greeter
uses Logger

public new(name: String) {
    this.Greeter.name = name
}

public func run(): Void {
    this.Logger.log("starting")
    this.Greeter.greet()
}
```

---

# 6. Расширим HelloWorld

```forge
trait Greeter {
    public name: String

    public func greet(): Void {
        print "Hello, " + this.name + "!"
    }
}

trait ArgumentPrinter {
    public args: String[]

    public func printArgs(): Void {
        for this.args as i, name {
            print i + ": " + name
        }
    }
}

class
uses Greeter
uses ArgumentPrinter

public static func main(args: String[]): Void {
    const app: App = App.new(args)
    app.run()
}

public new(args: String[]) {
    this.ArgumentPrinter.args = args
    this.Greeter.name = "Forge"
}

public func run(): Void {
    this.Greeter.greet()
    this.ArgumentPrinter.printArgs()
}
```

---

# 7. Итог

- Trait — единица поведения и (опционально) состояния.
- Класс компонирует трейты через `: Trait1 + Trait2`.
- Если член однозначен — можно обращаться напрямую: `this.greet()`.  
* Если есть конфликт — нужно указывать trait: `this.Greeter.greet()`.
- Если поля трейта не имеют значений по умолчанию, их инициализация — обязанность класса (обычно в `new`) или вызывающего кода.
# 8. Trait-view и каст к трейту

Когда класс подключает trait, объект можно рассматривать как экземпляр этого трейта.

Это называется **trait-view**.

---

## Явный каст к трейту

```forge
trait Greeter {
    public name: String

    public func greet(): Void {
        print "Hello, " + this.name + "!"
    }
}

class
uses Greeter

public new(name: String) {
    this.Greeter.name = name
}

public static func main(args: String[]): Void {
    const app: App = App.new("Forge")

    const g: Greeter = app
    g.greet()
}
```

Здесь:

```forge
const g: Greeter = app
```

Объект `app` рассматривается как `Greeter`.

---

## Что такое trait-view

Trait-view:

- ограничивает доступ только API трейта
- скрывает остальные трейты класса
- скрывает собственные члены класса

Если у класса есть другие трейты или методы, через `Greeter` они недоступны.

---

## Важно

Trait-view — это не копия объекта.  
Это представление того же экземпляра через контракт трейта.

---

## Явность

Даже внутри класса доступ к членам трейта остаётся явным:

```forge
this.Greeter.greet()
```

Но после приведения:

```forge
const g: Greeter = this
g.greet()
```

Доступ идёт напрямую через тип `Greeter`.

---

## Зачем это нужно

Trait-view позволяет:

- передавать поведение без раскрытия всего объекта
- строить архитектуру на контракте трейта
- избегать жёсткой связанности
