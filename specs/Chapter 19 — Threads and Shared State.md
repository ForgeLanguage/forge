

Forge разделяет асинхронность и многопоточность.
- Асинхронность (`Task`) — кооперативная, без потоков
- Потоки (`Thread`) — реальный параллелизм

Потоки используются для выполнения CPU-bound задач и параллельной работы.

---

# 1. Создание потока

```forge
const t = Thread.start(() => compute())
```

- создаёт новый поток
- запускает функцию
- возвращает `Thread<T>`

---

## С возвратом результата

```forge
const t = Thread.start(() => compute())
const result = t.join()
```

---

# 2. Thread

```forge
class Thread<T>
{
    join(): T
}
```

- `join()` блокирует текущий поток
- возвращает результат выполнения

---

# 3. Передача владения

Предпочтительный способ работы с потоками — передача владения:

```forge
Thread.start(move data)
```

- объект полностью передаётся в поток
- в текущем потоке становится недоступен
- не требует `lock`
- гарантирует отсутствие гонок

---

# 4. Shared state

Объект становится **shared**, если используется более чем в одном потоке.

---

## Главное правило

> Shared-объект нельзя читать или изменять вне `lock`

---

## Пример

```forge
const user = User.new()

Thread.start(() => {
    lock user {
        user.name = "Bob"
    }
})
```

---

## Нарушение

```forge
user.name = "Alice"   // ❌ если user shared
```

Даже в исходном потоке.

---

# 5. lock

```forge
lock obj {
    ...
}
```

Гарантии:
- эксклюзивный доступ
- защищает объект и всё, чем он владеет (ownership graph)

---

## Внутренности объекта

```forge
lock user {
    user.cache.set("x", "y")   // допустимо
}
```

Если `cache` принадлежит `user`.
## Shared, Borrow и `lock`

### Главное правило

Если объект становится `shared`, доступ к нему разрешён **только внутри `lock`**.

Это касается:
- чтения
- записи
- вызова методов
- доступа к полям
- доступа к внутренним объектам
- borrow-ссылок на его внутренности
### Когда объект становится shared

Объект становится `shared`, если он используется более чем в одном потоке.

```forge
const user: User = User.new()

Thread.start(() => {
    lock user {
        user.name = "Bob"
    }
})

// user теперь shared
```

После этого даже исходный поток не может обращаться к `user` напрямую.

```forge
print user.name   // ❌ shared object requires lock
```

Нужно:

```forge
lock user {
    print user.name
}
```
### Borrow на shared-объект

Если `user` shared, то borrow на его внутренности тоже считается shared-зависимым.

```forge
const cache = user.cache   // ❌ нельзя вне lock, user shared
```

Правильно:

```forge
lock user {
    user.cache.set("x", "y")
}
```

### Нельзя выносить borrow из lock

```forge
var cache: Cache

lock user {
    cache = user.cache   // ❌ borrow escapes lock
}

cache.set("x", "y")
```

Так нельзя, потому что `cache` — внутренняя часть защищённого графа `user`.

### Что можно выносить из lock

Можно выносить только значения, не связанные с защищённым mutable-графом:

```forge
var name: String

lock user {
    name = user.name
}

print name   // ✅ string value-like
```

Разрешено выносить:
- scalar value types
- immutable value-like значения (`String`)
- копии
- новые объекты, не связанные с locked-графом

### Lock защищает ownership graph

```forge
lock user {
    user.cache.set("x", "y")   // ✅ cache принадлежит user
}
```

`lock user` защищает:
- `user`
- поля `user`
- объекты, которыми `user` владеет транзитивно

Не защищает:
- внешние объекты
- borrow-ссылки на чужие объекты
- shared-объекты, не принадлежащие `user`

## Запрещено

Выносить внутренние ссылки:

```forge
var cache

lock user {
    cache = user.cache   // ❌ нельзя
}
```

---

# 6. Ownership внутри lock

`lock obj` защищает:
- сам объект
- все объекты, которыми он владеет транзитивно

Не защищает:
- borrow-ссылки
- внешние объекты

---

# 7. await в потоках

`await()` можно использовать внутри потоков:

```forge
Thread.start(() => {
    const data = fetch().await()
    process(data)
})
```

Каждый поток может иметь собственный event loop.

---

## await внутри lock

```forge
lock user {
    fetch().await()   // допустимо
}
```

Это разрешено, но:
- блокировка удерживается во время ожидания
- может привести к задержкам и дедлокам

> Использование — на ответственности программиста

---

# 8. Потоки и async

- async не использует потоки
- `await()` блокирует текущий поток

```forge
const data = fetch().await()
```

---

# 9. Гарантии модели

Forge гарантирует:
- нельзя обращаться к shared-объекту без `lock`
- нельзя вынести внутренности объекта из `lock`
- безопасная передача через `take`-параметры и `move`-аргументы
- отсутствие гонок при корректном использовании

---

# 10. Философия

- безопасность по умолчанию
- shared state — явно
- синхронизация — явно
- предпочтение — явная передача владения (`move` в `take`-параметр)

---

# 11. Итог

- `Thread.start()` — запуск потока
- `join()` — ожидание результата
- `take` + `move` — безопасная передача владения
- shared state — только через `lock`
- `lock` защищает ownership graph
- `await()` разрешён в потоках
- `await()` внутри `lock` — допустим, но опасен
