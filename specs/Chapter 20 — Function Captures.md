Отлично, тогда фиксируем модель **closure + ownership** в простом и безопасном виде:

---

# 📌 Итог по Function Captures в Forge

## 1. Захват по умолчанию

Стрелочные функции захватывают внешний контекст **по borrow**:

```forge
const prefix: String = "Hello"
const greet = name => print prefix + ", " + name
```

- безопасно
- без копирования (если не нужно)
- без владения

---

## 2. Owning-ресурсы не захватываются

```forge
const file: File = File.open("x.csv")
const fn = () => file.readLine() // ❌ ошибка
```

Причина:
- непонятно, кто владеет `file`
- можно сломать lifecycle (`dispose` / `terminate`)

---

## 3. Работа с owning-значениями — только через параметры

### Borrow

```forge
const fn = (file: File): String => file.readLine()

const line = fn(file)
file.dispose()
```

---

### Ownership (`take` + `move`)

```forge
const fn = (take file: File): Void => {
    file.dispose()
}

fn(move file)
// file moved
```

---

## 4. Ограничение на возврат closure

Нельзя вернуть closure, если она захватывает borrow из текущей области:

```forge
public makePrinter(): func(): Void {
    const message: String = "Hello"

    return () => print message // ❌
}
```

---

## 5. Разрешённый вариант

Если значение безопасно (value-like):

```forge
public makePrinter(message: String): func(): Void {
    return () => print message // ✅
}
```

---

## 6. Что считаем безопасным для захвата

Можно захватывать:
- value types (`Int`, `Float`, и т.д.)
- строки (immutable, value-like)
- immutable значения

---

# 🧠 Философия

- простота > гибкость
- явность > магия
- ownership — только явно через `take`-параметры и `move`-аргументы

---

# 🔥 Итог

Closure в Flow:

- удобные для обычного кода
- безопасные по умолчанию
- без скрытых владений
    
- без сложных lifetime-правил
