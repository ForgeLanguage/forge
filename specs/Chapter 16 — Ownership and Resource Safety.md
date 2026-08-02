Forge использует модель линейного владения для управления ресурсами.

Цель модели:

- исключить двойное освобождение
- исключить использование после перемещения
- исключить использование после завершения
- гарантировать завершение жизненного цикла ресурса
- избежать borrow-lifetime сложности

Ownership — часть контракта типа.

Если ты владеешь — ты отвечаешь.

---

# 15.1 Move-only классы

Классы в Forge — **move-only**.

Owning-хэндл нельзя копировать. Его можно только:

- заимствовать (borrow)
- переместить в `take`-параметр через явный `move`

---

## Borrow по умолчанию

```forge
let a: File = ...
let b: File = a
```

Это **borrow**, а не копия.

`b`:

- не владеет
- не обязан вызывать `terminate`
- не может вызывать `exclusive`
- инвалидируется, если владелец завершён

Владельцем остаётся `a`.

---

## Перемещение владения (`take` + `move`)

```forge
let a: File = ...
consume(move a)
```

Это **move**.

После этого:

- `a` считается moved
- `a` недоступен
- callee получает owning-хэндл
- обязанность `terminate` переходит в callee

Попытка:

```forge
a.dispose()   // ❌ moved
```

— ошибка компиляции.

Передача владения через границу вызова должна быть явной с двух сторон:

```forge
public func consume(take file: File): Void {
    file.dispose()
}

public func main(): Void {
    let file: File = File.open("test.csv")
    consume(move file)
}
```

Если параметр объявлен как `take`, вызывающий код обязан передать аргумент через `move`.

```forge
consume(file)       // ❌ параметр принимает владение, нужен move
```

Если параметр не объявлен как `take`, `move` запрещён.

```forge
inspect(move file)  // ❌ inspect не принимает владение
```

Внутри функции `take`-параметр уже является owned value, поэтому его можно передать дальше без повторного `move`:

```forge
public func setProfile(take profile: Profile): Void {
    this.profile = profile
}
```

Если функция получила `take`-параметр и не передала владение дальше, не вернула его и не завершила явно, функция очищает этот ресурс при выходе.

Обычная локальная owner-переменная требует явного `move` при передаче в owned field:

```forge
let profile: Profile = Profile.new()
this.profile = profile       // ❌ нужен move
this.profile = move profile  // ✅
```

То же правило действует при перезаписи owned local:

```forge
let first: Profile = Profile.new()
let second: Profile = Profile.new()

first = second       // ❌ нужен move
first = move second  // ✅ old first очищается, second становится moved
```

Для nullable owned local присваивание `null` очищает старое значение и записывает `null`:

```forge
let profile: Profile? = Profile.new()
profile = null
```

Non-null owned fields должны быть инициализированы каждым constructor:

```forge
class User {
    public profile: Profile

    public new(take profile: Profile) {
        this.profile = profile
    }
}
```

Если поле объявлено как `Profile?`, constructor может оставить его `null`.

---

# 15.2 Borrow

Borrow — это временное представление объекта.

Borrow:

- не переносит ответственность
- не может вызывать `exclusive`
- не может пережить владельца
- инвалидируется после `terminate`

---

## Инвалидирование borrow

```forge
const file: File = ...
const csv: CsvFile = file   // borrow

file.dispose()              // terminate

csv.read()                  // ❌ ошибка
```

Вызов `terminate` завершает владение и инвалидирует все borrows, полученные от владельца.

---

# 15.3 exclusive

```forge
exclusive func fn(...)
```

Метод:

- может быть вызван только владельцем
- не может быть вызван через borrow
- не может быть вызван после move

`exclusive` описывает **право вызова**.

---

# 15.4 terminate

```forge
exclusive terminate func dispose(): Void
```

Правила:

1. В классе может быть не более одного `terminate`.
2. `terminate` завершает владение.
3. После вызова:
    - владелец считается consumed
    - все borrows инвалидируются
4. Владелец обязан:
    - вызвать `terminate`,  
        или
    - передать владение в `take`-параметр через `move`,  
        или
    - вернуть объект наружу как declared outcome

`terminate` описывает **конец жизненного цикла**.

---

# 15.5 Компиляторная проверка

Если переменная владеет объектом с `terminate`-методом, компилятор обязан доказать, что на всех путях выполнения:

- `terminate` вызван  
    или
- владение передано в `take`-параметр через `move`  
    или
- объект возвращён наружу как must-handle outcome

Иначе — ошибка компиляции.

---

# 15.6 Передача владения наружу

Функция может вернуть владение вызывающему:

```forge
private func process(take file: File): File
{
    return file
}
```

В этом случае:

- локальное владение прекращается
- обязанность `terminate` переходит вызывающему

Обычная локальная owner-переменная возвращается через `move`:

```forge
private func makeFile(): File {
    let file: File = File.open("test.csv")
    return move file
}
```

Если `move` происходит только в ветке, которая сразу возвращает управление (`return`), эта ветка не влияет на состояние переменной после `if`. Если же ветка после `move` может продолжиться, переменная считается moved после `if`.

Возврат borrowed resource как owned результата запрещён:

```forge
private func identity(file: File): File {
    return file // ❌ file — borrow
}
```

---

# 15.7 Пример полного цикла

```forge
class File
{
    exclusive terminate func dispose(): Void {
        ...
    }

    public static func open(path: String): File!, IoIssue! {
        ...
    }
}
```

Использование:

```forge
public func main(): Void
{
    const file: File = catch File.open("test.csv") {
        io: IoIssue => return
    }

    file.dispose()
}
```

Если забыть `dispose()` — ошибка компиляции.

---

# 15.8 Ownership Containers

Иногда объект временно владеет ресурсом и затем возвращает его.

## Итератор как контейнер владения

Создание итератора забирает владение:

```forge
class Iterators
{
    public static func create(take list: List<String>): Iterator<List<String>>
}
```

В вызывающем коде передача должна быть явной:

```forge
const iterator = Iterators.create(move list)
```

`list` становится moved.

---

## Возврат ресурса через terminate

```forge
class Iterator<T>
{
    exclusive terminate func getOriginal(): T
}
```

Вызов `getOriginal()`:

- завершает владение итератора
- возвращает новый owning-хэндл на исходный ресурс
- делает итератор недоступным

---

## Пример

```forge
let list: List<String> = ...

let it: Iterator<List<String>> = Iterators.create(move list)
// list moved

// работа через it

let list2: List<String> = it.getOriginal()
// it terminated
```

Этот паттерн позволяет:

- избегать borrow-lifetime модели
- строить безопасные обёртки
- сохранять линейность владения

---

# 15.9 Гарантии модели

Ownership в Forge гарантирует:

- единственного владельца
- отсутствие копирования owning-хэндлов
- невозможность use-after-move
- невозможность use-after-terminate
- обязательное завершение жизненного цикла
- явную передачу владения

---

# 15.10 Философия

Forge не использует:

- скрытые финализаторы
- lifetime-аннотации
- неявные деструкторы

Владение выражается через:

- `take`-параметры и `move`-аргументы
- borrow по умолчанию
- `exclusive`
- `terminate`
- declared outcomes
