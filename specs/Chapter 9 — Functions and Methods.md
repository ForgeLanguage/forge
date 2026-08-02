В предыдущей главе мы познакомились с классами и объектами.

Теперь разберёмся, как описывается поведение — через функции.

---

# 1. Функция

Функция объявляется через `func`.

```forge
public static func greet(name: String): Void {
    print "Hello, " + name + "!"
}
```

Синтаксис:

```
[access] [static] func name(parameters): returnType {
    ...
}
```

---

# 2. Параметры

Параметры записываются как:

```
name: type
```

Можно передавать несколько параметров:

```forge
public static func add(a: Int, b: Int): Int {
    return a + b
}
```

Параметр класса по умолчанию является borrow. Если функция должна принять владение объектом, перед именем параметра указывается `take`:

```forge
public func setProfile(take profile: Profile): Void {
    this.profile = profile
}
```

Вызов такой функции требует явного `move` у аргумента:

```forge
user.setProfile(move profile)
```

После `move profile` переменная `profile` недоступна в вызывающем коде.

---

# 3. Возвращаемое значение

Тип возвращаемого значения указывается после `:`.

```forge
public static func multiply(a: Int, b: Int): Int {
    return a * b
}
```

Если функция возвращает `Void`, `return` можно опустить.

---

# 4. Экземплярные методы

Метод без `static` принадлежит объекту.

```forge
public func sayHello(): Void {
    print "Hello, " + this.name
}
```

В экземплярных методах:

- доступ к полям всегда через `this`
- вызов других методов тоже через `this`

```forge
this.sayHello()
```

---

# 5. Static методы

`static` методы принадлежат классу.

```forge
public static func version(): String {
    return "1.0"
}
```

Вызываются через имя класса:

```forge
print App.version()
```

Внутри `static` метода:

- `this` недоступен
- для обращения к статическим членам используется `self`

```forge
self.version()
```

---

# 6. Краткая форма

Если функция состоит из одного выражения, можно использовать сокращённую запись:

```forge
public static func square(x: Int): Int => x * x
```

Это эквивалентно:

```forge
public static func square(x: Int): Int {
    return x * x
}
```

---

# 7. Генераторы

Генератор объявляется через `generator` и отдаёт значения постепенно через `yield`.

Тип после `:` указывает тип значений, которые генератор отдаёт наружу.

```forge
public generator numbers(): Int {
    yield 1
    yield 2
    yield 3
}
```

Каждый `yield` отдаёт одно значение вызывающему коду и приостанавливает выполнение функции до следующей итерации.

В генераторе `numbers(): Int` значения, передаваемые в `yield`, должны иметь тип `Int`.

Вызов генератора создаёт объект генератора:

```forge
const gen = numbers()
```

Генератор можно использовать как источник значений в `for`:

```forge
for numbers() as n {
    print n
}
```

## 7.1 `catch` для генераторов

Если `catch` применяется к генератору, обработчик может использовать специальные результаты `continue` и `break`.

```forge
const rows = catch Csv.parseStream {
    error: ParseError => continue
}
```

`continue` означает: пропустить проблемный `yield` и продолжить генератор со следующего значения.

```forge
const rows = catch Csv.parseStream {
    error: ParseError => break
}
```

`break` означает: завершить генератор и больше не отдавать значений.

Эти формы допустимы только в `catch`, который оборачивает генератор. Для обычной функции ветка `catch` должна вернуть значение success-типа или выполнить `return` из текущей функции.

---

# 8. Расширим пример

```forge
class

public static func main(args: String[]): Void {
    const app: App = App.new(args)
    app.run()
}

public args: String[]

public new(args: String[]) {
    this.args = args
}

public func run(): Void {
    this.printArguments()
    this.repeatGreeting(3)
}

public func printArguments(): Void {
    for this.args as i, name {
        print i + ": " + name
    }
}

public func repeatGreeting(n: Int): Void {
    for n as i {
        print "Hello #" + i
    }
}
```

Теперь поведение отделено от точки входа,  
а код структурирован вокруг объекта.
