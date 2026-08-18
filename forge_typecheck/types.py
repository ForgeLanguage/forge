"""Internal type model for Forge type checking."""

from __future__ import annotations

from dataclasses import dataclass

from forge_analysis import Symbol


@dataclass(frozen=True, slots=True)
class Type:
    """Base class for type checker types."""

    name: str

    @property
    def display_name(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class BuiltinType(Type):
    pass


@dataclass(frozen=True, slots=True)
class ClassType(Type):
    symbol: Symbol | None = None
    type_arguments: tuple[Type, ...] = ()

    @property
    def display_name(self) -> str:
        return _generic_display_name(self.name, self.type_arguments)


@dataclass(frozen=True, slots=True)
class StructType(Type):
    symbol: Symbol | None = None
    type_arguments: tuple[Type, ...] = ()

    @property
    def display_name(self) -> str:
        return _generic_display_name(self.name, self.type_arguments)


@dataclass(frozen=True, slots=True)
class EnumType(Type):
    symbol: Symbol | None = None
    value_type: Type | None = None


@dataclass(frozen=True, slots=True)
class InterfaceType(Type):
    symbol: Symbol | None = None
    type_arguments: tuple[Type, ...] = ()

    @property
    def display_name(self) -> str:
        return _generic_display_name(self.name, self.type_arguments)


@dataclass(frozen=True, slots=True)
class TypeParameterType(Type):
    symbol: Symbol | None = None


@dataclass(frozen=True, slots=True)
class ArrayType(Type):
    element_type: Type
    size: int | None = None

    @property
    def display_name(self) -> str:
        suffix = "[]" if self.size is None else f"[{self.size}]"
        return f"{self.element_type.display_name}{suffix}"


@dataclass(frozen=True, slots=True)
class NullableType(Type):
    inner_type: Type

    @property
    def display_name(self) -> str:
        return f"{self.inner_type.display_name}?"


@dataclass(frozen=True, slots=True)
class TaskType(Type):
    result_type: Type

    @property
    def display_name(self) -> str:
        return f"Task<{self.result_type.display_name}>"


@dataclass(frozen=True, slots=True)
class TaskCollectionType(Type):
    result_type: Type

    @property
    def display_name(self) -> str:
        return f"TaskCollection<{self.result_type.display_name}>"


@dataclass(frozen=True, slots=True)
class OutcomeType:
    type: Type
    required: bool

    @property
    def display_name(self) -> str:
        prefix = "!" if self.required else "?"
        return f"{prefix}{self.type.display_name}"


@dataclass(frozen=True, slots=True)
class FunctionType(Type):
    parameter_types: tuple[Type, ...]
    return_type: Type
    parameter_ownership: tuple[str, ...] = ()
    parameter_lazy: tuple[bool, ...] = ()
    outcomes: tuple[OutcomeType, ...] = ()
    return_ownership: str = "take"
    return_borrow_source: str | int | None = None

    @property
    def display_name(self) -> str:
        lazy_flags = self.parameter_lazy or (False,) * len(self.parameter_types)
        parameters = ", ".join(
            " ".join(
                part
                for part in (
                    "lazy" if lazy else "",
                    f"take {type_.display_name}" if ownership == "take" else type_.display_name,
                )
                if part
            )
            for type_, ownership, lazy in zip(
                self.parameter_types,
                self.parameter_ownership or ("borrow",) * len(self.parameter_types),
                lazy_flags,
            )
        )
        success = self.return_type.display_name
        if self.return_ownership == "borrow":
            success = f"borrow {success}"
        results = ", ".join((success, *(outcome.display_name for outcome in self.outcomes)))
        return f"func({parameters}): {results}"


INT = BuiltinType("Int")
DOUBLE = BuiltinType("Double")
BOOL = BuiltinType("Bool")
STRING = BuiltinType("String")
ARRAY = BuiltinType("Array")
PATTERN_MISMATCH = BuiltinType("PatternMismatch")
VOID = BuiltinType("Void")
NULL = BuiltinType("Null")
UNKNOWN = BuiltinType("<unknown>")

NUMERIC_TYPES = frozenset({INT, DOUBLE})


def _generic_display_name(name: str, type_arguments: tuple[Type, ...]) -> str:
    if not type_arguments:
        return name
    arguments = ", ".join(argument.display_name for argument in type_arguments)
    return f"{name}<{arguments}>"


def normalize_builtin_name(name: str) -> str:
    """Return the canonical built-in type name for a parsed type reference."""

    aliases = {
        "byte": "Byte",
        "ubyte": "UByte",
        "short": "Short",
        "ushort": "UShort",
        "int": "Int",
        "uint": "UInt",
        "long": "Long",
        "ulong": "ULong",
        "float": "Float",
        "double": "Double",
        "bool": "Bool",
        "string": "String",
        "void": "Void",
        "null": "Null",
    }
    return aliases.get(name, name)


def builtin_type(name: str) -> BuiltinType:
    canonical = normalize_builtin_name(name)
    if canonical == "Int":
        return INT
    if canonical == "Double":
        return DOUBLE
    if canonical == "Bool":
        return BOOL
    if canonical == "String":
        return STRING
    if canonical == "Array":
        return ARRAY
    if canonical == "PatternMismatch":
        return PATTERN_MISMATCH
    if canonical == "Void":
        return VOID
    if canonical == "Null":
        return NULL
    return BuiltinType(canonical)


def apply_type_modifiers(
    type_: Type,
    *,
    array_depth: int,
    nullable: bool,
    array_sizes: tuple[int | None, ...] | None = None,
) -> Type:
    result = type_
    sizes = array_sizes or (None,) * array_depth
    for size in sizes:
        suffix = "[]" if size is None else f"[{size}]"
        result = ArrayType(f"{result.name}{suffix}", result, size)
    if nullable:
        result = NullableType(f"{result.name}?", result)
    return result


def is_unknown(type_: Type) -> bool:
    return type_ == UNKNOWN


def is_numeric(type_: Type) -> bool:
    return type_ in NUMERIC_TYPES


def specialize_type(type_: Type, substitutions: dict[int, Type]) -> Type:
    if (
        isinstance(type_, TypeParameterType)
        and type_.symbol is not None
        and id(type_.symbol) in substitutions
    ):
        return substitutions[id(type_.symbol)]
    if isinstance(type_, NullableType):
        inner = specialize_type(type_.inner_type, substitutions)
        if inner == type_.inner_type:
            return type_
        return NullableType(f"{inner.name}?", inner)
    if isinstance(type_, ArrayType):
        element = specialize_type(type_.element_type, substitutions)
        if element == type_.element_type:
            return type_
        suffix = "[]" if type_.size is None else f"[{type_.size}]"
        return ArrayType(f"{element.name}{suffix}", element, type_.size)
    if isinstance(type_, TaskType):
        result = specialize_type(type_.result_type, substitutions)
        if result == type_.result_type:
            return type_
        return TaskType(f"Task<{result.display_name}>", result)
    if isinstance(type_, TaskCollectionType):
        result = specialize_type(type_.result_type, substitutions)
        if result == type_.result_type:
            return type_
        return TaskCollectionType(f"TaskCollection<{result.display_name}>", result)
    if isinstance(type_, FunctionType):
        parameter_types = tuple(
            specialize_type(parameter_type, substitutions)
            for parameter_type in type_.parameter_types
        )
        return_type = specialize_type(type_.return_type, substitutions)
        outcomes = tuple(
            OutcomeType(specialize_type(outcome.type, substitutions), outcome.required)
            for outcome in type_.outcomes
        )
        if (
            parameter_types == type_.parameter_types
            and return_type == type_.return_type
            and outcomes == type_.outcomes
        ):
            return type_
        return FunctionType(
            type_.name,
            parameter_types,
            return_type,
            type_.parameter_ownership,
            type_.parameter_lazy,
            outcomes,
            type_.return_ownership,
            type_.return_borrow_source,
        )
    if isinstance(type_, ClassType):
        arguments = tuple(specialize_type(argument, substitutions) for argument in type_.type_arguments)
        if arguments == type_.type_arguments:
            return type_
        return ClassType(type_.name, type_.symbol, arguments)
    if isinstance(type_, StructType):
        arguments = tuple(specialize_type(argument, substitutions) for argument in type_.type_arguments)
        if arguments == type_.type_arguments:
            return type_
        return StructType(type_.name, type_.symbol, arguments)
    if isinstance(type_, InterfaceType):
        arguments = tuple(specialize_type(argument, substitutions) for argument in type_.type_arguments)
        if arguments == type_.type_arguments:
            return type_
        return InterfaceType(type_.name, type_.symbol, arguments)
    return type_


def is_assignable(source: Type, target: Type) -> bool:
    if is_unknown(source) or is_unknown(target):
        return True
    if source == target:
        return True
    if source == NULL and isinstance(target, NullableType):
        return True
    if isinstance(source, NullableType) and isinstance(target, NullableType):
        return is_assignable(source.inner_type, target.inner_type)
    if isinstance(target, NullableType):
        return is_assignable(source, target.inner_type)
    if isinstance(source, TaskType) and isinstance(target, TaskType):
        return is_assignable(source.result_type, target.result_type)
    if isinstance(source, TaskCollectionType) and isinstance(target, TaskCollectionType):
        return is_assignable(source.result_type, target.result_type)
    if isinstance(source, EnumType) and isinstance(target, EnumType):
        return source.symbol == target.symbol
    if isinstance(target, InterfaceType):
        if not isinstance(source, ClassType) or source.symbol is None:
            return False
        declaration = source.symbol.node
        implements = getattr(declaration, "implements", ())
        return any(
            reference.name == target.name
            or (
                target.symbol is not None
                and getattr(target.symbol, "name", None) == reference.name
            )
            for reference in implements
        )
    return False
