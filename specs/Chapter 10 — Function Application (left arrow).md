# 10. Function Application

Forge поддерживает обычный вызов функции через круглые скобки:

```forge
print("Hello")
```

Квадратные скобки после callable-выражения означают массовый вызов
(`bulk call`): функция вызывается для каждого элемента коллекции, а результат
собирается в массив.

```forge
const stringNumbers = ["1", "2", "3"]
const parsed: Int[] = Int.parse[stringNumbers]
```

Это эквивалентно:

```forge
const parsed: Int[] = [
    Int.parse(stringNumbers[0]),
    Int.parse(stringNumbers[1]),
    Int.parse(stringNumbers[2]),
]
```

Если функция принимает несколько аргументов, элементы bulk call могут быть
аргументными пакетами:

```forge
const vectors: Vector2Int[] = Vector2Int.new[(0, 0), (1, 1)]
```

Это эквивалентно:

```forge
const vectors: Vector2Int[] = [
    Vector2Int.new(0, 0),
    Vector2Int.new(1, 1),
]
```

Обычный вызов функции с массивом как единственным аргументом остается вызовом
через круглые скобки:

```forge
Vector2Int.normalize(vectors)
```

Массовый вызов этой же функции пишется через квадратные скобки:

```forge
const normalizedVectors: Vector2Int[] = Vector2Int.normalize[vectors]
```

## Indexing vs Bulk Call

Квадратные скобки имеют два разных значения, которые различаются по выражению
слева:

```forge
numbers[0]              // indexing
Int.parse[stringValues] // bulk call
```

Если слева коллекция, это индексирование. Если слева callable-выражение
(функция, метод, конструктор или callable value), это bulk call.

## Generator Bulk Call

Если перед квадратными скобками указать `generator`, массовый вызов создает
ленивый генератор вместо массива.

```forge
const parsed = Int.parse generator[stringNumbers]
```

В этом случае `parsed` вызывает `Int.parse` лениво для каждого значения из
`stringNumbers`.

Генераторный bulk call можно использовать в цепочках:

```forge
save[
    User.new generator[
        safeParse(filename)
    ]
]
```

В этом примере:

- `safeParse(filename)` отдаёт поток строк
- `User.new generator[...]` лениво создаёт пользователей из строк
- `save[...]` массово вызывает `save` для каждого созданного пользователя

## Execution Strategy

`bulk call` описывает одну общую форму: применить callable-выражение к
элементам коллекции.

Стратегия исполнения задаётся модификатором bulk call:

```forge
process[items]          // sync bulk map
process generator[items] // lazy bulk map
process task[items]     // async task bulk map
```

`process[items]` выполняет вызовы сразу и возвращает массив результатов,
если функция возвращает значение.

`process task[items]` использует ту же форму обхода коллекции, но возвращает
`TaskCollection<T>`. Результаты и declared outcomes становятся доступными
на точке `await`, например через `.all().await()`.

Таким образом sync bulk call и async task bulk call разделяют общий механизм
bulk-map, но отличаются моментом выполнения и обработкой outcomes.

## Errors

`catch` можно применить к bulk call. Обработчик применяется к каждому
отдельному вызову.

```forge
const parsed = catch Int.parse[stringNumbers] {
    error: ParseError => 0
}
```

Эквивалентная модель:

```forge
const parsed: Int[] = []

for stringNumbers as num {
    parsed.add(catch Int.parse(num) {
        error: ParseError => 0
    })
}
```
