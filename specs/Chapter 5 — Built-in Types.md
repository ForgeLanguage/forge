Forge предоставляет набор встроенных типов, доступных без объявления и импорта.

---

# 1. Числовые типы

## Целые числа

|Тип|Размер|
|---|---|
|`Byte`|8 бит|
|`UByte`|8 бит|
|`Short`|16 бит|
|`UShort`|16 бит|
|`Int`|32 бит|
|`UInt`|32 бит|
|`Long`|64 бит|
|`ULong`|64 бит|

Пример:

```forge
const age: Int = 25
const count: UInt = 100
```

---

## Числа с плавающей точкой

|Тип|Размер|
|---|---|
|`Float`|32 бит|
|`Double`|64 бит|

Пример:

```forge
const pi: Double = 3.1415926535
```

---

# 2. Bool

Логический тип.

Допустимые значения:

```forge
true
false
```

Пример:

```forge
const isAdmin: Bool = true
```

---

# 3. String

Строковый тип.

Пример:

```forge
const name: String = "Forge"
```

Строки являются отдельным встроенным типом.

Несмотря на хранение данных в куче, строки передаются по значению и ведут себя как value-type.

---

# 4. `toString()`

Все primitive value types поддерживают метод:

```forge
toString(): String
```

Примеры:

```forge
const text = age.toString()
const flag = isAdmin.toString()
const label = name.toString()
```

Для `String` метод возвращает саму строку. Для чисел и `Bool` создаётся строковое представление значения.

---

# 5. Null

Forge поддерживает специальное значение:

```forge
null
```

`null` означает отсутствие значения.

---

## Nullable-типы

Тип может быть объявлен nullable через `?`.

```forge
const age: Int? = null
const user: User? = null
```

Без `?` присваивание `null` запрещено:

```forge
const age: Int = null // ❌ ошибка
```

---

## Проверка на null

Перед использованием nullable-значения необходимо:

- проверить его на `null`
    
- либо использовать null-safe оператор
    

Пример:

```forge
if user != null {
    print user.name
}
```

---

## Null-safe доступ

Оператор `?.` позволяет безопасно обращаться к членам nullable-объекта.

```forge
const name: String? = user?.name
```

Если:

```forge
user == null
```

то результатом выражения будет:

```forge
null
```

---

## Null-coalescing оператор

Оператор `??` возвращает значение справа, если слева находится `null`.

```forge
const name: String = user?.name ?? "Unknown"
```

Эквивалентно:

```forge
const name: String =
    user?.name != null
        ? user?.name
        : "Unknown"
```

---

## Сравнение с null

Правила сравнения:

```forge
null == null      // true
null != null      // false
```

Любое сравнение `null` с не-null значением возвращает:

```forge
null == value     // false
null != value     // true
```

Пример:

```forge
null == 0         // false
null == false     // false
null == ""        // false
```

---

# 6. Arrays

Dynamic array обозначается через `[]`.

```forge
const numbers: Int[] = [1, 2, 3]
```

Fixed-size array указывает длину в квадратных скобках:

```forge
const bytes: Int[3] = [10, 20, 30]
```

Длина fixed-size array должна быть compile-time integer constant expression:

```forge
const a: Int[2 + 3] = [1, 2, 3, 4, 5] // ✅ Int[5]
const b: Int[count] = [1, 2, 3]       // ❌ count не вычисляется на этапе компиляции
```

Массивы могут содержать любые типы:

```forge
const names: String[] = ["Alice", "Bob"]
const users: User[] = [User.new(), User.new()]
```

Пустой array literal требует явный тип:

```forge
const inferred = []       // ❌ неизвестен тип элементов
const values: Int[] = []  // ✅
```

Для fixed-size array количество элементов literal должно совпадать с размером:

```forge
const ok: Int[2] = [1, 2]   // ✅
const bad: Int[3] = [1, 2]  // ❌ ожидалось 3 элемента
```

---

## Доступ по индексу

```forge
const first: Int = numbers[0]
```

---

## Присваивание по индексу

Элемент динамического или fixed-size массива можно заменить по индексу:

```forge
var numbers: Int[] = [1, 2]
numbers[0] = 10
```

Тип значения справа должен быть присваиваем типу элемента массива.

---

## Размер массива

```forge
const count: Int = numbers.len
```

---

## Создание массива заданной длины

`Array.new<T>(length)` создаёт динамический массив `T[]` с длиной и ёмкостью
`length`:

```forge
var numbers: Int[] = Array.new<Int>(2)
numbers[0] = 20
numbers[1] = 22
```

Эта форма предназначена для буферов и реализации коллекций в stdlib. Элементы
нужно записать перед чтением.

---

# 6. Function

Функции являются полноценными значениями.

Пример:

```forge
const sum: Function<Int, Int, Int> =
    (a: Int, b: Int) => a + b
```

Функции можно:

- сохранять в переменные
    
- передавать в параметры
    
- возвращать из функций
    
---

# 7. Значимые и ссылочные типы

Встроенные скалярные типы являются value-types:

```forge
Bool
Byte
UByte
Short
UShort
Int
UInt
Long
ULong
Float
Double
```

Объекты являются reference-types.

Строки занимают особое положение:

- данные строки хранятся в куче
    
- строки передаются по значению
    
- строки ведут себя как immutable value-type
    

---

# Что дальше?

Теперь мы знаем базовые типы языка.

В следующей главе разберём выражения и операторы:

- арифметические операции
    
- логические операции
    
- сравнения
    
- тернарный оператор
    
- присваивание
    
- приоритет операций
