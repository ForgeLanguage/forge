Forge использует модификаторы видимости, чтобы управлять доступом к типам и их членам.

Видимость применяется к:
- `class`
- `trait`
- `interface`
- `struct`
- `enum`
- полям
- функциям
- `static` членам

---

# 1. Уровни видимости

| Модификатор | Доступ                        |
| ----------- | ----------------------------- |
| `public`    | из любого пакета              |
| `internal`  | только внутри текущего пакета |
| `private`   | только внутри текущего файла  |

---

# 2. Видимость по умолчанию

Если модификатор не указан, используется `internal`.

```forge
class Parser {
}
```

Эквивалентно:

```forge
internal class Parser {
}
```

То же правило применяется к членам:

```forge
class Parser {
    buffer: String
}
```

Эквивалентно:

```forge
internal class Parser {
    internal buffer: String
}
```

---

# 3. Public API

`public` делает тип или член частью внешнего API пакета.

```forge
public class Client {
    public request(): Response {
        ...
    }
}
```

Такой тип можно импортировать из другого пакета:

```forge
use http.Client
```

---

# 4. Internal API

`internal` доступен только внутри пакета.

```forge
internal class Parser {
    public parse(): Void {
        ...
    }
}
```

Даже если метод `parse` объявлен как `public`, сам тип `Parser` остаётся `internal`.

Значит, снаружи пакета он недоступен.

---

# 5. Private API

`private` доступен только внутри файла.

```forge
public class Client {
    private cache: Cache

    private resetCache(): Void {
        ...
    }
}
```

Другие файлы, даже в том же пакете, не имеют доступа к `private` членам.

---

# 6. Итоговая видимость члена

Итоговая доступность члена ограничивается и видимостью члена, и видимостью типа.

```text
effective_visibility(member) =
    min(visibility(type), visibility(member))
```

---

## Пример: internal тип + public член

```forge
internal class Parser {
    public parse(): Void {
        ...
    }
}
```

`parse()` публичен только в пределах пакета, потому что сам `Parser` не виден снаружи.

---

## Пример: public тип + internal член

```forge
public class Client {
    internal debug(): Void {
        ...
    }
}
```

`Client` виден из других пакетов, но `debug()` доступен только внутри пакета.

---

# 7. Утечка закрытых типов

Нельзя использовать менее видимый тип в более видимом API.

---

## Нельзя

```forge
internal class Parser {
}

public class Client {
    public parser(): Parser {
        ...
    }
}
```

Ошибка: `Parser` — `internal`, но метод `parser()` — `public`.

---

## Можно

```forge
internal class Parser {
}

public class Client {
    internal parser(): Parser {
        ...
    }
}
```

Теперь метод тоже `internal`, и закрытый тип не утекает наружу.

---

# 8. Visibility и `use`

`use` может импортировать только те символы, которые доступны из текущего пакета.

```forge
use http.Client   // ✅ если Client public
use http.Parser   // ❌ если Parser internal
```

---

# 9. Итог

- `public` — внешний API
- `internal` — API пакета
- `private` — API файла
- по умолчанию всё `internal`
- член не может быть доступнее своего типа
- закрытые типы не могут появляться в более открытом API