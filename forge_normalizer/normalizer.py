"""Normalize Forge AST programs before semantic analysis and lowering."""

from __future__ import annotations

from dataclasses import dataclass, replace

from forge_parser import (
    AssignmentExpression,
    BlockStatement,
    ClassDeclaration,
    Declaration,
    ExpressionStatement,
    FunctionDeclaration,
    IdentifierExpression,
    MemberExpression,
    Parameter,
    Program,
    Statement,
    ThisExpression,
    VariableDeclaration,
)


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """The result of AST normalization."""

    program: Program


def normalize(program: Program) -> Program:
    """Return a normalized copy of *program*.

    Normalization preserves parsed nodes where possible and creates new nodes only
    for compiler-synthesized declarations.
    """

    return normalize_program(program).program


def normalize_program(program: Program) -> NormalizationResult:
    """Run all AST normalization passes for *program*."""

    return NormalizationResult(_Normalizer().run(program))


class _Normalizer:
    def run(self, program: Program) -> Program:
        return replace(
            program,
            declarations=self._normalize_items(program.declarations),
        )

    def _normalize_items(
        self, items: tuple[Declaration | Statement, ...]
    ) -> tuple[Declaration | Statement, ...]:
        return tuple(self._normalize_item(item) for item in items)

    def _normalize_item(self, item: Declaration | Statement) -> Declaration | Statement:
        if isinstance(item, ClassDeclaration):
            return self._normalize_class(item)
        return item

    def _normalize_class(self, declaration: ClassDeclaration) -> ClassDeclaration:
        members = self._normalize_items(declaration.members)
        if declaration.kind != "class":
            return replace(declaration, members=members)
        members = self._promote_constructor_parameters(members)
        if not self._has_user_constructor(members):
            members = (*members, self._default_constructor(declaration))
        return replace(declaration, members=members)

    def _promote_constructor_parameters(
        self, members: tuple[Declaration | Statement, ...]
    ) -> tuple[Declaration | Statement, ...]:
        promoted_fields: list[VariableDeclaration] = []
        normalized_members: list[Declaration | Statement] = []
        for member in members:
            if isinstance(member, FunctionDeclaration) and member.kind == "new":
                member, fields = self._normalize_constructor_promotions(member)
                promoted_fields.extend(fields)
            normalized_members.append(member)
        return (*promoted_fields, *normalized_members)

    def _normalize_constructor_promotions(
        self, constructor: FunctionDeclaration
    ) -> tuple[FunctionDeclaration, tuple[VariableDeclaration, ...]]:
        promoted_parameters = tuple(
            parameter for parameter in constructor.parameters if parameter.modifiers
        )
        if not promoted_parameters:
            return constructor, ()

        fields = tuple(self._promoted_field(parameter) for parameter in promoted_parameters)
        parameters = tuple(
            replace(parameter, modifiers=())
            if parameter.modifiers
            else parameter
            for parameter in constructor.parameters
        )
        body = constructor.body
        if isinstance(body, BlockStatement):
            assignments = tuple(
                self._promoted_assignment(parameter)
                for parameter in promoted_parameters
            )
            body = replace(body, statements=(*assignments, *body.statements))
        return replace(constructor, parameters=parameters, body=body), fields

    def _promoted_field(self, parameter: Parameter) -> VariableDeclaration:
        return VariableDeclaration(
            parameter.location,
            parameter.name,
            None,
            False,
            parameter.type,
            parameter.modifiers,
            parameter.ownership,
        )

    def _promoted_assignment(self, parameter: Parameter) -> ExpressionStatement:
        return ExpressionStatement(
            parameter.location,
            AssignmentExpression(
                parameter.location,
                MemberExpression(
                    parameter.location,
                    ThisExpression(parameter.location),
                    parameter.name,
                ),
                IdentifierExpression(parameter.location, parameter.name),
            ),
        )

    def _has_user_constructor(
        self, members: tuple[Declaration | Statement, ...]
    ) -> bool:
        return any(
            isinstance(member, FunctionDeclaration) and member.kind == "new"
            for member in members
        )

    def _default_constructor(self, declaration: ClassDeclaration) -> FunctionDeclaration:
        return FunctionDeclaration(
            declaration.location,
            "new",
            (),
            None,
            (),
            BlockStatement(declaration.location, ()),
            ("public",),
            "new",
        )
