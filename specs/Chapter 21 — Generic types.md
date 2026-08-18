Дженерики позволяют создавать типы и функции, работающие с различными типами данных без дублирования кода.

---

# 1. Зачем нужны дженерики

Без дженериков пришлось бы создавать отдельный тип для каждого варианта:

```forge
data IntBox {
    public value: Int
}

data StringBox {
    public value: String
}
```

С дженериками достаточно одного определения:

```forge
data Box<T> {
    public value: T
}
```

Использование:

```forge
const a: Box<Int> = Box<Int> {
    value: 10
}

const b: Box<String> = Box<String> {
    value: "Hello"
}
```

---

# 2. Generic типы

Параметры типа указываются в угловых скобках.

```forge
data Pair<T1, T2> {
    public first: T1
    public second: T2
}
```

Пример:

```forge
const pair: Pair<String, Int> = Pair<String, Int> {
    first: "Age",
    second: 25
}
```

---

# 3. Generic функции

Дженерики можно использовать и в функциях.

```forge
public static identity<T>(value: T): T {
    return value
}
```

Использование:

```forge
const a: Int = identity(10)
const b: String = identity("Forge")
```

В большинстве случаев тип выводится автоматически.

Текущий компилятор поддерживает этот базовый вариант generic-функций: параметры
типа объявляются после имени функции, а значения выводятся из типов аргументов.

При необходимости его можно указать явно:

```forge
const value: Int = identity<Int>(10)
```

Явное указание параметров типа при вызове поддерживается для generic-функций.

---

# 4. Ограничения типов

Иногда необходимо потребовать от типа определённое поведение.

Для этого используются ограничения.

```forge
interface Printable {
    public print(): Void
}
```

```forge
public static show<T: Printable>(value: T): Void {
    value.print()
}
```

Теперь функцию можно вызывать только для типов, реализующих `Printable`.

---

# 5. Несколько ограничений

Тип может удовлетворять нескольким контрактам одновременно.

```forge
public static save<T: Printable + Storable>(value: T): Void {
    value.print()
    value.save()
}
```

Тип обязан удовлетворять всем указанным ограничениям.

---

# 6. Ограничения в типах

Ограничения можно использовать и при объявлении generic типов.

```forge
data Repository<T: Entity> {
    private items: T[] = []
}
```

Теперь в `Repository` можно хранить только типы, реализующие `Entity`.

---

# 7. Значения по умолчанию

Параметр типа может иметь значение по умолчанию.

```forge
data Cache<TKey = String, TValue = String> {
    ...
}
```

Использование:

```forge
const cache: Cache = Cache.new()
```

Эквивалентно:

```forge
const cache: Cache<String, String> = Cache.new()
```

---

# 8. Ограничения и значения по умолчанию

Значение по умолчанию должно удовлетворять всем ограничениям.

```forge
data Box<T: Printable = DefaultPrinter> {
    ...
}
```

Если `DefaultPrinter` не реализует `Printable`, код не скомпилируется.

---

# 9. Generic и nullable типы

Nullable-модификатор применяется после подстановки типа.

```forge
data Box<T> {
    public value: T?
}
```

Пример:

```forge
const box: Box<Int> = Box<Int> {
    value: null
}
```

Тип поля будет:

```forge
Int?
```

---

# 10. Инвариантность

Generic-типы в Forge инвариантны.

Предположим:

```forge
interface Animal { }
interface Dog : Animal { }
```

Тогда:

```forge
const dogs: List<Dog> = ...
const animals: List<Animal> = dogs
```

недопустимо:

```forge
// ❌ ошибка
```

Даже если `Dog` совместим с `Animal`.

Это предотвращает множество ошибок времени выполнения и упрощает систему типов.

---

# 11. Ограничения версии 1

В первой версии языка отсутствуют:

- covariance (`out`)
    
- contravariance (`in`)
    
- специализация шаблонов
    
- частичная специализация
    

Эти возможности могут появиться в будущих версиях языка.

---

# Что дальше?

Теперь мы умеем создавать универсальные типы и функции.

В следующей главе разберём пространства имён, пакеты и директиву `use`.
