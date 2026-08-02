В Forge функция не просто возвращает значение.  
Она **объявляет все возможные исходы своего выполнения**.

В языке нет union-типов и нет скрытых исключений.

Каждый возможный исход указывается прямо в сигнатуре функции.

---

# 1. Структура исходов

Функция может объявить:

- **один success-тип**
- любое количество **обязательных outcome-типов**
- любое количество **опциональных outcome-типов**

Пример:

```forge
public static func parseInt(text: String): Int, !ParseIssue
```

Это означает:

- основной результат — `Int`
- альтернативный исход — `ParseIssue`
- вызывающий код обязан обработать `ParseIssue`

Outcome-маркеры являются префиксными:

```forge
T   // success-тип
!E  // обязательный outcome
?E  // опциональный outcome
```

---

## Только один success-тип

Сигнатура может содержать **не более одного непомеченного типа**.
Непомеченный тип — это тип без префикса `!` или `?`.

Некорректно:

```forge
func example(): Int, String   // ❌ два success-типа
```

---

## Если success-тип отсутствует

Если непомеченный тип не указан, success-тип считается `Void`.

```forge
public static func save(path: String): !IoIssue, !AccessDenied
```

Эквивалентно:

```forge
public static func save(path: String): Void, !IoIssue, !AccessDenied
```

---

# 2. Outcome-типы

Тип с префиксом `!` означает:

> Этот исход обязан быть обработан.

Обязательный outcome-тип — это не обязательно ошибка.  
Это любой альтернативный результат, который нельзя игнорировать.

Тип с префиксом `?` означает:

> Этот исход можно обработать явно, но обработка не обязательна.

Если опциональный outcome не обработан и не проброшен выше, применяется default policy runtime.
Для `AllocFailed` такой policy может быть аварийным завершением программы с диагностикой.

Outcome-тип должен быть объявленным верхнеуровневым типом (`class`, `trait` или `interface`).
Если он объявлен в том же файле рядом с основной программой, файл должен использовать `@multidef`.

Пример:

```forge
public func reserve(size: Int): Void, ?AllocFailed
```

Вызывающий код может проигнорировать `AllocFailed`:

```forge
array.reserve(1000)
```

В этом случае при `AllocFailed` будет применён default handler.

Или обработать его явно:

```forge
catch array.reserve(1000) {
    error: AllocFailed => {
        print "Not enough memory"
    }
}
```

---

# 3. Обработка через `catch`

Для обработки declared outcomes используется `catch`.

`catch` — это декоратор выражения, которое может вернуть обязательный или опциональный outcome.

```forge
let value: Int = catch parseInt(text) {
    issue: ParseIssue => 0
}
```

`catch`:

- вызывает функцию
- перехватывает указанные outcome-типы
- возвращает success-значение

`catch` указывает тип outcome без маркера `!` или `?`, потому что обязательность относится к сигнатуре функции, а не к обработчику.

---

# 4. `catch` как декоратор функции

`catch` можно применить не только к результату вызова функции, но и к самой функции.

```forge
const safeParseInt = catch Int.parse {
    error: ParseError => 0
}

const num = safeParseInt("1")
```

Такой код создаёт безопасную версию функции: при каждом вызове она вызывает исходную функцию и применяет указанные обработчики.

Это эквивалентно обработке конкретного вызова:

```forge
const num = catch Int.parse("1") {
    error: ParseError => 0
}
```

Если исходная функция принимает параметры `(A, B)` и возвращает success-тип `T`, то `catch` над самой функцией создаёт функцию с теми же параметрами `(A, B)` и возвращаемым типом `T`, но без обработанных outcome-исходов.

Для генераторов у `catch` есть дополнительное правило: ветка обработчика может вернуть `continue`, чтобы пропустить проблемный `yield`, или `break`, чтобы завершить генератор.

---

# 5. Блок-ветка

Ветка может быть блоком.  
Значение блока — последнее выражение, если не выполнен `return`.

```forge
let value: Int = catch parseInt(text) {
    issue: ParseIssue => {
        print "Invalid number: " + issue.message
        0
    }
}
```

---

# 6. Правило типизации `catch`

Если success-тип функции — `T`,  
каждая перехватываемая ветка обязана:

- либо вернуть значение, совместимое с `T`
- либо выполнить `return` из текущей функции

Иначе возникает ошибка компиляции.

Исключение: если `catch` оборачивает генератор, ветка может вернуть `continue` или `break` вместо значения success-типа.

---

# 7. Частичная обработка и `forward`

Если необходимо обработать только часть исходов, остальные можно пробросить вверх.

```forge
let value = forward catch fn() {
    io: IoIssue => {
        print io.message
        0
    }
}
```

В этом случае:

- `IoIssue` обработан
- остальные обязательные outcome-типы проброшены
- success-значение остаётся

---

# 8. Правило для `forward`

Если функция использует `forward`,  
она обязана указать пробрасываемые outcome-типы в своей сигнатуре.

Корректно:

```forge
public static func read(text: String): Int, !ParseIssue {
    forward parseInt(text)
}
```

Некорректно:

```forge
public static func read(text: String): Int {
    forward parseInt(text)   // ❌ ParseIssue не объявлен
}
```

`forward` сопоставляет outcome вызываемой функции с outcome-контекстом текущей функции.

Если вызываемая функция возвращает обязательный outcome:

```forge
func parse(text: String): Int, !ParseIssue
```

то вызывающий код обязан либо обработать `ParseIssue` через `catch`, либо пробросить его через `forward` из функции, которая тоже объявляет `!ParseIssue`.

Если вызываемая функция возвращает опциональный outcome:

```forge
func reserve(size: Int): Void, ?AllocFailed
```

то вызывающий код может:

- проигнорировать `AllocFailed`, тогда применяется default handler
- обработать `AllocFailed` через `catch`
- пробросить `AllocFailed` через `forward`, если текущая функция объявляет `?AllocFailed` или `!AllocFailed`

Проброс как опциональный outcome:

```forge
public func prepare(): Void, ?AllocFailed {
    forward array.reserve(1000)
}
```

Проброс с повышением до обязательного outcome:

```forge
public func load(): Void, !AllocFailed {
    forward array.reserve(1000)
}
```

В этом примере `array.reserve` объявляет `?AllocFailed`, но `load` делает `AllocFailed` частью своего обязательного контракта.
Вызывающий код `load` теперь обязан обработать `AllocFailed` или пробросить его дальше.

Если текущая функция не объявляет `AllocFailed`, использовать `forward` нельзя:

```forge
public func load(): Void {
    forward array.reserve(1000) // ❌ AllocFailed не объявлен
}
```

---

# 9. Повышение опциональных outcomes политикой проекта или модуля

Проект или модуль может объявить, что некоторые опциональные outcomes должны рассматриваться как обязательные.

Пример возможной модульной политики:

```forge
@mustHandle(AllocFailed)
module app.core
```

После такой политики вызов функции:

```forge
func reserve(size: Int): Void, ?AllocFailed
```

проверяется так, будто `AllocFailed` является обязательным outcome для кода этого модуля.

Некорректно:

```forge
public func load(): Void {
    array.reserve(1000) // ❌ AllocFailed должен быть обработан или проброшен
}
```

Корректно:

```forge
public func load(): Void {
    catch array.reserve(1000) {
        error: AllocFailed => {
            print "Not enough memory"
        }
    }
}
```

Также корректно:

```forge
public func load(): Void, !AllocFailed {
    forward array.reserve(1000)
}
```

Политика не меняет сигнатуру `reserve`.
Она меняет только требования к вызывающему коду в выбранном контексте.

---

# 10. Пример

```forge
@multidef

class DivisionByZero

class Calculator {
public static func divide(a: Int, b: Int): Int, !DivisionByZero {
    if b == 0 {
        return DivisionByZero.new()
    }

    return a / b
}
}
```

Использование:

```forge
let result: Int = catch divide(10, 0) {
    issue: DivisionByZero => {
        print "Cannot divide by zero"
        0
    }
}
```

---

# 11. Почему это не union

В Forge:

- нет типов вида `Int | String`
- нет скрытых исключений
- нет неявных альтернатив

Функция обязана объявить все исходы.  
Вызывающий код обязан обработать обязательные исходы.
Опциональные исходы можно обработать явно; если они не обработаны, применяется default policy.

Сигнатура полностью описывает поведение функции.
Политика проекта или модуля может сделать часть опциональных исходов обязательными для обработки в конкретном контексте, но не добавляет скрытых исходов.

# 12. Итог

- Один success-тип.
- Любое количество обязательных outcome-типов через `!Type`.
- Любое количество опциональных outcome-типов через `?Type`.
- Обязательная обработка только для `!Type`.
- Опциональные outcomes можно игнорировать, обработать через `catch` или пробросить через `forward`.
- `forward` может повысить `?Type` до `!Type`, если текущая функция объявляет `!Type`.
- Политика проекта или модуля может требовать обработки выбранных `?Type` как обязательных.
- `catch` — декоратор выражения или функции.
- `forward` требует явного объявления в сигнатуре.
- Union-типов нет.

### 13. Рекомендация: не используйте outcomes как замену union-типам

Forge разрешает объявлять несколько outcome-типов:

```forge
public static func fn(): !IntOutcome, !FloatOutcome, ?StringOutcome
```

Но это следует использовать осторожно.

Такие сигнатуры:

- плохо читаются
- размывают контракт функции
- быстро превращаются в “ручной union” на уровне сигнатуры

Рекомендуется:

- держать список outcome-типов коротким и смысловым
- группировать близкие альтернативы через один контрактный тип (interface) или один “категорийный” outcome-тип, если это уместно
