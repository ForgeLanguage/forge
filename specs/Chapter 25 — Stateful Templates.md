# Глава 25 — Stateful Templates

## Цель

Добавить в Forge первый вариант stateful template rendering: небольшой
compile-time renderer, похожий по роли на Twig, который исполняет только
template-конструкции и генерирует обычный Forge-код.

Фича нужна прежде всего для `std.Di.DiContainer`, но должна быть общей:
schema builders, routers, RPC, FSM builders и другие compile-time builders
должны использовать ту же модель.

## Базовая модель

Компиляция должна разделять три уровня:

- `TemplateInvocationContext` — одноразовый контекст конкретного template-вызова;
- `TemplateState` — типизированное состояние renderer'а, живущее между вызовами;
- generated Forge code — обычный Forge-код, который затем проходит стандартный
  parser, typechecker, lowering и backend.

Template renderer выполняет только compile-time конструкции:

```forge
#if ...
#for ...
#{
    ...
#}
```

Код вне этих конструкций не исполняется во время template rendering. Он
попадает в итоговую Forge-программу.

Пример:

```forge
public template apply<T:struct>(defs: T): Void {
    #{
        state.compiled = false
    #}

    this.defs.add(...)
}
```

Здесь блок `#{...}` исполняется renderer'ом во время компиляции, а
`this.defs.add(...)` становится частью сгенерированной runtime-программы.

## TemplateInvocationContext

Каждый template-вызов получает compile-time контекст:

- receiver expression, если вызов является member-вызовом;
- receiver configuration identity, если receiver вычислим для stateful template;
- type arguments;
- Reflection metadata;
- source location.

`TemplateInvocationContext` не является пользовательским объектом Forge. Это
модель компилятора, доступная renderer'у через встроенные значения и APIs.

## TemplateState

Template state объявляется явно и типизированно:

```forge
#state graph: Dict<String, Array<String>> = {}
#state compiled: Bool = false
```

`#state` не является runtime-полем класса и не является compile-time полем
runtime-объекта. Это состояние template renderer'а.

Для member templates состояние scoped by:

```text
TemplateStateKey =
    owner type
    +
    receiver configuration identity
```

State key не должен включать конкретный template method или его generic
specialization. Вызовы:

```forge
container.apply(CoreDefs)
container.apply(HttpDefs)
container.compile()
```

должны видеть один и тот же state:

```text
TemplateState[DiContainer, Config#1]
```

Другой receiver получает другой state:

```forge
const app = DiContainer.new()
const worker = DiContainer.new()
```

```text
TemplateState[DiContainer, Config#1]
TemplateState[DiContainer, Config#2]
```

## Receiver Configuration Identity

В v1 receiver configuration identity должна поддерживать только локальный
очевидный flow:

```forge
const app = DiContainer.new()
const alias = app

app.apply(CoreDefs)
alias.apply(HttpDefs)
```

Компилятор должен понимать:

```text
app   -> Config#1
alias -> Config#1
```

Каждый локальный вызов `SomeBuilder.new()` для stateful receiver создает новый
configuration identity.

Межпроцедурная propagation в v1 не требуется:

```forge
const app = createContainer()
app.apply(CoreDefs)
```

Если `createContainer()` не является частью template renderer, receiver
configuration считается unknown, и state-changing template invocation должен
завершаться ошибкой компиляции.

Рекомендуемый diagnostic:

```text
Stateful template invocation requires a compile-time-resolvable receiver configuration.
```

## Compile-Time Control Flow

State-changing template invocation должен находиться в compile-time
deterministic control flow.

Недопустимо:

```forge
if runtimeFlag {
    app.apply(DebugDefs)
}
```

Потому что renderer должен выполнить `apply` во время компиляции, а runtime
condition неизвестен.

Допустимо:

```forge
#if build.debug {
    app.apply(DebugDefs)
#}
```

Обычные `if`, `for`, `while` не должны автоматически интерпретироваться
renderer'ом в v1. Compile-time control flow должен быть синтаксически явным:
`#if`, `#for`, `#{...}`.

## Template Language v1

Renderer language в v1 является маленьким Forge-like языком, а не полноценным
Forge runtime.

Поддерживаемые значения:

- `Bool`;
- `Int`;
- `Float`;
- `String`;
- `Null`;
- `Array`;
- `Dict`;
- `Set`;
- Reflection-типы: `TypeInfo`, `FieldInfo`, `MethodInfo`, `ParameterInfo`;
- typed `#state`.

Поддерживаемые конструкции:

- `const` и `var`;
- assignment;
- `if` / `else` внутри `#{...}`;
- `for` внутри `#{...}`;
- `break` / `continue` внутри compile-time loops;
- field access;
- index access;
- базовые выражения;
- вызов только встроенных compile-time APIs;
- `Compiler.error(...)`;
- `Compiler.warning(...)`.

В v1 запрещены:

- пользовательские compile-time функции;
- пользовательские compile-time типы;
- `class`, `struct`, `trait`, `interface` внутри `#{...}`;
- constructors пользовательских типов внутри renderer'а;
- arbitrary Forge function calls;
- I/O;
- network;
- threads;
- ownership/lifetime semantics для compile-time объектов.

## Built-In Compile-Time APIs

Минимальный набор встроенных APIs:

- `Compiler.error(message: String): Never`;
- `Compiler.warning(message: String): Void`;
- `Array.*`;
- `Dict.*`;
- `Set.*`;
- `String.*`;
- `Reflection.*`;
- `Graph.*`.

`Graph.*` должен быть универсальным API, не привязанным только к DI.

Минимально полезная операция:

```forge
Graph.findCycle(graph: Dict<String, Array<String>>): Array<String>?
```

Пример использования:

```forge
public template compile(): Void {
    #{
        const cycle = Graph.findCycle(state.graph)

        if cycle != null {
            const path = cycle.join(" -> ")
            Compiler.error("Circular dependency: #{path}")
        }

        state.compiled = true
    #}
}
```

## DI Use Case

Пример целевой модели для DI:

```forge
class

#state graph: Dict<String, Array<String>> = {}
#state compiled: Bool = false

public template apply<T:struct>(defs: T): Void {
    #if state.compiled {
        Compiler.error("Cannot register services after DI compilation")
    #}

    #for Reflection.type<T>().fields as field {
        #{
            state.graph[field.type.name] =
                field.type.constructor.parameters.map(p => p.type.name)
        #}

        this.defs.add("#{field.type.name}", defs.#{field.name})
    #}
}

public template compile(): Void {
    #{
        const cycle = Graph.findCycle(state.graph)

        if cycle != null {
            const path = cycle.join(" -> ")
            Compiler.error("Circular dependency: #{path}")
        }

        state.compiled = true
    #}
}
```

Expected behavior:

```forge
const app = DiContainer.new()
app.apply(CoreDefs)
app.apply(HttpDefs)
app.compile()

const worker = DiContainer.new()
worker.apply(WorkerDefs)
worker.compile()
```

Renderer state:

```text
TemplateState[DiContainer, Config#1]
    graph = CoreDefs + HttpDefs
    compiled = true

TemplateState[DiContainer, Config#2]
    graph = WorkerDefs
    compiled = true
```

После `compile()` повторный `apply()` на той же receiver configuration должен
быть compile-time ошибкой.

## Implementation Scope v1

В рамках первой реализации необходимо:

1. Добавить AST/model для `#state` declarations.
2. Добавить модель `TemplateInvocationContext`.
3. Добавить модель `TemplateState`, scoped by owner type + receiver config.
4. Добавить локальный анализ receiver configuration identity:
   `const x = Builder.new()` и `const y = x`.
5. Запретить state-changing template calls при unknown receiver config.
6. Запретить state-changing template calls внутри runtime control flow.
7. Поддержать typed primitive/collection state values.
8. Поддержать встроенные compile-time APIs, минимум `Compiler.*` и `Graph.findCycle`.
9. Сохранить output как обычный Forge source/AST для существующего compiler pipeline.
10. Покрыть DI-сценарии тестами на expansion, diagnostics и end-to-end compile/run.

## Out Of Scope v1

В v1 не входят:

- межпроцедурная propagation receiver configuration identity;
- specialization функций по configuration identity;
- partial evaluation обычного Forge-кода;
- пользовательские compile-time функции;
- пользовательские compile-time типы;
- compile-time classes/objects/heap;
- I/O в renderer'е;
- выполнение произвольных Forge функций во время компиляции;
- изменение runtime ownership model.

## Возможная Эволюция

Порядок расширения после v1:

```text
v2: user compile-time functions
v3: compile-time structs/value types
v4: compile-time objects/classes, only if truly needed
```

Пользовательские функции можно добавить раньше типов: для них достаточно stack
frames, arguments и return values. Пользовательские типы и классы требуют
гораздо более сложной модели identity, constructors, lifetime и ownership, и не
должны обещаться заранее.

## Acceptance Criteria

Фича считается готовой для v1, если:

- stateless templates продолжают работать как раньше;
- `#state` declarations типизируются и доступны во всех template methods одного
  owner + receiver config;
- разные локальные receivers получают разные state;
- aliases получают тот же state, что исходный receiver;
- `apply<A>()`, `apply<B>()`, `compile()` одного receiver работают с одним state;
- unknown receiver config дает понятную compile-time ошибку;
- runtime control flow вокруг state-changing template invocation дает понятную
  compile-time ошибку;
- `#if` и `#for` позволяют deterministic compile-time control flow;
- DI может накопить graph, проверить cycle через `Graph.findCycle`, и запретить
  registrations после `compile()`;
- существующий compiler pipeline после rendering получает обычный Forge-код;
- полный набор tests для templates/DI проходит через `python3 -m unittest discover -s tests`.
