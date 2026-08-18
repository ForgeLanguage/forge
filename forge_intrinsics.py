"""Compiler-provided members for builtin Forge types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntrinsicFunction:
    name: str
    parameter_types: tuple[str, ...]
    return_type: str
    native_name: str
    static: bool = False


STRING_INTRINSICS = {
    intrinsic.name: intrinsic
    for intrinsic in (
        IntrinsicFunction("length", (), "Int", "forge_string_length"),
        IntrinsicFunction("isEmpty", (), "Bool", "forge_string_is_empty"),
        IntrinsicFunction("toBytes", (), "Byte[]", "forge_string_to_bytes"),
        IntrinsicFunction("equals", ("String",), "Bool", "forge_string_equals"),
        IntrinsicFunction("indexOf", ("String",), "Int", "forge_string_index_of"),
        IntrinsicFunction("contains", ("String",), "Bool", "forge_string_contains"),
        IntrinsicFunction("startsWith", ("String",), "Bool", "forge_string_starts_with"),
        IntrinsicFunction("endsWith", ("String",), "Bool", "forge_string_ends_with"),
        IntrinsicFunction(
            "substring",
            ("Int", "Int"),
            "String",
            "forge_string_substring",
        ),
        IntrinsicFunction("trim", (), "String", "forge_string_trim"),
        IntrinsicFunction("toLowerCase", (), "String", "forge_string_to_lower_case"),
        IntrinsicFunction("toUpperCase", (), "String", "forge_string_to_upper_case"),
        IntrinsicFunction(
            "replace",
            ("String", "String"),
            "String",
            "forge_string_replace",
        ),
        IntrinsicFunction(
            "split",
            ("String", "Int"),
            "String[]",
            "forge_string_split",
        ),
        IntrinsicFunction("parseInt", (), "Int", "forge_string_parse_int"),
        IntrinsicFunction(
            "fromBytes",
            ("Byte[]",),
            "String",
            "forge_string_from_bytes",
            static=True,
        ),
        IntrinsicFunction(
            "fromInt",
            ("Int",),
            "String",
            "forge_string_from_int",
            static=True,
        ),
    )
}


def string_intrinsic(name: str, *, static: bool) -> IntrinsicFunction | None:
    intrinsic = STRING_INTRINSICS.get(name)
    if intrinsic is None or intrinsic.static != static:
        return None
    return intrinsic
