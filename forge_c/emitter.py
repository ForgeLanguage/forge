"""Emit straightforward C source from lowered Forge IR."""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields, is_dataclass
from pathlib import PurePath
import re
from typing import TypeAlias

from forge_intrinsics import string_intrinsic
from forge_ir import (
    IrAssignment,
    IrArrayDestructuring,
    IrArrayBulkCall,
    IrArrayLiteral,
    IrArrayPatternCheck,
    IrBinary,
    IrBlock,
    IrBreak,
    IrBuiltinRef,
    IrBulkMapCall,
    IrCall,
    IrCatch,
    IrClass,
    IrConditional,
    IrDoWhile,
    IrDoWhileExpression,
    IrEnum,
    IrExpression,
    IrExpressionStatement,
    IrForExpression,
    IrFunction,
    IrForward,
    IrIf,
    IrIndex,
    IrLiteral,
    IrLocalRef,
    IrMemberBlock,
    IrMember,
    IrMove,
    IrParameter,
    IrPrint,
    IrProgram,
    IrReturn,
    IrSequence,
    IrSpecialRef,
    IrStatement,
    IrStructLiteral,
    IrSwitch,
    IrTaskBulkCall,
    IrUnary,
    IrVariable,
    IrWhile,
    IrWhileExpression,
)
from forge_lexer import TokenKind
from forge_analysis import Symbol
from forge_lowering import LoweringResult, LoweringUnsupportedError, lower
from forge_ownership import OwnershipPlan, analyze_ownership
from forge_parser import ClassDeclaration, EnumVariant, FunctionDeclaration, Program, VariableDeclaration
from forge_typecheck import (
    BOOL,
    DOUBLE,
    INT,
    PATTERN_MISMATCH,
    STRING,
    VOID,
    ArrayType,
    BuiltinType,
    ClassType,
    EnumType,
    FunctionType,
    InterfaceType,
    NullableType,
    OutcomeType,
    StructType,
    TaskCollectionType,
    TaskType,
    Type,
    TypeParameterType,
)

Input = Program | LoweringResult | IrProgram
CleanupBinding: TypeAlias = IrVariable | IrParameter


@dataclass(frozen=True, slots=True)
class _ConditionalArrayCleanup:
    variable: IrVariable
    condition: str


ArrayCleanupBinding: TypeAlias = IrVariable | _ConditionalArrayCleanup


@dataclass(slots=True)
class _ReturnCleanupContext:
    return_type: Type
    return_var: str | None = None
    used: bool = False


@dataclass(slots=True)
class _AsyncNativeTaskCollectionContext:
    tasks: str
    contexts: str
    length: str


class CEmissionError(Exception):
    """Raised when the current C emitter cannot represent an IR construct."""


def emit_c(
    program_or_ir: Input,
    *,
    preamble: str = "",
    external_helpers: bool = False,
    declarations_in_header: bool = False,
) -> str:
    """Emit C source from a parsed program, lowering result, or IR program."""

    ir = _coerce_ir(program_or_ir)
    emitter = _Emitter(
        ownership=analyze_ownership(ir),
        external_helpers=external_helpers,
        declarations_in_header=declarations_in_header,
    )
    return emitter.emit_program(ir, preamble=preamble)


def emit_c_header(program_or_ir: Input) -> str:
    """Emit C forward declarations for a lowered Forge program."""

    ir = _coerce_ir(program_or_ir)
    emitter = _Emitter(ownership=analyze_ownership(ir))
    return emitter.emit_header(ir)


def _coerce_ir(program_or_ir: Input) -> IrProgram:
    if isinstance(program_or_ir, IrProgram):
        return program_or_ir
    if isinstance(program_or_ir, LoweringResult):
        return program_or_ir.ir
    try:
        return lower(program_or_ir).ir
    except LoweringUnsupportedError as exc:
        raise CEmissionError(str(exc)) from exc


@dataclass(slots=True)
class _Emitter:
    ownership: OwnershipPlan
    includes: set[str] = field(default_factory=set)
    helpers: set[str] = field(default_factory=set)
    external_helpers: bool = False
    declarations_in_header: bool = False
    _indent: int = 0
    _main_returns_int: bool = False
    _cleanup_stack: list[list[CleanupBinding]] = field(default_factory=list)
    _array_cleanup_stack: list[list[ArrayCleanupBinding]] = field(default_factory=list)
    _string_cleanup_stack: list[list[IrVariable]] = field(default_factory=list)
    _struct_field_cleanup_stack: list[list[tuple[Symbol, str, str]]] = field(default_factory=list)
    _statement_prelude_stack: list[list[str]] = field(default_factory=list)
    _statement_cleanup_stack: list[list[str]] = field(default_factory=list)
    _temp_index: int = 0
    _function_stack: list[IrFunction] = field(default_factory=list)
    _return_cleanup_stack: list[_ReturnCleanupContext] = field(default_factory=list)
    _loop_result_stack: list[tuple[str, str, Type] | None] = field(default_factory=list)
    _loop_cleanup_depth_stack: list[int] = field(default_factory=list)
    _async_native_helpers: dict[str, str] = field(default_factory=dict)
    _async_native_task_contexts: dict[int, str] = field(default_factory=dict)
    _async_native_task_collections: dict[str, _AsyncNativeTaskCollectionContext] = field(default_factory=dict)

    def emit_program(self, program: IrProgram, *, preamble: str = "") -> str:
        specialization_chunks = [] if self.declarations_in_header else [
            self._emit_generic_struct_specialization(type_)
            for type_ in self._generic_struct_specializations(program)
        ]
        body_chunks = [
            self._emit_top_level(item)
            for item in program.declarations
        ]
        body = "\n\n".join(chunk for chunk in (*specialization_chunks, *body_chunks) if chunk)
        helpers = self._emit_helpers()
        includes = self._emit_includes()
        chunks = [chunk for chunk in (preamble.rstrip(), includes, helpers, body) if chunk]
        body = "\n\n".join(chunks)
        return f"{body}\n" if body else ""

    def emit_header(self, program: IrProgram) -> str:
        type_declarations: list[str] = []
        declarations: list[str] = []
        type_declarations.extend(
            self._emit_generic_struct_specialization(type_)
            for type_ in self._generic_struct_specializations(program)
        )
        for item in program.declarations:
            if isinstance(item, IrClass):
                if self._is_generic_class_declaration(item):
                    continue
                type_declarations.extend(self._class_type_header_declarations(item))
                declarations.extend(self._class_member_header_declarations(item))
            elif isinstance(item, IrEnum):
                type_declarations.extend(self._enum_header_declarations(item))
            elif isinstance(item, IrFunction):
                if item.native_name is not None:
                    declarations.append(f"{self._function_signature(item, c_name=item.native_name)};")
                    continue
                declarations.append(f"{self._function_signature(item)};")

        if not type_declarations and not declarations:
            return ""
        pre_type_helpers = self._emit_array_type_helpers()
        helpers = self._emit_helpers()
        includes = self._emit_includes()
        chunks = [
            chunk
            for chunk in (
                includes,
                pre_type_helpers,
                "\n".join(type_declarations),
                helpers,
                "\n".join(declarations),
            )
            if chunk
        ]
        return "#pragma once\n\n" + "\n\n".join(chunks) + "\n"

    def _class_header_declarations(self, class_: IrClass) -> list[str]:
        return [
            *self._class_type_header_declarations(class_),
            *self._class_member_header_declarations(class_),
        ]

    def _class_type_header_declarations(self, class_: IrClass) -> list[str]:
        if class_.name is None:
            raise CEmissionError("Cannot emit unnamed class")
        if class_.kind == "interface":
            return self._interface_header_declarations(class_)
        class_name = self._class_c_name(class_.name, class_.symbol)
        fields = [
            member
            for member in class_.members
            if isinstance(member, IrVariable) and "static" not in member.modifiers
        ]
        return [self._struct_definition(class_name, fields)]

    def _class_member_header_declarations(self, class_: IrClass) -> list[str]:
        if class_.name is None:
            raise CEmissionError("Cannot emit unnamed class")
        if class_.kind == "interface":
            return []
        class_name = self._class_c_name(class_.name, class_.symbol)
        declarations: list[str] = []
        declarations.append(f"void _forge_free_{class_name}(struct {class_name}* value);")
        for member in class_.members:
            if isinstance(member, IrFunction):
                if member.native_name is not None:
                    extra_parameters = ()
                    if "static" not in member.modifiers:
                        extra_parameters = (f"struct {class_name}* this",)
                    declarations.append(
                        f"{self._function_signature(member, c_name=member.native_name, extra_parameters=extra_parameters)};"
                    )
                    continue
                declarations.append(f"{self._method_signature(class_name, member)};")
            elif isinstance(member, IrVariable) and "static" in member.modifiers:
                declarations.append(
                    f"extern {self._c_type(member.type)} {class_name}_{member.name};"
                )
        for interface_type in class_.implements:
            if isinstance(interface_type, InterfaceType) and interface_type.symbol is not None:
                interface_name = self._interface_type_c_name(interface_type)
                declarations.append(
                    f"extern const struct {interface_name}_vtable {class_name}_as_{interface_name}_vtable;"
                )
        return declarations

    def _interface_header_declarations(self, interface: IrClass) -> list[str]:
        if interface.name is None:
            raise CEmissionError("Cannot emit unnamed interface")
        interface_name = self._class_c_name(interface.name, interface.symbol)
        vtable_name = f"{interface_name}_vtable"
        method_lines: list[str] = []
        for member in interface.members:
            if not isinstance(member, IrFunction):
                continue
            parameters = ", ".join(
                f"{self._c_type(parameter.type)} {parameter.name}"
                for parameter in member.parameters
            )
            if parameters:
                parameters = ", " + parameters
            method_lines.append(
                f"    {self._function_c_return_type(member)} (*{member.name})(void* object{parameters});"
            )
        if not method_lines:
            method_lines.append("    char _forge_empty;")
        return [
            f"struct {vtable_name} {{\n" + "\n".join(method_lines) + "\n};",
            f"struct {interface_name} {{\n"
            f"    void* object;\n"
            f"    const struct {vtable_name}* vtable;\n"
            f"}};",
        ]

    def _function_signature(
        self,
        function: IrFunction,
        *,
        c_name: str | None = None,
        extra_parameters: tuple[str, ...] = (),
    ) -> str:
        own_parameters = tuple(
            f"{self._c_type(parameter.type)} {parameter.name}"
            for parameter in function.parameters
        )
        parameters = ", ".join((*extra_parameters, *own_parameters))
        if not parameters:
            parameters = "void"
        emitted_name = c_name or function.name
        if c_name is None:
            emitted_name = self._function_c_name(function)
        return_type = (
            "int"
            if emitted_name == "main" and function.return_type == VOID
            else self._function_c_return_type(function)
        )
        return f"{return_type} {emitted_name}({parameters})"

    def _function_c_name(self, function: IrFunction) -> str:
        if (
            function.symbol is not None
            and isinstance(function.symbol.node, FunctionDeclaration)
            and "async" in function.symbol.node.modifiers
            and len(function.symbol.scope.overloads.get(function.symbol.name, ())) > 1
        ):
            return f"{function.name}_async"
        return function.name

    def _method_signature(self, class_name: str, function: IrFunction) -> str:
        extra_parameters = ()
        if function.kind != "new" and "static" not in function.modifiers:
            extra_parameters = (f"struct {class_name}* this",)
        return self._function_signature(
            function,
            c_name=f"{class_name}_{function.name}",
            extra_parameters=extra_parameters,
        )

    def _emit_includes(self) -> str:
        return "\n".join(f"#include <{header}>" for header in sorted(self.includes))

    def _emit_helpers(self) -> str:
        chunks: list[str] = []
        needs_alloc = (
            "string_copy" in self.helpers
            or "string_concat" in self.helpers
            or "bool_to_string" in self.helpers
            or any(
                helper.startswith(("primitive_to_string:", "array_runtime:"))
                for helper in self.helpers
            )
            or "alloc" in self.helpers
        )
        if needs_alloc and not self.external_helpers:
            self.includes.add("stdlib.h")
            chunks.append(
                """static void* _forge_alloc(size_t size) {
    void* result = malloc(size == 0 ? 1 : size);
    if (result == NULL) {
        abort();
    }
    return result;
}

static void* _forge_realloc(void* pointer, size_t size) {
    void* result = realloc(pointer, size == 0 ? 1 : size);
    if (result == NULL) {
        abort();
    }
    return result;
}"""
            )
        if any(helper.startswith("array_runtime:") for helper in self.helpers) and not self.external_helpers:
            self.includes.add("stdlib.h")
            chunks.append(
                """static void* _forge_array_new(size_t capacity, size_t element_size) {
    return capacity == 0 ? NULL : _forge_alloc(element_size * capacity);
}

static void _forge_array_grow(void** data, size_t* cap, size_t element_size) {
    size_t next = *cap == 0 ? 1 : *cap * 2;
    *data = _forge_realloc(*data, element_size * next);
    *cap = next;
}"""
            )
        if "string_copy" in self.helpers and not self.external_helpers:
            self.includes.update({"stdlib.h", "string.h"})
            chunks.append(
                """static char* _forge_string_copy(const char* value) {
    size_t len = strlen(value);
    char* result = _forge_alloc(len + 1);
    memcpy(result, value, len + 1);
    return result;
}"""
            )
        if "string_concat" in self.helpers and not self.external_helpers:
            self.includes.update({"stdarg.h", "stdlib.h", "string.h"})
            chunks.append(
                """static char* _forge_string_concat(size_t count, ...) {
    va_list args;
    size_t len = 0;
    va_start(args, count);
    for (size_t i = 0; i < count; i += 1) {
        len += strlen(va_arg(args, const char*));
    }
    va_end(args);

    char* result = _forge_alloc(len + 1);
    char* cursor = result;
    va_start(args, count);
    for (size_t i = 0; i < count; i += 1) {
        const char* part = va_arg(args, const char*);
        size_t part_len = strlen(part);
        memcpy(cursor, part, part_len);
        cursor += part_len;
    }
    va_end(args);
    *cursor = '\\0';
    return result;
}"""
            )
        for helper in sorted(self.helpers):
            if not helper.startswith("primitive_to_string:"):
                continue
            _, helper_name, c_type, fmt, cast = helper.split(":", 4)
            self.includes.update({"stdio.h", "stdlib.h"})
            chunks.append(
                f"""static char* {helper_name}({c_type} value) {{
    int len = snprintf(NULL, 0, "{fmt}", {cast});
    char* result = _forge_alloc((size_t)len + 1);
    snprintf(result, (size_t)len + 1, "{fmt}", {cast});
    return result;
}}"""
            )
        if "bool_to_string" in self.helpers:
            self.includes.update({"stdbool.h", "stdlib.h", "string.h"})
            chunks.append(
                """static char* _forge_bool_to_string(bool value) {
    const char* text = value ? "true" : "false";
    size_t len = strlen(text);
    char* result = _forge_alloc(len + 1);
    memcpy(result, text, len + 1);
    return result;
}"""
            )
        for helper in sorted(self.helpers):
            if not helper.startswith("array_type:"):
                continue
            _, array_name, element_type = helper.split(":", 2)
            self.includes.add("stdlib.h")
            guard = f"{array_name.upper()}_DEFINED"
            chunks.append(
                f"""#ifndef {guard}
#define {guard}
typedef struct {{
    size_t len;
    size_t cap;
    {element_type}* data;
}} {array_name};"""
                + f"""
#endif"""
            )
        for helper in sorted(self.helpers):
            if not helper.startswith("array_runtime:"):
                continue
            _, array_name, element_type = helper.split(":", 2)
            self.includes.add("stdlib.h")
            chunks.append(
                f"""static {array_name} {array_name}_new(size_t capacity) {{
    {array_name} array;
    array.len = 0;
    array.cap = capacity;
    array.data = _forge_array_new(capacity, sizeof({element_type}));
    return array;
}}

static void {array_name}_push({array_name}* array, {element_type} value) {{
    if (array->len == array->cap) {{
        _forge_array_grow((void**)&array->data, &array->cap, sizeof({element_type}));
    }}
    array->data[array->len] = value;
    array->len += 1;
}}"""
            )
        for helper in sorted(self.helpers):
            if not (
                helper.startswith("outcome_result:")
                or helper.startswith("local_outcome_result:")
            ):
                continue
            kind, result_name, success_type, outcome_specs = helper.split(":", 3)
            if kind == "outcome_result" and self.declarations_in_header:
                continue
            self.includes.add("stdint.h")
            guard = f"{result_name.upper()}_DEFINED"
            fields = []
            if success_type != "void":
                fields.append(f"    {success_type} success;")
            outcomes = tuple(spec for spec in outcome_specs.split(",") if spec)
            for spec in outcomes:
                field_name, c_type = spec.split("=", 1)
                fields.append(f"    {c_type} {field_name};")
            if not fields:
                fields.append("    char _forge_empty;")
            tag_type = f"{result_name}Tag"
            tag_lines = [f"    {result_name}_SUCCESS = 0"]
            tag_lines.extend(
                f"    {result_name}_{field_name.upper()} = {index}"
                for index, spec in enumerate(outcomes, start=1)
                for field_name, _ in (spec.split("=", 1),)
            )
            chunks.append(
                f"""#ifndef {guard}
#define {guard}
typedef enum {{
{("," + chr(10)).join(tag_lines)}
}} {tag_type};

typedef struct {{
    uint8_t tag;
{chr(10).join(fields)}
}} {result_name};
#endif"""
            )
        chunks.extend(
            self._async_native_helpers[key]
            for key in sorted(self._async_native_helpers)
        )
        return "\n\n".join(chunks)

    def _emit_array_type_helpers(self) -> str:
        chunks: list[str] = []
        for helper in sorted(self.helpers):
            if not helper.startswith("array_type:"):
                continue
            _, array_name, element_type = helper.split(":", 2)
            self.includes.add("stdlib.h")
            guard = f"{array_name.upper()}_DEFINED"
            chunks.append(
                f"""#ifndef {guard}
#define {guard}
typedef struct {{
    size_t len;
    size_t cap;
    {element_type}* data;
}} {array_name};
#endif"""
            )
        return "\n\n".join(chunks)

    def _emit_top_level(self, node) -> str:
        if isinstance(node, IrClass):
            if self._is_generic_class_declaration(node):
                return ""
            return self._emit_class(node)
        if isinstance(node, IrEnum):
            return self._emit_enum(node)
        if isinstance(node, IrFunction):
            if node.native_name is not None:
                return ""
            return self._emit_function(node)
        if isinstance(node, IrVariable):
            return self._emit_variable(node)
        if isinstance(node, IrStatement):
            return self._emit_statement(node)
        return ""

    def _is_generic_class_declaration(self, class_: IrClass) -> bool:
        node = class_.symbol.node if class_.symbol is not None else None
        return isinstance(node, ClassDeclaration) and bool(node.type_parameters)

    def _generic_struct_specializations(self, program: IrProgram) -> tuple[StructType, ...]:
        found: dict[str, StructType] = {}
        generic_classes = {
            id(declaration.symbol): declaration
            for declaration in program.declarations
            if isinstance(declaration, IrClass)
            and declaration.symbol is not None
            and self._is_generic_class_declaration(declaration)
        }

        def visit_type(type_: Type) -> None:
            if isinstance(type_, NullableType):
                visit_type(type_.inner_type)
            elif isinstance(type_, ArrayType):
                visit_type(type_.element_type)
            elif isinstance(type_, (TaskType, TaskCollectionType)):
                visit_type(type_.result_type)
            elif isinstance(type_, FunctionType):
                for parameter_type in type_.parameter_types:
                    visit_type(parameter_type)
                visit_type(type_.return_type)
                for outcome in type_.outcomes:
                    visit_type(outcome.type)
            elif isinstance(type_, StructType):
                for argument in type_.type_arguments:
                    visit_type(argument)
                if self._is_generic_struct_type(type_):
                    found[self._class_type_c_name(type_)] = type_
            elif isinstance(type_, (ClassType, InterfaceType)):
                for argument in type_.type_arguments:
                    visit_type(argument)

        def visit_node(node) -> None:
            if isinstance(node, IrClass):
                for member in node.members:
                    visit_node(member)
                for interface_type in node.implements:
                    visit_type(interface_type)
            elif isinstance(node, IrEnum):
                visit_type(node.value_type)
                for variant in node.variants:
                    if variant.value is not None:
                        visit_node(variant.value)
            elif isinstance(node, IrFunction):
                visit_type(node.function_type)
                for parameter in node.parameters:
                    visit_type(parameter.type)
                for statement in node.body.statements:
                    visit_node(statement)
            elif isinstance(node, IrVariable):
                visit_type(node.type)
                if node.initializer is not None:
                    visit_node(node.initializer)
            elif isinstance(node, IrStructLiteral):
                visit_type(node.type)
                for field in node.fields:
                    visit_node(field.value)
            else:
                values = (
                    getattr(node, field.name)
                    for field in dataclass_fields(node)
                ) if is_dataclass(node) else ()
                for value in values:
                    if isinstance(value, Type):
                        visit_type(value)
                    elif isinstance(value, tuple):
                        for item in value:
                            if isinstance(item, Type):
                                visit_type(item)
                            elif hasattr(item, "__dict__"):
                                visit_node(item)
                    elif hasattr(value, "__dict__"):
                        visit_node(value)

        for declaration in program.declarations:
            visit_node(declaration)
        return tuple(found.values())

    def _is_generic_struct_type(self, type_: StructType) -> bool:
        node = type_.symbol.node if type_.symbol is not None else None
        return (
            isinstance(node, ClassDeclaration)
            and node.kind == "struct"
            and bool(node.type_parameters)
            and bool(type_.type_arguments)
        )

    def _emit_generic_struct_specialization(self, type_: StructType) -> str:
        node = type_.symbol.node if type_.symbol is not None else None
        if not isinstance(node, ClassDeclaration):
            return ""
        substitutions = {
            parameter.name: argument
            for parameter, argument in zip(node.type_parameters, type_.type_arguments)
        }
        fields = []
        class_ = self._generic_ir_class(type_)
        if class_ is not None:
            for member in class_.members:
                if not isinstance(member, IrVariable) or "static" in member.modifiers:
                    continue
                field_type = self._specialize_type_by_name(member.type, substitutions)
                fields.append(
                    IrVariable(
                        member.location,
                        member.symbol,
                        member.name,
                        field_type,
                        member.mutable,
                        None,
                        member.modifiers,
                        member.safety,
                        member.field_ownership,
                    )
                )
        else:
            for member in node.members:
                if not isinstance(member, VariableDeclaration) or member.type is None or "static" in member.modifiers:
                    continue
                field_type = self._type_from_generic_ast_reference(member.type, substitutions)
                fields.append(
                    IrVariable(
                        member.location,
                        type_.symbol,
                        member.name,
                        field_type,
                        member.mutable,
                        None,
                        member.modifiers,
                    )
                )
        return self._struct_definition(self._class_type_c_name(type_), fields)

    def _type_from_generic_ast_reference(self, reference, substitutions: dict[str, Type]) -> Type:
        if reference.name in substitutions:
            base = substitutions[reference.name]
        else:
            base = {
                "Bool": BOOL,
                "bool": BOOL,
                "Int": INT,
                "int": INT,
                "Double": DOUBLE,
                "double": DOUBLE,
                "String": STRING,
                "string": STRING,
                "Void": VOID,
                "void": VOID,
            }.get(reference.name, TypeParameterType(reference.name))
        if reference.arguments and isinstance(base, (ClassType, StructType, InterfaceType)):
            arguments = tuple(
                self._type_from_generic_ast_reference(argument, substitutions)
                for argument in reference.arguments
            )
            if isinstance(base, ClassType):
                base = ClassType(base.name, base.symbol, arguments)
            elif isinstance(base, StructType):
                base = StructType(base.name, base.symbol, arguments)
            else:
                base = InterfaceType(base.name, base.symbol, arguments)
        return self._apply_ast_type_modifiers(base, reference)

    def _apply_ast_type_modifiers(self, base: Type, reference) -> Type:
        result = base
        for dimension in reference.array_dimensions:
            size = dimension.value if dimension is not None and isinstance(dimension.value, int) else None
            suffix = "[]" if size is None else f"[{size}]"
            result = ArrayType(f"{result.name}{suffix}", result, size)
        for _ in range(reference.array_depth - len(reference.array_dimensions)):
            result = ArrayType(f"{result.name}[]", result)
        if reference.nullable:
            result = NullableType(f"{result.name}?", result)
        return result

    def _generic_ir_class(self, type_: StructType) -> IrClass | None:
        target_symbol = type_.symbol
        if target_symbol is None:
            return None
        for declaration in self.ownership.program.declarations:
            if isinstance(declaration, IrClass) and declaration.symbol == target_symbol:
                return declaration
        return None

    def _specialize_type_by_name(self, type_: Type, substitutions: dict[str, Type]) -> Type:
        if isinstance(type_, TypeParameterType) and type_.name in substitutions:
            return substitutions[type_.name]
        if isinstance(type_, NullableType):
            inner = self._specialize_type_by_name(type_.inner_type, substitutions)
            if inner == type_.inner_type:
                return type_
            return NullableType(f"{inner.name}?", inner)
        if isinstance(type_, ArrayType):
            element = self._specialize_type_by_name(type_.element_type, substitutions)
            if element == type_.element_type:
                return type_
            suffix = "[]" if type_.size is None else f"[{type_.size}]"
            return ArrayType(f"{element.name}{suffix}", element, type_.size)
        if isinstance(type_, (TaskType, TaskCollectionType)):
            result = self._specialize_type_by_name(type_.result_type, substitutions)
            if result == type_.result_type:
                return type_
            if isinstance(type_, TaskType):
                return TaskType(f"Task<{result.display_name}>", result)
            return TaskCollectionType(f"TaskCollection<{result.display_name}>", result)
        if isinstance(type_, ClassType):
            arguments = tuple(
                self._specialize_type_by_name(argument, substitutions)
                for argument in type_.type_arguments
            )
            if arguments == type_.type_arguments:
                return type_
            return ClassType(type_.name, type_.symbol, arguments)
        if isinstance(type_, StructType):
            arguments = tuple(
                self._specialize_type_by_name(argument, substitutions)
                for argument in type_.type_arguments
            )
            if arguments == type_.type_arguments:
                return type_
            return StructType(type_.name, type_.symbol, arguments)
        if isinstance(type_, InterfaceType):
            arguments = tuple(
                self._specialize_type_by_name(argument, substitutions)
                for argument in type_.type_arguments
            )
            if arguments == type_.type_arguments:
                return type_
            return InterfaceType(type_.name, type_.symbol, arguments)
        return type_

    def _emit_class(self, class_: IrClass) -> str:
        if class_.name is None:
            raise CEmissionError("Cannot emit unnamed class")
        if class_.kind == "interface":
            if self.declarations_in_header:
                return ""
            return "\n".join(self._interface_header_declarations(class_))
        class_name = self._class_c_name(class_.name, class_.symbol)

        fields = [
            member
            for member in class_.members
            if isinstance(member, IrVariable)
            and "static" not in member.modifiers
        ]
        static_fields = [
            member
            for member in class_.members
            if isinstance(member, IrVariable)
            and "static" in member.modifiers
        ]
        methods = [
            member
            for member in class_.members
            if isinstance(member, IrFunction)
            and member.native_name is None
        ]

        chunks = []
        if not self.declarations_in_header:
            chunks.append(self._struct_definition(class_name, fields))
        static_field_chunks = [
            self._emit_static_field(class_name, field)
            for field in static_fields
        ]
        method_chunks = [
            self._emit_method(class_name, method, fields)
            for method in methods
        ]
        interface_adapter_chunks = [
            self._emit_interface_adapter(class_, class_name, interface_type)
            for interface_type in class_.implements
            if isinstance(interface_type, InterfaceType) and interface_type.symbol is not None
        ]
        destructor = self._emit_destructor(class_name, fields, methods)
        parts = (*chunks, *static_field_chunks, *method_chunks, *interface_adapter_chunks)
        parts = (*parts, destructor)
        return "\n\n".join(parts)

    def _emit_interface_adapter(
        self,
        class_: IrClass,
        class_name: str,
        interface_type: InterfaceType,
    ) -> str:
        if interface_type.symbol is None or not isinstance(interface_type.symbol.node, ClassDeclaration):
            raise CEmissionError(f"Cannot emit adapter for interface {interface_type.name}")
        interface_name = self._interface_type_c_name(interface_type)
        chunks: list[str] = []
        entries: list[str] = []
        for interface_member in interface_type.symbol.node.members:
            if not isinstance(interface_member, FunctionDeclaration):
                continue
            method = self._ir_method_named(class_, interface_member.name)
            if method is None:
                raise CEmissionError(
                    f"Class {class_.name} does not implement interface method {interface_member.name}"
                )
            wrapper_name = f"{class_name}_as_{interface_name}_{method.name}"
            parameters = ", ".join(
                f"{self._c_type(parameter.type)} arg{index}"
                for index, parameter in enumerate(method.parameters)
            )
            signature_parameters = f"void* object{', ' if parameters else ''}{parameters}"
            arguments = ", ".join(
                f"arg{index}"
                for index, _ in enumerate(method.parameters)
            )
            call = f"{class_name}_{method.name}((struct {class_name}*)object{', ' if arguments else ''}{arguments})"
            has_outcomes = (
                isinstance(method.function_type, FunctionType)
                and bool(method.function_type.outcomes)
            )
            if method.return_type == VOID and not has_outcomes:
                body = f"    {call};"
            else:
                body = f"    return {call};"
            chunks.append(
                f"static {self._function_c_return_type(method)} {wrapper_name}({signature_parameters}) {{\n"
                f"{body}\n"
                f"}}"
            )
            entries.append(f"    .{method.name} = {wrapper_name},")
        if not entries:
            entries.append("    ._forge_empty = 0,")
        chunks.append(
            f"const struct {interface_name}_vtable {class_name}_as_{interface_name}_vtable = {{\n"
            + "\n".join(entries)
            + "\n};"
        )
        return "\n\n".join(chunks)

    def _ir_method_named(self, class_: IrClass, name: str) -> IrFunction | None:
        for member in class_.members:
            if isinstance(member, IrFunction) and member.name == name:
                return member
        return None

    def _emit_enum(self, enum: IrEnum) -> str:
        if enum.name is None:
            raise CEmissionError("Cannot emit unnamed enum")
        if not isinstance(enum.value_type, EnumType) or enum.value_type.value_type is None:
            raise CEmissionError(f"Cannot emit enum {enum.name} without a value type")
        c_type = self._c_type(enum.value_type.value_type)
        lines: list[str] = []
        if not self.declarations_in_header:
            definition = self._enum_value_struct_definition(enum.value_type)
            if definition:
                lines.append(definition)
        for index, variant in enumerate(enum.variants):
            if variant.value is None:
                raise CEmissionError(f"Cannot emit enum variant {enum.name}.{variant.name} without a value")
            name = f"{self._enum_type_c_name(enum.value_type)}_{self._c_identifier(variant.name)}"
            declaration_type = (
                f"{c_type} const"
                if c_type.endswith("*")
                else f"const {c_type}"
            )
            storage = "static " if not self.declarations_in_header else ""
            value = self._emit_enum_variant_value(enum.value_type, variant.value, index)
            lines.append(f"{storage}{declaration_type} {name} = {value};")
        return "\n".join(lines)

    def _enum_header_declarations(self, enum: IrEnum) -> list[str]:
        if enum.name is None:
            raise CEmissionError("Cannot emit unnamed enum")
        if not isinstance(enum.value_type, EnumType) or enum.value_type.value_type is None:
            raise CEmissionError(f"Cannot emit enum {enum.name} without a value type")
        c_type = self._c_type(enum.value_type.value_type)
        declarations: list[str] = []
        definition = self._enum_value_struct_definition(enum.value_type)
        if definition:
            declarations.append(definition)
        for variant in enum.variants:
            name = f"{self._enum_type_c_name(enum.value_type)}_{self._c_identifier(variant.name)}"
            declaration_type = (
                f"{c_type} const"
                if c_type.endswith("*")
                else f"const {c_type}"
            )
            declarations.append(f"extern {declaration_type} {name};")
        return declarations

    def _enum_value_struct_definition(self, enum_type: EnumType) -> str:
        value_type = enum_type.value_type
        if not isinstance(value_type, StructType):
            return ""
        enum_node = enum_type.symbol.node if enum_type.symbol is not None else None
        inline_type = getattr(enum_node, "value_type", None)
        fields = getattr(inline_type, "fields", None)
        if fields is None:
            return ""
        class_name = self._class_type_c_name(value_type)
        field_lines = ["    int _forge_variant_id;"]
        field_lines.extend(
            f"    {self._type_reference_c_type(field.type)} {field.name};"
            for field in fields
            if field.type is not None
        )
        return f"struct {class_name} {{\n" + "\n".join(field_lines) + "\n};"

    def _emit_enum_variant_value(self, enum_type: EnumType, value: IrExpression, index: int) -> str:
        if not isinstance(enum_type.value_type, StructType) or not isinstance(value, IrStructLiteral):
            return self._emit_expression(value)
        class_name = self._class_type_c_name(enum_type.value_type)
        fields = [
            f".{field.name} = {self._emit_expression(field.value)}"
            if field.name is not None
            else self._emit_expression(field.value)
            for field in value.fields
        ]
        fields.insert(0, f"._forge_variant_id = {index}")
        return f"(struct {class_name}){{{', '.join(fields)}}}"

    def _struct_definition(self, class_name: str, fields: list[IrVariable]) -> str:
        field_lines = [
            f"    {self._c_type(field.type)} {field.name};"
            for field in fields
        ]
        if not field_lines:
            field_lines.append("    char _forge_empty;")
        return f"struct {class_name} {{\n" + "\n".join(field_lines) + "\n};"

    def _emit_destructor(
        self,
        class_name: str,
        fields: list[IrVariable],
        methods: list[IrFunction],
    ) -> str:
        self.includes.add("stdlib.h")
        terminate_method = next(
            (method for method in methods if "terminate" in method.modifiers),
            None,
        )

        self._indent += 1
        lines = [self._line("if (value == NULL) {")]
        self._indent += 1
        lines.append(self._line("return;"))
        self._indent -= 1
        lines.append(self._line("}"))
        if terminate_method is not None:
            lines.append(self._line(f"{class_name}_{terminate_method.name}(value);"))
        for field in fields:
            cleanup_kind = self.ownership.destructor_field_cleanup_kind(field)
            if cleanup_kind == "string":
                lines.append(self._line(f"free((void*)value->{field.name});"))
                continue
            if cleanup_kind == "class":
                field_type = self._class_type(field.type)
                lines.append(
                    self._line(
                        f"_forge_free_{self._class_type_c_name(field_type)}(value->{field.name});"
                    )
                )
                continue
            if cleanup_kind == "array" and isinstance(field.type, ArrayType):
                lines.extend(
                    self._line(line)
                    for line in self._array_cleanup_lines_for(
                        field.type,
                        f"value->{field.name}",
                    )
                )
        lines.append(self._line("free(value);"))
        self._indent -= 1

        body = "\n".join(lines)
        return f"void _forge_free_{class_name}(struct {class_name}* value) {{\n{body}\n}}"

    def _emit_static_field(self, class_name: str, field: IrVariable) -> str:
        initializer = ""
        if field.initializer is not None:
            initializer = f" = {self._emit_expression(field.initializer)}"
        return f"{self._c_type(field.type)} {class_name}_{field.name}{initializer};"

    def _emit_method(
        self,
        class_name: str,
        function: IrFunction,
        fields: list[IrVariable],
    ) -> str:
        if function.kind == "new":
            return self._emit_constructor(class_name, function, fields)
        extra_parameters = ()
        if "static" not in function.modifiers:
            extra_parameters = (f"struct {class_name}* this",)
        return self._emit_function(
            function,
            c_name=f"{class_name}_{function.name}",
            extra_parameters=extra_parameters,
        )

    def _emit_constructor(
        self,
        class_name: str,
        function: IrFunction,
        fields: list[IrVariable],
    ) -> str:
        self.helpers.add("alloc")
        signature = self._function_signature(
            function,
            c_name=f"{class_name}_{function.name}",
        )

        self._indent += 1
        lines = [
            self._line(f"struct {class_name}* this = _forge_alloc(sizeof(struct {class_name}));")
        ]
        lines.extend(self._constructor_field_initializers(fields, function))
        lines.extend(
            self._emit_constructor_statement(statement, function)
            for statement in function.body.statements
        )
        if not self._ends_with_return(function.body):
            lines.append(self._line("return this;"))
        self._indent -= 1

        return f"{signature} {{\n" + "\n".join(lines) + "\n" + self._line("}")

    def _emit_constructor_statement(
        self,
        statement: IrStatement,
        function: IrFunction,
    ) -> str:
        if not isinstance(statement, IrExpressionStatement):
            return self._emit_indented_statement(statement)
        expression = statement.expression
        if (
            not isinstance(expression, IrAssignment)
            or not isinstance(expression.target, IrMember)
            or not isinstance(expression.target.receiver, IrSpecialRef)
            or expression.target.receiver.kind != "this"
            or not isinstance(expression.value, IrLocalRef)
        ):
            return self._emit_indented_statement(statement)

        parameter = next(
            (
                item
                for item in function.parameters
                if item.symbol == expression.value.symbol
            ),
            None,
        )
        if parameter is None:
            return self._emit_indented_statement(statement)

        target = self._emit_expression(expression.target)
        value = self._emit_expression(expression.value)
        if (
            expression.target.type == STRING
            and getattr(parameter.symbol.node, "ownership", "borrow") != "take"
        ):
            self.helpers.add("string_copy")
            value = f"_forge_string_copy({value})"
        return self._line(f"{target} = {value};")

    def _constructor_field_initializers(
        self,
        fields: list[IrVariable],
        function: IrFunction,
    ) -> list[str]:
        lines: list[str] = []
        parameter_names = {parameter.name for parameter in function.parameters}
        for field in fields:
            if field.name in parameter_names:
                continue
            if isinstance(field.type, ArrayType) and field.type.size is None:
                array_type = self._c_type(field.type)
                initializer = (
                    self._emit_expression(field.initializer)
                    if field.initializer is not None
                    else f"({array_type}){{0, 0, NULL}}"
                )
                lines.append(self._line(f"this->{field.name} = {initializer};"))
                continue
            if self._class_type(field.type) is not None:
                initializer = (
                    self._emit_expression(field.initializer)
                    if field.initializer is not None
                    else "NULL"
                )
                lines.append(self._line(f"this->{field.name} = {initializer};"))
        return lines

    def _emit_function(
        self,
        function: IrFunction,
        *,
        c_name: str | None = None,
        extra_parameters: tuple[str, ...] = (),
    ) -> str:
        emitted_name = c_name or self._function_c_name(function)
        signature = self._function_signature(
            function,
            c_name=c_name,
            extra_parameters=extra_parameters,
        )
        main_returns_int = emitted_name == "main" and function.return_type == VOID

        previous = self._main_returns_int
        self._main_returns_int = main_returns_int
        self._function_stack.append(function)
        body = self._emit_block(
            function.body,
            append_main_return=main_returns_int,
            initial_cleanup=self._owned_class_parameters(function),
            use_return_cleanup=not self._function_has_outcomes(function),
            append_outcome_success_return=(
                self._function_has_outcomes(function)
                and function.return_type == VOID
            ),
        )
        self._function_stack.pop()
        self._main_returns_int = previous
        return f"{signature} {body}"

    def _emit_block(
        self,
        block: IrBlock,
        *,
        append_main_return: bool = False,
        initial_cleanup: tuple[CleanupBinding, ...] = (),
        use_return_cleanup: bool = False,
        append_outcome_success_return: bool = False,
    ) -> str:
        if (
            not block.statements
            and not append_main_return
            and not append_outcome_success_return
            and not initial_cleanup
        ):
            return "{}"

        self._cleanup_stack.append(list(initial_cleanup))
        self._array_cleanup_stack.append([])
        self._string_cleanup_stack.append([])
        self._struct_field_cleanup_stack.append([])
        context = None
        if use_return_cleanup:
            current = self._current_function()
            return_type = INT if append_main_return else (current.return_type if current is not None else VOID)
            context = _ReturnCleanupContext(return_type)
            self._return_cleanup_stack.append(context)
        self._indent += 1
        lines = [self._emit_indented_statement(statement) for statement in block.statements]
        block_ends_with_return = self._ends_with_return(block)
        if context is not None:
            if context.used:
                if context.return_var is not None:
                    lines.insert(0, self._line(f"{self._c_return_type(context.return_type)} {context.return_var};"))
                lines.append(self._line("cleanup:"))
                lines.extend(self._line(line) for line in self._block_cleanup_lines())
                if context.return_var is None:
                    lines.append(self._line("return 0;" if append_main_return else "return;"))
                else:
                    lines.append(self._line(f"return {context.return_var};"))
            elif not block_ends_with_return:
                lines.extend(self._line(line) for line in self._block_cleanup_lines())
                if append_main_return:
                    lines.append(self._line("return 0;"))
                if append_outcome_success_return:
                    lines.append(self._line(f"return {self._success_result_initializer(None)};"))
            self._return_cleanup_stack.pop()
        else:
            if not block_ends_with_return:
                lines.extend(self._line(line) for line in self._block_cleanup_lines())
            if append_main_return and not block_ends_with_return:
                lines.append(self._line("return 0;"))
            if append_outcome_success_return and not block_ends_with_return:
                lines.append(self._line(f"return {self._success_result_initializer(None)};"))
        self._indent -= 1
        self._string_cleanup_stack.pop()
        self._array_cleanup_stack.pop()
        self._struct_field_cleanup_stack.pop()
        self._cleanup_stack.pop()
        inner = "\n".join(lines)
        return "{\n" + inner + "\n" + self._line("}")

    def _ends_with_return(self, block: IrBlock) -> bool:
        return bool(block.statements and isinstance(block.statements[-1], IrReturn))

    def _emit_indented_statement(self, node) -> str:
        self._statement_prelude_stack.append([])
        self._statement_cleanup_stack.append([])
        statement = self._emit_statement(node)
        prelude = self._statement_prelude_stack.pop()
        cleanup = [] if isinstance(node, IrReturn) else self._statement_cleanup_stack.pop()
        if cleanup:
            self.includes.add("stdlib.h")
        if not isinstance(node, IrReturn) and not prelude and not cleanup:
            if (
                isinstance(node, IrExpressionStatement)
                and isinstance(node.expression, (IrMemberBlock, IrSequence, IrArrayBulkCall))
            ) or isinstance(node, (IrSwitch, IrArrayDestructuring)) or (
                isinstance(node, IrVariable) and "\n" in statement
            ):
                return "\n".join(self._line(line) for line in statement.splitlines())
            return self._line(statement)
        if isinstance(node, IrReturn):
            self._statement_cleanup_stack.pop()
        lines = (*prelude, *statement.splitlines(), *cleanup)
        return "\n".join(self._line(line) for line in lines)

    def _emit_statement(self, node) -> str:
        if isinstance(node, IrVariable):
            return self._emit_variable(node)
        if isinstance(node, IrArrayDestructuring):
            return self._emit_array_destructuring(node)
        if isinstance(node, IrReturn):
            if node.expression is None:
                statement_cleanup = self._statement_cleanup_lines()
                cleanup = self._cleanup_lines_for_return()
                if self._current_function_has_outcomes():
                    result = f"return {self._success_result_initializer(None)};"
                else:
                    if (statement_cleanup or cleanup) and self._can_goto_function_cleanup_void():
                        context = self._return_cleanup_stack[-1]
                        context.used = True
                        return "\n".join((*statement_cleanup, "goto cleanup;"))
                    result = "return 0;" if self._main_returns_int else "return;"
                return "\n".join((*statement_cleanup, *cleanup, result))
            return "\n".join(self._emit_return_lines(node.expression))
        if isinstance(node, IrBreak):
            return self._emit_break(node)
        if isinstance(node, IrPrint):
            return self._emit_print(node)
        if isinstance(node, IrIf):
            return self._emit_if(node)
        if isinstance(node, IrSwitch):
            return self._emit_switch(node)
        if isinstance(node, IrWhile):
            return self._emit_while(node)
        if isinstance(node, IrDoWhile):
            self._loop_result_stack.append(None)
            self._loop_cleanup_depth_stack.append(len(self._cleanup_stack))
            body = self._emit_block(node.body)
            condition = self._emit_loop_condition_check(node.condition)
            self._loop_cleanup_depth_stack.pop()
            self._loop_result_stack.pop()
            return "\n".join(
                (
                    "do {",
                    *(f"    {line}" for line in body.splitlines()),
                    *(f"    {line}" for line in condition),
                    "} while (true);",
                )
            )
        if isinstance(node, IrExpressionStatement):
            if isinstance(node.expression, IrMemberBlock):
                return self._emit_member_block_statement(node.expression)
            if isinstance(node.expression, IrSequence):
                return self._emit_sequence_statement(node.expression)
            if isinstance(node.expression, IrArrayBulkCall):
                return self._emit_array_bulk_call_statement(node.expression)
            return f"{self._emit_expression(node.expression)};"
        if isinstance(node, IrBlock):
            return self._emit_block(node)
        raise CEmissionError(f"Cannot emit statement {type(node).__name__}")

    def _emit_array_destructuring(
        self, declaration: IrArrayDestructuring
    ) -> str:
        lines: list[str] = []
        if declaration.source_temp is not None:
            source_temp = declaration.source_temp
            if (
                isinstance(source_temp.type, ArrayType)
                and source_temp.type.size is None
                and isinstance(source_temp.initializer, IrCatch)
            ):
                owns_source = self._new_temp("array_owned")
                self._statement_prelude_stack[-1].append(
                    f"int {owns_source} = 0;"
                )
                source_value = self._emit_catch_expression(
                    source_temp.initializer,
                    ownership_temp=owns_source,
                )
                lines.append(
                    f"{self._c_type(source_temp.type)} {source_temp.name} = {source_value};"
                )
                if self._array_cleanup_stack:
                    self._array_cleanup_stack[-1].append(
                        _ConditionalArrayCleanup(source_temp, owns_source)
                    )
            else:
                lines.extend(self._emit_variable(source_temp).splitlines())
        for binding in declaration.bindings:
            prelude_start = len(self._statement_prelude_stack[-1])
            emitted = self._emit_variable(binding)
            binding_prelude = self._statement_prelude_stack[-1][prelude_start:]
            del self._statement_prelude_stack[-1][prelude_start:]
            lines.extend(binding_prelude)
            lines.extend(emitted.splitlines())
        return "\n".join(lines)

    def _emit_return_expression(self, expression: IrExpression) -> str:
        if expression.type == STRING:
            returned_symbol = self._returned_symbol(expression)
            if returned_symbol is not None and self._is_owned_string_symbol(returned_symbol):
                return self._emit_expression(expression)
            return self._emit_owned_string_value(expression, cleanup_result=False)
        if self.ownership.owned_array_expression(expression):
            return self._emit_owned_array_value(expression, cleanup_result=False)
        return self._emit_expression(expression)

    def _emit_return_lines(self, expression: IrExpression) -> tuple[str, ...]:
        if (
            isinstance(expression, IrConditional)
            and not self.ownership.owned_array_expression(expression)
        ):
            return self._emit_conditional_return_lines(expression)

        if self._current_function_has_outcomes():
            return self._emit_outcome_function_return_lines(expression)

        prelude_start = len(self._statement_prelude_stack[-1])
        cleanup_start = len(self._statement_cleanup_stack[-1])
        emitted_expression = self._emit_return_expression(expression)

        prelude = tuple(self._statement_prelude_stack[-1][prelude_start:])
        del self._statement_prelude_stack[-1][prelude_start:]

        statement_cleanup = tuple(
            reversed(self._statement_cleanup_stack[-1][cleanup_start:])
        )
        del self._statement_cleanup_stack[-1][cleanup_start:]

        cleanup = self._cleanup_lines_for_return(
            skip_symbol=self._returned_symbol(expression)
        )
        if statement_cleanup or cleanup:
            if self._can_goto_function_cleanup(expression):
                context = self._return_cleanup_stack[-1]
                if context.return_var is None:
                    context.return_var = self._new_temp("return")
                context.used = True
                return (
                    *prelude,
                    f"{context.return_var} = {emitted_expression};",
                    *statement_cleanup,
                    "goto cleanup;",
                )
            temp = self._new_temp("return")
            return (
                *prelude,
                f"{self._c_return_type(expression.type)} {temp} = {emitted_expression};",
                *statement_cleanup,
                *cleanup,
                f"return {temp};",
            )
        return (*prelude, *statement_cleanup, f"return {emitted_expression};")

    def _can_goto_function_cleanup(self, expression: IrExpression) -> bool:
        if not self._return_cleanup_stack:
            return False
        if (
            len(self._cleanup_stack) != 1
            or len(self._array_cleanup_stack) != 1
            or len(self._string_cleanup_stack) != 1
            or len(self._struct_field_cleanup_stack) != 1
        ):
            return False
        if self._returned_symbol(expression) is not None:
            return False
        return True

    def _can_goto_function_cleanup_void(self) -> bool:
        if not self._return_cleanup_stack:
            return False
        return (
            len(self._cleanup_stack) == 1
            and len(self._array_cleanup_stack) == 1
            and len(self._string_cleanup_stack) == 1
            and len(self._struct_field_cleanup_stack) == 1
        )

    def _emit_outcome_function_return_lines(self, expression: IrExpression) -> tuple[str, ...]:
        prelude_start = len(self._statement_prelude_stack[-1])
        cleanup_start = len(self._statement_cleanup_stack[-1])
        initializer = self._outcome_return_initializer(expression)

        prelude = tuple(self._statement_prelude_stack[-1][prelude_start:])
        del self._statement_prelude_stack[-1][prelude_start:]

        statement_cleanup = tuple(
            reversed(self._statement_cleanup_stack[-1][cleanup_start:])
        )
        del self._statement_cleanup_stack[-1][cleanup_start:]

        cleanup = self._cleanup_lines_for_return(
            skip_symbol=self._returned_symbol(expression)
        )
        if statement_cleanup or cleanup:
            temp = self._new_temp("return")
            current = self._current_function()
            if current is None or not isinstance(current.function_type, FunctionType):
                raise CEmissionError("Outcome return outside function")
            return (
                *prelude,
                f"{self._function_result_c_name(current.function_type)} {temp} = {initializer};",
                *statement_cleanup,
                *cleanup,
                f"return {temp};",
            )
        return (*prelude, f"return {initializer};")

    def _outcome_return_initializer(self, expression: IrExpression) -> str:
        current = self._current_function()
        if current is None or not isinstance(current.function_type, FunctionType):
            raise CEmissionError("Outcome return outside function")
        outcome = next(
            (
                candidate
                for candidate in current.function_type.outcomes
                if candidate.type == expression.type
            ),
            None,
        )
        emitted = self._emit_return_expression(expression)
        if outcome is not None:
            tag = self._result_tag_name(current.function_type, outcome.type)
            field = self._outcome_field_name(outcome.type)
            return f"({self._function_result_c_name(current.function_type)}){{.tag = {tag}, .{field} = {emitted}}}"
        return self._success_result_initializer(None if expression.type == VOID else emitted)

    def _success_result_initializer(self, emitted_expression: str | None) -> str:
        current = self._current_function()
        if current is None or not isinstance(current.function_type, FunctionType):
            raise CEmissionError("Success result outside function")
        tag = self._result_tag_name(current.function_type, None)
        if emitted_expression is None:
            return f"({self._function_result_c_name(current.function_type)}){{.tag = {tag}}}"
        return (
            f"({self._function_result_c_name(current.function_type)})"
            f"{{.tag = {tag}, .success = {emitted_expression}}}"
        )

    def _emit_conditional_return_lines(self, expression: IrConditional) -> tuple[str, ...]:
        condition = self._emit_expression(expression.condition)
        then_lines = self._emit_return_lines(expression.then_expression)
        else_lines = self._emit_return_lines(expression.else_expression)
        return (
            f"if ({condition}) {{",
            *(f"    {line}" for line in then_lines),
            "} else {",
            *(f"    {line}" for line in else_lines),
            "}",
        )

    def _emit_conditional_assignment_lines(
        self,
        target: str,
        expression: IrConditional,
        *,
        owned_string: bool = False,
    ) -> tuple[str, ...]:
        condition = self._emit_expression(expression.condition)
        then_lines = self._emit_assignment_branch_lines(
            target,
            expression.then_expression,
            owned_string=owned_string,
        )
        else_lines = self._emit_assignment_branch_lines(
            target,
            expression.else_expression,
            owned_string=owned_string,
        )
        return (
            f"if ({condition}) {{",
            *(f"    {line}" for line in then_lines),
            "} else {",
            *(f"    {line}" for line in else_lines),
            "}",
        )

    def _emit_assignment_branch_lines(
        self,
        target: str,
        expression: IrExpression,
        *,
        owned_string: bool = False,
    ) -> tuple[str, ...]:
        prelude_start = len(self._statement_prelude_stack[-1])
        cleanup_start = len(self._statement_cleanup_stack[-1])
        emitted_expression = (
            self._emit_owned_string_value(expression, cleanup_result=False)
            if owned_string
            else self._emit_return_expression(expression)
        )

        prelude = tuple(self._statement_prelude_stack[-1][prelude_start:])
        del self._statement_prelude_stack[-1][prelude_start:]

        statement_cleanup = tuple(
            reversed(self._statement_cleanup_stack[-1][cleanup_start:])
        )
        del self._statement_cleanup_stack[-1][cleanup_start:]

        return (*prelude, f"{target} = {emitted_expression};", *statement_cleanup)

    def _emit_array_conditional_assignment_lines(
        self,
        target: str,
        expression: IrConditional,
    ) -> tuple[str, ...]:
        condition = self._emit_expression(expression.condition)
        then_lines = self._emit_array_assignment_branch_lines(
            target,
            expression.then_expression,
        )
        else_lines = self._emit_array_assignment_branch_lines(
            target,
            expression.else_expression,
        )
        return (
            f"if ({condition}) {{",
            *(f"    {line}" for line in then_lines),
            "} else {",
            *(f"    {line}" for line in else_lines),
            "}",
        )

    def _emit_array_assignment_branch_lines(
        self,
        target: str,
        expression: IrExpression,
    ) -> tuple[str, ...]:
        if isinstance(expression, IrConditional):
            return self._emit_array_conditional_assignment_lines(target, expression)
        if not self.ownership.owned_array_expression(expression):
            return self._emit_array_copy_assignment_lines(target, expression)
        prelude_start = len(self._statement_prelude_stack[-1])
        cleanup_start = len(self._statement_cleanup_stack[-1])
        value = self._emit_owned_array_value(expression, cleanup_result=False)
        prelude = tuple(self._statement_prelude_stack[-1][prelude_start:])
        del self._statement_prelude_stack[-1][prelude_start:]
        cleanup = tuple(
            reversed(self._statement_cleanup_stack[-1][cleanup_start:])
        )
        del self._statement_cleanup_stack[-1][cleanup_start:]
        return (*prelude, f"{target} = {value};", *cleanup)

    def _emit_array_copy_assignment_lines(
        self,
        target: str,
        expression: IrExpression,
    ) -> tuple[str, ...]:
        array_type = expression.type
        if not isinstance(array_type, ArrayType) or array_type.size is not None:
            raise CEmissionError("Expected a borrowed dynamic array")
        if self.ownership.array_element_cleanup_kind(array_type) == "class":
            raise CEmissionError(
                "Cannot copy a borrowed conditional array with owned class elements"
            )

        prelude_start = len(self._statement_prelude_stack[-1])
        cleanup_start = len(self._statement_cleanup_stack[-1])
        source_value = self._emit_expression(expression)
        prelude = tuple(self._statement_prelude_stack[-1][prelude_start:])
        del self._statement_prelude_stack[-1][prelude_start:]
        cleanup = tuple(
            reversed(self._statement_cleanup_stack[-1][cleanup_start:])
        )
        del self._statement_cleanup_stack[-1][cleanup_start:]

        array_name = self._array_c_name(array_type)
        self._array_runtime_helper(array_type)
        source = self._new_temp("array_source")
        lines = [
            *prelude,
            f"{array_name} {source} = {source_value};",
            f"{target} = {array_name}_new({source}.len);",
            f"for (size_t _forge_i = 0; _forge_i < {source}.len; _forge_i += 1) {{",
        ]
        element = f"{source}.data[_forge_i]"
        if array_type.element_type == STRING:
            self.helpers.add("string_copy")
            element = f"_forge_string_copy({element})"
        lines.extend(
            (
                f"    {array_name}_push(&{target}, {element});",
                "}",
                *cleanup,
            )
        )
        return tuple(lines)

    def _returned_symbol(self, expression: IrExpression):
        returned_expression = (
            expression.expression
            if isinstance(expression, IrMove)
            else expression
        )
        return (
            returned_expression.symbol
            if isinstance(returned_expression, IrLocalRef)
            else None
        )

    def _emit_member_block_statement(self, expression: IrMemberBlock) -> str:
        lines: list[str] = []
        for child in expression.expressions:
            prelude_start = len(self._statement_prelude_stack[-1])
            child_expression = self._emit_expression(child)
            prelude = self._statement_prelude_stack[-1][prelude_start:]
            del self._statement_prelude_stack[-1][prelude_start:]
            lines.extend(prelude)
            lines.append(f"{child_expression};")
        return "\n".join(lines)

    def _emit_member_block_expression(self, expression: IrMemberBlock) -> str:
        if not self._statement_prelude_stack:
            raise CEmissionError("Member block expression requires a statement context")
        block = self._emit_member_block_statement(expression)
        if block:
            self._statement_prelude_stack[-1].extend(block.splitlines())
        return self._emit_expression(expression.receiver)

    def _emit_variable(self, variable: IrVariable) -> str:
        if isinstance(variable.type, TaskType) and self._is_async_runtime_call(variable.initializer):
            return self._emit_async_native_task_variable(variable)
        if (
            isinstance(variable.type, TaskCollectionType)
            and self._is_async_runtime_task_bulk_call(variable.initializer)
        ):
            return self._emit_async_native_task_collection_variable(variable)
        if isinstance(variable.type, ArrayType) and variable.type.size is not None:
            if (
                variable.safety is not None
                and variable.safety.ownership == "borrow"
                and variable.initializer is not None
                and not isinstance(variable.initializer, IrArrayLiteral)
            ):
                element_type = self._c_type(variable.type.element_type)
                initializer = self._emit_expression(variable.initializer)
                return f"{element_type}* {variable.name} = {initializer};"
            return self._emit_fixed_array_variable(variable)
        if (
            isinstance(variable.type, ArrayType)
            and variable.type.size is None
            and variable.initializer is not None
            and isinstance(variable.initializer, IrArrayLiteral)
            and not self._statement_prelude_stack
        ):
            return self._emit_top_level_dynamic_array_variable(variable)
        initializer = ""
        c_type = self._c_type(variable.type)
        if variable.initializer is not None:
            if isinstance(variable.type, InterfaceType):
                initializer = f" = {self._emit_interface_value(variable.initializer, variable.type)}"
                return f"{c_type} {variable.name}{initializer};"
            if variable.type == STRING and isinstance(variable.initializer, IrConditional):
                if self._string_cleanup_stack:
                    self._string_cleanup_stack[-1].append(variable)
                return "\n".join(
                    (
                        f"char* {variable.name};",
                        *self._emit_conditional_assignment_lines(
                            variable.name,
                            variable.initializer,
                            owned_string=True,
                        ),
                    )
                )
            if (
                isinstance(variable.type, ArrayType)
                and variable.type.size is None
                and isinstance(variable.initializer, IrConditional)
                and self.ownership.owned_array_expression(variable.initializer)
            ):
                if self._array_cleanup_stack:
                    self._array_cleanup_stack[-1].append(variable)
                return "\n".join(
                    (
                        f"{c_type} {variable.name};",
                        *self._emit_array_conditional_assignment_lines(
                            variable.name,
                            variable.initializer,
                        ),
                    )
                )
            if self.ownership.string_local_owns_initializer(variable):
                c_type = "char*"
                initializer = (
                    f" = {self._emit_owned_string_value(variable.initializer, cleanup_result=False)}"
                )
                if self._string_cleanup_stack:
                    self._string_cleanup_stack[-1].append(variable)
                return f"{c_type} {variable.name}{initializer};"
            if isinstance(variable.type, NullableType):
                initializer = f" = {self._emit_nullable_value(variable.initializer, variable.type)}"
                return f"{c_type} {variable.name}{initializer};"
            if (
                variable.type == STRING
                and self.ownership.owned_string_expression(variable.initializer)
            ):
                c_type = "char*"
                initializer = (
                    f" = {self._emit_owned_string_expression(variable.initializer, cleanup_result=False)}"
                )
                if self._string_cleanup_stack:
                    self._string_cleanup_stack[-1].append(variable)
            elif (
                isinstance(variable.type, ArrayType)
                and variable.type.size is None
                and self.ownership.allocating_array_call(variable.initializer)
            ):
                initializer = (
                    f" = {self._emit_owned_array_call(variable.initializer, cleanup_result=False)}"
                )
            else:
                initializer = f" = {self._emit_expression(variable.initializer)}"
        cleanup_kind = self.ownership.local_cleanup_kind(variable)
        if cleanup_kind == "array" and self._array_cleanup_stack:
            self._array_cleanup_stack[-1].append(variable)
        if cleanup_kind == "class" and self._cleanup_stack:
            self._cleanup_stack[-1].append(variable)
        return f"{c_type} {variable.name}{initializer};"

    def _emit_interface_value(
        self,
        expression: IrExpression,
        interface_type: InterfaceType,
    ) -> str:
        if isinstance(expression.type, InterfaceType):
            return self._emit_expression(expression)
        class_type = self._class_type(expression.type)
        if class_type is None:
            raise CEmissionError(
                f"Cannot convert {expression.type.display_name} to interface {interface_type.display_name}"
            )
        class_name = self._class_type_c_name(class_type)
        interface_name = self._interface_type_c_name(interface_type)
        return (
            f"(struct {interface_name}){{"
            f".object = {self._emit_expression(expression)}, "
            f".vtable = &{class_name}_as_{interface_name}_vtable"
            f"}}"
        )

    def _ensure_interface_adapter(
        self,
        class_type: ClassType,
        interface_type: InterfaceType,
    ) -> None:
        interface_symbol = interface_type.symbol
        if interface_symbol is None or not isinstance(interface_symbol.node, ClassDeclaration):
            raise CEmissionError(f"Cannot emit adapter for builtin interface {interface_type.name}")
        class_name = self._class_type_c_name(class_type)
        interface_name = self._interface_type_c_name(interface_type)
        vtable_name = f"{class_name}_as_{interface_name}_vtable"
        helper_key = f"interface-adapter:{vtable_name}"
        if helper_key in self.helpers:
            return
        method_names = [
            member.name
            for member in interface_symbol.node.members
            if isinstance(member, FunctionDeclaration)
        ]
        wrappers: list[str] = []
        vtable_entries: list[str] = []
        for method_name in method_names:
            method = self._class_method_for_interface(class_type, method_name)
            if method is None:
                raise CEmissionError(
                    f"Class {class_type.display_name} does not implement interface method {method_name}"
                )
            function_type = self._function_type_for_declaration(method, class_type)
            return_type = self._function_type_c_return_type(function_type)
            parameters = ", ".join(
                f"{self._c_type(parameter_type)} arg{index}"
                for index, parameter_type in enumerate(function_type.parameter_types)
            )
            signature_parameters = f"void* object{', ' if parameters else ''}{parameters}"
            arguments = ", ".join(
                f"arg{index}"
                for index, _ in enumerate(function_type.parameter_types)
            )
            call = f"{class_name}_{method_name}((struct {class_name}*)object{', ' if arguments else ''}{arguments})"
            if function_type.return_type == VOID and not function_type.outcomes:
                body = f"    {call};"
            else:
                body = f"    return {call};"
            wrapper_name = f"{class_name}_as_{interface_name}_{method_name}"
            wrappers.append(
                f"static {return_type} {wrapper_name}({signature_parameters}) {{\n"
                f"{body}\n"
                f"}}"
            )
            vtable_entries.append(f"    .{method_name} = {wrapper_name},")
        if not vtable_entries:
            vtable_entries.append("    ._forge_empty = 0,")
        helper = (
            "\n\n".join(wrappers)
            + ("\n\n" if wrappers else "")
            + f"static const struct {interface_name}_vtable {vtable_name} = {{\n"
            + "\n".join(vtable_entries)
            + "\n};"
        )
        self.helpers.add(helper_key)
        self.helpers.add(helper)

    def _class_method_for_interface(
        self,
        class_type: ClassType,
        method_name: str,
    ) -> FunctionDeclaration | None:
        if class_type.symbol is None or not isinstance(class_type.symbol.node, ClassDeclaration):
            return None
        declaration = class_type.symbol.node
        for member in declaration.members:
            if isinstance(member, FunctionDeclaration) and member.name == method_name:
                return member
        for reference in declaration.uses:
            resolved = self._symbol_for_type_reference(reference)
            if not isinstance(resolved, Symbol) or not isinstance(resolved.node, ClassDeclaration):
                continue
            for member in resolved.node.members:
                if isinstance(member, FunctionDeclaration) and member.name == method_name:
                    return member
        return None

    def _emit_async_native_task_variable(self, variable: IrVariable) -> str:
        if not isinstance(variable.initializer, IrCall):
            raise CEmissionError("Expected async task initializer")
        node = self._function_declaration_for_callee(variable.initializer.callee)
        if node is None:
            raise CEmissionError("Expected async function")
        call_name = self._async_runtime_call_name(variable.initializer.callee, node)
        receiver_type = self._async_runtime_receiver_type(variable.initializer.callee, node)
        helper = self._async_native_helper(variable.initializer, call_name, receiver_type)
        context_type = helper["context_type"]
        run_function = helper["run_function"]
        context = f"{variable.name}_context"
        self._async_native_task_contexts[id(variable.symbol)] = context
        lines = [f"{context_type} {context};"]
        if receiver_type is not None and isinstance(variable.initializer.callee, IrMember):
            lines.append(f"{context}.receiver = {self._emit_expression(variable.initializer.callee.receiver)};")
        for index, argument in enumerate(variable.initializer.arguments):
            lines.append(f"{context}.arg{index} = {self._emit_expression(argument)};")
        lines.append(
            f"_ForgeAsyncTask* {variable.name} = _forge_async_task_new({run_function}, &{context});"
        )
        lines.append(f"_forge_async_task_start({variable.name});")
        return "\n".join(lines)

    def _emit_async_native_task_collection_variable(self, variable: IrVariable) -> str:
        if not isinstance(variable.initializer, IrTaskBulkCall):
            raise CEmissionError("Expected async native task collection initializer")
        return "\n".join(
            self._emit_async_native_task_collection_start(
                variable.initializer,
                result_name=variable.name,
            )
        )

    def _emit_top_level_dynamic_array_variable(self, variable: IrVariable) -> str:
        if not isinstance(variable.type, ArrayType):
            raise CEmissionError("Expected dynamic array variable")
        if not isinstance(variable.initializer, IrArrayLiteral):
            raise CEmissionError("Expected array literal initializer")
        elements = ", ".join(
            self._emit_expression(element)
            for element in variable.initializer.elements
        )
        element_type = self._c_type(variable.type.element_type)
        length = len(variable.initializer.elements)
        data = "NULL" if length == 0 else f"({element_type}[]){{{elements}}}"
        return f"{self._c_type(variable.type)} {variable.name} = {{{length}, {length}, {data}}};"

    def _emit_fixed_array_variable(self, variable: IrVariable) -> str:
        type_ = variable.type
        if not isinstance(type_, ArrayType) or type_.size is None:
            raise CEmissionError("Expected fixed array variable")
        initializer = ""
        if variable.initializer is not None:
            if not isinstance(variable.initializer, IrArrayLiteral):
                raise CEmissionError("Fixed array initializer must be an array literal")
            elements = ", ".join(
                self._emit_expression(element)
                for element in variable.initializer.elements
            )
            initializer = f" = {{{elements}}}"
        if self.ownership.fixed_array_local_needs_cleanup(variable):
            self._array_cleanup_stack[-1].append(variable)
        return f"{self._c_type(type_.element_type)} {variable.name}[{type_.size}]{initializer};"

    def _owned_class_parameters(self, function: IrFunction) -> tuple[CleanupBinding, ...]:
        return tuple(
            parameter
            for parameter in function.parameters
            if self.ownership.owned_class_binding(parameter)
        )

    def _cleanup_lines(self, variables: list[CleanupBinding]) -> tuple[str, ...]:
        if variables:
            self.includes.add("stdlib.h")
        return tuple(
            f"_forge_free_{self._class_type_c_name(self._class_type(variable.type))}({variable.name});"
            for variable in reversed(variables)
            if self._class_type(variable.type) is not None
        )

    def _block_cleanup_lines(self) -> tuple[str, ...]:
        string_variables = self._string_cleanup_stack[-1]
        array_variables = self._array_cleanup_stack[-1]
        class_variables = self._cleanup_stack[-1]
        struct_fields = self._struct_field_cleanup_stack[-1]
        if string_variables or array_variables or class_variables or struct_fields:
            self.includes.add("stdlib.h")
        string_lines = tuple(
            f"free((void*){variable.name});"
            for variable in reversed(string_variables)
        )
        struct_field_lines = tuple(
            f"free((void*){name}.{field});"
            for _, name, field in reversed(struct_fields)
        )
        array_lines = tuple(
            line
            for variable in reversed(array_variables)
            for line in self._array_cleanup_lines(variable)
        )
        return (*string_lines, *struct_field_lines, *array_lines, *self._cleanup_lines(class_variables))

    def _array_cleanup_lines(
        self,
        binding: ArrayCleanupBinding,
    ) -> tuple[str, ...]:
        if isinstance(binding, _ConditionalArrayCleanup):
            lines = self._array_cleanup_lines(binding.variable)
            if not lines:
                return ()
            return (
                f"if ({binding.condition}) {{",
                *(f"    {line}" for line in lines),
                "}",
            )
        variable = binding
        variable_type = variable.type
        if isinstance(variable_type, TaskCollectionType):
            variable_type = self._task_collection_array_type(variable_type)
        if not isinstance(variable_type, ArrayType):
            return ()
        return self._array_cleanup_lines_for(variable_type, variable.name)

    def _array_cleanup_lines_for(
        self,
        type_: ArrayType,
        array: str,
    ) -> tuple[str, ...]:
        element_cleanup_kind = self.ownership.array_element_cleanup_kind(type_)
        lines: list[str] = []
        if element_cleanup_kind != "none":
            length = (
                f"{array}.len"
                if type_.size is None
                else str(type_.size)
            )
            accessor = (
                f"{array}.data[_forge_i]"
                if type_.size is None
                else f"{array}[_forge_i]"
            )
            element_cleanup = (
                f"free((void*){accessor});"
                if element_cleanup_kind == "string"
                else f"_forge_free_{self._class_type_c_name(self._class_type(type_.element_type))}({accessor});"
            )
            lines.extend(
                (
                    f"for (size_t _forge_i = 0; _forge_i < {length}; _forge_i += 1) {{",
                    f"    {element_cleanup}",
                    "}",
                )
            )
        if type_.size is None:
            lines.append(f"free({array}.data);")
        return tuple(lines)

    def _cleanup_lines_for_return(self, *, skip_symbol=None) -> tuple[str, ...]:
        string_variables = [
            variable
            for cleanup_scope in reversed(self._string_cleanup_stack)
            for variable in reversed(cleanup_scope)
            if skip_symbol is None or variable.symbol != skip_symbol
        ]
        class_variables = [
            variable
            for cleanup_scope in reversed(self._cleanup_stack)
            for variable in reversed(cleanup_scope)
            if skip_symbol is None or variable.symbol != skip_symbol
        ]
        array_variables = [
            variable
            for cleanup_scope in reversed(self._array_cleanup_stack)
            for variable in reversed(cleanup_scope)
            if skip_symbol is None
            or self._array_cleanup_symbol(variable) != skip_symbol
        ]
        struct_fields = [
            (symbol, name, field)
            for cleanup_scope in reversed(self._struct_field_cleanup_stack)
            for symbol, name, field in reversed(cleanup_scope)
            if skip_symbol is None or symbol != skip_symbol
        ]
        if string_variables or class_variables or array_variables or struct_fields:
            self.includes.add("stdlib.h")
        string_lines = tuple(
            f"free((void*){variable.name});"
            for variable in string_variables
        )
        struct_field_lines = tuple(
            f"free((void*){name}.{field});"
            for _, name, field in struct_fields
        )
        class_lines = tuple(
            f"_forge_free_{self._class_type_c_name(self._class_type(variable.type))}({variable.name});"
            for variable in class_variables
            if self._class_type(variable.type) is not None
        )
        array_lines = tuple(
            line
            for variable in array_variables
            for line in self._array_cleanup_lines(variable)
        )
        return (*string_lines, *struct_field_lines, *array_lines, *class_lines)

    def _cleanup_lines_for_break(self, *, skip_symbol=None) -> tuple[str, ...]:
        if not self._loop_cleanup_depth_stack:
            return ()
        depth = self._loop_cleanup_depth_stack[-1]
        string_variables = [
            variable
            for cleanup_scope in reversed(self._string_cleanup_stack[depth:])
            for variable in reversed(cleanup_scope)
            if skip_symbol is None or variable.symbol != skip_symbol
        ]
        class_variables = [
            variable
            for cleanup_scope in reversed(self._cleanup_stack[depth:])
            for variable in reversed(cleanup_scope)
            if skip_symbol is None or variable.symbol != skip_symbol
        ]
        array_variables = [
            variable
            for cleanup_scope in reversed(self._array_cleanup_stack[depth:])
            for variable in reversed(cleanup_scope)
            if skip_symbol is None
            or self._array_cleanup_symbol(variable) != skip_symbol
        ]
        struct_fields = [
            (symbol, name, field)
            for cleanup_scope in reversed(self._struct_field_cleanup_stack[depth:])
            for symbol, name, field in reversed(cleanup_scope)
            if skip_symbol is None or symbol != skip_symbol
        ]
        if string_variables or class_variables or array_variables or struct_fields:
            self.includes.add("stdlib.h")
        return (
            *(f"free((void*){variable.name});" for variable in string_variables),
            *(f"free((void*){name}.{field});" for _, name, field in struct_fields),
            *(
                line
                for variable in array_variables
                for line in self._array_cleanup_lines(variable)
            ),
            *(
                f"_forge_free_{self._class_type_c_name(self._class_type(variable.type))}({variable.name});"
                for variable in class_variables
                if self._class_type(variable.type) is not None
            ),
        )

    def _statement_cleanup_lines(self) -> tuple[str, ...]:
        cleanup = self._statement_cleanup_stack[-1]
        if cleanup:
            self.includes.add("stdlib.h")
        return tuple(reversed(cleanup))

    def _emit_print(self, statement: IrPrint) -> str:
        self.includes.add("stdio.h")
        expression = self._emit_expression(statement.expression)
        format_ = self._printf_format(statement.expression.type)
        return f'printf("{format_}\\n", {expression});'

    def _emit_if(self, statement: IrIf) -> str:
        result = (
            f"if ({self._emit_expression(statement.condition)}) "
            f"{self._emit_block(statement.then_branch)}"
        )
        if statement.else_branch is None:
            return result
        if isinstance(statement.else_branch, IrIf):
            return f"{result} else {self._emit_if(statement.else_branch)}"
        return f"{result} else {self._emit_block(statement.else_branch)}"

    def _emit_switch(self, statement: IrSwitch) -> str:
        selector = self._new_temp("switch")
        lines = [f"{self._c_type(statement.expression.type)} {selector} = {self._emit_expression(statement.expression)};"]
        chain = ""
        for index, arm in enumerate(statement.arms):
            if arm.pattern is None:
                chain = (
                    f"{chain} else {self._emit_block(arm.body)}"
                    if chain
                    else self._emit_block(arm.body)
                )
                continue
            prefix = "if" if index == 0 else "else if"
            condition = self._emit_switch_arm_condition(selector, statement.expression, arm.pattern)
            arm_source = (
                f"{prefix} ({condition}) "
                f"{self._emit_block(arm.body)}"
            )
            chain = f"{chain} {arm_source}" if chain else arm_source
        if chain:
            lines.append(chain)
        return "\n".join(lines)

    def _emit_switch_arm_condition(
        self,
        selector: str,
        expression: IrExpression,
        pattern: IrExpression,
    ) -> str:
        if (
            isinstance(expression.type, EnumType)
            and isinstance(pattern.type, EnumType)
            and expression.type.symbol == pattern.type.symbol
            and isinstance(expression.type.value_type, StructType)
        ):
            return f"{selector}._forge_variant_id == {self._emit_operand(pattern)}._forge_variant_id"
        return f"{selector} == {self._emit_expression(pattern)}"

    def _emit_while(self, statement: IrWhile) -> str:
        self._loop_result_stack.append(None)
        self._loop_cleanup_depth_stack.append(len(self._cleanup_stack))
        condition = self._emit_loop_condition_check(statement.condition)
        body = self._emit_block(statement.body)
        self._loop_cleanup_depth_stack.pop()
        self._loop_result_stack.pop()
        return "\n".join(
            (
                "while (true) {",
                *(f"    {line}" for line in condition),
                *(f"    {line}" for line in body.splitlines()),
                "}",
            )
        )

    def _emit_break(self, statement: IrBreak) -> str:
        context = self._loop_result_stack[-1] if self._loop_result_stack else None
        cleanup = self._cleanup_lines_for_break()
        if context is None:
            if statement.expression is not None:
                raise CEmissionError("Valued break outside expression loop")
            return "\n".join((*cleanup, "break;"))
        result, has_value, target_type = context
        if statement.expression is None:
            return "\n".join((*cleanup, "break;"))
        assignment = self._emit_loop_result_assignment_lines(
            result, statement.expression, target_type
        )
        return "\n".join(
            (
                *assignment,
                f"{has_value} = true;",
                *cleanup,
                "break;",
            )
        )

    def _emit_loop_expression(
        self,
        expression: IrWhileExpression | IrDoWhileExpression | IrForExpression,
    ) -> str:
        if not self._statement_prelude_stack:
            raise CEmissionError("Loop expression requires a statement context")
        result = self._new_temp("loop_result")
        has_value = self._new_temp("loop_has_value")
        lines = [
            f"{self._c_type(expression.type)} {result};",
            f"bool {has_value} = false;",
        ]
        self._loop_result_stack.append((result, has_value, expression.type))
        self._loop_cleanup_depth_stack.append(len(self._cleanup_stack))
        body = self._emit_block(expression.body)
        condition = (
            self._emit_loop_condition_check(expression.condition)
            if isinstance(expression, (IrWhileExpression, IrDoWhileExpression))
            else ()
        )
        self._loop_cleanup_depth_stack.pop()
        self._loop_result_stack.pop()

        if isinstance(expression, IrWhileExpression):
            lines.extend(
                (
                    "while (true) {",
                    *(f"    {line}" for line in condition),
                    *(f"    {line}" for line in body.splitlines()),
                    "}",
                )
            )
        elif isinstance(expression, IrDoWhileExpression):
            lines.extend(
                (
                    "do {",
                    *(f"    {line}" for line in body.splitlines()),
                    *(f"    {line}" for line in condition),
                    "} while (true);",
                )
            )
        else:
            source_value = self._emit_expression(expression.source)
            source = self._new_temp("loop_source")
            index = self._new_temp("loop_index")
            lines.append(
                f"{self._c_type(expression.source.type)} {source} = {source_value};"
            )
            length = (
                f"{source}.len"
                if isinstance(expression.source.type, ArrayType)
                and expression.source.type.size is None
                else str(
                    expression.source.type.size
                    if isinstance(expression.source.type, ArrayType)
                    else 0
                )
            )
            item_line = (
                f"{self._c_type(expression.item.type)} {expression.item.name} = "
                f"{source}.data[{index}];"
            )
            body_lines = body.splitlines()
            body_lines.insert(1, f"    {item_line}")
            body = "\n".join(body_lines)
            lines.append(
                f"for (int {index} = 0; {index} < {length}; {index} += 1) {body}"
            )

        fallback = self._emit_loop_result_assignment_lines(
            result,
            expression.fallback, expression.type
        )
        lines.extend(
            (
                f"if (!{has_value}) {{",
                *(f"    {line}" for line in fallback),
                "}",
            )
        )
        self._statement_prelude_stack[-1].extend(lines)
        return result

    def _emit_loop_result_value(
        self, expression: IrExpression, target_type: Type
    ) -> str:
        if isinstance(target_type, NullableType):
            if isinstance(expression, IrLiteral) and expression.value is None:
                return "NULL"
            if target_type.inner_type == STRING and expression.type == STRING:
                return self._emit_owned_string_value(
                    expression, cleanup_result=False
                )
            return self._emit_nullable_value(expression, target_type)
        if target_type == STRING:
            return self._emit_owned_string_value(
                expression, cleanup_result=False
            )
        return self._emit_expression(expression)

    def _emit_loop_result_assignment_lines(
        self,
        target: str,
        expression: IrExpression,
        target_type: Type,
    ) -> tuple[str, ...]:
        if isinstance(expression, IrConditional):
            prelude_start = len(self._statement_prelude_stack[-1])
            cleanup_start = len(self._statement_cleanup_stack[-1])
            condition = self._emit_expression(expression.condition)
            condition_prelude = tuple(
                self._statement_prelude_stack[-1][prelude_start:]
            )
            del self._statement_prelude_stack[-1][prelude_start:]
            condition_cleanup = tuple(
                reversed(self._statement_cleanup_stack[-1][cleanup_start:])
            )
            del self._statement_cleanup_stack[-1][cleanup_start:]
            condition_value = self._new_temp("loop_choice")
            then_lines = self._emit_loop_result_assignment_lines(
                target, expression.then_expression, target_type
            )
            else_lines = self._emit_loop_result_assignment_lines(
                target, expression.else_expression, target_type
            )
            return (
                *condition_prelude,
                f"bool {condition_value} = {condition};",
                *condition_cleanup,
                f"if ({condition_value}) {{",
                *(f"    {line}" for line in then_lines),
                "} else {",
                *(f"    {line}" for line in else_lines),
                "}",
            )

        prelude_start = len(self._statement_prelude_stack[-1])
        cleanup_start = len(self._statement_cleanup_stack[-1])
        value = self._emit_loop_result_value(expression, target_type)
        prelude = tuple(self._statement_prelude_stack[-1][prelude_start:])
        del self._statement_prelude_stack[-1][prelude_start:]
        cleanup = tuple(
            reversed(self._statement_cleanup_stack[-1][cleanup_start:])
        )
        del self._statement_cleanup_stack[-1][cleanup_start:]
        source = expression.expression if isinstance(expression, IrMove) else expression
        transfer = (
            (f"{self._emit_expression(source)} = NULL;",)
            if self._class_type(target_type) is not None
            and isinstance(source, IrLocalRef)
            else ()
        )
        return (*prelude, f"{target} = {value};", *transfer, *cleanup)

    def _emit_loop_condition_check(
        self,
        expression: IrExpression,
    ) -> tuple[str, ...]:
        self.includes.add("stdbool.h")
        prelude_start = len(self._statement_prelude_stack[-1])
        cleanup_start = len(self._statement_cleanup_stack[-1])
        condition = self._emit_expression(expression)
        prelude = tuple(self._statement_prelude_stack[-1][prelude_start:])
        del self._statement_prelude_stack[-1][prelude_start:]
        cleanup = tuple(
            reversed(self._statement_cleanup_stack[-1][cleanup_start:])
        )
        del self._statement_cleanup_stack[-1][cleanup_start:]
        value = self._new_temp("loop_condition")
        return (
            *prelude,
            f"bool {value} = {condition};",
            *cleanup,
            f"if (!{value}) break;",
        )

    def _emit_expression(self, expression: IrExpression) -> str:
        if isinstance(expression, IrLiteral):
            return self._emit_literal(expression)
        if isinstance(expression, IrBuiltinRef):
            return expression.name
        if isinstance(expression, IrLocalRef):
            symbol_node = expression.symbol.node
            if (
                isinstance(symbol_node, FunctionDeclaration)
                and symbol_node.native_name is not None
            ):
                return symbol_node.native_name
            if isinstance(symbol_node, FunctionDeclaration):
                return self._function_symbol_c_name(expression.symbol)
            return expression.symbol.name
        if isinstance(expression, IrSpecialRef):
            return expression.kind
        if isinstance(expression, IrUnary):
            if expression.operator is TokenKind.AWAIT:
                if isinstance(expression.operand, IrCall) and self._is_task_collection_all_call(expression.operand):
                    return self._emit_task_collection_all_await(expression.operand)
                if isinstance(expression.operand, IrCall) and self._is_task_collection_scalar_call(expression.operand):
                    return self._emit_task_collection_scalar_await(expression.operand)
                if self._is_async_interface_call(expression.operand):
                    return self._emit_method_call(expression.operand)
                if self._is_async_runtime_call(expression.operand):
                    return self._emit_async_native_awaited_call(expression.operand)
                return self._emit_expression(expression.operand)
            return f"{self._c_unary_operator(expression.operator)}{self._emit_operand(expression.operand)}"
        if isinstance(expression, IrMove):
            return self._emit_expression(expression.expression)
        if isinstance(expression, IrForward):
            return self._emit_forward_expression(expression)
        if isinstance(expression, IrCatch):
            return self._emit_catch_expression(expression)
        if isinstance(expression, IrBinary):
            if expression.operator is TokenKind.PLUS and expression.type == STRING:
                return self._emit_owned_string_expression(expression)
            enum_equality = self._emit_enum_struct_equality(expression)
            if enum_equality is not None:
                return enum_equality
            return (
                f"{self._emit_operand(expression.left)} "
                f"{self._c_binary_operator(expression.operator)} "
                f"{self._emit_operand(expression.right)}"
            )
        if isinstance(expression, IrAssignment):
            if expression.operator is not TokenKind.EQUAL:
                operator = self._c_binary_operator(expression.operator)
                if expression.operator in {TokenKind.PLUS, TokenKind.MINUS} and isinstance(expression.value, IrLiteral) and expression.value.value == 1:
                    return f"{self._emit_expression(expression.target)}{operator}{operator}"
                return (
                    f"{self._emit_expression(expression.target)} {operator}= "
                    f"{self._emit_expression(expression.value)}"
                )
            field_assignment = self._emit_owned_field_assignment(expression)
            if field_assignment is not None:
                return field_assignment
            string_assignment = self._emit_owned_string_local_assignment(expression)
            if string_assignment is not None:
                return string_assignment
            string_field_assignment = self._emit_owned_string_struct_field_assignment(expression)
            if string_field_assignment is not None:
                return string_field_assignment
            local_assignment = self._emit_owned_local_assignment(expression)
            if local_assignment is not None:
                return local_assignment
            array_assignment = self._emit_owned_array_local_assignment(expression)
            if array_assignment is not None:
                return array_assignment
            if isinstance(expression.target.type, NullableType):
                return (
                    f"{self._emit_expression(expression.target)} = "
                    f"{self._emit_nullable_value(expression.value, expression.target.type)}"
                )
            return (
                f"{self._emit_expression(expression.target)} = "
                f"{self._emit_expression(expression.value)}"
            )
        if isinstance(expression, IrConditional):
            if expression.type == STRING:
                return self._emit_owned_string_value(expression)
            if self.ownership.owned_array_expression(expression):
                return self._emit_owned_array_value(
                    expression,
                    cleanup_result=True,
                )
            return (
                f"{self._emit_expression(expression.condition)} ? "
                f"{self._emit_expression(expression.then_expression)} : "
                f"{self._emit_expression(expression.else_expression)}"
            )
        if isinstance(
            expression,
            (IrWhileExpression, IrDoWhileExpression, IrForExpression),
        ):
            return self._emit_loop_expression(expression)
        if isinstance(expression, IrCall):
            if self._call_has_outcomes(expression):
                if self._is_task_await_call(expression):
                    return self._emit_task_await_expression(expression)
                return self._emit_default_outcome_call_expression(expression)
            if self.ownership.owned_string_expression(expression):
                return self._emit_owned_string_expression(expression)
            if self.ownership.owned_array_expression(expression):
                return self._emit_owned_array_value(expression, cleanup_result=True)
            return self._emit_call_expression(expression)
        if isinstance(expression, IrArrayLiteral):
            return self._emit_array_literal(expression)
        if isinstance(expression, IrStructLiteral):
            return self._emit_struct_literal(expression)
        if isinstance(expression, IrSequence):
            raise CEmissionError("Sequence expression can only be emitted as a statement")
        if isinstance(expression, IrArrayBulkCall):
            raise CEmissionError("Array bulk call can only be emitted as a statement")
        if isinstance(expression, IrBulkMapCall):
            return self._emit_bulk_map_call_expression(expression)
        if isinstance(expression, IrTaskBulkCall):
            return self._emit_task_bulk_call_expression(expression)
        if isinstance(expression, IrMember):
            if isinstance(expression.symbol.node, EnumVariant) if expression.symbol is not None else False:
                receiver_type = expression.receiver.type
                enum_name = (
                    self._enum_type_c_name(receiver_type)
                    if isinstance(receiver_type, EnumType)
                    else self._emit_expression(expression.receiver)
                )
                return f"{self._c_identifier(enum_name)}_{self._c_identifier(expression.member)}"
            if self._is_static_variable_member(expression):
                class_type = self._class_type(expression.receiver.type)
                if class_type is None:
                    raise CEmissionError(
                        f"Cannot determine receiver class for static member '{expression.member}'"
                    )
                return f"{self._class_type_c_name(class_type)}_{expression.member}"
            if expression.null_safe:
                receiver = self._emit_expression(expression.receiver)
                access = self._emit_member_access(receiver, expression)
                return f"({receiver} != NULL ? {access} : NULL)"
            receiver = self._emit_expression(expression.receiver)
            return self._emit_member_access(receiver, expression)
        if isinstance(expression, IrMemberBlock):
            return self._emit_member_block_expression(expression)
        if isinstance(expression, IrIndex):
            if self.ownership.string_from_temporary_array_index(expression):
                return self._emit_temporary_string_array_index(expression)
            receiver_type = expression.receiver.type
            if isinstance(receiver_type, ArrayType) and receiver_type.size is None:
                return (
                    f"{self._emit_expression(expression.receiver)}"
                    f".data[{self._emit_expression(expression.index)}]"
                )
            return (
                f"{self._emit_expression(expression.receiver)}"
                f"[{self._emit_expression(expression.index)}]"
            )
        raise CEmissionError(f"Cannot emit expression {type(expression).__name__}")

    def _emit_member_access(self, receiver: str, expression: IrMember) -> str:
        if (
            isinstance(expression.receiver.type, ArrayType)
            and expression.receiver.type.size is None
            and expression.member == "len"
        ):
            return f"(int){receiver}.len"
        operator = "->" if self._is_pointer_member_receiver(expression.receiver.type) else "."
        access = f"{receiver}{operator}{expression.member}"
        if self._is_narrowed_nullable_struct_member(expression):
            return f"(*{access})"
        return access

    def _is_pointer_member_receiver(self, type_: Type) -> bool:
        if self._is_class_pointer(type_):
            return True
        return isinstance(type_, NullableType) and isinstance(type_.inner_type, StructType)

    def _is_narrowed_nullable_struct_member(self, expression: IrMember) -> bool:
        if not isinstance(expression.type, StructType):
            return False
        if not isinstance(expression.symbol, Symbol):
            return False
        node = expression.symbol.node
        if not isinstance(node, VariableDeclaration) or node.type is None:
            return False
        return node.type.nullable

    def _emit_struct_literal(self, expression: IrStructLiteral) -> str:
        struct_type = (
            expression.type.value_type
            if isinstance(expression.type, EnumType)
            else expression.type
        )
        if not isinstance(struct_type, StructType):
            raise CEmissionError("Struct literal requires a struct type")
        class_name = self._class_type_c_name(struct_type)
        fields = ", ".join(
            f".{field.name} = {self._emit_struct_literal_field_value(field.value, field.target_type)}"
            if field.name is not None
            else self._emit_struct_literal_field_value(field.value, field.target_type)
            for field in expression.fields
        )
        return f"(struct {class_name}){{{fields}}}"

    def _emit_struct_literal_field_value(
        self,
        expression: IrExpression,
        target_type: Type | None,
    ) -> str:
        if isinstance(target_type, NullableType):
            return self._emit_nullable_value(expression, target_type)
        if expression.type == STRING and self._statement_prelude_stack:
            return self._emit_owned_string_value(expression, cleanup_result=False)
        return self._emit_expression(expression)

    def _emit_sequence_statement(self, expression: IrSequence) -> str:
        return "\n".join(
            f"{self._emit_expression(child)};"
            for child in expression.expressions
        )

    def _emit_array_bulk_call_statement(self, expression: IrArrayBulkCall) -> str:
        if not isinstance(expression.array.type, ArrayType) or expression.array.type.size is not None:
            raise CEmissionError("Only dynamic array bulk calls are supported")
        if not isinstance(expression.callee, IrMember):
            raise CEmissionError("Only member bulk calls are supported")
        member_node = expression.callee.symbol.node if expression.callee.symbol is not None else None
        if not isinstance(member_node, FunctionDeclaration) or "static" not in member_node.modifiers:
            raise CEmissionError("Only static function bulk calls are supported")
        receiver_type = self._class_type(expression.callee.receiver.type)
        if receiver_type is None:
            raise CEmissionError("Cannot determine bulk call receiver")

        array = self._emit_expression(expression.array)
        function = member_node.native_name or f"{self._class_type_c_name(receiver_type)}_{expression.callee.member}"
        element_type = expression.array.type.element_type
        element = f"{array}.data[_forge_i]"
        argument = element
        prelude: list[str] = []
        cleanup: list[str] = []
        function_type = expression.callee.type
        if (
            isinstance(function_type, FunctionType)
            and function_type.parameter_types
            and function_type.parameter_types[0] == STRING
            and element_type != STRING
        ):
            argument, prelude, cleanup = self._stringable_conversion_lines(element_type, element)
        lines = [f"for (size_t _forge_i = 0; _forge_i < {array}.len; _forge_i += 1) {{"]
        lines.extend(f"    {line}" for line in prelude)
        lines.append(f"    {function}({argument});")
        lines.extend(f"    {line}" for line in cleanup)
        lines.append("}")
        return "\n".join(lines)

    def _emit_task_bulk_call_expression(self, expression: IrTaskBulkCall) -> str:
        if self._is_async_runtime_task_bulk_call(expression):
            temp = self._new_temp("tasks")
            self._statement_prelude_stack[-1].extend(
                self._emit_async_native_task_collection_start(
                    expression,
                    result_name=temp,
                )
            )
            return temp
        if not isinstance(expression.array.type, ArrayType) or expression.array.type.size is not None:
            raise CEmissionError("Only dynamic array task bulk calls are supported")
        if not isinstance(expression.type, TaskCollectionType):
            raise CEmissionError("Expected TaskCollection<T> task bulk call")
        if not self._statement_prelude_stack:
            raise CEmissionError("Top-level task bulk calls are not supported yet")

        return self._emit_bulk_map_call_expression(
            IrBulkMapCall(
                expression.location,
                expression.callee,
                expression.array,
                "task",
                self._task_collection_array_type(expression.type),
                (),
            )
        )

    def _emit_bulk_map_call_expression(self, expression: IrBulkMapCall) -> str:
        if not isinstance(expression.array.type, ArrayType) or expression.array.type.size is not None:
            raise CEmissionError("Only dynamic array bulk map calls are supported")
        if not isinstance(expression.type, ArrayType) or expression.type.size is not None:
            raise CEmissionError("Bulk map calls must produce a dynamic array")
        if not self._statement_prelude_stack:
            raise CEmissionError("Top-level bulk map calls are not supported yet")

        array_type = expression.type
        array_name = self._array_c_name(array_type)
        self._array_runtime_helper(array_type)
        source_array = self._emit_expression(expression.array)
        function = self._emit_expression(expression.callee)
        temp = self._new_temp("bulk")
        self._statement_prelude_stack[-1].append(
            f"{array_name} {temp} = {array_name}_new({source_array}.len);"
        )
        self._statement_prelude_stack[-1].append(
            f"for (size_t _forge_i = 0; _forge_i < {source_array}.len; _forge_i += 1) {{"
        )
        if isinstance(expression.callee, IrMember) and self._is_method_member(expression.callee):
            call = self._emit_method_bulk_map_call(expression.callee, f"{source_array}.data[_forge_i]")
        else:
            function = self._emit_expression(expression.callee)
            call = f"{function}({source_array}.data[_forge_i])"
        self._statement_prelude_stack[-1].append(
            f"    {array_name}_push(&{temp}, {call});"
        )
        self._statement_prelude_stack[-1].append("}")
        return temp

    def _emit_bulk_map_outcome_result(self, expression: IrBulkMapCall) -> str:
        if not isinstance(expression.array.type, ArrayType) or expression.array.type.size is not None:
            raise CEmissionError("Only dynamic array bulk map calls are supported")
        if not isinstance(expression.type, ArrayType) or expression.type.size is not None:
            raise CEmissionError("Bulk map calls must produce a dynamic array")
        if not isinstance(expression.callee.type, FunctionType):
            raise CEmissionError("Cannot determine bulk map function type")
        if not self._statement_prelude_stack:
            raise CEmissionError("Top-level bulk map calls are not supported yet")

        function_type = expression.callee.type
        bulk_function_type = self._function_type_for_expression(expression)
        if bulk_function_type is None:
            raise CEmissionError("Cannot determine bulk map outcome type")

        array_type = expression.type
        array_name = self._array_c_name(array_type)
        self._array_runtime_helper(array_type)
        source_array = self._emit_expression(expression.array)
        function = self._emit_expression(expression.callee)
        array_temp = self._new_temp("bulk")
        item_temp = self._new_temp("bulk_item")
        result_temp = self._new_temp("bulk_outcome")
        done_label = self._new_temp("bulk_done")
        item_result_type = self._function_result_c_name(function_type)
        bulk_result_type = self._function_result_c_name(bulk_function_type, local=True)
        item_success_tag = self._result_tag_name(function_type, None)
        bulk_success_tag = self._result_tag_name(bulk_function_type, None)

        lines = self._statement_prelude_stack[-1]
        lines.append(f"{array_name} {array_temp} = {array_name}_new({source_array}.len);")
        lines.append(f"{bulk_result_type} {result_temp};")
        lines.append(
            f"for (size_t _forge_i = 0; _forge_i < {source_array}.len; _forge_i += 1) {{"
        )
        if isinstance(expression.callee, IrMember) and self._is_method_member(expression.callee):
            call = self._emit_method_bulk_map_call(
                expression.callee,
                f"{source_array}.data[_forge_i]",
            )
        else:
            call = f"{function}({source_array}.data[_forge_i])"
        lines.append(f"    {item_result_type} {item_temp} = {call};")
        lines.append(f"    if ({item_temp}.tag == {item_success_tag}) {{")
        lines.append(f"        {array_name}_push(&{array_temp}, {item_temp}.success);")
        for outcome in function_type.outcomes:
            item_tag = self._result_tag_name(function_type, outcome.type)
            bulk_tag = self._result_tag_name(bulk_function_type, outcome.type)
            field = self._outcome_field_name(outcome.type)
            lines.append(f"    }} else if ({item_temp}.tag == {item_tag}) {{")
            for cleanup_line in self._array_cleanup_lines_for(array_type, array_temp):
                lines.append(f"        {cleanup_line}")
            lines.append(
                f"        {result_temp} = ({bulk_result_type})"
                f"{{.tag = {bulk_tag}, .{field} = {item_temp}.{field}}};"
            )
            lines.append(f"        goto {done_label};")
        lines.append("    } else {")
        self.includes.add("stdlib.h")
        lines.append("        abort();")
        lines.append("    }")
        lines.append("}")
        lines.append(
            f"{result_temp} = ({bulk_result_type})"
            f"{{.tag = {bulk_success_tag}, .success = {array_temp}}};"
        )
        lines.append(f"{done_label}:;")
        return result_temp

    def _emit_method_bulk_map_call(self, callee: IrMember, argument: str) -> str:
        if isinstance(callee.receiver.type, InterfaceType):
            receiver = self._emit_expression(callee.receiver)
            return f"{receiver}.vtable->{callee.member}({receiver}.object, {argument})"
        class_type = self._class_type(callee.receiver.type)
        if class_type is None:
            raise CEmissionError(f"Cannot determine receiver class for method '{callee.member}'")
        member_node = callee.symbol.node if callee.symbol is not None else None
        is_static = (
            isinstance(member_node, FunctionDeclaration)
            and (member_node.kind == "new" or "static" in member_node.modifiers)
        )
        function = (
            member_node.native_name
            if isinstance(member_node, FunctionDeclaration)
            and member_node.native_name is not None
            else f"{self._class_type_c_name(class_type)}_{callee.member}"
        )
        if is_static:
            return f"{function}({argument})"
        return f"{function}({self._emit_expression(callee.receiver)}, {argument})"

    def _stringable_conversion_lines(self, type_: Type, value: str) -> tuple[str, list[str], list[str]]:
        if isinstance(type_, ClassType):
            self.includes.add("stdlib.h")
            temp = self._new_temp("string")
            class_name = self._class_type_c_name(type_)
            return temp, [f"char* {temp} = {class_name}_toString({value});"], [f"free({temp});"]
        if isinstance(type_, BuiltinType):
            self.includes.add("stdlib.h")
            helper = self._primitive_to_string_helper(type_)
            temp = self._new_temp("string")
            return temp, [f"char* {temp} = {helper}({value});"], [f"free({temp});"]
        return value, [], []

    def _emit_owned_field_assignment(self, expression: IrAssignment) -> str | None:
        if not isinstance(expression.target, IrMember):
            return None
        if expression.target.field_ownership != "take":
            return None
        field_type = self._class_type(expression.target.type)
        if field_type is None:
            return None
        return self._emit_owned_reassignment(
            self._emit_expression(expression.target),
            self._emit_expression(expression.value),
            self._class_type_c_name(field_type),
        )

    def _emit_owned_local_assignment(self, expression: IrAssignment) -> str | None:
        if not isinstance(expression.target, IrLocalRef):
            return None
        local_type = self._class_type(expression.target.type)
        if local_type is None:
            return None
        return self._emit_owned_reassignment(
            self._emit_expression(expression.target),
            self._emit_expression(expression.value),
            self._class_type_c_name(local_type),
        )

    def _emit_owned_string_local_assignment(self, expression: IrAssignment) -> str | None:
        if not isinstance(expression.target, IrLocalRef):
            return None
        if expression.target.type != STRING or expression.value.type != STRING:
            return None
        target = self._emit_expression(expression.target)
        value = self._emit_owned_string_value(expression.value, cleanup_result=False)
        if self._is_owned_string_symbol(expression.target.symbol):
            self.includes.add("stdlib.h")
            self._statement_prelude_stack[-1].append(f"free((void*){target});")
        return (
            f"{target} = {value}"
        )

    def _emit_owned_array_local_assignment(self, expression: IrAssignment) -> str | None:
        if not isinstance(expression.target, IrLocalRef):
            return None
        array_type = expression.target.type
        if not isinstance(array_type, ArrayType) or array_type.size is not None:
            return None
        if not (
            self.ownership.allocating_array_call(expression.value)
            or self.ownership.owned_array_expression(expression.value)
        ):
            return None

        target = self._emit_expression(expression.target)
        replacement = self._new_temp("array_replacement")
        self._statement_prelude_stack[-1].append(
            f"{self._array_c_name(array_type)} {replacement};"
        )
        if isinstance(expression.value, IrConditional):
            self._statement_prelude_stack[-1].extend(
                self._emit_array_conditional_assignment_lines(
                    replacement,
                    expression.value,
                )
            )
        else:
            value = self._emit_owned_array_value(
                expression.value,
                cleanup_result=False,
            )
            self._statement_prelude_stack[-1].append(
                f"{replacement} = {value};"
            )
        self._statement_prelude_stack[-1].extend(
            self._array_cleanup_lines_for(array_type, target)
        )
        return f"{target} = {replacement}"

    def _emit_owned_string_struct_field_assignment(self, expression: IrAssignment) -> str | None:
        if not isinstance(expression.target, IrMember):
            return None
        if expression.target.type != STRING or expression.value.type != STRING:
            return None
        if not isinstance(expression.target.receiver, IrLocalRef):
            return None
        receiver = expression.target.receiver
        if not isinstance(receiver.type, StructType):
            return None
        if not self.ownership.owned_string_assignment_value(expression.value):
            return None

        target = self._emit_expression(expression.target)
        value = (
            self._emit_expression(expression.value)
            if isinstance(expression.value, (IrForward, IrCatch))
            else self._emit_owned_string_value(expression.value, cleanup_result=False)
        )
        if self._is_registered_struct_field_cleanup(receiver.symbol, expression.target.member):
            self.includes.add("stdlib.h")
            self._statement_prelude_stack[-1].append(f"free((void*){target});")
        else:
            self._register_struct_field_cleanup(receiver.symbol, receiver.symbol.name, expression.target.member)
        return f"{target} = {value}"

    def _register_struct_field_cleanup(self, symbol: Symbol, name: str, field: str) -> None:
        if not self._struct_field_cleanup_stack:
            return
        self._struct_field_cleanup_stack[-1].append((symbol, name, field))

    def _is_registered_struct_field_cleanup(self, symbol: Symbol, field: str) -> bool:
        return any(
            cleanup_symbol is symbol and cleanup_field == field
            for cleanup_scope in self._struct_field_cleanup_stack
            for cleanup_symbol, _, cleanup_field in cleanup_scope
        )

    def _emit_owned_reassignment(self, target: str, value: str, class_name: str) -> str:
        self.includes.add("stdlib.h")
        if self._statement_prelude_stack:
            self._statement_prelude_stack[-1].append(f"_forge_free_{class_name}({target});")
            return f"{target} = {value}"
        return f"(_forge_free_{class_name}({target}), {target} = {value})"

    def _emit_owned_string_expression(
        self,
        expression: IrExpression,
        *,
        cleanup_result: bool = True,
    ) -> str:
        if self.ownership.string_from_temporary_array_index(expression):
            if not isinstance(expression, IrIndex):
                raise CEmissionError("Expected indexed temporary String[]")
            return self._emit_temporary_string_array_index(
                expression,
                cleanup_result=cleanup_result,
            )
        if self.ownership.string_from_array_index(expression):
            return self._emit_string_copy(
                expression,
                cleanup_result=cleanup_result,
            )
        if self.ownership.allocating_primitive_to_string_call(expression):
            return self._emit_primitive_to_string(expression, cleanup_result=cleanup_result)
        if self.ownership.allocating_string_call(expression):
            call = self._emit_call_expression(expression)
            if not cleanup_result:
                return call
            temp = self._new_temp("string")
            self._statement_prelude_stack[-1].append(f"char* {temp} = {call};")
            self._statement_cleanup_stack[-1].append(f"free({temp});")
            return temp
        if not isinstance(expression, IrBinary):
            return self._emit_expression(expression)
        self.helpers.add("string_concat")
        operands = [
            self._emit_string_concat_operand(operand)
            for operand in self._flatten_string_concat_operands(expression)
        ]
        temp = self._new_temp("string")
        self._statement_prelude_stack[-1].append(
            f"char* {temp} = _forge_string_concat({len(operands)}, {', '.join(operands)});"
        )
        if cleanup_result:
            self._statement_cleanup_stack[-1].append(f"free({temp});")
        return temp

    def _emit_owned_array_call(
        self,
        expression: IrExpression,
        *,
        cleanup_result: bool = True,
    ) -> str:
        if not isinstance(expression, IrCall) or not isinstance(expression.type, ArrayType):
            return self._emit_expression(expression)
        call = self._emit_call_expression(expression)
        if not cleanup_result:
            return call
        array_type = expression.type
        temp = self._new_temp("array")
        self._statement_prelude_stack[-1].append(
            f"{self._array_c_name(array_type)} {temp} = {call};"
        )
        cleanup_lines = self._array_cleanup_lines_for(array_type, temp)
        if cleanup_lines:
            self._statement_cleanup_stack[-1].append("\n".join(cleanup_lines))
        return temp

    def _emit_owned_array_value(
        self,
        expression: IrExpression,
        *,
        cleanup_result: bool,
    ) -> str:
        if self.ownership.allocating_array_call(expression):
            return self._emit_owned_array_call(
                expression,
                cleanup_result=cleanup_result,
            )
        if isinstance(expression, IrArrayLiteral):
            value = self._emit_expression(expression)
            if cleanup_result and isinstance(expression.type, ArrayType):
                cleanup_lines = self._array_cleanup_lines_for(
                    expression.type,
                    value,
                )
                if cleanup_lines:
                    self._statement_cleanup_stack[-1].append(
                        "\n".join(cleanup_lines)
                    )
            return value
        if isinstance(expression, IrConditional):
            array_type = expression.type
            if not isinstance(array_type, ArrayType) or array_type.size is not None:
                return self._emit_expression(expression)
            temp = self._new_temp("array")
            self._statement_prelude_stack[-1].append(
                f"{self._array_c_name(array_type)} {temp};"
            )
            self._statement_prelude_stack[-1].extend(
                self._emit_array_conditional_assignment_lines(temp, expression)
            )
            if cleanup_result:
                cleanup_lines = self._array_cleanup_lines_for(array_type, temp)
                if cleanup_lines:
                    self._statement_cleanup_stack[-1].append(
                        "\n".join(cleanup_lines)
                    )
            return temp
        return self._emit_expression(expression)

    def _emit_temporary_string_array_index(
        self,
        expression: IrIndex,
        *,
        cleanup_result: bool = True,
    ) -> str:
        receiver = self._emit_expression(expression.receiver)
        index = self._emit_expression(expression.index)
        self.helpers.add("string_copy")
        temp = self._new_temp("string")
        self._statement_prelude_stack[-1].append(
            f"char* {temp} = _forge_string_copy({receiver}.data[{index}]);"
        )
        if cleanup_result:
            self._statement_cleanup_stack[-1].append(f"free({temp});")
        return temp

    def _flatten_string_concat_operands(self, expression: IrExpression) -> tuple[IrExpression, ...]:
        if (
            isinstance(expression, IrBinary)
            and expression.operator is TokenKind.PLUS
            and expression.type == STRING
        ):
            return (
                *self._flatten_string_concat_operands(expression.left),
                *self._flatten_string_concat_operands(expression.right),
            )
        return (expression,)

    def _emit_string_concat_operand(self, expression: IrExpression) -> str:
        if expression.type == STRING:
            return self._emit_expression(expression)
        value = self._emit_expression(expression)
        converted, prelude, cleanup = self._stringable_conversion_lines(expression.type, value)
        self._statement_prelude_stack[-1].extend(prelude)
        self._statement_cleanup_stack[-1].extend(cleanup)
        return converted

    def _emit_owned_string_value(
        self,
        expression: IrExpression,
        *,
        cleanup_result: bool = True,
    ) -> str:
        if isinstance(expression, IrConditional):
            return self._emit_owned_string_conditional(
                expression,
                cleanup_result=cleanup_result,
            )
        if self.ownership.owned_string_expression(expression):
            return self._emit_owned_string_expression(
                expression,
                cleanup_result=cleanup_result,
            )
        return self._emit_string_copy(expression, cleanup_result=cleanup_result)

    def _emit_owned_string_conditional(
        self,
        expression: IrConditional,
        *,
        cleanup_result: bool,
    ) -> str:
        temp = self._new_temp("string")
        self._statement_prelude_stack[-1].append(f"char* {temp};")
        self._statement_prelude_stack[-1].extend(
            self._emit_conditional_assignment_lines(
                temp,
                expression,
                owned_string=True,
            )
        )
        if cleanup_result:
            self._statement_cleanup_stack[-1].append(f"free({temp});")
        return temp

    def _emit_string_copy(
        self,
        expression: IrExpression,
        *,
        cleanup_result: bool,
    ) -> str:
        self.helpers.add("string_copy")
        source = self._emit_expression(expression)
        temp = self._new_temp("string")
        self._statement_prelude_stack[-1].append(
            f"char* {temp} = _forge_string_copy({source});"
        )
        if cleanup_result:
            self._statement_cleanup_stack[-1].append(f"free({temp});")
        return temp

    def _is_primitive_to_string_call(self, expression: IrExpression) -> bool:
        return self.ownership.primitive_to_string_call(expression)

    def _emit_primitive_to_string(
        self,
        expression: IrCall,
        *,
        cleanup_result: bool = True,
    ) -> str:
        callee = expression.callee
        if not isinstance(callee, IrMember):
            raise CEmissionError("Expected primitive toString member")
        receiver = self._emit_expression(callee.receiver)
        if callee.receiver.type == STRING:
            return receiver
        helper = self._primitive_to_string_helper(callee.receiver.type)
        temp = self._new_temp("string")
        self._statement_prelude_stack[-1].append(f"char* {temp} = {helper}({receiver});")
        if cleanup_result:
            self._statement_cleanup_stack[-1].append(f"free({temp});")
        return temp

    def _primitive_to_string_helper(self, type_: Type) -> str:
        if type_ == BOOL:
            self.helpers.add("bool_to_string")
            return "_forge_bool_to_string"
        if not isinstance(type_, BuiltinType):
            raise CEmissionError(f"Cannot convert {type_.display_name} to String")
        name = self._c_identifier(type_.display_name)
        helper = f"_forge_{name}_to_string"
        c_type = self._c_type(type_)
        if type_ == DOUBLE or type_.name == "Float":
            self.helpers.add(f"primitive_to_string:{helper}:{c_type}:%g:(double)value")
        elif type_.name in {"UByte", "UShort", "UInt", "ULong"}:
            self.helpers.add(f"primitive_to_string:{helper}:{c_type}:%llu:(unsigned long long)value")
        else:
            self.helpers.add(f"primitive_to_string:{helper}:{c_type}:%lld:(long long)value")
        return helper

    def _emit_array_literal(self, expression: IrArrayLiteral) -> str:
        if not isinstance(expression.type, ArrayType) or expression.type.size is not None:
            raise CEmissionError("Only dynamic array literals are supported")
        if not self._statement_prelude_stack:
            raise CEmissionError("Top-level array literals are not supported yet")

        array_name = self._array_c_name(expression.type)
        self._array_runtime_helper(expression.type)
        temp = self._new_temp("array")
        self._statement_prelude_stack[-1].append(
            f"{array_name} {temp} = {array_name}_new({len(expression.elements)});"
        )
        for element in expression.elements:
            if isinstance(expression.type.element_type, InterfaceType):
                value = self._emit_interface_value(element, expression.type.element_type)
            elif expression.type.element_type == STRING:
                value = self._emit_owned_string_value(element, cleanup_result=False)
            else:
                value = self._emit_expression(element)
            self._statement_prelude_stack[-1].append(
                f"{array_name}_push(&{temp}, {value});"
            )
        return temp

    def _new_temp(self, prefix: str) -> str:
        name = f"forge_tmp_{prefix}{self._temp_index}"
        self._temp_index += 1
        return name

    def _emit_call_expression(self, expression: IrCall) -> str:
        if self._is_task_await_call(expression):
            return self._emit_task_await_expression(expression)
        if self._is_task_collection_all_call(expression):
            callee = expression.callee
            if not isinstance(callee, IrMember):
                raise CEmissionError("Expected TaskCollection.all member call")
            return self._emit_expression(callee.receiver)
        if self._is_task_collection_concurrency_call(expression):
            callee = expression.callee
            if not isinstance(callee, IrMember):
                raise CEmissionError("Expected TaskCollection.concurrency member call")
            return self._emit_expression(callee.receiver)
        if self._is_task_collection_scalar_call(expression):
            return self._emit_task_collection_scalar_call(expression)
        if self._is_primitive_to_string_call(expression):
            return self._emit_primitive_to_string(expression)
        if isinstance(expression.callee, IrMember) and self._is_method_member(expression.callee):
            return self._emit_method_call(expression)
        arguments = ", ".join(self._emit_expression(argument) for argument in expression.arguments)
        return f"{self._emit_expression(expression.callee)}({arguments})"

    def _emit_task_await_expression(
        self,
        expression: IrCall,
        *,
        outcome_result: bool = False,
    ) -> str:
        callee = expression.callee
        if not isinstance(callee, IrMember):
            raise CEmissionError("Expected Task.await member call")
        if isinstance(callee.receiver, IrCall) and self._is_task_collection_all_call(callee.receiver):
            return self._emit_task_collection_all_await(callee.receiver, outcome_result=outcome_result)
        if isinstance(callee.receiver, IrCall) and self._is_task_collection_scalar_call(callee.receiver):
            return self._emit_task_collection_scalar_await(callee.receiver, outcome_result=outcome_result)
        if self._is_async_interface_call(callee.receiver):
            if outcome_result:
                raise CEmissionError("Interface async outcome calls are not supported yet")
            return self._emit_method_call(callee.receiver)
        if self._is_async_runtime_call(callee.receiver):
            return self._emit_async_native_awaited_call(callee.receiver, outcome_result=outcome_result)
        if isinstance(callee.receiver, IrLocalRef):
            context = self._async_native_task_contexts.get(id(callee.receiver.symbol))
            if context is not None:
                return self._emit_async_native_task_variable_await(
                    callee.receiver,
                    context,
                    outcome_result=outcome_result,
                )
        if outcome_result:
            raise CEmissionError("Cannot emit outcome result for unsupported task await")
        return self._emit_expression(callee.receiver)

    def _emit_task_collection_all_await(
        self,
        expression: IrCall,
        *,
        outcome_result: bool = False,
    ) -> str:
        callee = expression.callee
        if not isinstance(callee, IrMember):
            raise CEmissionError("Expected TaskCollection.all member call")
        collection = self._emit_expression(callee.receiver)
        context = self._async_native_task_collections.get(collection)
        if context is None:
            if outcome_result:
                raise CEmissionError("Cannot emit outcome result for unsupported task collection")
            return collection
        if not self._statement_prelude_stack:
            raise CEmissionError("Top-level task collection await is not supported")
        outcomes = self._task_outcomes_for_ir(callee.receiver)
        if outcomes:
            return self._emit_task_collection_all_outcome_await(
                expression,
                collection,
                context,
                outcome_result=outcome_result,
            )
        self._statement_prelude_stack[-1].append(
            f"for (size_t _forge_i = 0; _forge_i < {context.length}; _forge_i += 1) {{"
        )
        self._statement_prelude_stack[-1].append(
            f"    _forge_async_task_await({context.tasks}[_forge_i]);"
        )
        self._statement_prelude_stack[-1].append(
            f"    {self._array_c_name(self._task_collection_array_type(callee.receiver.type))}_push(&{collection}, {context.contexts}[_forge_i].result);"
        )
        self._statement_prelude_stack[-1].append(
            f"    _forge_async_task_free({context.tasks}[_forge_i]);"
        )
        self._statement_prelude_stack[-1].append("}")
        self._statement_prelude_stack[-1].append(f"free({context.tasks});")
        self._statement_prelude_stack[-1].append(f"free({context.contexts});")
        return collection

    def _emit_task_collection_all_outcome_await(
        self,
        expression: IrCall,
        collection: str,
        context: _AsyncNativeTaskCollectionContext,
        *,
        outcome_result: bool,
    ) -> str:
        callee = expression.callee
        if not isinstance(callee, IrMember) or not isinstance(callee.receiver.type, TaskCollectionType):
            raise CEmissionError("Expected TaskCollection.all member call")
        outcomes = self._task_outcomes_for_ir(callee.receiver)
        if not outcomes:
            return collection
        if not isinstance(expression.type, TaskType):
            raise CEmissionError("Expected TaskCollection.all to return Task<T[]>")
        item_function_type = FunctionType(
            "taskItem",
            (),
            callee.receiver.type.result_type,
            (),
            outcomes,
        )
        collection_function_type = FunctionType(
            "all",
            (),
            expression.type.result_type,
            (),
            outcomes,
        )
        item_success_tag = self._result_tag_name(item_function_type, None)
        if outcome_result:
            result_type = self._function_result_c_name(collection_function_type, local=True)
            result_temp = self._new_temp("outcome")
            collection_success_tag = self._result_tag_name(collection_function_type, None)
            self._statement_prelude_stack[-1].append(f"{result_type} {result_temp};")
            self._statement_prelude_stack[-1].append(f"{result_temp}.tag = {collection_success_tag};")
            result_expr = result_temp
        else:
            result_temp = ""
            result_expr = collection
        self._statement_prelude_stack[-1].append(
            f"for (size_t _forge_i = 0; _forge_i < {context.length}; _forge_i += 1) {{"
        )
        self._statement_prelude_stack[-1].append(
            f"    _forge_async_task_await({context.tasks}[_forge_i]);"
        )
        item_result = f"{context.contexts}[_forge_i].result"
        if outcome_result:
            self._statement_prelude_stack[-1].append(f"    if ({result_temp}.tag == {self._result_tag_name(collection_function_type, None)}) {{")
            self._statement_prelude_stack[-1].append(f"        if ({item_result}.tag == {item_success_tag}) {{")
            self._statement_prelude_stack[-1].append(
                f"            {self._array_c_name(self._task_collection_array_type(callee.receiver.type))}_push(&{collection}, {item_result}.success);"
            )
            for index, outcome in enumerate(outcomes):
                prefix = "} else if" if index == 0 else "        } else if"
                item_tag = self._result_tag_name(item_function_type, outcome.type)
                collection_tag = self._result_tag_name(collection_function_type, outcome.type)
                field = self._outcome_field_name(outcome.type)
                self._statement_prelude_stack[-1].append(f"        {prefix} ({item_result}.tag == {item_tag}) {{")
                self._statement_prelude_stack[-1].append(
                    f"            {result_temp} = ({result_type}){{.tag = {collection_tag}, .{field} = {item_result}.{field}}};"
                )
            self._statement_prelude_stack[-1].append("        }")
            self._statement_prelude_stack[-1].append("    }")
        else:
            self._statement_prelude_stack[-1].append(f"    if ({item_result}.tag != {item_success_tag}) {{")
            self.includes.add("stdlib.h")
            self._statement_prelude_stack[-1].append("        abort();")
            self._statement_prelude_stack[-1].append("    }")
            self._statement_prelude_stack[-1].append(
                f"    {self._array_c_name(self._task_collection_array_type(callee.receiver.type))}_push(&{collection}, {item_result}.success);"
            )
        self._statement_prelude_stack[-1].append(
            f"    _forge_async_task_free({context.tasks}[_forge_i]);"
        )
        self._statement_prelude_stack[-1].append("}")
        if outcome_result:
            self._statement_prelude_stack[-1].append(
                f"if ({result_temp}.tag == {self._result_tag_name(collection_function_type, None)}) {{"
            )
            self._statement_prelude_stack[-1].append(f"    {result_temp}.success = {collection};")
            self._statement_prelude_stack[-1].append("}")
        self._statement_prelude_stack[-1].append(f"free({context.tasks});")
        self._statement_prelude_stack[-1].append(f"free({context.contexts});")
        return result_expr

    def _emit_task_collection_scalar_await(
        self,
        expression: IrCall,
        *,
        outcome_result: bool = False,
    ) -> str:
        callee = expression.callee
        if not isinstance(callee, IrMember):
            raise CEmissionError("Expected TaskCollection scalar member call")
        if self._task_outcomes_for_ir(callee.receiver):
            raise CEmissionError("TaskCollection scalar awaits with outcomes are not supported yet")
        if outcome_result:
            raise CEmissionError("Cannot emit outcome result for task collection scalar await")
        collection = self._emit_expression(callee.receiver)
        context = self._async_native_task_collections.get(collection)
        if context is None:
            return self._emit_task_collection_scalar_call(expression)
        if not self._statement_prelude_stack:
            raise CEmissionError("Top-level task collection await is not supported")
        self._statement_prelude_stack[-1].append(
            f"for (size_t _forge_i = 0; _forge_i < {context.length}; _forge_i += 1) {{"
        )
        self._statement_prelude_stack[-1].append(
            f"    _forge_async_task_await({context.tasks}[_forge_i]);"
        )
        self._statement_prelude_stack[-1].append(
            f"    {self._array_c_name(self._task_collection_array_type(callee.receiver.type))}_push(&{collection}, {context.contexts}[_forge_i].result);"
        )
        self._statement_prelude_stack[-1].append(
            f"    _forge_async_task_free({context.tasks}[_forge_i]);"
        )
        self._statement_prelude_stack[-1].append("}")
        self._statement_prelude_stack[-1].append(f"free({context.tasks});")
        self._statement_prelude_stack[-1].append(f"free({context.contexts});")
        if isinstance(callee.receiver, IrTaskBulkCall):
            self._statement_cleanup_stack[-1].append(f"free({collection}.data);")
        index = "0"
        if callee.member == "last":
            index = f"{collection}.len - 1"
        return f"{collection}.data[{index}]"

    def _emit_async_native_task_variable_await(
        self,
        receiver: IrLocalRef,
        context: str,
        *,
        outcome_result: bool = False,
    ) -> str:
        if not isinstance(receiver.type, TaskType):
            raise CEmissionError("Expected Task<T> receiver")
        task = self._emit_expression(receiver)
        if not self._statement_prelude_stack:
            raise CEmissionError("Top-level async native task await is not supported")
        self._statement_prelude_stack[-1].append(f"_forge_async_task_await({task});")
        self._statement_prelude_stack[-1].append(f"_forge_async_task_free({task});")
        function_type = self._await_function_type(receiver)
        if function_type is not None and function_type.outcomes:
            if outcome_result:
                return f"{context}.result"
            return self._emit_default_outcome_result_success(
                function_type,
                f"{context}.result",
                receiver.type.result_type,
            )
        return "0" if receiver.type.result_type == VOID else f"{context}.result"

    def _emit_async_native_task_collection_start(
        self,
        expression: IrTaskBulkCall,
        *,
        result_name: str,
    ) -> tuple[str, ...]:
        if not isinstance(expression.array.type, ArrayType) or expression.array.type.size is not None:
            raise CEmissionError("Only dynamic array task bulk calls are supported")
        if not isinstance(expression.type, TaskCollectionType):
            raise CEmissionError("Expected TaskCollection<T> task bulk call")
        node = self._function_declaration_for_callee(expression.callee)
        if node is None:
            raise CEmissionError("Expected async function")
        function_type = expression.callee.type
        if not isinstance(function_type, FunctionType):
            raise CEmissionError("Cannot determine async native task collection function type")
        if len(function_type.parameter_types) != 1:
            raise CEmissionError("TaskCollection async native calls support one array-fed parameter for now")

        array_type = self._task_collection_array_type(expression.type)
        array_name = self._array_c_name(array_type)
        self._array_runtime_helper(array_type)
        source_array = self._emit_expression(expression.array)
        call_name = self._async_runtime_call_name(expression.callee, node)
        receiver_type = self._async_runtime_receiver_type(expression.callee, node)
        helper = self._async_native_helper_for_function(function_type, call_name, receiver_type)
        context_type = helper["context_type"]
        run_function = helper["run_function"]
        contexts = self._new_temp("async_contexts")
        tasks = self._new_temp("async_tasks")
        length = f"{source_array}.len"
        self._async_native_task_collections[result_name] = _AsyncNativeTaskCollectionContext(
            tasks,
            contexts,
            length,
        )
        return (
            f"{array_name} {result_name} = {array_name}_new({length});",
            f"{context_type}* {contexts} = _forge_alloc(sizeof({context_type}) * {length});",
            f"_ForgeAsyncTask** {tasks} = _forge_alloc(sizeof(_ForgeAsyncTask*) * {length});",
            f"for (size_t _forge_i = 0; _forge_i < {length}; _forge_i += 1) {{",
            *(
                (f"    {contexts}[_forge_i].receiver = {self._emit_expression(expression.callee.receiver)};",)
                if receiver_type is not None and isinstance(expression.callee, IrMember)
                else ()
            ),
            f"    {contexts}[_forge_i].arg0 = {source_array}.data[_forge_i];",
            f"    {tasks}[_forge_i] = _forge_async_task_new({run_function}, &{contexts}[_forge_i]);",
            f"    _forge_async_task_start({tasks}[_forge_i]);",
            "}",
        )

    def _is_async_runtime_call(self, expression: IrExpression) -> bool:
        if not isinstance(expression, IrCall):
            return False
        node = self._function_declaration_for_callee(expression.callee)
        return (
            node is not None
            and "async" in node.modifiers
        )

    def _is_async_interface_call(self, expression: IrExpression) -> bool:
        if not isinstance(expression, IrCall):
            return False
        if not isinstance(expression.callee, IrMember):
            return False
        node = self._function_declaration_for_callee(expression.callee)
        return (
            node is not None
            and "async" in node.modifiers
            and isinstance(expression.callee.receiver.type, InterfaceType)
        )

    def _is_async_runtime_task_bulk_call(self, expression: IrExpression | None) -> bool:
        if not isinstance(expression, IrTaskBulkCall):
            return False
        node = self._function_declaration_for_callee(expression.callee)
        return (
            node is not None
            and "async" in node.modifiers
        )

    def _function_declaration_for_callee(self, expression: IrExpression) -> FunctionDeclaration | None:
        if isinstance(expression, IrLocalRef):
            node = expression.symbol.node
            return node if isinstance(node, FunctionDeclaration) else None
        if isinstance(expression, IrMember):
            node = expression.symbol.node if expression.symbol is not None else None
            return node if isinstance(node, FunctionDeclaration) else None
        return None

    def _async_runtime_call_name(
        self,
        callee: IrExpression,
        declaration: FunctionDeclaration,
    ) -> str:
        if declaration.native_name is not None:
            return declaration.native_name
        if isinstance(callee, IrLocalRef):
            return self._function_symbol_c_name(callee.symbol)
        if isinstance(callee, IrMember):
            if declaration.native_name is not None:
                return declaration.native_name
            class_type = self._class_type(callee.receiver.type)
            if class_type is None:
                raise CEmissionError(f"Cannot determine receiver class for async method '{callee.member}'")
            return f"{self._class_type_c_name(class_type)}_{callee.member}"
        raise CEmissionError("Unsupported async callee")

    def _async_runtime_receiver_type(
        self,
        callee: IrExpression,
        declaration: FunctionDeclaration,
    ) -> ClassType | None:
        if not isinstance(callee, IrMember):
            return None
        if declaration.kind == "new" or "static" in declaration.modifiers:
            return None
        class_type = self._class_type(callee.receiver.type)
        if class_type is None:
            raise CEmissionError(f"Cannot determine receiver class for async method '{callee.member}'")
        return class_type

    def _emit_async_native_awaited_call(
        self,
        expression: IrExpression,
        *,
        outcome_result: bool = False,
    ) -> str:
        if not isinstance(expression, IrCall):
            raise CEmissionError("Expected async call")
        node = self._function_declaration_for_callee(expression.callee)
        if node is None:
            raise CEmissionError("Expected async function")
        if not isinstance(expression.callee, (IrLocalRef, IrMember)):
            raise CEmissionError("Unsupported async callee")
        if not self._statement_prelude_stack:
            raise CEmissionError("Top-level async calls are not supported")

        call_name = self._async_runtime_call_name(expression.callee, node)
        receiver_type = self._async_runtime_receiver_type(expression.callee, node)
        helper = self._async_native_helper(expression, call_name, receiver_type)
        context_type = helper["context_type"]
        run_function = helper["run_function"]
        context = self._new_temp("async_context")
        self._statement_prelude_stack[-1].append(f"{context_type} {context};")
        if receiver_type is not None and isinstance(expression.callee, IrMember):
            self._statement_prelude_stack[-1].append(
                f"{context}.receiver = {self._emit_expression(expression.callee.receiver)};"
            )
        for index, argument in enumerate(expression.arguments):
            self._statement_prelude_stack[-1].append(
                f"{context}.arg{index} = {self._emit_expression(argument)};"
            )
        task = self._new_temp("async_task")
        self._statement_prelude_stack[-1].append(
            f"_ForgeAsyncTask* {task} = _forge_async_task_new({run_function}, &{context});"
        )
        self._statement_prelude_stack[-1].append(f"_forge_async_task_start({task});")
        self._statement_prelude_stack[-1].append(f"_forge_async_task_await({task});")
        self._statement_prelude_stack[-1].append(f"_forge_async_task_free({task});")
        function_type = self._function_type_for_expression(expression)
        if function_type is not None and function_type.outcomes:
            if outcome_result:
                return f"{context}.result"
            return self._emit_default_outcome_result_success(
                function_type,
                f"{context}.result",
                expression.type,
            )
        return "0" if expression.type == VOID else f"{context}.result"

    def _async_native_helper(
        self,
        expression: IrCall,
        native_name: str,
        receiver_type: ClassType | None = None,
    ) -> dict[str, str]:
        function_type = expression.callee.type
        if not isinstance(function_type, FunctionType):
            raise CEmissionError("Cannot determine async native function type")
        return self._async_native_helper_for_function(function_type, native_name, receiver_type)

    def _async_native_helper_for_function(
        self,
        function_type: FunctionType,
        native_name: str,
        receiver_type: ClassType | None = None,
    ) -> dict[str, str]:
        key_parts = [native_name]
        if receiver_type is not None:
            key_parts.append(receiver_type.display_name)
        key_parts.extend(
            [
                function_type.return_type.display_name,
                *(parameter.display_name for parameter in function_type.parameter_types),
            ]
        )
        key = "|".join(key_parts)
        suffix = self._c_identifier("_".join(key_parts))
        context_type = f"ForgeAsyncNative_{suffix}_Context"
        run_function = f"ForgeAsyncNative_{suffix}_run"
        if key not in self._async_native_helpers:
            has_outcomes = bool(function_type.outcomes)
            result_type = (
                self._function_result_c_name(function_type)
                if has_outcomes
                else self._c_return_type(function_type.return_type)
            )
            fields = [
                f"    {self._c_type(parameter_type)} arg{index};"
                for index, parameter_type in enumerate(function_type.parameter_types)
            ]
            if receiver_type is not None:
                fields.insert(0, f"    {self._c_type(receiver_type)} receiver;")
            if has_outcomes or function_type.return_type != VOID:
                fields.append(f"    {result_type} result;")
            if not fields:
                fields.append("    char _forge_empty;")
            arguments = ", ".join(
                f"context->arg{index}"
                for index, _ in enumerate(function_type.parameter_types)
            )
            if receiver_type is not None:
                arguments = f"context->receiver{', ' if arguments else ''}{arguments}"
            call = f"{native_name}({arguments})"
            if function_type.return_type == VOID and not has_outcomes:
                call_line = f"    {call};"
            else:
                call_line = f"    context->result = {call};"
            parameters = ", ".join(
                self._c_type(parameter_type)
                for parameter_type in function_type.parameter_types
            )
            if receiver_type is not None:
                receiver_parameter = self._c_type(receiver_type)
                parameters = f"{receiver_parameter}{', ' if parameters else ''}{parameters}"
            if not parameters:
                parameters = "void"
            self._async_native_helpers[key] = (
                f"{result_type} {native_name}({parameters});\n\n"
                + f"typedef struct {{\n"
                + "\n".join(fields)
                + f"\n}} {context_type};\n\n"
                + f"static void {run_function}(void* raw_context) {{\n"
                + f"    {context_type}* context = raw_context;\n"
                + call_line
                + "\n}"
            )
        return {"context_type": context_type, "run_function": run_function}

    def _emit_raw_call_expression(self, expression: IrCall) -> str:
        if isinstance(expression.callee, IrMember) and self._is_method_member(expression.callee):
            return self._emit_method_call(expression)
        arguments = ", ".join(self._emit_expression(argument) for argument in expression.arguments)
        return f"{self._emit_expression(expression.callee)}({arguments})"

    def _emit_outcome_result_expression(self, expression: IrExpression) -> str:
        if isinstance(expression, IrArrayPatternCheck):
            return self._emit_array_pattern_outcome_result(expression)
        if isinstance(expression, IrUnary) and expression.operator is TokenKind.AWAIT:
            return self._emit_awaited_outcome_result(expression)
        if isinstance(expression, IrCall) and self._is_task_await_call(expression):
            return self._emit_task_await_expression(expression, outcome_result=True)
        if isinstance(expression, IrCall) and self._call_has_outcomes(expression):
            return self._emit_raw_call_expression(expression)
        if isinstance(expression, IrBulkMapCall) and expression.outcomes:
            return self._emit_bulk_map_outcome_result(expression)
        if isinstance(expression, IrCatch):
            return self._emit_partial_catch_result_expression(expression)
        raise CEmissionError("Only direct outcome calls can be used with catch or forward")

    def _emit_array_pattern_outcome_result(
        self,
        expression: IrArrayPatternCheck,
    ) -> str:
        array_type = expression.type
        if not isinstance(array_type, ArrayType):
            raise CEmissionError("Array pattern check requires an array source")
        function_type = self._function_type_for_expression(expression)
        if function_type is None:
            raise CEmissionError("Cannot determine array pattern outcome type")
        result_type = self._function_result_c_name(function_type, local=True)
        result_temp = self._new_temp("outcome")
        self._statement_prelude_stack[-1].append(f"{result_type} {result_temp};")

        source_function_type = self._function_type_for_expression(expression.source)
        if source_function_type is not None and source_function_type.outcomes:
            source_result_type = self._function_result_c_name(
                source_function_type,
                local=self._expression_needs_local_outcome_result(expression.source),
            )
            source_result = self._emit_outcome_result_expression(expression.source)
            source_temp = self._new_temp("outcome")
            self._statement_prelude_stack[-1].append(
                f"{source_result_type} {source_temp} = {source_result};"
            )
            source_success_tag = self._result_tag_name(source_function_type, None)
            self._statement_prelude_stack[-1].append(
                f"if ({source_temp}.tag == {source_success_tag}) {{"
            )
            self._emit_array_pattern_length_branch(
                expression,
                function_type,
                result_temp,
                f"{source_temp}.success",
                indent="    ",
            )
            for outcome in source_function_type.outcomes:
                source_tag = self._result_tag_name(source_function_type, outcome.type)
                target_tag = self._result_tag_name(function_type, outcome.type)
                field = self._outcome_field_name(outcome.type)
                self._statement_prelude_stack[-1].append(
                    f"}} else if ({source_temp}.tag == {source_tag}) {{"
                )
                self._statement_prelude_stack[-1].append(
                    f"    {result_temp} = ({result_type})"
                    f"{{.tag = {target_tag}, .{field} = {source_temp}.{field}}};"
                )
            self.includes.add("stdlib.h")
            self._statement_prelude_stack[-1].extend(
                (
                    "} else {",
                    "    abort();",
                    "}",
                )
            )
            return result_temp

        source_value = (
            self._emit_owned_array_value(expression.source, cleanup_result=False)
            if self.ownership.owned_array_expression(expression.source)
            else self._emit_expression(expression.source)
        )
        source_temp = self._new_temp("array_pattern")
        self._statement_prelude_stack[-1].append(
            f"{self._c_type(array_type)} {source_temp} = {source_value};"
        )
        self._emit_array_pattern_length_branch(
            expression,
            function_type,
            result_temp,
            source_temp,
        )
        return result_temp

    def _emit_array_pattern_length_branch(
        self,
        expression: IrArrayPatternCheck,
        function_type: FunctionType,
        result_temp: str,
        source: str,
        *,
        indent: str = "",
    ) -> None:
        array_type = expression.type
        if not isinstance(array_type, ArrayType):
            raise CEmissionError("Array pattern check requires an array source")
        result_type = self._function_result_c_name(function_type, local=True)
        success_tag = self._result_tag_name(function_type, None)
        mismatch_tag = self._result_tag_name(function_type, PATTERN_MISMATCH)
        mismatch_field = self._outcome_field_name(PATTERN_MISMATCH)
        if array_type.size is not None:
            self._statement_prelude_stack[-1].append(
                f"{indent}{result_temp} = ({result_type})"
                f"{{.tag = {success_tag}, .success = {source}}};"
            )
            return

        self._statement_prelude_stack[-1].append(
            f"{indent}if ({source}.len >= {expression.required_count}) {{"
        )
        self._statement_prelude_stack[-1].append(
            f"{indent}    {result_temp} = ({result_type})"
            f"{{.tag = {success_tag}, .success = {source}}};"
        )
        self._statement_prelude_stack[-1].append(f"{indent}}} else {{")
        if self.ownership.owned_array_expression(expression.source):
            cleanup_lines = self._array_cleanup_lines_for(array_type, source)
            if cleanup_lines:
                self.includes.add("stdlib.h")
            for line in cleanup_lines:
                self._statement_prelude_stack[-1].append(f"{indent}    {line}")
        self._statement_prelude_stack[-1].append(
            f"{indent}    {result_temp} = ({result_type})"
            f"{{.tag = {mismatch_tag}, .{mismatch_field} = NULL}};"
        )
        self._statement_prelude_stack[-1].append(f"{indent}}}")

    def _emit_awaited_outcome_result(self, expression: IrUnary) -> str:
        operand = expression.operand
        if isinstance(operand, IrCall) and self._is_task_collection_all_call(operand):
            return self._emit_task_collection_all_await(operand, outcome_result=True)
        if isinstance(operand, IrCall) and self._is_task_collection_scalar_call(operand):
            return self._emit_task_collection_scalar_await(operand, outcome_result=True)
        if self._is_async_runtime_call(operand):
            return self._emit_async_native_awaited_call(operand, outcome_result=True)
        if isinstance(operand, IrLocalRef):
            context = self._async_native_task_contexts.get(id(operand.symbol))
            if context is not None:
                return self._emit_async_native_task_variable_await(
                    operand,
                    context,
                    outcome_result=True,
                )
        raise CEmissionError("Unsupported awaited outcome expression")

    def _emit_default_outcome_result_success(
        self,
        function_type: FunctionType,
        result: str,
        success_type: Type,
    ) -> str:
        result_type = self._function_result_c_name(function_type)
        temp = self._new_temp("outcome")
        success_tag = self._result_tag_name(function_type, None)
        self.includes.add("stdlib.h")
        self._statement_prelude_stack[-1].append(f"{result_type} {temp} = {result};")
        self._statement_prelude_stack[-1].append(f"if ({temp}.tag != {success_tag}) {{")
        self._statement_prelude_stack[-1].append("    abort();")
        self._statement_prelude_stack[-1].append("}")
        return "0" if success_type == VOID else f"{temp}.success"

    def _emit_default_outcome_call_expression(self, expression: IrCall) -> str:
        function_type = self._function_type_for_expression(expression)
        if function_type is None:
            raise CEmissionError("Cannot determine outcome call type")
        result_type = self._function_result_c_name(function_type)
        temp = self._new_temp("outcome")
        success_tag = self._result_tag_name(function_type, None)
        self._statement_prelude_stack[-1].append(
            f"{result_type} {temp} = {self._emit_raw_call_expression(expression)};"
        )
        self._statement_prelude_stack[-1].append(f"if ({temp}.tag != {success_tag}) {{")
        self.includes.add("stdlib.h")
        self._statement_prelude_stack[-1].append("    abort();")
        self._statement_prelude_stack[-1].append("}")
        return "0" if expression.type == VOID else f"{temp}.success"

    def _emit_forward_expression(self, expression: IrForward) -> str:
        current = self._current_function()
        if current is None or not isinstance(current.function_type, FunctionType):
            raise CEmissionError("'forward' can only be emitted inside a function")
        expression_function_type = self._function_type_for_expression(expression.expression)
        if expression_function_type is None:
            raise CEmissionError("Cannot determine forwarded expression outcome type")
        local_result = self._expression_needs_local_outcome_result(expression.expression)
        result_type = self._function_result_c_name(expression_function_type, local=local_result)
        temp = self._new_temp("outcome")
        result = self._emit_outcome_result_expression(expression.expression)
        success_tag = self._result_tag_name(expression_function_type, None)
        self._statement_prelude_stack[-1].append(f"{result_type} {temp} = {result};")
        for index, outcome in enumerate(expression_function_type.outcomes):
            prefix = "if" if index == 0 else "} else if"
            tag = self._result_tag_name(expression_function_type, outcome.type)
            field = self._outcome_field_name(outcome.type)
            current_tag = self._result_tag_name(current.function_type, outcome.type)
            current_result = self._function_result_c_name(current.function_type)
            self._statement_prelude_stack[-1].append(f"{prefix} ({temp}.tag == {tag}) {{")
            for line in self._outcome_return_statement(
                f"({current_result}){{.tag = {current_tag}, .{field} = {temp}.{field}}}"
            ):
                self._statement_prelude_stack[-1].append(f"    {line}")
        if expression_function_type.outcomes:
            self._statement_prelude_stack[-1].append("}")
        self._statement_prelude_stack[-1].append(f"if ({temp}.tag != {success_tag}) {{")
        self.includes.add("stdlib.h")
        self._statement_prelude_stack[-1].append("    abort();")
        self._statement_prelude_stack[-1].append("}")
        return "0" if expression.type == VOID else f"{temp}.success"

    def _outcome_return_statement(self, initializer: str) -> tuple[str, ...]:
        cleanup = self._cleanup_lines_for_return()
        if not cleanup:
            return (f"return {initializer};",)
        temp = self._new_temp("return")
        current = self._current_function()
        if current is None or not isinstance(current.function_type, FunctionType):
            raise CEmissionError("Outcome return outside function")
        return (
            f"{self._function_result_c_name(current.function_type)} {temp} = {initializer};",
            *cleanup,
            f"return {temp};",
        )

    def _emit_catch_expression(
        self,
        expression: IrCatch,
        *,
        ownership_temp: str | None = None,
    ) -> str:
        function_type = self._function_type_for_expression(expression.expression)
        if function_type is None:
            raise CEmissionError("Cannot determine caught expression outcome type")
        caught_outcomes = self._outcomes_for_expression(expression.expression)
        handled = tuple(handler.type for handler in expression.handlers)
        if any(
            not any(outcome.type == handled_type for handled_type in handled)
            for outcome in caught_outcomes
        ):
            raise CEmissionError("Partial catch forwarding is not supported by the C emitter yet")

        result_type = self._function_result_c_name(
            function_type,
            local=self._expression_needs_local_outcome_result(expression.expression),
        )
        result_temp = self._new_temp("outcome")
        result = self._emit_outcome_result_expression(expression.expression)
        self._statement_prelude_stack[-1].append(f"{result_type} {result_temp} = {result};")
        value_temp = ""
        if expression.type != VOID:
            value_temp = self._new_temp("catch")
            self._statement_prelude_stack[-1].append(f"{self._c_type(expression.type)} {value_temp};")
            self._statement_prelude_stack[-1].append(
                f"if ({result_temp}.tag == {self._result_tag_name(function_type, None)}) {{"
            )
            self._statement_prelude_stack[-1].append(f"    {value_temp} = {result_temp}.success;")
            if ownership_temp is not None:
                owns_success = self.ownership.owned_array_expression(
                    expression.expression
                )
                self._statement_prelude_stack[-1].append(
                    f"    {ownership_temp} = {1 if owns_success else 0};"
                )
        else:
            self._statement_prelude_stack[-1].append(
                f"if ({result_temp}.tag == {self._result_tag_name(function_type, None)}) {{"
            )
            self._statement_prelude_stack[-1].append("    ;")
        for handler in expression.handlers:
            self._emit_catch_handler_branch(
                function_type,
                result_temp,
                value_temp,
                handler,
                ownership_temp=ownership_temp,
            )
        self.includes.add("stdlib.h")
        self._statement_prelude_stack[-1].append("} else {")
        self._statement_prelude_stack[-1].append("    abort();")
        self._statement_prelude_stack[-1].append("}")
        return "0" if expression.type == VOID else value_temp

    def _emit_partial_catch_result_expression(self, expression: IrCatch) -> str:
        function_type = self._function_type_for_expression(expression.expression)
        if function_type is None:
            raise CEmissionError("Cannot determine caught expression outcome type")
        remaining = self._remaining_outcomes_for_catch(expression)
        if not remaining:
            raise CEmissionError("Fully handled catch does not produce an outcome result")

        full_result_type = self._function_result_c_name(
            function_type,
            local=self._expression_needs_local_outcome_result(expression.expression),
        )
        partial_function_type = FunctionType(
            "catch",
            (),
            expression.type,
            (),
            remaining,
        )
        partial_result_type = self._function_result_c_name(partial_function_type)
        full_temp = self._new_temp("outcome")
        partial_temp = self._new_temp("outcome")
        result = self._emit_outcome_result_expression(expression.expression)
        self._statement_prelude_stack[-1].append(f"{full_result_type} {full_temp} = {result};")
        self._statement_prelude_stack[-1].append(f"{partial_result_type} {partial_temp};")
        success_tag = self._result_tag_name(function_type, None)
        partial_success_tag = self._result_tag_name(partial_function_type, None)
        if expression.type == VOID:
            self._statement_prelude_stack[-1].append(f"if ({full_temp}.tag == {success_tag}) {{")
            self._statement_prelude_stack[-1].append(
                f"    {partial_temp} = ({partial_result_type}){{.tag = {partial_success_tag}}};"
            )
        else:
            self._statement_prelude_stack[-1].append(f"if ({full_temp}.tag == {success_tag}) {{")
            self._statement_prelude_stack[-1].append(
                f"    {partial_temp} = ({partial_result_type}){{.tag = {partial_success_tag}, .success = {full_temp}.success}};"
            )
        for handler in expression.handlers:
            self._emit_partial_catch_handler_branch(
                function_type,
                partial_function_type,
                full_temp,
                partial_temp,
                handler,
            )
        for outcome in remaining:
            tag = self._result_tag_name(function_type, outcome.type)
            partial_tag = self._result_tag_name(partial_function_type, outcome.type)
            field = self._outcome_field_name(outcome.type)
            self._statement_prelude_stack[-1].append(f"}} else if ({full_temp}.tag == {tag}) {{")
            self._statement_prelude_stack[-1].append(
                f"    {partial_temp} = ({partial_result_type}){{.tag = {partial_tag}, .{field} = {full_temp}.{field}}};"
            )
        self.includes.add("stdlib.h")
        self._statement_prelude_stack[-1].append("} else {")
        self._statement_prelude_stack[-1].append("    abort();")
        self._statement_prelude_stack[-1].append("}")
        return partial_temp

    def _emit_partial_catch_handler_branch(
        self,
        function_type: FunctionType,
        partial_function_type: FunctionType,
        full_temp: str,
        partial_temp: str,
        handler,
    ) -> None:
        if isinstance(handler.expression, IrBlock):
            raise CEmissionError("Partial catch handler blocks are not supported by the C emitter yet")
        tag = self._result_tag_name(function_type, handler.type)
        field = self._outcome_field_name(handler.type)
        partial_result_type = self._function_result_c_name(partial_function_type)
        partial_success_tag = self._result_tag_name(partial_function_type, None)
        self._statement_prelude_stack[-1].append(f"}} else if ({full_temp}.tag == {tag}) {{")
        self._statement_prelude_stack[-1].append(
            f"    {self._c_type(handler.type)} {handler.name} = {full_temp}.{field};"
        )
        value = self._emit_expression(handler.expression)
        if partial_function_type.return_type == VOID:
            self._statement_prelude_stack[-1].append(
                f"    {partial_temp} = ({partial_result_type}){{.tag = {partial_success_tag}}};"
            )
        else:
            self._statement_prelude_stack[-1].append(
                f"    {partial_temp} = ({partial_result_type}){{.tag = {partial_success_tag}, .success = {value}}};"
            )
        class_type = self._class_type(handler.type)
        if class_type is not None:
            self._statement_prelude_stack[-1].append(
                f"    _forge_free_{self._class_type_c_name(class_type)}({handler.name});"
            )

    def _emit_catch_handler_branch(
        self,
        function_type: FunctionType,
        result_temp: str,
        value_temp: str,
        handler,
        *,
        ownership_temp: str | None = None,
    ) -> None:
        tag = self._result_tag_name(function_type, handler.type)
        field = self._outcome_field_name(handler.type)
        self._statement_prelude_stack[-1].append(f"}} else if ({result_temp}.tag == {tag}) {{")
        self._statement_prelude_stack[-1].append(
            f"    {self._c_type(handler.type)} {handler.name} = {result_temp}.{field};"
        )
        if isinstance(handler.expression, IrBlock):
            for statement in handler.expression.statements:
                for line in self._emit_nested_statement_lines(statement):
                    self._statement_prelude_stack[-1].append(f"    {line}")
            return
        owns_value = (
            ownership_temp is not None
            and self.ownership.owned_array_expression(handler.expression)
        )
        value = (
            self._emit_owned_array_value(
                handler.expression,
                cleanup_result=False,
            )
            if owns_value
            else self._emit_expression(handler.expression)
        )
        if value_temp:
            self._statement_prelude_stack[-1].append(f"    {value_temp} = {value};")
            if ownership_temp is not None:
                self._statement_prelude_stack[-1].append(
                    f"    {ownership_temp} = {1 if owns_value else 0};"
                )
        else:
            self._statement_prelude_stack[-1].append(f"    {value};")
        class_type = self._class_type(handler.type)
        if class_type is not None:
            self._statement_prelude_stack[-1].append(
                f"    _forge_free_{self._class_type_c_name(class_type)}({handler.name});"
            )

    def _array_cleanup_symbol(self, binding: ArrayCleanupBinding):
        return (
            binding.variable.symbol
            if isinstance(binding, _ConditionalArrayCleanup)
            else binding.symbol
        )

    def _emit_nested_statement_lines(self, node) -> tuple[str, ...]:
        self._statement_prelude_stack.append([])
        self._statement_cleanup_stack.append([])
        return_cleanup_stack = self._return_cleanup_stack
        self._return_cleanup_stack = []
        statement = self._emit_statement(node)
        self._return_cleanup_stack = return_cleanup_stack
        prelude = tuple(self._statement_prelude_stack.pop())
        cleanup = () if isinstance(node, IrReturn) else tuple(reversed(self._statement_cleanup_stack.pop()))
        if isinstance(node, IrReturn):
            self._statement_cleanup_stack.pop()
        return (*prelude, *statement.splitlines(), *cleanup)

    def _call_has_outcomes(self, expression: IrCall) -> bool:
        function_type = expression.callee.type
        return isinstance(function_type, FunctionType) and bool(function_type.outcomes)

    def _function_type_for_expression(self, expression: IrExpression) -> FunctionType | None:
        if isinstance(expression, IrArrayPatternCheck):
            return FunctionType(
                "array_pattern",
                (),
                expression.type,
                (),
                expression.outcomes,
            )
        if isinstance(expression, IrUnary) and expression.operator is TokenKind.AWAIT:
            return self._await_function_type(expression.operand, success_type=expression.type)
        if isinstance(expression, IrCall) and self._is_task_await_call(expression):
            return self._await_function_type(expression)
        if isinstance(expression, IrCall) and isinstance(expression.callee.type, FunctionType):
            return expression.callee.type
        if (
            isinstance(expression, IrBulkMapCall)
            and isinstance(expression.callee.type, FunctionType)
            and expression.outcomes
        ):
            return FunctionType(
                "bulk_map",
                (),
                expression.type,
                (),
                expression.outcomes,
            )
        if isinstance(expression, IrCatch):
            remaining = self._remaining_outcomes_for_catch(expression)
            if remaining:
                return FunctionType("catch", (), expression.type, (), remaining)
        return None

    def _await_function_type(
        self,
        expression: IrExpression,
        *,
        success_type: Type | None = None,
    ) -> FunctionType | None:
        if isinstance(expression, IrCall) and self._is_task_await_call(expression):
            outcomes = self._outcomes_for_task_await_call(expression)
            return FunctionType("await", (), expression.type, (), outcomes)
        if isinstance(expression.type, TaskType):
            outcomes = self._task_outcomes_for_ir(expression)
            return FunctionType(
                "await",
                (),
                success_type or expression.type.result_type,
                (),
                outcomes,
            )
        return None

    def _outcomes_for_task_await_call(self, expression: IrCall) -> tuple[OutcomeType, ...]:
        callee = expression.callee
        if not isinstance(callee, IrMember):
            return ()
        return self._task_outcomes_for_ir(callee.receiver)

    def _task_outcomes_for_ir(self, expression: IrExpression) -> tuple[OutcomeType, ...]:
        return getattr(expression, "task_outcomes", ())

    def _outcomes_for_expression(self, expression: IrExpression) -> tuple[OutcomeType, ...]:
        function_type = self._function_type_for_expression(expression)
        return function_type.outcomes if function_type is not None else ()

    def _expression_needs_local_outcome_result(self, expression: IrExpression) -> bool:
        if isinstance(expression, IrArrayPatternCheck):
            return True
        if isinstance(expression, IrBulkMapCall) and expression.outcomes:
            return True
        if isinstance(expression, IrUnary) and expression.operator is TokenKind.AWAIT:
            return (
                isinstance(expression.operand, IrCall)
                and (
                    self._is_task_collection_all_call(expression.operand)
                    or self._is_task_collection_scalar_call(expression.operand)
                )
            )
        if isinstance(expression, IrCall) and self._is_task_await_call(expression):
            callee = expression.callee
            return (
                isinstance(callee, IrMember)
                and isinstance(callee.receiver, IrCall)
                and (
                    self._is_task_collection_all_call(callee.receiver)
                    or self._is_task_collection_scalar_call(callee.receiver)
                )
            )
        return False

    def _remaining_outcomes_for_catch(self, expression: IrCatch) -> tuple[OutcomeType, ...]:
        function_type = self._function_type_for_expression(expression.expression)
        if function_type is None:
            return ()
        handled = tuple(handler.type for handler in expression.handlers)
        return tuple(
            outcome
            for outcome in function_type.outcomes
            if not any(outcome.type == handled_type for handled_type in handled)
        )

    def _emit_method_call(self, expression: IrCall) -> str:
        callee = expression.callee
        if not isinstance(callee, IrMember):
            raise CEmissionError("Expected method member call")
        intrinsic = string_intrinsic(
            callee.member,
            static=isinstance(callee.receiver, IrBuiltinRef),
        )
        if intrinsic is not None and callee.receiver.type == STRING:
            arguments = [
                self._emit_expression(argument)
                for argument in expression.arguments
            ]
            if not intrinsic.static:
                arguments.insert(0, self._emit_expression(callee.receiver))
            return f"{intrinsic.native_name}({', '.join(arguments)})"
        if isinstance(callee.receiver.type, InterfaceType):
            receiver = self._emit_expression(callee.receiver)
            arguments = ", ".join(self._emit_expression(argument) for argument in expression.arguments)
            return (
                f"{receiver}.vtable->{callee.member}({receiver}.object"
                f"{', ' if arguments else ''}{arguments})"
            )
        class_type = self._class_type(callee.receiver.type)
        if class_type is None:
            raise CEmissionError(f"Cannot determine receiver class for method '{callee.member}'")

        arguments = [self._emit_expression(argument) for argument in expression.arguments]
        member_node = callee.symbol.node if callee.symbol is not None else None
        is_static = (
            isinstance(member_node, FunctionDeclaration)
            and (member_node.kind == "new" or "static" in member_node.modifiers)
        )
        if not is_static:
            arguments.insert(0, self._emit_expression(callee.receiver))
        function = (
            member_node.native_name
            if isinstance(member_node, FunctionDeclaration)
            and member_node.native_name is not None
            else f"{self._class_type_c_name(class_type)}_{callee.member}"
        )
        return f"{function}({', '.join(arguments)})"

    def _function_symbol_c_name(self, symbol) -> str:
        node = symbol.node
        if (
            isinstance(node, FunctionDeclaration)
            and "async" in node.modifiers
            and len(symbol.scope.overloads.get(symbol.name, ())) > 1
        ):
            return f"{symbol.name}_async"
        return symbol.name

    def _is_task_await_call(self, expression: IrCall) -> bool:
        return (
            isinstance(expression.callee, IrMember)
            and expression.callee.member == "await"
            and isinstance(expression.callee.receiver.type, TaskType)
        )

    def _is_task_collection_all_call(self, expression: IrCall) -> bool:
        return (
            isinstance(expression.callee, IrMember)
            and expression.callee.member == "all"
            and isinstance(expression.callee.receiver.type, TaskCollectionType)
        )

    def _is_task_collection_concurrency_call(self, expression: IrCall) -> bool:
        return (
            isinstance(expression.callee, IrMember)
            and expression.callee.member == "concurrency"
            and isinstance(expression.callee.receiver.type, TaskCollectionType)
        )

    def _is_task_collection_scalar_call(self, expression: IrCall) -> bool:
        return (
            isinstance(expression.callee, IrMember)
            and expression.callee.member in {"any", "first", "last"}
            and isinstance(expression.callee.receiver.type, TaskCollectionType)
        )

    def _emit_task_collection_scalar_call(self, expression: IrCall) -> str:
        callee = expression.callee
        if not isinstance(callee, IrMember):
            raise CEmissionError("Expected TaskCollection scalar member call")
        receiver = self._emit_expression(callee.receiver)
        if isinstance(callee.receiver, IrTaskBulkCall):
            self._statement_cleanup_stack[-1].append(f"free({receiver}.data);")
        index = "0"
        if callee.member == "last":
            index = f"{receiver}.len - 1"
        return f"{receiver}.data[{index}]"

    def _emit_operand(self, expression: IrExpression) -> str:
        if isinstance(expression, (IrLiteral, IrBuiltinRef, IrLocalRef, IrCall, IrArrayLiteral, IrMember, IrIndex, IrSpecialRef)):
            return self._emit_expression(expression)
        return f"({self._emit_expression(expression)})"

    def _emit_literal(self, expression: IrLiteral) -> str:
        value = expression.value
        if isinstance(value, bool):
            self.includes.add("stdbool.h")
            return "true" if value else "false"
        if isinstance(value, str):
            return self._c_string(value)
        if value is None:
            return "NULL"
        return str(value)

    def _c_type(self, type_: Type) -> str:
        if isinstance(type_, TaskType):
            return self._c_type(type_.result_type)
        if isinstance(type_, TaskCollectionType):
            return self._c_type(self._task_collection_array_type(type_))
        if isinstance(type_, NullableType):
            return self._nullable_c_type(type_)
        if isinstance(type_, ArrayType):
            if type_.size is None:
                return self._array_c_name(type_)
            return f"{self._c_type(type_.element_type)}*"
        if isinstance(type_, ClassType):
            return f"struct {self._class_type_c_name(type_)}*"
        if isinstance(type_, InterfaceType):
            return f"struct {self._interface_type_c_name(type_)}"
        if isinstance(type_, StructType):
            return f"struct {self._class_type_c_name(type_)}"
        if isinstance(type_, EnumType) and type_.value_type is not None:
            return self._c_type(type_.value_type)
        if isinstance(type_, BuiltinType):
            return self._builtin_c_type(type_)
        raise CEmissionError(f"Cannot emit C type for {type_.display_name}")

    def _is_method_member(self, expression: IrMember) -> bool:
        if expression.receiver.type == STRING:
            intrinsic = string_intrinsic(
                expression.member,
                static=isinstance(expression.receiver, IrBuiltinRef),
            )
            if intrinsic is not None:
                return True
        return expression.symbol is not None and expression.symbol.kind == "function"

    def _is_static_variable_member(self, expression: IrMember) -> bool:
        member_node = expression.symbol.node if expression.symbol is not None else None
        return (
            isinstance(member_node, VariableDeclaration)
            and "static" in member_node.modifiers
        )

    def _is_class_pointer(self, type_: Type) -> bool:
        return self._class_type(type_) is not None

    def _is_owned_string_symbol(self, symbol) -> bool:
        return any(
            variable.symbol == symbol
            for cleanup_scope in self._string_cleanup_stack
            for variable in cleanup_scope
        )

    def _class_type(self, type_: Type) -> ClassType | None:
        if isinstance(type_, NullableType):
            type_ = type_.inner_type
        return type_ if isinstance(type_, ClassType) else None

    def _class_type_c_name(self, type_: ClassType | StructType) -> str:
        base = self._class_c_name(type_.name, type_.symbol)
        type_arguments = getattr(type_, "type_arguments", ())
        if not type_arguments:
            return base
        suffix = "_".join(
            self._c_identifier(argument.display_name)
            for argument in type_arguments
        )
        return f"{base}_{suffix}"

    def _enum_type_c_name(self, type_: EnumType) -> str:
        return self._class_c_name(type_.name, type_.symbol)

    def _emit_enum_struct_equality(self, expression: IrBinary) -> str | None:
        if expression.operator not in {TokenKind.EQUAL_EQUAL, TokenKind.BANG_EQUAL}:
            return None
        left_type = expression.left.type
        right_type = expression.right.type
        if not (
            isinstance(left_type, EnumType)
            and isinstance(right_type, EnumType)
            and left_type.symbol == right_type.symbol
            and isinstance(left_type.value_type, StructType)
        ):
            return None
        operator = self._c_binary_operator(expression.operator)
        return (
            f"{self._emit_operand(expression.left)}._forge_variant_id "
            f"{operator} "
            f"{self._emit_operand(expression.right)}._forge_variant_id"
        )

    def _interface_type_c_name(self, type_: InterfaceType) -> str:
        return self._class_c_name(type_.name, type_.symbol)

    def _type_reference_c_type(self, reference) -> str:
        if reference.name == "Int":
            return "int"
        if reference.name == "Double":
            return "double"
        if reference.name == "Bool":
            self.includes.add("stdbool.h")
            return "bool"
        if reference.name == "String":
            return "const char*"
        return f"struct {self._c_identifier(reference.name)}"

    def _array_c_name(self, type_: ArrayType) -> str:
        element_type = self._c_type(type_.element_type)
        name = f"ForgeArray_{self._c_identifier(type_.element_type.display_name)}"
        self.helpers.add(f"array_type:{name}:{element_type}")
        self.includes.add("stdlib.h")
        return name

    def _task_collection_array_type(self, type_: TaskCollectionType) -> ArrayType:
        return ArrayType(f"{type_.result_type.name}[]", type_.result_type)

    def _array_runtime_helper(self, type_: ArrayType) -> None:
        element_type = self._c_type(type_.element_type)
        name = self._array_c_name(type_)
        self.helpers.add(f"array_runtime:{name}:{element_type}")

    def _class_c_name(self, class_name: str, symbol) -> str:
        source_name = None
        if symbol is not None:
            source_name = symbol.node.location.source_name
        if not source_name:
            return self._c_identifier(class_name)

        path = PurePath(source_name)
        stem_parts = (*path.parent.parts, path.stem)
        if path.stem == class_name:
            parts = stem_parts
        else:
            parts = (*stem_parts, class_name)
        return "_".join(self._c_identifier(part) for part in parts if part and part != ".")

    def _c_identifier(self, name: str) -> str:
        identifier = re.sub(r"[^0-9A-Za-z_]", "_", name)
        if not identifier:
            return "_"
        if identifier[0].isdigit():
            return f"_{identifier}"
        return identifier

    def _nullable_c_type(self, type_: NullableType) -> str:
        inner = type_.inner_type
        if isinstance(inner, (ClassType, ArrayType)) or inner == STRING:
            return self._c_type(inner)
        if isinstance(inner, StructType):
            return f"{self._c_type(inner)}*"
        raise CEmissionError(f"Nullable value type {type_.display_name} is not supported yet")

    def _emit_nullable_value(self, expression: IrExpression, target_type: NullableType) -> str:
        if isinstance(expression, IrLiteral) and expression.value is None:
            return "NULL"
        inner = target_type.inner_type
        if isinstance(inner, StructType) and expression.type == inner:
            return self._emit_boxed_struct(expression, inner)
        return self._emit_expression(expression)

    def _emit_boxed_struct(self, expression: IrExpression, type_: StructType) -> str:
        if not self._statement_prelude_stack:
            raise CEmissionError(
                f"Nullable struct value {type_.display_name}? requires a statement context"
            )
        self.helpers.add("alloc")
        c_type = self._c_type(type_)
        temp = self._new_temp("nullable")
        self._statement_prelude_stack[-1].append(
            f"{c_type}* {temp} = _forge_alloc(sizeof({c_type}));"
        )
        self._statement_prelude_stack[-1].append(
            f"*{temp} = {self._emit_expression(expression)};"
        )
        return temp

    def _c_return_type(self, type_: Type) -> str:
        if type_ == STRING:
            return "char*"
        return self._c_type(type_)

    def _builtin_c_type(self, type_: BuiltinType) -> str:
        if type_ == INT:
            return "int"
        if type_ == DOUBLE:
            return "double"
        if type_ == BOOL:
            self.includes.add("stdbool.h")
            return "bool"
        if type_ == STRING:
            return "const char*"
        if type_ == PATTERN_MISMATCH:
            return "struct ForgePatternMismatch*"
        if type_ == VOID:
            return "void"
        mapping = {
            "Byte": "signed char",
            "UByte": "unsigned char",
            "Short": "short",
            "UShort": "unsigned short",
            "UInt": "unsigned int",
            "Long": "long long",
            "ULong": "unsigned long long",
            "Float": "float",
        }
        if type_.name in mapping:
            return mapping[type_.name]
        raise CEmissionError(f"Unsupported built-in type {type_.display_name}")

    def _function_c_return_type(self, function: IrFunction) -> str:
        if self._function_has_outcomes(function):
            return self._function_result_c_name(function.function_type)
        return self._c_return_type(function.return_type)

    def _function_has_outcomes(self, function: IrFunction) -> bool:
        return (
            isinstance(function.function_type, FunctionType)
            and bool(function.function_type.outcomes)
        )

    def _current_function(self) -> IrFunction | None:
        return self._function_stack[-1] if self._function_stack else None

    def _current_function_has_outcomes(self) -> bool:
        current = self._current_function()
        return current is not None and self._function_has_outcomes(current)

    def _function_result_c_name(self, type_: Type, *, local: bool = False) -> str:
        if not isinstance(type_, FunctionType) or not type_.outcomes:
            raise CEmissionError("Expected function type with outcomes")
        return self._result_c_name_for_outcomes(type_.return_type, type_.outcomes, local=local)

    def _result_c_name_for_outcomes(
        self,
        return_type: Type,
        outcomes: tuple[OutcomeType, ...],
        *,
        local: bool = False,
    ) -> str:
        parts = ["ForgeResult", self._c_identifier(return_type.display_name)]
        parts.extend(self._c_identifier(outcome.type.display_name) for outcome in outcomes)
        name = "_".join(parts)
        success_type = "void" if return_type == VOID else self._c_return_type(return_type)
        specs = ",".join(
            f"{self._outcome_field_name(outcome.type)}={self._c_type(outcome.type)}"
            for outcome in outcomes
        )
        kind = "local_outcome_result" if local else "outcome_result"
        self.helpers.add(f"{kind}:{name}:{success_type}:{specs}")
        return name

    def _result_tag_name(self, function_type: FunctionType, outcome_type: Type | None) -> str:
        result_name = self._function_result_c_name(function_type)
        if outcome_type is None:
            return f"{result_name}_SUCCESS"
        return f"{result_name}_{self._outcome_field_name(outcome_type).upper()}"

    def _outcome_field_name(self, type_: Type) -> str:
        return f"outcome_{self._c_identifier(type_.display_name)}"

    def _printf_format(self, type_: Type) -> str:
        if type_ == STRING:
            return "%s"
        if type_ == INT:
            return "%d"
        if type_ == DOUBLE:
            return "%f"
        if type_ == BOOL:
            return "%d"
        return "%p"

    def _c_binary_operator(self, operator: TokenKind) -> str:
        mapping = {
            TokenKind.PLUS: "+",
            TokenKind.MINUS: "-",
            TokenKind.STAR: "*",
            TokenKind.SLASH: "/",
            TokenKind.PERCENT: "%",
            TokenKind.EQUAL_EQUAL: "==",
            TokenKind.BANG_EQUAL: "!=",
            TokenKind.LESS: "<",
            TokenKind.LESS_EQUAL: "<=",
            TokenKind.GREATER: ">",
            TokenKind.GREATER_EQUAL: ">=",
            TokenKind.AND_AND: "&&",
            TokenKind.OR_OR: "||",
        }
        if operator not in mapping:
            raise CEmissionError(f"Unsupported binary operator {operator.value}")
        return mapping[operator]

    def _c_unary_operator(self, operator: TokenKind) -> str:
        mapping = {
            TokenKind.BANG: "!",
            TokenKind.NOT: "!",
            TokenKind.MINUS: "-",
        }
        if operator not in mapping:
            raise CEmissionError(f"Unsupported unary operator {operator.value}")
        return mapping[operator]

    def _c_string(self, value: str) -> str:
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\r", "\\r")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'

    def _line(self, text: str) -> str:
        return f"{'    ' * self._indent}{text}"
