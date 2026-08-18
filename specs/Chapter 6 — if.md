Forge использует `if` для условного выполнения.

---

## Простейший `if`

```forge
class

public static main(args: String[]): Void
{
    const value: Int = 10

    if value > 5 {
        print "Value is greater than 5"
    }
}
```

Условие должно возвращать `Bool`.

---

## `if` / `else`

```forge
class

public static main(args: String[]): Void
{
    const value: Int = 3

    if value > 5 {
        print "Greater than 5"
    } else {
        print "5 or less"
    }
}
```

---

## `elseif`

```forge
class

public static main(args: String[]): Void
{
    const value: Int = 5

    if value > 5 {
        print "Greater"
    } elseif value == 5 {
        print "Equal"
    } else {
        print "Less"
    }
}
```

`elseif` — это часть конструкции `if`.  
Это не вложенный `if`, а продолжение цепочки.

---

## Правила  
- Блок `{}` обязателен.
- `elseif` может повторяться несколько раз.
- `else` может быть только один и всегда последним.
