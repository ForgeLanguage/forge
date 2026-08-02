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


@dataclass(frozen=True, slots=True)
class StructType(Type):
    symbol: Symbol | None = None


@dataclass(frozen=True, slots=True)
class EnumType(Type):
    symbol: Symbol | None = None
    value_type: Type | None = None


@dataclass(frozen=True, slots=True)
class InterfaceType(Type):
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
    outcomes: tuple[OutcomeType, ...] = ()
    return_ownership: str = "take"
    return_borrow_source: str | int | None = None

    @property
    def display_name(self) -> str:
        parameters = ", ".join(
            f"take {type_.display_name}" if ownership == "take" else type_.display_name
            for type_, ownership in zip(
                self.parameter_types,
                self.parameter_ownership or ("borrow",) * len(self.parameter_types),
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
PATTERN_MISMATCH = BuiltinType("PatternMismatch")
VOID = BuiltinType("Void")
NULL = BuiltinType("Null")
UNKNOWN = BuiltinType("<unknown>")

NUMERIC_TYPES = frozenset({INT, DOUBLE})


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
