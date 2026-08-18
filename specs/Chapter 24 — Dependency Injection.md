# Глава 24 — Dependency Injection

Forge предоставляет compile-time DI helper в `std.Di.DiContainer`.

Пакет `std.Di` написан на Forge и намеренно не является runtime-reflection
контейнером. Он использует template expansion до обычного parsing/typechecking:
компилятор раскрывает метаданные класса или интерфейса, а шаблон генерирует
обычный Forge-код вызова конструктора.

```forge
use std.Di.DiContainer

class Logger {}

class Service {
    public new(public take logger: Logger) {}
}

const service: Service = DiContainer.resolve<Service>()
```

Для `Service` шаблон раскрывается примерно в такой код:

```forge
return Service.new(move DiContainer.resolve<Logger>())
```

## API

```forge
DiContainer.resolve<T:class>(): T
DiContainer.resolveAll<T:interface>(): T[]
DiContainer.resolveWith<T:class>(
    strings: DiStringParameter[],
    ints: DiIntParameter[],
    bools: DiBoolParameter[]
): T

DiBuilder.empty(): DiBuilder
DiBuilder.create(
    strings: DiStringParameter[],
    ints: DiIntParameter[],
    bools: DiBoolParameter[]
): DiBuilder
DiBuilder.resolve<T:class>(builder: DiBuilder): T
DiBuilder.resolveAll<T:interface>(builder: DiBuilder): T[]
```

`resolve<T>()` строит concrete class через конструктор с максимальным числом
параметров. Для class-параметров он рекурсивно генерирует `resolve<Dep>()`.
Если параметр конструктора объявлен как `take`, шаблон генерирует `move`.

`resolveAll<T>()` работает для интерфейсов: компилятор находит все известные в
программе классы с `implements T` и генерирует массив этих реализаций. Элементы
массива проходят обычную адаптацию class-to-interface, поэтому после expansion
остается статически типизированный Forge-код.

`resolveWith<T>()` добавляет compile-time constructor injection с именованными
scalar-параметрами. `String`, `Int` и `Bool` берутся из массивов
`DiStringParameter`, `DiIntParameter` и `DiBoolParameter` по имени параметра
конструктора; class-параметры по-прежнему строятся рекурсивно.

```forge
use std.Di.DiBuilder
use std.Di.DiStringParameter

class Config {
    public new(public name: String) {}
}

const strings: DiStringParameter[] = [{ name: "name", value: "prod" }]
const builder = DiBuilder.create(strings, [], [])
const config = DiBuilder.resolve<Config>(builder)
```

`DiBuilder` не является runtime registry. Он хранит только compile-time friendly
массивы именованных scalar-параметров, а generic `resolve`/`resolveAll`
раскрываются в обычный Forge-код так же, как методы `DiContainer`.

## Compile-Time Метаданные

DI использует расширенные template shape-метаданные:

- `T:class`, `T:interface`, `T:struct`, `T:enum` в template type parameter;
- `Reflection.type<T>().constructor.parameters`;
- `parameter.name`, `parameter.type`, `parameter.ownership`,
  `parameter.movePrefix`;
- `Reflection.type<T>().implementations` для интерфейсов;
- простые type predicates: `isString`, `isInt`, `isBool`, `isSimple`.

Эти значения существуют только во время template expansion и не создают runtime
таблиц типов.

## Границы

В отличие от reflection-based контейнера из `DiContainer.zip`, текущий Forge
helper пока не хранит runtime-регистрации, singleton/transient lifetime,
factory/fromInstance bindings, tags и cycle detection. Ближайший безопасный
аналог tags сейчас — интерфейс плюс `resolveAll<Interface>()`.
