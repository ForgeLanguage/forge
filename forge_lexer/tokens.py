"""Token definitions for Forge lexical analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokenKind(str, Enum):
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name.lower()

    EOF = auto()
    IDENTIFIER = auto()
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()

    CLASS = auto()
    DATA = auto()
    ENUM = auto()
    STRUCT = auto()
    TRAIT = auto()
    INTERFACE = auto()
    COMPOSE = auto()
    PUBLIC = auto()
    INTERNAL = auto()
    PRIVATE = auto()
    STATIC = auto()
    NATIVE = auto()
    FUNC = auto()
    GENERATOR = auto()
    NEW = auto()
    CONST = auto()
    LAZY = auto()
    LET = auto()
    IF = auto()
    ELSE = auto()
    ELSEIF = auto()
    SWITCH = auto()
    DEFAULT = auto()
    FOR = auto()
    AS = auto()
    WHILE = auto()
    DO = auto()
    BREAK = auto()
    NEXT = auto()
    RETURN = auto()
    YIELD = auto()
    TRUE = auto()
    FALSE = auto()
    NULL = auto()
    THIS = auto()
    SELF = auto()
    USES = auto()
    USE = auto()
    IMPLEMENTS = auto()
    REQUIRES = auto()
    FROM = auto()
    IN = auto()
    NOT = auto()
    CATCH = auto()
    FORWARD = auto()
    CONTINUE = auto()
    ASYNC = auto()
    AWAIT = auto()
    TASK = auto()
    LOCK = auto()
    EXCLUSIVE = auto()
    TAKE = auto()
    BORROW = auto()
    MOVE = auto()
    TERMINATE = auto()
    TEMPLATE = auto()
    PRINT = auto()

    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    LEFT_BRACE = auto()
    RIGHT_BRACE = auto()
    LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto()
    COMMA = auto()
    DOT = auto()
    COLON = auto()
    AT = auto()
    SEMICOLON = auto()

    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    BANG = auto()
    QUESTION = auto()
    EQUAL = auto()
    LESS = auto()
    GREATER = auto()
    AMPERSAND = auto()
    PIPE = auto()

    EQUAL_EQUAL = auto()
    BANG_EQUAL = auto()
    LESS_EQUAL = auto()
    GREATER_EQUAL = auto()
    AND_AND = auto()
    OR_OR = auto()
    ARROW = auto()
    FAT_ARROW = auto()
    APPLY = auto()
    RANGE = auto()
    NULL_SAFE_DOT = auto()
    NULL_COALESCE = auto()
    PLUS_EQUAL = auto()
    MINUS_EQUAL = auto()
    STAR_EQUAL = auto()
    SLASH_EQUAL = auto()
    PERCENT_EQUAL = auto()
    PLUS_PLUS = auto()
    MINUS_MINUS = auto()


KEYWORDS: dict[str, TokenKind] = {
    "as": TokenKind.AS,
    "async": TokenKind.ASYNC,
    "await": TokenKind.AWAIT,
    "break": TokenKind.BREAK,
    "borrow": TokenKind.BORROW,
    "catch": TokenKind.CATCH,
    "class": TokenKind.CLASS,
    "compose": TokenKind.COMPOSE,
    "const": TokenKind.CONST,
    "continue": TokenKind.CONTINUE,
    "data": TokenKind.DATA,
    "default": TokenKind.DEFAULT,
    "do": TokenKind.DO,
    "else": TokenKind.ELSE,
    "elseif": TokenKind.ELSEIF,
    "enum": TokenKind.ENUM,
    "exclusive": TokenKind.EXCLUSIVE,
    "false": TokenKind.FALSE,
    "for": TokenKind.FOR,
    "forward": TokenKind.FORWARD,
    "from": TokenKind.FROM,
    "func": TokenKind.FUNC,
    "generator": TokenKind.GENERATOR,
    "if": TokenKind.IF,
    "implements": TokenKind.IMPLEMENTS,
    "in": TokenKind.IN,
    "interface": TokenKind.INTERFACE,
    "internal": TokenKind.INTERNAL,
    "let": TokenKind.LET,
    "lazy": TokenKind.LAZY,
    "lock": TokenKind.LOCK,
    "new": TokenKind.NEW,
    "next": TokenKind.NEXT,
    "not": TokenKind.NOT,
    "null": TokenKind.NULL,
    "print": TokenKind.PRINT,
    "private": TokenKind.PRIVATE,
    "public": TokenKind.PUBLIC,
    "requires": TokenKind.REQUIRES,
    "return": TokenKind.RETURN,
    "self": TokenKind.SELF,
    "static": TokenKind.STATIC,
    "struct": TokenKind.STRUCT,
    "switch": TokenKind.SWITCH,
    "take": TokenKind.TAKE,
    "task": TokenKind.TASK,
    "move": TokenKind.MOVE,
    "native": TokenKind.NATIVE,
    "terminate": TokenKind.TERMINATE,
    "template": TokenKind.TEMPLATE,
    "this": TokenKind.THIS,
    "trait": TokenKind.TRAIT,
    "true": TokenKind.TRUE,
    "use": TokenKind.USE,
    "uses": TokenKind.USES,
    "while": TokenKind.WHILE,
    "yield": TokenKind.YIELD,
}


@dataclass(frozen=True, slots=True)
class SourceLocation:
    line: int
    column: int
    offset: int
    source_name: str | None = None

    def format(self) -> str:
        if self.source_name:
            return f"{self.source_name}:{self.line}:{self.column}"
        return f"line {self.line}, column {self.column}"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    lexeme: str
    location: SourceLocation
    literal: object | None = None


class LexerError(SyntaxError):
    """Raised when Forge source cannot be tokenized."""

    def __init__(self, message: str, location: SourceLocation) -> None:
        super().__init__(f"{message} at {location.format()}")
        self.message = message
        self.location = location
