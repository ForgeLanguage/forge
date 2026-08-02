"""Minimal source-level expansion for Forge template functions.

This MVP intentionally expands templates textually before the regular Forge
parser runs. The generated source is then parsed, typechecked, lowered, and
emitted by the normal compiler pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from forge_parser import (
    CallExpression,
    ClassDeclaration,
    Expression,
    IdentifierExpression,
    MemberExpression,
    TypeReference,
    VariableDeclaration,
    parse,
    parse_expression,
)


class TemplateExpansionError(SyntaxError):
    """Raised when a template function cannot be expanded."""


@dataclass(frozen=True, slots=True)
class _TemplateFunction:
    source_name: str
    name: str
    owner: str | None
    type_parameter: str | None
    constraint: str | None
    parameters: str
    results: str
    body: str
    modifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Property:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class _PropertyInfo:
    name: str
    type: "_TypeInfo"
    separator: str = ""


@dataclass(frozen=True, slots=True)
class _TypeInfo:
    name: str
    properties: tuple[_PropertyInfo, ...]
    is_struct: bool = False
    is_array: bool = False
    is_nullable: bool = False
    element_name: str = ""
    element_type: "_TypeInfo | None" = None
    inner_type: "_TypeInfo | None" = None

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class _ReflectionClass:
    pass


_TEMPLATE_HEADER = re.compile(
    r"(?P<prefix>(?:(?:public|internal|private|static|async|native)\s+)*)"
    r"template\s+func\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*<\s*(?P<type_parameter>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*:\s*(?P<constraint>struct|class|enum)\s*>)?"
    r"\s*\((?P<parameters>[^)]*)\)"
    r"\s*:\s*(?P<results>[^{]+?)"
    r"\s*\{",
)


def expand_templates(source: str, *, source_name: str | None = None) -> str:
    """Expand top-level Forge template functions in *source*."""

    expanded = expand_template_sources(((source_name or "<source>", source),))
    return expanded[source_name or "<source>"]


def expand_template_sources(
    sources: tuple[tuple[str, str], ...],
) -> dict[str, str]:
    """Expand template functions across a set of named Forge sources."""

    stripped_by_name: dict[str, str] = {}
    templates: list[_TemplateFunction] = []
    for source_name, source in sources:
        stripped_source, extracted = _extract_templates(source, source_name=source_name)
        stripped_by_name[source_name] = stripped_source
        templates.extend(extracted)

    if not templates:
        return dict(sources)

    structs: dict[str, tuple[_Property, ...]] = {}
    for source_name, stripped_source in stripped_by_name.items():
        structs.update(_collect_structs(stripped_source, source_name=source_name))

    templates_by_key = {
        _template_key(template.owner, template.name): template
        for template in templates
        if template.type_parameter is not None
    }

    expanded: dict[str, str] = {}
    for source_name, stripped_source in stripped_by_name.items():
        rewritten = stripped_source
        folded_owner = _folded_owner(stripped_source, source_name)
        generated: list[str] = [
            _generate_nongeneric_function(template)
            for template in templates
            if template.type_parameter is None and template.source_name == source_name
        ]
        instantiations: set[tuple[str, str]] = set()
        changed = True
        while changed:
            changed = False
            search_source = "\n\n".join((rewritten, *generated))
            for key, template in templates_by_key.items():
                calls = _template_calls(search_source, key)
                for type_name in calls:
                    instantiation = (key, type_name)
                    if instantiation in instantiations:
                        continue
                    instantiations.add(instantiation)
                    properties = _properties_for(type_name, template, structs)
                    generated.append(
                        _generate_function(
                            template,
                            type_name,
                            properties,
                            structs,
                            force_static=folded_owner is not None,
                        )
                    )
                    changed = True
                rewritten = _rewrite_calls(
                    rewritten,
                    key,
                    qualifier=folded_owner,
                    instantiations=instantiations,
                )
                generated = [
                    _rewrite_calls(
                        fragment,
                        key,
                        qualifier=folded_owner,
                        instantiations=instantiations,
                    )
                    for fragment in generated
                ]
        if generated and any("JsonValue" in fragment for fragment in generated):
            rewritten = _ensure_use(rewritten, "std.Json.JsonValue")
        expanded[source_name] = (
            rewritten.rstrip() + "\n\n" + "\n\n".join(generated) + "\n"
            if generated
            else rewritten
        )
    return expanded


def _ensure_use(source: str, path: str) -> str:
    line = f"use {path}"
    if re.search(rf"^\s*{re.escape(line)}\s*$", source, re.M):
        return source
    match = re.match(r"(?P<attrs>(?:\s*@\w+\s*\n)+)(?P<rest>.*)", source, re.S)
    if match is not None:
        return match.group("attrs") + line + "\n" + match.group("rest")
    return line + "\n" + source


def _extract_templates(
    source: str,
    *,
    source_name: str | None = None,
) -> tuple[str, tuple[_TemplateFunction, ...]]:
    templates: list[_TemplateFunction] = []
    chunks: list[str] = []
    cursor = 0
    while True:
        match = _TEMPLATE_HEADER.search(source, cursor)
        if match is None:
            chunks.append(source[cursor:])
            break
        body_start = match.end()
        body_end = _matching_brace(source, body_start - 1)
        chunks.append(source[cursor:match.start()])
        templates.append(
            _TemplateFunction(
                source_name or "<source>",
                match.group("name"),
                _template_owner(source, match.start(), source_name),
                match.group("type_parameter"),
                match.group("constraint"),
                match.group("parameters").strip(),
                match.group("results").strip(),
                source[body_start:body_end],
                tuple(part for part in match.group("prefix").split() if part),
            )
        )
        cursor = body_end + 1
    return "".join(chunks), tuple(templates)


def _template_owner(source: str, match_start: int, source_name: str | None) -> str | None:
    prefix = source[:match_start]
    if re.search(r"\bclass\b\s*(?:\n|\r\n|\{|$)", prefix):
        if source_name is None:
            return None
        return source_name.rsplit("/", 1)[-1].removesuffix(".forge")
    match = re.search(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{[^{}]*$", prefix, re.S)
    if match is not None:
        return match.group(1)
    return None


def _folded_owner(source: str, source_name: str) -> str | None:
    if re.match(r"\s*@multidef\b", source):
        return None
    prefix = r"(?:\s*use\s+[^\n]+\n|\s*@\w+\n)*"
    match = re.match(prefix + r"\s*(?:public\s+|internal\s+|private\s+)?(?:class|struct)\s*(?:\n|\r\n|$)", source)
    if match is None:
        return None
    return source_name.rsplit("/", 1)[-1].removesuffix(".forge")


def _matching_brace(source: str, open_index: int) -> int:
    depth = 0
    index = open_index
    in_string = False
    escape = False
    while index < len(source):
        char = source[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    raise TemplateExpansionError("Unterminated template function body")


def _collect_structs(
    source: str,
    *,
    source_name: str | None = None,
) -> dict[str, tuple[_Property, ...]]:
    structs: dict[str, tuple[_Property, ...]] = {}
    try:
        program = parse(source, source_name=source_name)
    except SyntaxError as exc:
        raise TemplateExpansionError(
            f"Cannot parse source for compile-time reflection metadata: {exc}"
        ) from exc
    for declaration in program.declarations:
        if not isinstance(declaration, ClassDeclaration) or declaration.kind != "struct":
            continue
        if declaration.name is None:
            continue
        properties = []
        for member in declaration.members:
            if isinstance(member, VariableDeclaration) and member.type is not None:
                properties.append(_Property(member.name, _type_reference_source(member.type)))
        structs[declaration.name] = tuple(properties)
    return structs


def _type_reference_source(type_: TypeReference) -> str:
    text = type_.name
    if type_.arguments:
        text += "<" + ", ".join(_type_reference_source(argument) for argument in type_.arguments) + ">"
    text += "[]" * type_.array_depth
    if type_.nullable:
        text += "?"
    return text


def _template_calls(source: str, key: str) -> tuple[str, ...]:
    pattern = re.compile(
        rf"\b{re.escape(key)}\s*<\s*([A-Za-z_][A-Za-z0-9_.]*)\s*>(?=\s*[\(\[])"
    )
    return tuple(match.group(1) for match in pattern.finditer(source))


def _rewrite_calls(
    source: str,
    key: str,
    *,
    qualifier: str | None = None,
    instantiations: set[tuple[str, str]] | None = None,
) -> str:
    pattern = re.compile(
        rf"\b{re.escape(key)}\s*<\s*([A-Za-z_][A-Za-z0-9_.]*)\s*>(?P<space>\s*)(?P<open>[\(\[])"
    )

    def replacement(match: re.Match[str]) -> str:
        type_name = match.group(1)
        if instantiations is not None and (key, type_name) not in instantiations:
            return match.group(0)
        name = _generated_name(key, type_name)
        if qualifier is not None:
            name = f"{qualifier}.{name}"
        return f"{name}{match.group('space')}{match.group('open')}"

    return pattern.sub(replacement, source)


def _properties_for(
    type_name: str,
    template: _TemplateFunction,
    structs: dict[str, tuple[_Property, ...]],
) -> tuple[_Property, ...]:
    if template.constraint is None:
        return ()
    if template.constraint != "struct":
        raise TemplateExpansionError(
            f"Template constraint '{template.constraint}' is not supported yet"
        )
    short_name = type_name.rsplit(".", 1)[-1]
    properties = structs.get(short_name)
    if properties is None:
        raise TemplateExpansionError(f"Cannot reflect unknown struct '{type_name}'")
    return properties


def _generate_function(
    template: _TemplateFunction,
    type_name: str,
    properties: tuple[_Property, ...],
    structs: dict[str, tuple[_Property, ...]],
    *,
    force_static: bool = False,
) -> str:
    modifier_parts = [mod for mod in template.modifiers if mod != "template"]
    if force_static:
        if "static" not in modifier_parts:
            modifier_parts.append("static")
    else:
        modifier_parts = [mod for mod in modifier_parts if mod != "static"]
    modifiers = " ".join(modifier_parts)
    if modifiers:
        modifiers += " "
    key = _template_key(template.owner, template.name)
    name = _generated_name(key, type_name)
    if template.type_parameter is None:
        raise TemplateExpansionError("Generic template expansion requires a type parameter")
    parameters = _replace_type_parameter(template.parameters, template.type_parameter, type_name)
    results = _replace_type_parameter(template.results, template.type_parameter, type_name)
    body = _expand_body(template, type_name, properties, structs)
    return f"{modifiers}func {name}({parameters}): {results} {{\n{body}\n}}"


def _generate_nongeneric_function(template: _TemplateFunction) -> str:
    modifiers = " ".join(mod for mod in template.modifiers if mod != "template")
    if modifiers:
        modifiers += " "
    body = _expand_body(template, None, (), {})
    return f"{modifiers}func {template.name}({template.parameters}): {template.results} {{\n{body}\n}}"


def _expand_body(
    template: _TemplateFunction,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, tuple[_Property, ...]],
) -> str:
    context: dict[str, object] = {
        "Reflection": _ReflectionClass(),
    }
    if template.type_parameter is not None and type_name is not None:
        context[template.type_parameter] = type_name
    return "\n".join(
        _expand_lines(
            template.body.splitlines(),
            context,
            type_parameter=template.type_parameter,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
    )


def _expand_lines(
    lines: list[str],
    context: dict[str, object],
    *,
    type_parameter: str | None,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, tuple[_Property, ...]],
) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("#for "):
            source_expression, item_name = _parse_for_directive(stripped)
            items = _eval_template_expression(
                source_expression,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            if not isinstance(items, tuple):
                raise TemplateExpansionError("#for source expression must evaluate to an array")
            block: list[str] = []
            index += 1
            depth = 0
            while index < len(lines):
                nested = lines[index].strip()
                if nested.startswith("#for ") or nested.startswith("#if "):
                    depth += 1
                elif nested.startswith("#}") and not nested.startswith("#} else"):
                    if depth == 0:
                        break
                    depth -= 1
                block.append(lines[index])
                index += 1
            if index == len(lines):
                raise TemplateExpansionError("Unterminated #for template block")
            for item in items:
                context[item_name] = item
                output.extend(
                    _expand_lines(
                        block,
                        context,
                        type_parameter=type_parameter,
                        type_name=type_name,
                        properties=properties,
                        structs=structs,
                    )
                )
            context.pop(item_name, None)
            index += 1
            continue
        if stripped.startswith("#if "):
            condition_expression = _parse_if_directive(stripped)
            then_block, else_block, next_index = _collect_if_blocks(lines, index + 1)
            condition = _eval_template_expression(
                condition_expression,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            selected = then_block if bool(condition) else else_block
            output.extend(
                _expand_lines(
                    selected,
                    context,
                    type_parameter=type_parameter,
                    type_name=type_name,
                    properties=properties,
                    structs=structs,
                )
            )
            index = next_index
            continue
        if stripped.startswith("#"):
            index += 1
            continue
        output.append(
            _expand_template_line(
                _replace_type_parameter_outside_template_expressions(
                    line,
                    type_parameter,
                    type_name,
                ),
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
        )
        index += 1
    return output


def _parse_for_directive(line: str) -> tuple[str, str]:
    text = line.removeprefix("#for ").strip()
    if text.endswith("{"):
        text = text[:-1].rstrip()
    match = re.match(r"(?P<source>.+)\s+as\s+(?P<item>[A-Za-z_][A-Za-z0-9_]*)$", text)
    if match is None:
        raise TemplateExpansionError("Expected '#for <expression> as <name> {'")
    return match.group("source"), match.group("item")


def _parse_if_directive(line: str) -> str:
    text = line.removeprefix("#if ").strip()
    if text.endswith("{"):
        text = text[:-1].rstrip()
    if not text:
        raise TemplateExpansionError("Expected '#if <expression> {'")
    return text


def _collect_if_blocks(lines: list[str], start: int) -> tuple[list[str], list[str], int]:
    then_block: list[str] = []
    else_block: list[str] = []
    current = then_block
    index = start
    depth = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("#for ") or stripped.startswith("#if "):
            depth += 1
        elif stripped.startswith("#}") and not stripped.startswith("#} else"):
            if depth == 0:
                return then_block, else_block, index + 1
            depth -= 1
        elif stripped.startswith("#} else") and depth == 0:
            current = else_block
            index += 1
            continue
        current.append(lines[index])
        index += 1
    raise TemplateExpansionError("Unterminated #if template block")


def _expand_template_line(
    line: str,
    context: dict[str, object],
    *,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, tuple[_Property, ...]],
) -> str:
    def replace(match: re.Match[str]) -> str:
        value = _eval_template_expression(
            match.group(1),
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        return str(value)

    return re.sub(r"#\{([^}]+)\}", replace, line)


def _eval_template_expression(
    source: str,
    context: dict[str, object],
    *,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, tuple[_Property, ...]],
) -> object:
    try:
        expression = parse_expression(source)
    except SyntaxError as exc:
        raise TemplateExpansionError(f"Cannot parse template expression '{source}': {exc}") from exc
    return _eval_expression(
        expression,
        context,
        type_name=type_name,
        properties=properties,
        structs=structs,
    )


def _eval_expression(
    expression: Expression,
    context: dict[str, object],
    *,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, tuple[_Property, ...]],
) -> object:
    if isinstance(expression, IdentifierExpression):
        if expression.name in context:
            return context[expression.name]
        raise TemplateExpansionError(f"Unknown compile-time value '{expression.name}'")
    if isinstance(expression, MemberExpression):
        receiver = _eval_expression(
            expression.receiver,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        return _eval_member(receiver, expression.member)
    if isinstance(expression, CallExpression):
        if isinstance(expression.callee, MemberExpression):
            receiver = _eval_expression(
                expression.callee.receiver,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            return _eval_call(
                receiver,
                expression.callee.member,
                expression.type_arguments,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
        raise TemplateExpansionError("Only member calls are supported in template expressions")
    raise TemplateExpansionError(f"Unsupported template expression '{type(expression).__name__}'")


def _eval_member(receiver: object, member: str) -> object:
    if isinstance(receiver, _TypeInfo) and member == "properties":
        return receiver.properties
    if isinstance(receiver, _TypeInfo) and member == "isStruct":
        return receiver.is_struct
    if isinstance(receiver, _TypeInfo) and member == "isArray":
        return receiver.is_array
    if isinstance(receiver, _TypeInfo) and member == "isNullable":
        return receiver.is_nullable
    if isinstance(receiver, _TypeInfo) and member == "elementName":
        return receiver.element_name
    if isinstance(receiver, _TypeInfo) and member == "elementType":
        if receiver.element_type is None:
            raise TemplateExpansionError("Non-array type has no elementType")
        return receiver.element_type
    if isinstance(receiver, _TypeInfo) and member == "innerType":
        if receiver.inner_type is None:
            raise TemplateExpansionError("Non-nullable type has no innerType")
        return receiver.inner_type
    if isinstance(receiver, _TypeInfo) and member == "name":
        return receiver.name
    if isinstance(receiver, _PropertyInfo):
        if member == "name":
            return receiver.name
        if member == "type":
            return receiver.type
        if member == "separator":
            return receiver.separator
    raise TemplateExpansionError(f"Unknown compile-time member '{member}'")


def _eval_call(
    receiver: object,
    member: str,
    type_arguments: tuple[TypeReference, ...],
    context: dict[str, object],
    *,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, tuple[_Property, ...]],
) -> object:
    if isinstance(receiver, _ReflectionClass) and member == "type":
        if len(type_arguments) != 1:
            raise TemplateExpansionError("Reflection.type expects one type argument")
        reflected_type = _resolve_type_argument(type_arguments[0], context, type_name)
        if reflected_type is None:
            raise TemplateExpansionError("Cannot resolve Reflection.type argument")
        return _TypeInfo(
            reflected_type,
            tuple(
                _PropertyInfo(
                    property_.name,
                    _type_info_for(property_.type, structs),
                    "" if index == 0 else ",",
                )
                for index, property_ in enumerate(properties)
            ),
            is_struct=True,
        )
    raise TemplateExpansionError(f"Unknown compile-time call '{member}'")


def _resolve_type_argument(
    type_reference: TypeReference,
    context: dict[str, object],
    type_name: str | None,
) -> str | None:
    if type_reference.name in context:
        value = context[type_reference.name]
        if isinstance(value, str):
            return value
    if type_reference.name == "T" and type_name is not None:
        return type_name
    return _type_reference_source(type_reference)


def _type_info_for(
    type_name: str,
    structs: dict[str, tuple[_Property, ...]],
) -> _TypeInfo:
    if type_name.endswith("?"):
        inner_name = type_name[:-1]
        return _TypeInfo(
            type_name,
            (),
            is_nullable=True,
            inner_type=_type_info_for(inner_name, structs),
        )
    if type_name.endswith("[]"):
        element_name = type_name[:-2]
        return _TypeInfo(
            type_name,
            (),
            is_array=True,
            element_name=element_name,
            element_type=_type_info_for(element_name, structs),
        )
    short_name = type_name.rsplit(".", 1)[-1]
    properties = structs.get(short_name)
    if properties is None:
        return _TypeInfo(type_name, ())
    return _TypeInfo(
        type_name,
        tuple(
            _PropertyInfo(
                property_.name,
                _type_info_for(property_.type, structs),
                "" if index == 0 else ",",
            )
            for index, property_ in enumerate(properties)
        ),
        is_struct=True,
    )


def _replace_type_parameter(text: str, parameter: str | None, type_name: str | None) -> str:
    if parameter is None or type_name is None:
        return text
    return re.sub(rf"\b{re.escape(parameter)}\b", type_name, text)


def _replace_type_parameter_outside_template_expressions(
    text: str,
    parameter: str | None,
    type_name: str | None,
) -> str:
    if parameter is None or type_name is None:
        return text
    parts = re.split(r"(#\{[^}]+\})", text)
    return "".join(
        part
        if part.startswith("#{") and part.endswith("}")
        else _replace_type_parameter(part, parameter, type_name)
        for part in parts
    )


def _type_suffix(type_name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", type_name)


def _template_key(owner: str | None, name: str) -> str:
    return f"{owner}.{name}" if owner is not None else name


def _generated_name(key: str, type_name: str) -> str:
    return f"{key.replace('.', '_')}__{_type_suffix(type_name)}"
