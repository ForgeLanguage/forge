Вернёмся к нашему примеру.

```forge
class

public static main(args: String[]): Void
{
    print "Hello, World!"
}
```

Теперь сделаем его немного живее.

---

## Использование выражений

```forge
class

public static main(args: String[]): Void
{
    const name: String = "World"
    print "Hello, " + name + "!"
}
```

Здесь появляется выражение:

```forge
"Hello, " + name + "!"
```

Оператор `+` для строк выполняет конкатенацию.

---

## Арифметика

Выражения работают не только со строками.

```forge
class

public static main(args: String[]): Void
{
    const a: Int = 5
    const b: Int = 3

    const sum: Int = a + b

    print "Sum = " + sum
}
```

Операторы:

```
+  -  *  /  %
```

Работают стандартно.

---

## Приоритет операций

```forge
class

public static main(args: String[]): Void
{
    const value: Int = 2 + 3 * 4
    print value
}
```

Результат будет:

```
14
```

Потому что `*` имеет более высокий приоритет.

Скобки меняют порядок:

```forge
const value: Int = (2 + 3) * 4
```

---

## Булевы выражения

```forge
class

public static main(args: String[]): Void
{
    const a: Int = 10
    const isBig: Bool = a > 5

    print isBig
}
```

Операторы сравнения:

```
==  !=  <  >  <=  >=
```

Логические операторы:

```
&&  ||  !
```

---

## Оператор принадлежности

Оператор `in` проверяет, содержится ли значение в другом значении.

```forge
if 1 in someArrayOfInts {
    print "found"
}
```

Оператор `not in` проверяет обратное условие:

```forge
if "someString" not in anyString {
    print "not found"
}
```

Под капотом `in` вызывает метод `contains` из `ContainsTrait`.

---

## Member block

Если нужно выполнить несколько операций над одним объектом, можно использовать member block:

```forge
user.{
    age = 42
    name = "Vasya"
    save()
}
```

Это эквивалентно последовательным обращениям к тому же receiver:

```forge
user.age = 42
user.name = "Vasya"
user.save()
```

Внутри блока допустимы обращения к полям, assignment и вызовы методов receiver.

---

## Nullable narrowing

К полям nullable class value нельзя обращаться без non-null проверки:

```forge
this.profile.firstName // ❌ profile: Profile?
```

В guarded ветке значение считается non-null:

```forge
return this.profile ? this.profile.firstName : ""
return this.profile != null ? this.profile.firstName : ""
```

Для одиночного nullable access можно использовать `?.`. Результат такого выражения nullable:

```forge
const firstName: String? = this.profile?.firstName
```

Для `if` narrowing действует только внутри соответствующей ветки:

```forge
if this.profile {
    print this.profile.firstName
}
```

```forge
value in container
```

эквивалентно:

```forge
container.contains(value)
```

А:

```forge
value not in container
```

эквивалентно:

```forge
!container.contains(value)
```

Следовательно, правый операнд должен иметь `ContainsTrait` и поддерживать вызов `contains` для типа левого операнда.

# Тернарный оператор и Null-coalescing

```
const i: Int? = null
print i is null ? "unknown" : i

// или

print i ?? "unknown"
```
