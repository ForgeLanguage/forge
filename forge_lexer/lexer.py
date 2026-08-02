"""A hand-written lexer for the Forge language."""

from __future__ import annotations

from collections.abc import Iterator

from .tokens import KEYWORDS, LexerError, SourceLocation, Token, TokenKind


_SINGLE_CHAR_TOKENS: dict[str, TokenKind] = {
    "(": TokenKind.LEFT_PAREN,
    ")": TokenKind.RIGHT_PAREN,
    "{": TokenKind.LEFT_BRACE,
    "}": TokenKind.RIGHT_BRACE,
    "[": TokenKind.LEFT_BRACKET,
    "]": TokenKind.RIGHT_BRACKET,
    ",": TokenKind.COMMA,
    ":": TokenKind.COLON,
    "@": TokenKind.AT,
    ";": TokenKind.SEMICOLON,
    "+": TokenKind.PLUS,
    "-": TokenKind.MINUS,
    "*": TokenKind.STAR,
    "/": TokenKind.SLASH,
    "%": TokenKind.PERCENT,
    "!": TokenKind.BANG,
    "?": TokenKind.QUESTION,
    "=": TokenKind.EQUAL,
    "<": TokenKind.LESS,
    ">": TokenKind.GREATER,
    "&": TokenKind.AMPERSAND,
    "|": TokenKind.PIPE,
    ".": TokenKind.DOT,
}

_MULTI_CHAR_TOKENS: tuple[tuple[str, TokenKind], ...] = (
    ("==", TokenKind.EQUAL_EQUAL),
    ("!=", TokenKind.BANG_EQUAL),
    ("<=", TokenKind.LESS_EQUAL),
    (">=", TokenKind.GREATER_EQUAL),
    ("+=", TokenKind.PLUS_EQUAL),
    ("-=", TokenKind.MINUS_EQUAL),
    ("*=", TokenKind.STAR_EQUAL),
    ("/=", TokenKind.SLASH_EQUAL),
    ("%=", TokenKind.PERCENT_EQUAL),
    ("++", TokenKind.PLUS_PLUS),
    ("--", TokenKind.MINUS_MINUS),
    ("&&", TokenKind.AND_AND),
    ("||", TokenKind.OR_OR),
    ("->", TokenKind.ARROW),
    ("=>", TokenKind.FAT_ARROW),
    ("<-", TokenKind.APPLY),
    ("..", TokenKind.RANGE),
    ("?.", TokenKind.NULL_SAFE_DOT),
    ("??", TokenKind.NULL_COALESCE),
)

_ESCAPES: dict[str, str] = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "0": "\0",
}


class Lexer:
    """Tokenize Forge source code.

    The lexer deliberately stops at lexical concerns: it classifies keywords,
    identifiers, literals, punctuation, and operators, while preserving precise
    source locations for later parser and diagnostic layers.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self._length = len(source)
        self._start = 0
        self._current = 0
        self._line = 1
        self._column = 1
        self._start_location = SourceLocation(1, 1, 0)

    def __iter__(self) -> Iterator[Token]:
        return iter(self.tokenize())

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while not self._is_at_end():
            self._start = self._current
            self._start_location = self._location()
            token = self._scan_token()
            if token is not None:
                tokens.append(token)

        tokens.append(Token(TokenKind.EOF, "", self._location()))
        return tokens

    def _scan_token(self) -> Token | None:
        char = self._advance()

        if char in " \t\r":
            return None
        if char == "\n":
            return None

        if char == "/" and self._match("/"):
            self._skip_line_comment()
            return None
        if char == "/" and self._match("*"):
            self._skip_block_comment()
            return None

        if char == '"':
            return self._string()
        if char.isdigit():
            return self._number()
        if self._is_identifier_start(char):
            return self._identifier()

        for lexeme, kind in _MULTI_CHAR_TOKENS:
            if char == lexeme[0] and self.source.startswith(
                lexeme, self._start
            ):
                while self._current < self._start + len(lexeme):
                    self._advance()
                return self._make_token(kind)

        kind = _SINGLE_CHAR_TOKENS.get(char)
        if kind is not None:
            return self._make_token(kind)

        raise LexerError(f"Unexpected character {char!r}", self._start_location)

    def _identifier(self) -> Token:
        while self._is_identifier_part(self._peek()):
            self._advance()

        lexeme = self._lexeme()
        return self._make_token(KEYWORDS.get(lexeme, TokenKind.IDENTIFIER))

    def _number(self) -> Token:
        while self._peek().isdigit() or self._peek() == "_":
            self._advance()

        is_float = False
        if self._peek() == "." and self._peek_next().isdigit():
            is_float = True
            self._advance()
            while self._peek().isdigit() or self._peek() == "_":
                self._advance()

        if self._peek() in "eE" and self._starts_exponent():
            is_float = True
            self._advance()
            if self._peek() in "+-":
                self._advance()
            while self._peek().isdigit() or self._peek() == "_":
                self._advance()

        lexeme = self._lexeme()
        value_text = lexeme.replace("_", "")
        try:
            literal: int | float = float(value_text) if is_float else int(value_text)
        except ValueError as exc:
            raise LexerError("Invalid number literal", self._start_location) from exc
        return self._make_token(
            TokenKind.FLOAT if is_float else TokenKind.INTEGER,
            literal,
        )

    def _string(self) -> Token:
        value: list[str] = []
        while not self._is_at_end():
            char = self._advance()
            if char == '"':
                return self._make_token(TokenKind.STRING, "".join(value))
            if char == "\n":
                raise LexerError("Unterminated string literal", self._start_location)
            if char == "\\":
                value.append(self._escape_sequence())
            else:
                value.append(char)

        raise LexerError("Unterminated string literal", self._start_location)

    def _escape_sequence(self) -> str:
        if self._is_at_end():
            raise LexerError("Unterminated escape sequence", self._location())

        char = self._advance()
        if char == "u":
            digits = ""
            for _ in range(4):
                digit = self._peek()
                if not digit or digit.lower() not in "0123456789abcdef":
                    raise LexerError("Invalid unicode escape", self._location())
                digits += self._advance()
            return chr(int(digits, 16))

        escaped = _ESCAPES.get(char)
        if escaped is None:
            raise LexerError(f"Unknown escape sequence \\{char}", self._location())
        return escaped

    def _skip_line_comment(self) -> None:
        while self._peek() not in {"", "\n"}:
            self._advance()

    def _skip_block_comment(self) -> None:
        while not self._is_at_end():
            if self._peek() == "*" and self._peek_next() == "/":
                self._advance()
                self._advance()
                return
            self._advance()

        raise LexerError("Unterminated block comment", self._start_location)

    def _make_token(self, kind: TokenKind, literal: object | None = None) -> Token:
        return Token(kind, self._lexeme(), self._start_location, literal)

    def _lexeme(self) -> str:
        return self.source[self._start : self._current]

    def _advance(self) -> str:
        char = self.source[self._current]
        self._current += 1
        if char == "\n":
            self._line += 1
            self._column = 1
        else:
            self._column += 1
        return char

    def _match(self, expected: str) -> bool:
        if self._is_at_end() or self.source[self._current] != expected:
            return False
        self._advance()
        return True

    def _peek(self) -> str:
        if self._is_at_end():
            return ""
        return self.source[self._current]

    def _peek_next(self) -> str:
        next_index = self._current + 1
        if next_index >= self._length:
            return ""
        return self.source[next_index]

    def _starts_exponent(self) -> bool:
        next_index = self._current + 1
        if next_index < self._length and self.source[next_index] in "+-":
            next_index += 1
        return next_index < self._length and self.source[next_index].isdigit()

    def _is_at_end(self) -> bool:
        return self._current >= self._length

    def _location(self) -> SourceLocation:
        return SourceLocation(self._line, self._column, self._current)

    @staticmethod
    def _is_identifier_start(char: str) -> bool:
        return char == "_" or char.isalpha()

    @staticmethod
    def _is_identifier_part(char: str) -> bool:
        return char == "_" or char.isalpha() or char.isdigit()


def lex(source: str) -> list[Token]:
    """Return all tokens in *source*, including the final EOF token."""

    return Lexer(source).tokenize()
