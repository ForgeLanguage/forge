Forge использует два типа циклов:
- декларативные циклы (`for`)
- условные циклы (`while`, `do while`)

Для управления выполнением используются:
- `break` — завершить цикл
- `next` — перейти к следующей итерации

---

# 1. Декларативные циклы (`for`)

## 1.1 Диапазоны

```forge
for 0..5 {
    print "Hello"
}
```

Диапазон `0..5` означает от `0` до 4

---

## 1.2 Счётчик

```forge
for 0..5 as i {
    print i
}
```

---

## 1.3 Короткая форма

```forge
for 5 as i {
    print i
}
```

Эквивалентно:

```forge
for 0..5 as i { }
```

---

## 1.4 Коллекции

```forge
for items as item {
    print item
}
```

Источником `for` может быть не только коллекция, но и генератор:

```forge
for numbers() as n {
    print n
}
```

Если генератор объявлен как `numbers(): Int`, переменная `n` имеет тип `Int`.

---

## 1.5 С индексом

```forge
for items as i, item {
    print i + ": " + item
}
```

---

## 1.6 Условие

```forge
for 0..10 as i if i % 2 == 0 {
    print i
}
```

---

# 2. Цепочные циклы

Forge позволяет объединять вложенные циклы в одну конструкцию.

```forge
for rows as row,
    row as cell {
    print cell
}
```

Эквивалент:

```forge
for rows as row {
    for row as cell {
        print cell
    }
}
```

---

## 2.1 Несколько уровней

```forge
for worlds as world,
    world.countries as country,
    country.cities as city {
    print city.name
}
```

---

## 2.2 Условия в цепочке

```forge
for rows as row if row.isValid(),
    row as cell if cell.value > 0 {
    print cell
}
```

Эквивалент:

```forge
for rows as row {
    if row.isValid() {
        for row as cell {
            if cell.value > 0 {
                print cell
            }
        }
    }
}
```

---

# 3. Уровни итерации

В цепочке:

```forge
for a as x,
    x as y,
    y as z {
}
```

уровни:

- `x` — первый
    
- `y` — второй
    
- `z` — третий
    

---

# 4. next

```forge
next
```

Переходит к следующей итерации цикла. Аналог continue в других языках.

---

## 4.1 next с уровнями

```forge
next level
```

означает:

> перейти к следующему значению указанного уровня

---

## Пример

```forge
for users as user,
    user.orders as order,
    order.items as item {

    if not order.isValid() {
        next user
    }

    if item.isBroken() {
        next order
    }

    print item
}
```

---

## Семантика

```forge
next item   // следующий item
next order  // следующий order
next user   // следующий user
```

---

# 5. break

```forge
break
break value
```

- завершает ближайший цикл полностью
- в statement-цикле используется без значения
- в expression-цикле `break value` задаёт результат цикла
- `break` без значения в expression-цикле выбирает fallback

---

## Пример

```forge
for 0..10 as i {
    if i == 5 {
        break
    }
}
```

В statement-цикле `break value` является ошибкой.

---

# 6. Циклы как выражения

`for`, `while` и `do while` могут вычислять значение. Новый вид цикла для
этого не вводится.

```forge
const user = for users as user {
    if user.id == id {
        break user
    }
} else null
```

`else` задаёт fallback. Он вычисляется ровно один раз, если цикл завершился
без `break value`: источник `for` исчерпан, условие `while` стало ложным или
выполнен `break` без значения.

```forge
const value = while queue.hasItems() {
    const candidate = queue.take()

    if candidate.isValid() {
        break candidate
    }

    if candidate.isTerminal() {
        break
    }
} else defaultValue
```

## 6.1 Nullable fallback

Явный fallback можно опустить, только когда окружающий контекст ожидает
nullable-тип. В этом случае используется неявный `else null`.

```forge
const user: User? = for users as user {
    if user.id == id {
        break user
    }
}
```

Без явного fallback или ожидаемого nullable-типа expression-loop является
ошибкой:

```forge
const user = for users as user { // ошибка
    if user.id == id {
        break user
    }
}
```

## 6.2 Тип результата

- все значения `break value` и fallback должны приводиться к общему типу;
- при ожидаемом типе каждое из этих значений должно быть ему присваиваемо;
- `else null` вместе с `break value: T` даёт результат `T?`;
- fallback и выбранное значение вычисляются не более одного раза.

## 6.3 Вложенность и цепочные for

`break` относится к ближайшему синтаксическому циклу. Цепочный `for`
считается одним циклом, поэтому `break value` завершает всю цепочку. Явно
вложенный цикл создаёт отдельную цель для `break`.

## 6.4 Ownership

Значение `break value` подчиняется обычным правилам ownership и escape.
Borrowed resource нельзя неявно вернуть как owned-результат; перенос owned
значения требует той же явной операции `move`, что assignment или return.

---

# 7. Ограничения

- `break level` — не поддерживается
- `next` может использовать только переменные цикла
- уровни определяются порядком объявления

---

# 7. switch

`switch` выбирает одну ветку по значению выражения.

```forge
switch response.status {
    FeedStatus.Ok => {
        okCount = okCount + 1
    }
    FeedStatus.FeedNoContent => noContentCount = noContentCount + 1
    default => print "Unknown status"
}
```

Особенности:
- слово `case` не используется
- ветка записывается как `pattern => statement` или `pattern => { ... }`
- `default => ...` необязателен и должен быть последней веткой
- после выполнения выбранной ветки `switch` завершается; fallthrough нет
- `break` внутри `switch` не нужен и не поддерживается как часть оператора `switch`

Семантически statement-форма эквивалентна цепочке сравнений:

```forge
if response.status == FeedStatus.Ok {
    okCount = okCount + 1
} elseif response.status == FeedStatus.FeedNoContent {
    noContentCount = noContentCount + 1
} else {
    print "Unknown status"
}
```

В будущем `switch` сможет использоваться как выражение, поэтому ветки уже имеют единую форму `pattern => body`.

---

# 8. Условные циклы

## 8.1 while

```forge
while condition {
    ...
}
```

---

## Пример

```forge
let i = 0

while i < 5 {
    print i
    i = i + 1
}
```

---

## 7.2 do while

```forge
do {
    ...
} while condition
```

---

## Пример

```forge
let i = 0

do {
    print i
    i = i + 1
} while i < 5
```

---

# 8. next и break в while

```forge
while true {

    if shouldSkip {
        next
    }

    if shouldStop {
        break
    }

    doWork()
}
```

---

# 9. Комбинация: условие + цепочный цикл

Цепочный `for` можно использовать внутри `while`.

```forge
while hasMoreData() {

    for users as user,
        user.orders as order if order.isValid(),
        order.items as item {

        if item.isBroken() {
            next order
        }

        process(item)
    }
}
```

---

## Более сложный пример

```forge
while server.isRunning() {

    for connections as conn if conn.isAlive(),
        conn.requests as req {

        if req.isInvalid() {
            next conn
        }

        if req.isCritical() {
            break
        }

        handle(req)
    }
}
```

---

# 10. Философия

Forge:

- использует `for` для декларативной итерации
- использует `while` для неопределённых циклов
- объединяет вложенность через цепочки
- делает `next` основным инструментом управления
- делает `break` простым и предсказуемым

---

# 11. Итог

- `for` — декларативный цикл
- цепочки заменяют вложенность
- `next level` управляет глубиной
- `break` завершает всё
- `while` / `do while` — для условных сценариев
