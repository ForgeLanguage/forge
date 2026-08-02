import unittest

from forge_lexer import KEYWORDS, LexerError, TokenKind, lex


def kinds(source: str) -> list[TokenKind]:
    return [token.kind for token in lex(source)]


class LexerTests(unittest.TestCase):
    def test_hello_world_tokens(self) -> None:
        source = '''
class

public static func main(args: String[]): Void
{
    print "Hello, World!"
}
'''

        self.assertEqual(
            kinds(source),
            [
                TokenKind.CLASS,
                TokenKind.PUBLIC,
                TokenKind.STATIC,
                TokenKind.FUNC,
                TokenKind.IDENTIFIER,
                TokenKind.LEFT_PAREN,
                TokenKind.IDENTIFIER,
                TokenKind.COLON,
                TokenKind.IDENTIFIER,
                TokenKind.LEFT_BRACKET,
                TokenKind.RIGHT_BRACKET,
                TokenKind.RIGHT_PAREN,
                TokenKind.COLON,
                TokenKind.IDENTIFIER,
                TokenKind.LEFT_BRACE,
                TokenKind.PRINT,
                TokenKind.STRING,
                TokenKind.RIGHT_BRACE,
                TokenKind.EOF,
            ],
        )

    def test_all_punctuation_tokens(self) -> None:
        self.assertEqual(
            kinds("( ) { } [ ] , . : @ ;"),
            [
                TokenKind.LEFT_PAREN,
                TokenKind.RIGHT_PAREN,
                TokenKind.LEFT_BRACE,
                TokenKind.RIGHT_BRACE,
                TokenKind.LEFT_BRACKET,
                TokenKind.RIGHT_BRACKET,
                TokenKind.COMMA,
                TokenKind.DOT,
                TokenKind.COLON,
                TokenKind.AT,
                TokenKind.SEMICOLON,
                TokenKind.EOF,
            ],
        )

    def test_template_is_keyword(self) -> None:
        self.assertEqual(
            kinds("template func parse"),
            [
                TokenKind.TEMPLATE,
                TokenKind.FUNC,
                TokenKind.IDENTIFIER,
                TokenKind.EOF,
            ],
        )

    def test_operators_use_maximal_munch(self) -> None:
        source = (
            "a == b != c <= d >= e && f || g => h -> i <- j .. k ?. l ?? m "
            "n += o -= p *= q /= r %= s ++ t -- u "
            "+ n - o * p / q % r ! s = t < u > v & w | x ? y . z"
        )

        self.assertEqual(
            kinds(source),
            [
                TokenKind.IDENTIFIER,
                TokenKind.EQUAL_EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.BANG_EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.LESS_EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.GREATER_EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.AND_AND,
                TokenKind.IDENTIFIER,
                TokenKind.OR_OR,
                TokenKind.IDENTIFIER,
                TokenKind.FAT_ARROW,
                TokenKind.IDENTIFIER,
                TokenKind.ARROW,
                TokenKind.IDENTIFIER,
                TokenKind.APPLY,
                TokenKind.IDENTIFIER,
                TokenKind.RANGE,
                TokenKind.IDENTIFIER,
                TokenKind.NULL_SAFE_DOT,
                TokenKind.IDENTIFIER,
                TokenKind.NULL_COALESCE,
                TokenKind.IDENTIFIER,
                TokenKind.IDENTIFIER,
                TokenKind.PLUS_EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.MINUS_EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.STAR_EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.SLASH_EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.PERCENT_EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.PLUS_PLUS,
                TokenKind.IDENTIFIER,
                TokenKind.MINUS_MINUS,
                TokenKind.IDENTIFIER,
                TokenKind.PLUS,
                TokenKind.IDENTIFIER,
                TokenKind.MINUS,
                TokenKind.IDENTIFIER,
                TokenKind.STAR,
                TokenKind.IDENTIFIER,
                TokenKind.SLASH,
                TokenKind.IDENTIFIER,
                TokenKind.PERCENT,
                TokenKind.IDENTIFIER,
                TokenKind.BANG,
                TokenKind.IDENTIFIER,
                TokenKind.EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.LESS,
                TokenKind.IDENTIFIER,
                TokenKind.GREATER,
                TokenKind.IDENTIFIER,
                TokenKind.AMPERSAND,
                TokenKind.IDENTIFIER,
                TokenKind.PIPE,
                TokenKind.IDENTIFIER,
                TokenKind.QUESTION,
                TokenKind.IDENTIFIER,
                TokenKind.DOT,
                TokenKind.IDENTIFIER,
                TokenKind.EOF,
            ],
        )

    def test_every_declared_keyword_is_tokenized_as_keyword(self) -> None:
        source = " ".join(KEYWORDS)
        token_kinds = kinds(source)

        self.assertEqual(token_kinds[:-1], [KEYWORDS[word] for word in KEYWORDS])
        self.assertEqual(token_kinds[-1], TokenKind.EOF)

    def test_keyword_prefixes_remain_identifiers(self) -> None:
        tokens = lex(
            "classifier interfaceName asyncFetch nullable nullValue useCase taskRunner"
        )

        self.assertTrue(all(token.kind is TokenKind.IDENTIFIER for token in tokens[:-1]))
        self.assertEqual(
            [token.lexeme for token in tokens[:-1]],
            [
                "classifier",
                "interfaceName",
                "asyncFetch",
                "nullable",
                "nullValue",
                "useCase",
                "taskRunner",
            ],
        )

    def test_literals_and_comments(self) -> None:
        tokens = lex(
            r'''
const pi = 3.14
const count = 1_000
const text = "Forge\n\u0021" // comment
/* block
   comment */
'''
        )

        self.assertEqual(
            [(token.kind, token.literal) for token in tokens if token.literal is not None],
            [
                (TokenKind.FLOAT, 3.14),
                (TokenKind.INTEGER, 1000),
                (TokenKind.STRING, "Forge\n!"),
            ],
        )

    def test_number_literal_shapes(self) -> None:
        tokens = lex("0 42 1_000 3.14 6.02e23 1e-9 2E+8 1.e2")

        self.assertEqual(
            [(token.kind, token.lexeme, token.literal) for token in tokens[:-1]],
            [
                (TokenKind.INTEGER, "0", 0),
                (TokenKind.INTEGER, "42", 42),
                (TokenKind.INTEGER, "1_000", 1000),
                (TokenKind.FLOAT, "3.14", 3.14),
                (TokenKind.FLOAT, "6.02e23", 6.02e23),
                (TokenKind.FLOAT, "1e-9", 1e-9),
                (TokenKind.FLOAT, "2E+8", 2e8),
                (TokenKind.INTEGER, "1", 1),
                (TokenKind.DOT, ".", None),
                (TokenKind.IDENTIFIER, "e2", None),
            ],
        )

    def test_string_escape_sequences(self) -> None:
        token = lex(r'"quote: \" slash: \\ tab:\t nul:\0"')[0]

        self.assertEqual(token.kind, TokenKind.STRING)
        self.assertEqual(token.literal, 'quote: " slash: \\ tab:\t nul:\0')

    def test_unicode_identifiers_are_supported(self) -> None:
        tokens = lex("const имя = значение_1")

        self.assertEqual(
            [(token.kind, token.lexeme) for token in tokens[:-1]],
            [
                (TokenKind.CONST, "const"),
                (TokenKind.IDENTIFIER, "имя"),
                (TokenKind.EQUAL, "="),
                (TokenKind.IDENTIFIER, "значение_1"),
            ],
        )

    def test_underscore_pipe_hole_is_an_identifier(self) -> None:
        tokens = lex('format("Hello, ", _, "!") <- name')
        pairs = [(token.kind, token.lexeme) for token in tokens]

        self.assertIn((TokenKind.IDENTIFIER, "_"), pairs)
        self.assertIn(TokenKind.APPLY, [token.kind for token in tokens])

    def test_line_and_block_comments_are_skipped_and_update_locations(self) -> None:
        tokens = lex("class // one\n/* two\nthree */\n  func")

        self.assertEqual(
            [token.kind for token in tokens],
            [TokenKind.CLASS, TokenKind.FUNC, TokenKind.EOF],
        )
        self.assertEqual(tokens[1].location.line, 4)
        self.assertEqual(tokens[1].location.column, 3)

    def test_keywords_from_spec_examples(self) -> None:
        source = """
@multidef
trait Greeter { requires Logger }
class App
uses Greeter
implements Printable
public async fetchUser(id: Int): User, NetworkError! {
    forward catch await Http.get("/users/" + id) {
        error: NetworkError => User.guest()
        default => null
    }
}
"""

        token_kinds = set(kinds(source))
        self.assertTrue(
            {
                TokenKind.AT,
                TokenKind.TRAIT,
                TokenKind.REQUIRES,
                TokenKind.CLASS,
                TokenKind.USES,
                TokenKind.IMPLEMENTS,
                TokenKind.PUBLIC,
                TokenKind.ASYNC,
                TokenKind.FORWARD,
                TokenKind.CATCH,
                TokenKind.AWAIT,
                TokenKind.DEFAULT,
                TokenKind.NULL,
            }
            <= token_kinds
        )

    def test_top_level_forms_from_specs(self) -> None:
        source = """
public enum Status {
    Pending,
    Done
}

data Box<T> {
    public value: T?
}

internal struct Point {
    public x: Int
    public y: Int
}

compose MyTraitsGroup {
    Greeter
    Logger
}
"""

        token_kinds = set(kinds(source))
        self.assertTrue(
            {
                TokenKind.PUBLIC,
                TokenKind.ENUM,
                TokenKind.DATA,
                TokenKind.STRUCT,
                TokenKind.COMPOSE,
                TokenKind.LESS,
                TokenKind.GREATER,
                TokenKind.QUESTION,
            }
            <= token_kinds
        )

    def test_function_application_mass_calls_generators_and_catch(self) -> None:
        source = """
const parsed = catch Int.parse generator[stringNumbers] {
    error: ParseError => continue
}

save[
    User.new generator[
        safeParse(filename)
    ]
]

print <- toUpper <- trim <- name
"""

        token_kinds = kinds(source)
        self.assertEqual(token_kinds.count(TokenKind.APPLY), 3)
        self.assertEqual(token_kinds.count(TokenKind.GENERATOR), 2)
        self.assertIn(TokenKind.CATCH, token_kinds)
        self.assertIn(TokenKind.CONTINUE, token_kinds)

    def test_control_flow_and_membership_example(self) -> None:
        source = """
for rows as row if row.isValid(),
    row as cell if cell.value > 0 {
    if cell not in ignored {
        next row
    } elseif cell == null {
        break
    } else {
        print cell
    }
}

do {
    print "tick"
} while true
"""

        token_kinds = kinds(source)
        self.assertEqual(token_kinds.count(TokenKind.FOR), 1)
        self.assertEqual(token_kinds.count(TokenKind.IF), 3)
        self.assertIn(TokenKind.NOT, token_kinds)
        self.assertIn(TokenKind.IN, token_kinds)
        self.assertIn(TokenKind.ELSEIF, token_kinds)
        self.assertIn(TokenKind.DO, token_kinds)
        self.assertIn(TokenKind.WHILE, token_kinds)

    def test_threads_lock_and_ownership_keywords(self) -> None:
        source = """
private func process(take file: File): Void, File! {
    forward file
}

consume(move file)

lock user {
    user.cache.set("x", "y")
}

exclusive terminate func dispose(): Void {
    return
}
"""

        token_kinds = set(kinds(source))
        self.assertTrue(
            {
                TokenKind.PRIVATE,
                TokenKind.TAKE,
                TokenKind.MOVE,
                TokenKind.FORWARD,
                TokenKind.LOCK,
                TokenKind.EXCLUSIVE,
                TokenKind.TERMINATE,
                TokenKind.RETURN,
            }
            <= token_kinds
        )

    def test_switch_and_declared_outcomes_example(self) -> None:
        source = """
public static switch classify(len: Int): String {
    len == 0 => "empty"
    len < 5 => "short"
    default => "long"
}

public static func parseInt(text: String): Int, ParseIssue! {
    yield 1
    return 2
}
"""

        token_kinds = kinds(source)
        self.assertIn(TokenKind.SWITCH, token_kinds)
        self.assertIn(TokenKind.DEFAULT, token_kinds)
        self.assertIn(TokenKind.FAT_ARROW, token_kinds)
        self.assertIn(TokenKind.BANG, token_kinds)
        self.assertIn(TokenKind.YIELD, token_kinds)

    def test_nullable_null_safe_and_coalescing_tokens(self) -> None:
        self.assertEqual(
            kinds('const city: String? = user?.address?.city ?? "Unknown"'),
            [
                TokenKind.CONST,
                TokenKind.IDENTIFIER,
                TokenKind.COLON,
                TokenKind.IDENTIFIER,
                TokenKind.QUESTION,
                TokenKind.EQUAL,
                TokenKind.IDENTIFIER,
                TokenKind.NULL_SAFE_DOT,
                TokenKind.IDENTIFIER,
                TokenKind.NULL_SAFE_DOT,
                TokenKind.IDENTIFIER,
                TokenKind.NULL_COALESCE,
                TokenKind.STRING,
                TokenKind.EOF,
            ],
        )

    def test_locations_are_one_based(self) -> None:
        tokens = lex("class\n  const name = \"Forge\"")

        const = tokens[1]
        self.assertIs(const.kind, TokenKind.CONST)
        self.assertEqual(const.location.line, 2)
        self.assertEqual(const.location.column, 3)

    def test_unterminated_string_reports_start_location(self) -> None:
        with self.assertRaises(LexerError) as error:
            lex('print "oops')

        self.assertEqual(error.exception.location.line, 1)
        self.assertEqual(error.exception.location.column, 7)

    def test_newline_inside_string_is_an_error(self) -> None:
        with self.assertRaises(LexerError) as error:
            lex('"first\nsecond"')

        self.assertEqual(error.exception.message, "Unterminated string literal")
        self.assertEqual(error.exception.location.line, 1)
        self.assertEqual(error.exception.location.column, 1)

    def test_unknown_escape_is_an_error(self) -> None:
        with self.assertRaises(LexerError) as error:
            lex(r'"bad \q"')

        self.assertEqual(error.exception.message, r"Unknown escape sequence \q")

    def test_invalid_unicode_escape_is_an_error(self) -> None:
        with self.assertRaises(LexerError) as error:
            lex(r'"bad \u12xz"')

        self.assertEqual(error.exception.message, "Invalid unicode escape")

    def test_unterminated_block_comment_reports_start_location(self) -> None:
        with self.assertRaises(LexerError) as error:
            lex("class\n  /* no end")

        self.assertEqual(error.exception.message, "Unterminated block comment")
        self.assertEqual(error.exception.location.line, 2)
        self.assertEqual(error.exception.location.column, 3)

    def test_unexpected_character_reports_location(self) -> None:
        with self.assertRaises(LexerError) as error:
            lex("class\n  $")

        self.assertEqual(error.exception.message, "Unexpected character '$'")
        self.assertEqual(error.exception.location.line, 2)
        self.assertEqual(error.exception.location.column, 3)


if __name__ == "__main__":
    unittest.main()
