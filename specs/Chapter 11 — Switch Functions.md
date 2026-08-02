До этого мы использовали `if` для ветвления.

В Forge есть более декларативный способ описывать выбор —  
**switch-функции**.

Это не просто оператор.  
Это форма объявления функции.

---

# 1. Простейшая switch-функция

Обычная функция:

```forge
public static func classify(n: Int): String {
    if n > 0 {
        return "positive"
    } elseif n < 0 {
        return "negative"
    } else {
        return "zero"
    }
}
```

Ту же логику можно записать через `switch`:

```forge
public static switch classify(n: Int): String {
    n > 0 => "positive"
    n < 0 => "negative"
    default => "zero"
}
```

---

# 2. Что такое switch-функция

Switch-функция:

- объявляется через `switch`
- состоит из условий и результатов
- всегда возвращает значение
- обязана иметь `default`

Форма:

```text
switch name(params): returnType {
    condition => expression
    ...
    default => expression
}
```

---

# 3. Поведение

- Условия проверяются сверху вниз.
- Первое истинное условие выбирается.
- Если ни одно условие не подошло — используется `default`.
- Fallthrough отсутствует.

---

# 4. Расширим HelloWorld

Добавим классификацию аргументов по длине.

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
    for this.args as name {
        print name + " -> " + self.classify(name.length)
    }
}

public static switch classify(len: Int): String {
    len == 0 => "empty"
    len < 5 => "short"
    len < 10 => "medium"
    default => "long"
}
```

---

# 5. Почему это удобно

Switch-функции:

- компактнее `if`
- декларативны
- легко читаются
- не содержат лишних `return`

Это особенно полезно, когда:

- функция — это чистое правило выбора
- нет побочных эффектов
- важна читаемость

---

# 6. Expression vs Block

Если нужно более сложное действие, можно использовать блок:

```forge
public static switch describe(n: Int): String {
    n > 100 => {
        print "Large number"
        return "big"
    }
    default => "small"
}
```
