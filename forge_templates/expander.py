"""Minimal source-level expansion for Forge template functions.

This MVP intentionally expands templates textually before the regular Forge
parser runs. The generated source is then parsed, typechecked, lowered, and
emitted by the normal compiler pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import re

from forge_lexer import TokenKind
from forge_parser import (
    ArrayLiteralExpression,
    AssignmentExpression,
    BinaryExpression,
    BulkCallExpression,
    CallExpression,
    ClassDeclaration,
    Expression,
    FunctionDeclaration,
    IdentifierExpression,
    IndexExpression,
    MemberExpression,
    LiteralExpression,
    TypeReference,
    UnaryExpression,
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
class _MethodSignature:
    name: str
    type_parameter: str | None
    constraint: str | None
    parameters: str
    results: str
    template: bool = False


@dataclass(frozen=True, slots=True)
class TemplateInvocationContext:
    receiver_expression: str | None
    receiver_configuration_identity: str | None
    type_arguments: tuple[str, ...]
    source_name: str
    source_location: int


@dataclass(frozen=True, slots=True)
class _StateDeclaration:
    owner: str
    name: str
    type_source: str
    initializer: str


@dataclass(frozen=True, slots=True)
class _Property:
    name: str
    type: str
    ownership: str = "borrow"


@dataclass(frozen=True, slots=True)
class _TypeShape:
    properties: tuple[_Property, ...]
    constructor_parameters: tuple[_Property, ...] = ()
    implements: tuple[str, ...] = ()
    is_struct: bool = False
    is_class: bool = False
    is_interface: bool = False


@dataclass(frozen=True, slots=True)
class _PropertyInfo:
    name: str
    type: "_TypeInfo"
    separator: str = ""


@dataclass(frozen=True, slots=True)
class _ConstructorInfo:
    parameters: tuple["_ParameterInfo", ...]


@dataclass(frozen=True, slots=True)
class _ParameterInfo:
    name: str
    type: "_TypeInfo"
    separator: str = ""
    ownership: str = "borrow"
    move_prefix: str = ""


@dataclass(frozen=True, slots=True)
class _ImplementationInfo:
    name: str
    type: "_TypeInfo"
    separator: str = ""


@dataclass(frozen=True, slots=True)
class _TypeInfo:
    name: str
    properties: tuple[_PropertyInfo, ...]
    constructor: _ConstructorInfo | None = None
    implementations: tuple[_ImplementationInfo, ...] = ()
    arguments: tuple["_TypeInfo", ...] = ()
    is_struct: bool = False
    is_class: bool = False
    is_interface: bool = False
    is_array: bool = False
    is_nullable: bool = False
    element_name: str = ""
    element_type: "_TypeInfo | None" = None
    inner_type: "_TypeInfo | None" = None

    def __str__(self) -> str:
        return self.name

    @property
    def is_simple(self) -> bool:
        return self.name in {"String", "Int", "Bool"}


@dataclass(frozen=True, slots=True)
class _ReflectionClass:
    pass


@dataclass(frozen=True, slots=True)
class _CompilerClass:
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class _GraphClass:
    pass


_TEMPLATE_HEADER = re.compile(
    r"(?P<prefix>(?:(?:public|internal|private|static|async|native)\s+)*)"
    r"template\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*<\s*(?P<type_parameter>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*:\s*(?P<constraint>struct|class|interface|enum)\s*>)?"
    r"\s*\((?P<parameters>[^)]*)\)"
    r"\s*:\s*(?P<results>[^{]+?)"
    r"\s*\{",
)

_TEMPLATE_SIGNATURE = re.compile(
    r"(?m)^(?P<indent>\s*)"
    r"(?P<prefix>(?:(?:public|internal|private|static|async|native)\s+)*)"
    r"template\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*<\s*(?P<type_parameter>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*:\s*(?P<constraint>struct|class|interface|enum)\s*>)?"
    r"\s*\((?P<parameters>[^)]*)\)"
    r"\s*:\s*(?P<results>[^\n{]+?)\s*$",
)

_STATE_DECLARATION = re.compile(
    r"(?m)^(?P<indent>\s*)#state\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
    r"(?P<type>[^=\n]+?)\s*=\s*"
    r"(?P<initializer>[^\n]+)\s*$"
)

_UNKNOWN_RECEIVER_CONFIG = (
    "Stateful template invocation requires a compile-time-resolvable receiver configuration."
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
    state_declarations: list[_StateDeclaration] = []
    for source_name, source in sources:
        source, extracted_states = _extract_state_declarations(source, source_name=source_name)
        state_declarations.extend(extracted_states)
        stripped_source, extracted = _extract_templates(source, source_name=source_name)
        stripped_by_name[source_name] = stripped_source
        templates.extend(extracted)

    if not templates:
        return dict(sources)

    structs: dict[str, _TypeShape] = {}
    for source_name, stripped_source in stripped_by_name.items():
        structs.update(_collect_structs(stripped_source, source_name=source_name))

    template_only_implements = _check_template_interface_contracts(stripped_by_name, templates)
    templates_by_key = {
        _template_key(template.owner, template.name): template
        for template in templates
        if template.type_parameter is not None
    }
    nongeneric_templates_by_key = {
        _template_key(template.owner, template.name): template
        for template in templates
        if template.type_parameter is None
    }
    stateful_owners = {declaration.owner for declaration in state_declarations}
    states_by_owner = _initial_states_by_owner(state_declarations, structs)

    expanded: dict[str, str] = {}
    for source_name, stripped_source in stripped_by_name.items():
        rewritten = _strip_template_only_implements(
            stripped_source,
            template_only_implements.get(source_name, ()),
        )
        folded_owner = _folded_owner(stripped_source, source_name)
        receiver_configs = _receiver_configurations(rewritten, stateful_owners)
        rewritten, stateful_fragments = _expand_stateful_template_calls(
            rewritten,
            {**templates_by_key, **nongeneric_templates_by_key},
            receiver_configs,
            states_by_owner,
            structs,
            source_name=source_name,
        )
        generated: list[str] = [
            _generate_nongeneric_function(template)
            for template in templates
            if (
                template.type_parameter is None
                and template.source_name == source_name
                and template.owner not in stateful_owners
            )
        ]
        generated.extend(stateful_fragments)
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


def _check_template_interface_contracts(
    stripped_by_name: dict[str, str],
    templates: list[_TemplateFunction],
) -> dict[str, tuple[tuple[str, str], ...]]:
    methods_by_owner: dict[str, dict[str, _MethodSignature]] = {}
    interfaces_by_class: dict[str, tuple[str, ...]] = {}
    source_by_class: dict[str, str] = {}
    template_only: dict[str, list[tuple[str, str]]] = {}

    for source_name, source in stripped_by_name.items():
        try:
            program = parse(source, source_name=source_name)
        except SyntaxError as exc:
            raise TemplateExpansionError(
                f"Cannot parse source for template interface contracts: {exc}"
            ) from exc
        for declaration in program.declarations:
            if not isinstance(declaration, ClassDeclaration) or declaration.name is None:
                continue
            source_by_class[declaration.name] = source_name
            methods = methods_by_owner.setdefault(declaration.name, {})
            for member in declaration.members:
                if isinstance(member, FunctionDeclaration):
                    methods[member.name] = _method_signature_from_function(member)
            if declaration.kind != "interface" and declaration.implements:
                interfaces_by_class[declaration.name] = tuple(
                    _type_reference_source(interface) for interface in declaration.implements
                )

    for template in templates:
        if template.owner is None:
            continue
        methods_by_owner.setdefault(template.owner, {})[template.name] = _method_signature_from_template(template)

    for class_name, interfaces in interfaces_by_class.items():
        class_methods = methods_by_owner.get(class_name, {})
        for interface_name in interfaces:
            required = methods_by_owner.get(interface_name.rsplit(".", 1)[-1], {})
            used_template = False
            for name, expected in required.items():
                actual = class_methods.get(name)
                if actual is None:
                    raise TemplateExpansionError(
                        f"Type {class_name} implements {interface_name} but is missing method '{name}'"
                    )
                if not _same_method_signature(actual, expected):
                    raise TemplateExpansionError(
                        f"Method '{name}' does not match interface {interface_name}"
                    )
                used_template = used_template or actual.template or expected.template
            if used_template:
                source_name = source_by_class[class_name]
                template_only.setdefault(source_name, []).append((class_name, interface_name))

    return {source_name: tuple(items) for source_name, items in template_only.items()}


def _method_signature_from_template(template: _TemplateFunction) -> _MethodSignature:
    return _MethodSignature(
        template.name,
        template.type_parameter,
        template.constraint,
        _normalize_signature_source(template.parameters),
        _normalize_signature_source(template.results),
        True,
    )


def _method_signature_from_function(function: FunctionDeclaration) -> _MethodSignature:
    type_parameter = function.type_parameters[0] if function.type_parameters else None
    return _MethodSignature(
        function.name,
        type_parameter.name if type_parameter is not None else None,
        type_parameter.constraint if type_parameter is not None else None,
        ", ".join(
            f"{parameter.name}: {_type_reference_source(parameter.type)}"
            for parameter in function.parameters
        ),
        _type_reference_source(function.return_type) if function.return_type is not None else "Void",
        "template" in function.modifiers,
    )


def _same_method_signature(actual: _MethodSignature, expected: _MethodSignature) -> bool:
    if (
        actual.name != expected.name
        or actual.constraint != expected.constraint
        or actual.results != expected.results
    ):
        return False
    actual_parameters = actual.parameters
    expected_parameters = expected.parameters
    if actual.type_parameter is not None and expected.type_parameter is not None:
        actual_parameters = re.sub(rf"\b{re.escape(actual.type_parameter)}\b", expected.type_parameter, actual_parameters)
        actual_result = re.sub(rf"\b{re.escape(actual.type_parameter)}\b", expected.type_parameter, actual.results)
    else:
        actual_result = actual.results
    return (
        actual.type_parameter is not None
        if expected.type_parameter is not None
        else actual.type_parameter is None
    ) and actual_parameters == expected_parameters and actual_result == expected.results


def _normalize_signature_source(source: str) -> str:
    return re.sub(r"\s+", " ", source.strip())


def _strip_template_only_implements(
    source: str,
    implements: tuple[tuple[str, str], ...],
) -> str:
    rewritten = source
    for _class_name, interface_name in implements:
        short_name = interface_name.rsplit(".", 1)[-1]
        pattern = re.compile(
            rf"(?m)^\s*implements\s+{re.escape(short_name)}\s*$"
        )
        rewritten = pattern.sub("", rewritten)
    return rewritten


def _ensure_use(source: str, path: str) -> str:
    line = f"use {path}"
    if re.search(rf"^\s*{re.escape(line)}\s*$", source, re.M):
        return source
    match = re.match(r"(?P<attrs>(?:\s*@\w+\s*\n)+)(?P<rest>.*)", source, re.S)
    if match is not None:
        return match.group("attrs") + line + "\n" + match.group("rest")
    return line + "\n" + source


def _extract_state_declarations(
    source: str,
    *,
    source_name: str | None = None,
) -> tuple[str, tuple[_StateDeclaration, ...]]:
    declarations: list[_StateDeclaration] = []

    def replace(match: re.Match[str]) -> str:
        owner = _template_owner(source, match.start(), source_name)
        if owner is None:
            raise TemplateExpansionError("#state declaration must belong to a template owner")
        declarations.append(
            _StateDeclaration(
                owner,
                match.group("name"),
                match.group("type").strip(),
                match.group("initializer").strip(),
            )
        )
        return ""

    return _STATE_DECLARATION.sub(replace, source), tuple(declarations)


def _initial_states_by_owner(
    declarations: list[_StateDeclaration],
    structs: dict[str, _TypeShape],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for declaration in declarations:
        state = result.setdefault(declaration.owner, {})
        state[declaration.name] = _eval_state_initializer(declaration.initializer, structs)
    return result


def _eval_state_initializer(source: str, structs: dict[str, _TypeShape]) -> object:
    text = source.strip()
    if text == "{}":
        return {}
    if text == "[]":
        return []
    if text in {"true", "false"}:
        return text == "true"
    if text == "null":
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return _eval_template_expression(text, _base_template_context({}), type_name=None, properties=(), structs=structs)


def _base_template_context(state: dict[str, object]) -> dict[str, object]:
    return {
        "Reflection": _ReflectionClass(),
        "Compiler": _CompilerClass([]),
        "Graph": _GraphClass(),
        "state": SimpleNamespace(**state),
    }


def _sync_state_from_context(context: dict[str, object], state: dict[str, object]) -> None:
    state_object = context.get("state")
    if isinstance(state_object, SimpleNamespace):
        state.update(vars(state_object))


def _receiver_configurations(source: str, stateful_owners: set[str]) -> dict[str, tuple[str, str]]:
    configs: dict[str, tuple[str, str]] = {}
    counters: dict[str, int] = {}
    pattern = re.compile(
        r"^\s*const\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s*:[^=]+)?\s*=\s*(?P<expr>[^\n]+)$",
        re.M,
    )
    changed = True
    while changed:
        changed = False
        for match in pattern.finditer(source):
            name = match.group("name")
            if name in configs:
                continue
            expression = match.group("expr").strip()
            new_match = re.fullmatch(r"(?P<owner>[A-Za-z_][A-Za-z0-9_.]*)\.new\s*\([^)]*\)", expression)
            if new_match is not None:
                owner = new_match.group("owner").rsplit(".", 1)[-1]
                if owner in stateful_owners:
                    counters[owner] = counters.get(owner, 0) + 1
                    configs[name] = (owner, f"Config#{counters[owner]}")
                    changed = True
                    continue
            alias_match = re.fullmatch(r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)", expression)
            if alias_match is not None and alias_match.group("alias") in configs:
                configs[name] = configs[alias_match.group("alias")]
                changed = True
    return configs


def _expand_stateful_template_calls(
    source: str,
    templates_by_key: dict[str, _TemplateFunction],
    receiver_configs: dict[str, tuple[str, str]],
    states_by_owner: dict[str, dict[str, object]],
    structs: dict[str, _TypeShape],
    *,
    source_name: str,
) -> tuple[str, list[str]]:
    generated: list[str] = []
    generated_names: set[str] = set()
    states: dict[tuple[str, str], dict[str, object]] = {}
    pattern = re.compile(
        r"\b(?P<receiver>[A-Za-z_][A-Za-z0-9_]*)\."
        r"(?P<method>[A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s*<\s*(?P<type>[A-Za-z_][A-Za-z0-9_.]*)\s*>)?"
        r"(?P<space>\s*)(?P<open>[\(\[])"
    )
    runtime_ranges = _runtime_control_ranges(source)
    declared_names = _declared_value_names(source)

    def replacement(match: re.Match[str]) -> str:
        receiver = match.group("receiver")
        config = receiver_configs.get(receiver)
        method = match.group("method")
        if config is None:
            if any(
                key.endswith(f".{method}") and key.rsplit(".", 1)[0] in states_by_owner
                for key in templates_by_key
                if "." in key
            ):
                if receiver not in declared_names:
                    return match.group(0)
                raise TemplateExpansionError(_UNKNOWN_RECEIVER_CONFIG)
            return match.group(0)
        owner, config_id = config
        key = _template_key(owner, method)
        template = templates_by_key.get(key)
        if template is None:
            return match.group(0)
        if any(start <= match.start() < end for start, end in runtime_ranges):
            raise TemplateExpansionError(
                "State-changing template invocation must be in compile-time deterministic control flow."
            )
        state_key = (owner, config_id)
        state = states.setdefault(state_key, _clone_state(states_by_owner[owner]))
        type_name = match.group("type")
        if template.type_parameter is not None and type_name is None:
            return match.group(0)
        if template.type_parameter is None and type_name is not None:
            return match.group(0)
        invocation = TemplateInvocationContext(
            receiver,
            config_id,
            (type_name,) if type_name is not None else (),
            source_name,
            match.start(),
        )
        state["context"] = invocation
        properties = _properties_for(type_name, template, structs) if type_name is not None else ()
        generated_name = _generated_stateful_name(key, type_name, config_id)
        fragment = _generate_stateful_function(
            template,
            type_name,
            properties,
            structs,
            state,
            config_id,
        )
        if fragment and generated_name not in generated_names:
            generated.append(fragment)
            generated_names.add(generated_name)
        return f"{generated_name}{match.group('space')}{match.group('open')}"

    return pattern.sub(replacement, source), generated


def _declared_value_names(source: str) -> set[str]:
    names = {
        match.group("name")
        for match in re.finditer(
            r"(?m)^\s*(?:const|var)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b",
            source,
        )
    }
    for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\((?P<parameters>[^)]*)\)\s*(?::|=>|\{)", source):
        for parameter in match.group("parameters").split(","):
            parameter = parameter.strip()
            if not parameter:
                continue
            parameter = re.sub(r"^(?:public|private|internal|take|borrow)\s+", "", parameter)
            parameter_name = parameter.split(":", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parameter_name):
                names.add(parameter_name)
    return names


def _clone_state(state: dict[str, object]) -> dict[str, object]:
    cloned: dict[str, object] = {}
    for key, value in state.items():
        if isinstance(value, dict):
            cloned[key] = {item_key: list(item_value) if isinstance(item_value, list) else item_value for item_key, item_value in value.items()}
        elif isinstance(value, list):
            cloned[key] = list(value)
        else:
            cloned[key] = value
    return cloned


def _runtime_control_ranges(source: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"(?m)^\s*(if|for|while|do)\b[^{]*\{", source):
        stripped = source[match.start() : match.end()].lstrip()
        if stripped.startswith("#"):
            continue
        try:
            ranges.append((match.start(), _matching_brace(source, match.end() - 1)))
        except TemplateExpansionError:
            continue
    return ranges


def _generate_stateful_function(
    template: _TemplateFunction,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, _TypeShape],
    state: dict[str, object],
    config_id: str,
) -> str:
    body = _expand_stateful_body(template, type_name, properties, structs, state)
    modifier_parts = [mod for mod in template.modifiers if mod != "template"]
    modifiers = " ".join(modifier_parts)
    if modifiers:
        modifiers += " "
    parameters = template.parameters
    if template.type_parameter is not None and type_name is not None:
        parameters = _replace_type_parameter(parameters, template.type_parameter, type_name)
        results = _replace_type_parameter(template.results, template.type_parameter, type_name)
    else:
        results = template.results
    name = _generated_stateful_name(_template_key(template.owner, template.name), type_name, config_id)
    return f"{modifiers}{name}({parameters}): {results} {{\n{body}\n}}"


def _generated_stateful_name(key: str, type_name: str | None, config_id: str) -> str:
    suffix = _type_suffix(type_name) if type_name is not None else "nongeneric"
    config_suffix = re.sub(r"[^0-9A-Za-z_]", "_", config_id)
    return f"{key.replace('.', '_')}__{suffix}__{config_suffix}"


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
    stripped = "".join(chunks)

    def replace_signature(match: re.Match[str]) -> str:
        templates.append(
            _TemplateFunction(
                source_name or "<source>",
                match.group("name"),
                _template_owner(stripped, match.start(), source_name),
                match.group("type_parameter"),
                match.group("constraint"),
                match.group("parameters").strip(),
                match.group("results").strip(),
                "",
                tuple(part for part in match.group("prefix").split() if part),
            )
        )
        return ""

    stripped = _TEMPLATE_SIGNATURE.sub(replace_signature, stripped)
    return stripped, tuple(templates)


def _template_owner(source: str, match_start: int, source_name: str | None) -> str | None:
    for match in re.finditer(
        r"\b(?:class|struct|interface|trait)\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)?\s*\{",
        source,
    ):
        if match.start() >= match_start:
            break
        try:
            body_end = _matching_brace(source, match.end() - 1)
        except TemplateExpansionError:
            continue
        if match.end() - 1 < match_start < body_end:
            name = match.group("name")
            if name is not None:
                return name
            if source_name is not None:
                return source_name.rsplit("/", 1)[-1].removesuffix(".forge")
    prefix = source[:match_start]
    if re.search(r"\b(?:class|struct|interface|trait)\b\s*(?:\n|\r\n|\{|$)", prefix):
        if source_name is None:
            return None
        return source_name.rsplit("/", 1)[-1].removesuffix(".forge")
    match = re.search(r"\b(?:class|struct|interface|trait)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{[^{}]*$", prefix, re.S)
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
) -> dict[str, _TypeShape]:
    structs: dict[str, _TypeShape] = {}
    try:
        program = parse(source, source_name=source_name)
    except SyntaxError as exc:
        raise TemplateExpansionError(
            f"Cannot parse source for compile-time reflection metadata: {exc}"
        ) from exc
    for declaration in program.declarations:
        if (
            not isinstance(declaration, ClassDeclaration)
            or declaration.kind not in {"struct", "class", "interface"}
        ):
            continue
        if declaration.name is None:
            continue
        properties = []
        for member in declaration.members:
            if isinstance(member, VariableDeclaration) and member.type is not None:
                properties.append(_Property(member.name, _type_reference_source(member.type)))
        constructor_parameters: tuple[_Property, ...] = ()
        constructors = [
            member
            for member in declaration.members
            if getattr(member, "kind", None) == "new"
        ]
        if constructors:
            constructor = max(constructors, key=lambda item: len(item.parameters))
            constructor_parameters = tuple(
                _Property(
                    parameter.name,
                    _type_reference_source(parameter.type),
                    parameter.ownership,
                )
                for parameter in constructor.parameters
            )
        structs[declaration.name] = _TypeShape(
            tuple(properties),
            constructor_parameters,
            tuple(_type_reference_source(interface) for interface in declaration.implements),
            is_struct=declaration.kind == "struct",
            is_class=declaration.kind == "class",
            is_interface=declaration.kind == "interface",
        )
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
    structs: dict[str, _TypeShape],
) -> tuple[_Property, ...]:
    if template.constraint is None:
        return ()
    if template.constraint not in {"struct", "class", "interface"}:
        raise TemplateExpansionError(
            f"Template constraint '{template.constraint}' is not supported yet"
        )
    short_name = type_name.rsplit(".", 1)[-1]
    shape = structs.get(short_name)
    if shape is None:
        raise TemplateExpansionError(f"Cannot reflect unknown {template.constraint} '{type_name}'")
    if template.constraint == "struct" and not shape.is_struct:
        raise TemplateExpansionError(f"Template expected struct '{type_name}'")
    if template.constraint == "class" and not shape.is_class:
        raise TemplateExpansionError(f"Template expected class '{type_name}'")
    if template.constraint == "interface" and not shape.is_interface:
        raise TemplateExpansionError(f"Template expected interface '{type_name}'")
    return shape.properties


def _generate_function(
    template: _TemplateFunction,
    type_name: str,
    properties: tuple[_Property, ...],
    structs: dict[str, _TypeShape],
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
    return f"{modifiers}{name}({parameters}): {results} {{\n{body}\n}}"


def _generate_nongeneric_function(template: _TemplateFunction) -> str:
    modifiers = " ".join(mod for mod in template.modifiers if mod != "template")
    if modifiers:
        modifiers += " "
    body = _expand_body(template, None, (), {})
    return f"{modifiers}{template.name}({template.parameters}): {template.results} {{\n{body}\n}}"


def _expand_body(
    template: _TemplateFunction,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, _TypeShape],
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


def _expand_stateful_body(
    template: _TemplateFunction,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, _TypeShape],
    state: dict[str, object],
) -> str:
    context = _base_template_context(state)
    if template.type_parameter is not None and type_name is not None:
        context[template.type_parameter] = type_name
    output = _expand_lines(
        template.body.splitlines(),
        context,
        type_parameter=template.type_parameter,
        type_name=type_name,
        properties=properties,
        structs=structs,
    )
    _sync_state_from_context(context, state)
    state.pop("context", None)
    return "\n".join(output)


def _expand_lines(
    lines: list[str],
    context: dict[str, object],
    *,
    type_parameter: str | None,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, _TypeShape],
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
            if not isinstance(items, (list, tuple)):
                raise TemplateExpansionError("#for source expression must evaluate to an array")
            block: list[str] = []
            index += 1
            depth = 0
            while index < len(lines):
                nested = lines[index].strip()
                if nested == "#{" or nested.startswith("#for ") or nested.startswith("#if "):
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
        if stripped == "#{":
            block, next_index = _collect_compile_time_block(lines, index + 1)
            _execute_compile_time_block(
                block,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            index = next_index
            continue
        if stripped.startswith("#panic "):
            message_source = stripped.removeprefix("#panic ").strip()
            message = _eval_template_expression(
                message_source,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            if isinstance(message, str):
                message = _expand_template_line(
                    message,
                    context,
                    type_name=type_name,
                    properties=properties,
                    structs=structs,
                )
            raise TemplateExpansionError(str(message))
        if stripped.startswith("#") and not stripped.startswith("#{"):
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


def _collect_compile_time_block(lines: list[str], start: int) -> tuple[list[str], int]:
    block: list[str] = []
    index = start
    depth = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == "#{":
            depth += 1
        elif stripped == "#}":
            if depth == 0:
                return block, index + 1
            depth -= 1
        block.append(lines[index])
        index += 1
    raise TemplateExpansionError("Unterminated compile-time template block")


def _execute_compile_time_block(
    lines: list[str],
    context: dict[str, object],
    *,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, _TypeShape],
) -> None:
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("const ") or line.startswith("var "):
            keyword, rest = line.split(" ", 1)
            if "=" not in rest:
                raise TemplateExpansionError(f"Expected initializer for compile-time {keyword}")
            name_part, expression_source = rest.split("=", 1)
            name = name_part.split(":", 1)[0].strip()
            context[name] = _eval_template_expression(
                expression_source.strip(),
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            index += 1
            continue
        if line.startswith("if "):
            condition_source = line.removeprefix("if ").strip()
            if condition_source.endswith("{"):
                condition_source = condition_source[:-1].strip()
            then_block, else_block, next_index = _collect_runtime_style_if_blocks(lines, index + 1)
            condition = _eval_template_expression(
                condition_source,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            _execute_compile_time_block(
                then_block if bool(condition) else else_block,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            index = next_index
            continue
        if line.startswith("for "):
            source_expression, item_name = _parse_compile_time_for(line)
            items = _eval_template_expression(
                source_expression,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            if isinstance(items, dict):
                items = list(items.keys())
            if not isinstance(items, (list, tuple)):
                raise TemplateExpansionError("Compile-time for source expression must evaluate to an array")
            block, next_index = _collect_runtime_style_block(lines, index + 1)
            previous = context.get(item_name)
            had_previous = item_name in context
            for item in items:
                context[item_name] = item
                _execute_compile_time_block(
                    block,
                    context,
                    type_name=type_name,
                    properties=properties,
                    structs=structs,
                )
            if had_previous:
                context[item_name] = previous
            else:
                context.pop(item_name, None)
            index = next_index
            continue
        if _execute_index_assignment(
            line,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        ):
            index += 1
            continue
        _eval_template_expression(
            line,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        index += 1


def _collect_runtime_style_if_blocks(lines: list[str], start: int) -> tuple[list[str], list[str], int]:
    then_block: list[str] = []
    else_block: list[str] = []
    current = then_block
    index = start
    depth = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.endswith("{"):
            depth += 1
        if stripped == "}" and depth == 0:
            return then_block, else_block, index + 1
        if stripped == "} else {" and depth == 0:
            current = else_block
            index += 1
            continue
        if stripped == "}":
            depth -= 1
        current.append(lines[index])
        index += 1
    raise TemplateExpansionError("Unterminated compile-time if block")


def _collect_runtime_style_block(lines: list[str], start: int) -> tuple[list[str], int]:
    block: list[str] = []
    index = start
    depth = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.endswith("{"):
            depth += 1
        if stripped == "}" and depth == 0:
            return block, index + 1
        if stripped == "}":
            depth -= 1
        block.append(lines[index])
        index += 1
    raise TemplateExpansionError("Unterminated compile-time block")


def _parse_compile_time_for(line: str) -> tuple[str, str]:
    text = line.removeprefix("for ").strip()
    if text.endswith("{"):
        text = text[:-1].strip()
    match = re.match(r"(?P<source>.+)\s+as\s+(?P<item>[A-Za-z_][A-Za-z0-9_]*)$", text)
    if match is not None:
        return match.group("source").strip(), match.group("item")
    match = re.match(r"(?P<item>[A-Za-z_][A-Za-z0-9_]*)\s+in\s+(?P<source>.+)$", text)
    if match is not None:
        return match.group("source").strip(), match.group("item")
    raise TemplateExpansionError("Expected compile-time 'for <expression> as <name> {'")


def _execute_index_assignment(
    line: str,
    context: dict[str, object],
    *,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, _TypeShape],
) -> bool:
    if "=" not in line or "==" in line or "!=" in line or ">=" in line or "<=" in line:
        return False
    target_source, value_source = line.split("=", 1)
    target_source = target_source.strip()
    value_source = value_source.strip()
    if not target_source.endswith("]") or "[" not in target_source:
        return False
    receiver_source, index_source = target_source.rsplit("[", 1)
    index_source = index_source[:-1]
    receiver = _eval_template_expression(
        receiver_source,
        context,
        type_name=type_name,
        properties=properties,
        structs=structs,
    )
    index = _eval_template_expression(
        index_source,
        context,
        type_name=type_name,
        properties=properties,
        structs=structs,
    )
    value = _eval_template_expression(
        value_source,
        context,
        type_name=type_name,
        properties=properties,
        structs=structs,
    )
    if isinstance(receiver, dict):
        receiver[index] = value
        return True
    if isinstance(receiver, list) and isinstance(index, int):
        receiver[index] = value
        return True
    raise TemplateExpansionError("Unsupported compile-time index assignment target")


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
        if stripped == "#{" or stripped.startswith("#for ") or stripped.startswith("#if "):
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
    structs: dict[str, _TypeShape],
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
    structs: dict[str, _TypeShape],
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
    structs: dict[str, _TypeShape],
) -> object:
    if isinstance(expression, IdentifierExpression):
        if expression.name in context:
            return context[expression.name]
        raise TemplateExpansionError(f"Unknown compile-time value '{expression.name}'")
    if isinstance(expression, AssignmentExpression):
        value = _eval_expression(
            expression.value,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        _assign_template_target(
            expression.target,
            value,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        return value
    if isinstance(expression, BinaryExpression):
        left = _eval_expression(
            expression.left,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        right = _eval_expression(
            expression.right,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        return _eval_binary(expression.operator, left, right)
    if isinstance(expression, UnaryExpression):
        value = _eval_expression(
            expression.operand,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        if expression.operator is TokenKind.BANG or expression.operator is TokenKind.NOT:
            return not bool(value)
        if expression.operator is TokenKind.MINUS:
            return -value
        raise TemplateExpansionError(f"Unsupported compile-time unary operator '{expression.operator.value}'")
    if isinstance(expression, MemberExpression):
        receiver = _eval_expression(
            expression.receiver,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        return _eval_member(receiver, expression.member, structs)
    if isinstance(expression, IndexExpression):
        receiver = _eval_expression(
            expression.receiver,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        index = _eval_expression(
            expression.index,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        if not isinstance(index, (int, str)):
            raise TemplateExpansionError("Template index must be an Int or String literal")
        if not isinstance(receiver, (tuple, list, dict)):
            raise TemplateExpansionError("Template index receiver is not indexable")
        try:
            return receiver[index]
        except (IndexError, KeyError) as exc:
            raise TemplateExpansionError("Template index is out of bounds") from exc
    if isinstance(expression, BulkCallExpression):
        receiver = _eval_expression(
            expression.callee,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        if len(expression.arguments) != 1:
            raise TemplateExpansionError("Template index expects one argument")
        index = _eval_expression(
            expression.arguments[0],
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        if not isinstance(index, (int, str)):
            raise TemplateExpansionError("Template index must be an Int or String literal")
        if not isinstance(receiver, (tuple, list, dict)):
            raise TemplateExpansionError("Template index receiver is not indexable")
        try:
            return receiver[index]
        except (IndexError, KeyError) as exc:
            raise TemplateExpansionError("Template index is out of bounds") from exc
    if isinstance(expression, LiteralExpression):
        return expression.value
    if isinstance(expression, ArrayLiteralExpression):
        return [
            _eval_expression(
                item,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            for item in expression.elements
        ]
    if isinstance(expression, CallExpression):
        arguments = [
            _eval_expression(
                argument,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
            for argument in expression.arguments
        ]
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
                arguments,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
        raise TemplateExpansionError("Only member calls are supported in template expressions")
    raise TemplateExpansionError(f"Unsupported template expression '{type(expression).__name__}'")


def _assign_template_target(
    target: Expression,
    value: object,
    context: dict[str, object],
    *,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, _TypeShape],
) -> None:
    if isinstance(target, IdentifierExpression):
        context[target.name] = value
        return
    if isinstance(target, MemberExpression):
        receiver = _eval_expression(
            target.receiver,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        if isinstance(receiver, SimpleNamespace):
            setattr(receiver, target.member, value)
            return
    if isinstance(target, IndexExpression):
        receiver = _eval_expression(
            target.receiver,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        index = _eval_expression(
            target.index,
            context,
            type_name=type_name,
            properties=properties,
            structs=structs,
        )
        if isinstance(receiver, dict):
            receiver[index] = value
            return
        if isinstance(receiver, list) and isinstance(index, int):
            receiver[index] = value
            return
    raise TemplateExpansionError("Unsupported compile-time assignment target")


def _eval_binary(operator: TokenKind, left: object, right: object) -> object:
    if operator is TokenKind.EQUAL_EQUAL:
        return left == right
    if operator is TokenKind.BANG_EQUAL:
        return left != right
    if operator is TokenKind.PLUS:
        return left + right
    if operator is TokenKind.MINUS:
        return left - right
    if operator is TokenKind.STAR:
        return left * right
    if operator is TokenKind.SLASH:
        return left / right
    if operator is TokenKind.GREATER:
        return left > right
    if operator is TokenKind.GREATER_EQUAL:
        return left >= right
    if operator is TokenKind.LESS:
        return left < right
    if operator is TokenKind.LESS_EQUAL:
        return left <= right
    raise TemplateExpansionError(f"Unsupported compile-time binary operator '{operator.value}'")


def _eval_member(receiver: object, member: str, structs: dict[str, _TypeShape]) -> object:
    if isinstance(receiver, SimpleNamespace):
        if hasattr(receiver, member):
            return getattr(receiver, member)
        raise TemplateExpansionError(f"Unknown compile-time state member '{member}'")
    if isinstance(receiver, _TypeInfo) and member == "properties":
        return receiver.properties
    if isinstance(receiver, _TypeInfo) and member == "fields":
        return receiver.properties
    if isinstance(receiver, _TypeInfo) and member == "constructor":
        if receiver.constructor is None:
            raise TemplateExpansionError(f"Type '{receiver.name}' has no reflected constructor")
        return receiver.constructor
    if isinstance(receiver, _TypeInfo) and member == "isStruct":
        return receiver.is_struct
    if isinstance(receiver, _TypeInfo) and member == "isClass":
        return receiver.is_class
    if isinstance(receiver, _TypeInfo) and member == "isInterface":
        return receiver.is_interface
    if isinstance(receiver, _TypeInfo) and member == "implementations":
        return receiver.implementations
    if isinstance(receiver, _TypeInfo) and member == "arguments":
        return receiver.arguments
    if isinstance(receiver, _TypeInfo) and member == "isArray":
        return receiver.is_array
    if isinstance(receiver, _TypeInfo) and member == "isNullable":
        return receiver.is_nullable
    if isinstance(receiver, _TypeInfo) and member == "isString":
        return receiver.name == "String"
    if isinstance(receiver, _TypeInfo) and member == "isInt":
        return receiver.name == "Int"
    if isinstance(receiver, _TypeInfo) and member == "isBool":
        return receiver.name == "Bool"
    if isinstance(receiver, _TypeInfo) and member == "isSimple":
        return receiver.name in {"String", "Int", "Bool"}
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
    if isinstance(receiver, _ConstructorInfo) and member == "parameters":
        return receiver.parameters
    if isinstance(receiver, _ParameterInfo):
        if member == "name":
            return receiver.name
        if member == "type":
            return receiver.type
        if member == "separator":
            return receiver.separator
        if member == "ownership":
            return receiver.ownership
        if member == "movePrefix":
            return receiver.move_prefix
    if isinstance(receiver, _ImplementationInfo):
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
    arguments: list[object],
    context: dict[str, object],
    *,
    type_name: str | None,
    properties: tuple[_Property, ...],
    structs: dict[str, _TypeShape],
) -> object:
    if isinstance(receiver, _ReflectionClass) and member == "type":
        if len(type_arguments) != 1:
            raise TemplateExpansionError("Reflection.type expects one type argument")
        reflected_type = _resolve_type_argument(type_arguments[0], context, type_name)
        if reflected_type is None:
            raise TemplateExpansionError("Cannot resolve Reflection.type argument")
        return _type_info_for(reflected_type, structs)
    if isinstance(receiver, _ReflectionClass) and member == "construct":
        if len(type_arguments) != 1:
            raise TemplateExpansionError("Reflection.construct expects one type argument")
        reflected_type = _resolve_type_argument(type_arguments[0], context, type_name)
        if reflected_type is None:
            raise TemplateExpansionError("Cannot resolve Reflection.construct argument")
        return _constructor_expression(reflected_type, structs, context)
    if isinstance(receiver, _CompilerClass) and member == "error":
        if len(arguments) != 1:
            raise TemplateExpansionError("Compiler.error expects one message")
        message = str(arguments[0])
        if "#{" in message:
            message = _expand_template_line(
                message,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
        raise TemplateExpansionError(message)
    if isinstance(receiver, _CompilerClass) and member == "warning":
        if len(arguments) != 1:
            raise TemplateExpansionError("Compiler.warning expects one message")
        message = str(arguments[0])
        if "#{" in message:
            message = _expand_template_line(
                message,
                context,
                type_name=type_name,
                properties=properties,
                structs=structs,
            )
        receiver.warnings.append(message)
        return None
    if isinstance(receiver, _GraphClass) and member == "findCycle":
        if len(arguments) != 1 or not isinstance(arguments[0], dict):
            raise TemplateExpansionError("Graph.findCycle expects a Dict<String, Array<String>>")
        return _find_cycle(arguments[0])
    if isinstance(receiver, list) and member == "join":
        separator = str(arguments[0]) if arguments else ""
        return separator.join(str(item) for item in receiver)
    if isinstance(receiver, list) and member == "add":
        if len(arguments) != 1:
            raise TemplateExpansionError("Array.add expects one value")
        receiver.append(arguments[0])
        return None
    if isinstance(receiver, dict) and member == "contains":
        if len(arguments) != 1:
            raise TemplateExpansionError("Dict.contains expects one key")
        return arguments[0] in receiver
    if isinstance(receiver, dict) and member == "add":
        if len(arguments) != 2:
            raise TemplateExpansionError("Dict.add expects key and value")
        receiver[arguments[0]] = arguments[1]
        return None
    raise TemplateExpansionError(f"Unknown compile-time call '{member}'")


def _constructor_expression(
    type_name: str,
    structs: dict[str, _TypeShape],
    context: dict[str, object],
) -> str:
    info = _type_info_for(type_name, structs)
    if info.constructor is None:
        raise TemplateExpansionError(f"Type '{type_name}' has no reflected constructor")
    arguments: list[str] = []
    for parameter in info.constructor.parameters:
        if parameter.type.is_simple:
            raise TemplateExpansionError(
                f"Cannot auto-resolve simple constructor parameter '{parameter.name}' for {type_name}"
            )
        state_object = context.get("state")
        if isinstance(state_object, SimpleNamespace):
            defs = getattr(state_object, "defs", {})
            if isinstance(defs, dict) and parameter.type.name not in defs:
                raise TemplateExpansionError(f"Missing dependency for {type_name}: {parameter.type.name}")
        arguments.append(parameter.move_prefix + _constructor_expression(parameter.type.name, structs, context))
    return f"{type_name}.new(" + ", ".join(arguments) + ")"


def _find_cycle(graph: dict[object, object]) -> list[str] | None:
    visited: set[str] = set()
    active: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in active:
            return active[active.index(node) :] + [node]
        if node in visited:
            return None
        visited.add(node)
        active.append(node)
        neighbors = graph.get(node, [])
        if not isinstance(neighbors, (list, tuple)):
            neighbors = []
        for neighbor in neighbors:
            cycle = visit(str(neighbor))
            if cycle is not None:
                return cycle
        active.pop()
        return None

    for key in graph:
        cycle = visit(str(key))
        if cycle is not None:
            return cycle
    return None


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
    structs: dict[str, _TypeShape],
) -> _TypeInfo:
    if type_name.endswith("?"):
        inner_name = type_name[:-1]
        return _TypeInfo(
            type_name,
            (),
            None,
            (),
            is_nullable=True,
            inner_type=_type_info_for(inner_name, structs),
        )
    if type_name.endswith("[]"):
        element_name = type_name[:-2]
        return _TypeInfo(
            type_name,
            (),
            None,
            (),
            is_array=True,
            element_name=element_name,
            element_type=_type_info_for(element_name, structs),
        )
    base_name, argument_names = _split_type_arguments(type_name)
    short_name = base_name.rsplit(".", 1)[-1]
    shape = structs.get(short_name)
    if shape is None:
        return _TypeInfo(
            type_name,
            (),
            arguments=tuple(_type_info_for(argument, structs) for argument in argument_names),
        )
    constructor = _ConstructorInfo(
        tuple(
            _ParameterInfo(
                parameter.name,
                _type_info_shallow(parameter.type, structs),
                "" if index == 0 else ",",
                parameter.ownership,
                "move " if parameter.ownership == "take" else "",
            )
            for index, parameter in enumerate(shape.constructor_parameters)
        )
    )
    implementations = tuple(
        _ImplementationInfo(
            candidate_name,
            _type_info_for(candidate_name, structs),
            "" if index == 0 else ",",
        )
        for index, candidate_name in enumerate(
            name
            for name, candidate in structs.items()
            if candidate.is_class and short_name in {impl.rsplit(".", 1)[-1] for impl in candidate.implements}
        )
    )
    return _TypeInfo(
        type_name,
        tuple(
            _PropertyInfo(
                property_.name,
                _type_info_for(property_.type, structs),
                "" if index == 0 else ",",
            )
            for index, property_ in enumerate(shape.properties)
        ),
        constructor,
        implementations,
        tuple(_type_info_for(argument, structs) for argument in argument_names),
        is_struct=shape.is_struct,
        is_class=shape.is_class,
        is_interface=shape.is_interface,
    )


def _type_info_shallow(
    type_name: str,
    structs: dict[str, _TypeShape],
) -> _TypeInfo:
    if type_name.endswith("?"):
        inner_name = type_name[:-1]
        return _TypeInfo(
            type_name,
            (),
            None,
            (),
            (),
            is_nullable=True,
            inner_type=_type_info_shallow(inner_name, structs),
        )
    if type_name.endswith("[]"):
        element_name = type_name[:-2]
        return _TypeInfo(
            type_name,
            (),
            None,
            (),
            (),
            is_array=True,
            element_name=element_name,
            element_type=_type_info_shallow(element_name, structs),
        )
    base_name, argument_names = _split_type_arguments(type_name)
    short_name = base_name.rsplit(".", 1)[-1]
    shape = structs.get(short_name)
    return _TypeInfo(
        type_name,
        (),
        None,
        (),
        tuple(_type_info_shallow(argument, structs) for argument in argument_names),
        is_struct=bool(shape and shape.is_struct),
        is_class=bool(shape and shape.is_class),
        is_interface=bool(shape and shape.is_interface),
    )


def _split_type_arguments(type_name: str) -> tuple[str, tuple[str, ...]]:
    if "<" not in type_name or not type_name.endswith(">"):
        return type_name, ()
    start = type_name.index("<")
    inner = type_name[start + 1 : -1]
    arguments: list[str] = []
    depth = 0
    cursor = 0
    for index, char in enumerate(inner):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            arguments.append(inner[cursor:index].strip())
            cursor = index + 1
    tail = inner[cursor:].strip()
    if tail:
        arguments.append(tail)
    return type_name[:start], tuple(arguments)


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
