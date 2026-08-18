До этого мы использовали traits как носители состояния и поведения.

Но иногда нужен только контракт —  
без хранения данных.

Для этого используются **interfaces**.

Если `interface`, `trait` и `class` показаны в одном файле, такой файл должен начинаться с `@multidef`.
Без `@multidef` файл содержит ровно один верхнеуровневый тип.

---

# 1. Interface

Interface — это trait без состояния.

Он описывает:

- какие методы должен реализовать тип
- но не содержит собственных полей

Пример:

```forge
interface Printable {
    public print(): Void
}
```

---

# 2. Реализация интерфейса через trait

Обычно интерфейс реализуется через trait.

```forge
trait UserPrintable {
    implements Printable

    public name: String

    public print(): Void {
        print "User: " + this.name
    }
}
```

---

# 3. Подключение к классу

```forge
class
uses UserPrintable
implements Printable
```

Теперь класс явно соответствует контракту `Printable`.

---

# 4. Использование интерфейса как типа

Interface можно использовать как тип.

```forge
public static output(item: Printable): Void {
    item.print()
}
```

Передать можно любой объект, который реализует `Printable`.

---

# 5. Trait-view

Когда объект рассматривается как интерфейс, доступ ограничивается контрактом.

```forge
const p: Printable = app
p.print()
```

В этом случае:

- доступ к полям невозможен
- доступны только методы интерфейса

---

# 6. Отличие от обычного trait

| Trait                         | Interface                     |
| ----------------------------- | ----------------------------- |
| Может содержать поля          | Не содержит состояния         |
| Может иметь реализацию        | Обычно определяет контракт    |
| Используется для наследования | Используется для полиморфизма |

---

# 7. Пример

```forge
interface Runnable {
    public run(): Void
}

trait AppLogic {
    implements Runnable

    public run(): Void {
        print "Running app"
    }
}

class
uses AppLogic
implements Runnable

public static main(args: String[]): Void {
    const app: Runnable = App.new()
    app.run()
}
```

# 7.1. Standard Interface `Stringable`

`Stringable` — стандартный интерфейс, доступный без `use`.

```forge
interface Stringable {
    public toString(): String
}
```

Класс реализует `Stringable`, если объявляет метод `toString(): String`:

```forge
class User
implements Stringable

public toString(): String {
    return "User"
}
```

Компилятор проверяет соответствие сигнатуры. Если метод отсутствует или
возвращает не `String`, это ошибка.

# 8. Неоднозначная реализация интерфейса

Рассмотрим ситуацию:

```forge
interface Printable {
    public print(): Void
}
```

Два разных трейта реализуют этот интерфейс:

```forge
trait UserPrintable {
    implements Printable

    public name: String

    public print(): Void {
        print "User: " + this.name
    }
}

trait DebugPrintable {
    implements Printable

    public id: Int

    public print(): Void {
        print "Debug id: " + this.id
    }
}
```

Теперь класс подключает оба:

```forge
class
uses UserPrintable
uses DebugPrintable
```

---

# Проблема

Класс содержит **две реализации** `Printable`.

Если теперь написать:

```forge
const p: Printable = app   // ❌
```

Компилятор не знает:

- какую реализацию выбрать?
- UserPrintable?
- DebugPrintable?

Такой каст запрещён.

---

# Правило

Если класс через разные трейты реализует один и тот же интерфейс,  
он обязан явно разрешить неоднозначность.

---

# 9. Явная реализация интерфейса классом

Класс может сам реализовать интерфейс и выбрать, какую реализацию использовать.

```forge
class
uses UserPrintable
uses DebugPrintable
implements Printable

public print(): Void from UserPrintable
```

Теперь:

```forge
const p: Printable = app   // ✅
p.print()
```

Неоднозначность устранена.

---

# Альтернативное решение

Класс может реализовать собственную логику:

```forge
public print(): Void {
    this.UserPrintable.print()
    this.DebugPrintable.print()
}
```
