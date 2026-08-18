# Асинхронное программирование

ForgeLang поддерживает асинхронное программирование с помощью модификатора `async`, типов `Task<T>` и `TaskCollection<T>`, а также оператора `await`.

Асинхронные функции позволяют выполнять длительные операции (сетевые запросы, файловый ввод-вывод, обращения к базам данных и другие операции ввода-вывода) без блокировки текущего потока выполнения.

## Асинхронные функции

Асинхронная функция объявляется с помощью модификатора `async`.

```forge
public async fetchUser(id: Int): User, NetworkError! {
    const response = await Http.get("/users/" + id)
    return User.fromJson(response.body)
}
```

Несмотря на то, что функция объявляет тип результата как `User`, её вызов возвращает объект типа:

```forge
Task<User>
```

Например:

```forge
const task = fetchUser(42)
```

Здесь выполнение операции уже началось, однако результат ещё не получен.

## Await

Оператор `await` ожидает завершения задачи и возвращает её результат.

```forge
const user = await fetchUser(42)
```

Оператор `await` может использоваться только внутри асинхронных функций.

Следующий код недопустим:

```forge
public loadUser(id: Int): User {
    const user = await fetchUser(id)
    return user
}
```

## Task

Тип `Task<T>` представляет асинхронную операцию, которая в будущем завершится значением типа `T`.

```forge
const task: Task<User> = fetchUser(42)
```

Задачи можно сохранять в переменных, передавать между функциями и объединять с другими задачами.

## Task.await()

В синхронном коде результат задачи можно получить с помощью метода `await()`.

```forge
const user = fetchUser(42).await()
```

Метод блокирует текущий поток выполнения до завершения задачи.

Это позволяет использовать асинхронные функции из обычного синхронного кода.

Например:

```forge
public loadUser(id: Int): User {
    return fetchUser(id).await()
}
```

## Параллельное выполнение

Создание нескольких задач позволяет выполнять операции параллельно.

```forge
const userTask = fetchUser(1)
const settingsTask = fetchSettings(1)

const user = await userTask
const settings = await settingsTask
```

Обе операции могут выполняться одновременно.

## Массовое создание задач

Forge поддерживает создание задач для каждого элемента коллекции.

```forge
const urls = [
    "https://example.com",
    "https://forge-lang.org",
    "https://openai.com"
]

const tasks = downloadPage task[urls]
```

Тип результата:

```forge
TaskCollection<String>
```

Каждый элемент коллекции обрабатывается независимо.

## TaskCollection

Тип `TaskCollection<T>` представляет набор задач одного типа.

### all()

Ожидает завершения всех задач и возвращает массив результатов.

```forge
const pages: String[] =
    await downloadPage task[urls].all()
```

Тип результата:

```forge
Task<String[]>
```

---

### any()

Завершается после получения первого успешного результата.

```forge
const page: String =
    await downloadPage task[urls].any()
```

Тип результата:

```forge
Task<String>
```

---

### first()

Возвращает результат первой завершившейся задачи.

```forge
const page: String =
    await downloadPage task[urls].first()
```

---

### last()

Ожидает завершения всех задач и возвращает результат последней завершившейся задачи.

```forge
const page: String =
    await downloadPage task[urls].last()
```

---

### concurrency()

Ограничивает количество одновременно выполняющихся задач.

```forge
const pages: String[] =
    await downloadPage
        task[urls]
        .concurrency(10)
        .all()
```

В каждый момент времени будет выполняться не более десяти задач.

Это особенно полезно при работе с большим количеством сетевых запросов или файлов.

## Обработка ошибок

Асинхронные функции используют ту же модель ошибок, что и обычные функции.

```forge
public async fetchUser(id: Int): User, NetworkError! {
    ...
}
```

Ошибки могут быть обработаны через `catch`.

```forge
const user = catch await fetchUser(42) {
    error: NetworkError => User.guest()
}
```

Также можно оборачивать саму функцию:

```forge
const safeFetchUser = catch fetchUser {
    error: NetworkError => User.guest()
}
```

После оборачивания новая функция больше не возвращает ошибку.

```forge
const user = await safeFetchUser(42)
```

## Синхронные и асинхронные версии функций

Библиотеки могут предоставлять как синхронную, так и асинхронную версию одной операции.

```forge
public readText(path: String): String, IoError!
```

```forge
public async readText(path: String): String, IoError!
```

Асинхронная версия является основной реализацией.

Синхронная версия может быть автоматически сгенерирована компилятором.

При этом синхронная и асинхронная версии не обязаны иметь разные имена.
Модификатор `async` является частью сигнатурной семантики функции.

Например, библиотека может объявить только асинхронную операцию:

```forge
public async readText(path: String): String, IoError! {
    ...
}
```

Компилятор может предоставить синхронную версию с тем же именем как
тонкую обёртку поверх асинхронной реализации.

Концептуально следующая функция:

```forge
public async readText(path: String): String, IoError! {
    ...
}
```

эквивалентна:

```forge
public readText(path: String): String, IoError! {
    return readText(path).await()
}
```

Таким образом разработчик может использовать один и тот же API как в синхронном, так и в асинхронном коде.

Выбор версии определяется контекстом:

```forge
public async load(path: String): String, IoError! {
    return await readText(path)
}
```

В асинхронном контексте `await readText(path)` выбирает асинхронную
версию и ожидает её результат.

```forge
public load(path: String): String, IoError! {
    return readText(path)
}
```

В синхронном контексте обычный вызов `readText(path)` может выбирать
синхронную обёртку, если она доступна или может быть сгенерирована.

Если синхронный код явно хочет получить задачу, он может использовать
контекст типа:

```forge
const task: Task<String> = readText(path)
const text = task.await()
```

`Task<T>` описывает только форму асинхронного значения. Declared outcomes
не являются частью пользовательского типа `Task<T>` или `TaskCollection<T>`.
Они остаются семантикой функции и выражения до точки `await`, `catch` или
`forward`.

Некорректно:

```forge
Task<String, !IoError>
```

Корректно:

```forge
public async readText(path: String): String, !IoError
```

## Runtime и event loop

Асинхронный runtime Forge строится вокруг event loop.

Event loop выполняется в отдельном runtime-потоке, но этот поток должен
создаваться лениво: обычная синхронная программа, которая не создаёт задач
и не вызывает async-first API, не обязана запускать event loop.

Поток event loop появляется при первом реальном асинхронном действии:

* вызове async IO операции;
* создании `Task<T>`, который должен выполняться асинхронно;
* массовом создании задач через `task[...]`.

Синхронный вызов async-first API через сгенерированную обёртку тоже может
запустить event loop, потому что синхронная версия является блокирующей
обёрткой поверх асинхронной реализации.

Концептуально:

```forge
public readText(path: String): String, !IoError {
    return readText(path).await()
}
```

Такой вызов блокирует текущий поток на `.await()`, но сама async IO операция
выполняется через runtime event loop.

Для реализации IO это означает:

* основная реализация IO API должна быть асинхронной;
* синхронный IO является автоматически сгенерированной обёрткой;
* blocking IO не должен выполняться в вызывающем потоке, если операция
  объявлена как async IO;
* `await` и `Task.await()` блокируют только ожидающий поток, а не весь runtime.

`task[...]` и `TaskCollection<T>` используют тот же event loop. Метод
`concurrency(n)` ограничивает количество одновременно активных операций
внутри коллекции, а не создаёт отдельную модель выполнения.

### Текущий C backend

Текущий runtime-инкремент C backend поддерживает `async` и
`async native` функции как async-first boundary.

```forge
async native readNative(path: String): String = "forge_read_text"

load(path: String): String {
    return readNative(path).await()
}
```

Для прямого async-вызова с непосредственным `await` backend создаёт runtime
task, отправляет её в event loop thread, ожидает завершения и берёт результат
из task context. Это означает, что тело `async` функции или blocking native IO
выполняется не в вызывающем потоке.

Текущий инкремент намеренно узкий:

* поддерживаются top-level `async` и `async native` функции;
* настоящий runtime task создаётся для прямого `call(...).await()` или
  `await call(...)`;
* локальное сохранение `Task<T>` из async-вызова сразу запускает
  runtime task, а последующий `task.await()` ожидает этот handle;
* локальное сохранение `TaskCollection<T>` из `asyncFunc task[array]`
  запускает runtime task для каждого элемента;
* `collection.all().await()` ожидает все task handles и собирает массив
  результатов;
* `TaskCollection<T>.any()`, `.first()` и `.last()` также ожидают runtime
  task handles и возвращают соответствующий результат.

Ограничение текущего C backend: `await` внутри тела `async` функции пока
реализован как блокирующее ожидание runtime task. Полная coroutine-семантика
с suspension/resume внутри event loop является следующим архитектурным слоем.

## Рекомендации

Используйте синхронные функции для:

* небольших утилит;
* консольных программ;
* простых скриптов.

Используйте асинхронные функции для:

* сетевых запросов;
* веб-серверов;
* работы с удалёнными сервисами;
* файлового ввода-вывода;
* массовой обработки данных;
* большого количества независимых операций.

Для обработки коллекций задач рекомендуется использовать `TaskCollection` и его методы (`all`, `any`, `first`, `last`, `concurrency`), поскольку они позволяют декларативно описывать стратегию выполнения и ожидания результатов.
