#include "forge_runtime.h"
#include "std/Json/Json.h"
#include "std/Json/JsonIssue.h"
#include "std/Json/JsonValue.h"

#include <ctype.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    const char* cursor;
    const char* error;
} JsonParser;

static void json_skip_ws(JsonParser* parser) {
    while (isspace((unsigned char)*parser->cursor)) {
        parser->cursor += 1;
    }
}

static bool json_consume(JsonParser* parser, char expected) {
    json_skip_ws(parser);
    if (*parser->cursor != expected) {
        return false;
    }
    parser->cursor += 1;
    return true;
}

static bool json_parse_value(JsonParser* parser);

static bool json_parse_string_raw(JsonParser* parser) {
    if (*parser->cursor != '"') {
        parser->error = "expected string";
        return false;
    }
    parser->cursor += 1;
    while (*parser->cursor != '\0') {
        unsigned char ch = (unsigned char)*parser->cursor;
        if (ch == '"') {
            parser->cursor += 1;
            return true;
        }
        if (ch == '\\') {
            parser->cursor += 1;
            if (*parser->cursor == '\0') {
                parser->error = "unterminated escape";
                return false;
            }
            if (*parser->cursor == 'u') {
                for (int i = 0; i < 4; i += 1) {
                    parser->cursor += 1;
                    if (!isxdigit((unsigned char)*parser->cursor)) {
                        parser->error = "invalid unicode escape";
                        return false;
                    }
                }
            }
            parser->cursor += 1;
            continue;
        }
        if (ch < 0x20) {
            parser->error = "control character in string";
            return false;
        }
        parser->cursor += 1;
    }
    parser->error = "unterminated string";
    return false;
}

static bool json_parse_number(JsonParser* parser) {
    const char* start = parser->cursor;
    if (*parser->cursor == '-') {
        parser->cursor += 1;
    }
    if (*parser->cursor == '0') {
        parser->cursor += 1;
    } else if (isdigit((unsigned char)*parser->cursor)) {
        while (isdigit((unsigned char)*parser->cursor)) {
            parser->cursor += 1;
        }
    } else {
        parser->error = "expected number";
        return false;
    }
    if (*parser->cursor == '.') {
        parser->cursor += 1;
        if (!isdigit((unsigned char)*parser->cursor)) {
            parser->error = "expected fractional digit";
            return false;
        }
        while (isdigit((unsigned char)*parser->cursor)) {
            parser->cursor += 1;
        }
    }
    if (*parser->cursor == 'e' || *parser->cursor == 'E') {
        parser->cursor += 1;
        if (*parser->cursor == '+' || *parser->cursor == '-') {
            parser->cursor += 1;
        }
        if (!isdigit((unsigned char)*parser->cursor)) {
            parser->error = "expected exponent digit";
            return false;
        }
        while (isdigit((unsigned char)*parser->cursor)) {
            parser->cursor += 1;
        }
    }
    return parser->cursor > start;
}

static bool json_parse_array(JsonParser* parser) {
    if (!json_consume(parser, '[')) {
        parser->error = "expected array";
        return false;
    }
    json_skip_ws(parser);
    if (*parser->cursor == ']') {
        parser->cursor += 1;
        return true;
    }
    while (true) {
        if (!json_parse_value(parser)) {
            return false;
        }
        json_skip_ws(parser);
        if (*parser->cursor == ']') {
            parser->cursor += 1;
            return true;
        }
        if (*parser->cursor != ',') {
            parser->error = "expected array comma";
            return false;
        }
        parser->cursor += 1;
    }
}

static bool json_parse_object(JsonParser* parser) {
    if (!json_consume(parser, '{')) {
        parser->error = "expected object";
        return false;
    }
    json_skip_ws(parser);
    if (*parser->cursor == '}') {
        parser->cursor += 1;
        return true;
    }
    while (true) {
        json_skip_ws(parser);
        if (!json_parse_string_raw(parser)) {
            return false;
        }
        if (!json_consume(parser, ':')) {
            parser->error = "expected object colon";
            return false;
        }
        if (!json_parse_value(parser)) {
            return false;
        }
        json_skip_ws(parser);
        if (*parser->cursor == '}') {
            parser->cursor += 1;
            return true;
        }
        if (*parser->cursor != ',') {
            parser->error = "expected object comma";
            return false;
        }
        parser->cursor += 1;
    }
}

static bool json_parse_literal(JsonParser* parser, const char* literal) {
    size_t len = strlen(literal);
    if (strncmp(parser->cursor, literal, len) != 0) {
        return false;
    }
    parser->cursor += len;
    return true;
}

static bool json_parse_value(JsonParser* parser) {
    json_skip_ws(parser);
    if (*parser->cursor == '"') {
        return json_parse_string_raw(parser);
    }
    if (*parser->cursor == '{') {
        return json_parse_object(parser);
    }
    if (*parser->cursor == '[') {
        return json_parse_array(parser);
    }
    if (*parser->cursor == '-' || isdigit((unsigned char)*parser->cursor)) {
        return json_parse_number(parser);
    }
    if (
        json_parse_literal(parser, "true")
        || json_parse_literal(parser, "false")
        || json_parse_literal(parser, "null")
    ) {
        return true;
    }
    parser->error = "expected value";
    return false;
}

static const char* json_text(struct std_Json_JsonValue* value) {
    if (value == NULL || value->handle == 0) {
        return NULL;
    }
    return (const char*)(uintptr_t)value->handle;
}

static struct std_Json_JsonIssue* json_issue_object(const char* message) {
    struct std_Json_JsonIssue* issue = std_Json_JsonIssue_new();
    issue->message = _forge_string_copy(message);
    return issue;
}

static ForgeResult_JsonValue_JsonIssue json_value_issue(const char* message) {
    return (ForgeResult_JsonValue_JsonIssue){
        .tag = ForgeResult_JsonValue_JsonIssue_OUTCOME_JSONISSUE,
        .outcome_JsonIssue = json_issue_object(message),
    };
}

static ForgeResult_String_JsonIssue json_string_issue(const char* message) {
    return (ForgeResult_String_JsonIssue){
        .tag = ForgeResult_String_JsonIssue_OUTCOME_JSONISSUE,
        .outcome_JsonIssue = json_issue_object(message),
    };
}

static ForgeResult_Int_JsonIssue json_int_issue(const char* message) {
    return (ForgeResult_Int_JsonIssue){
        .tag = ForgeResult_Int_JsonIssue_OUTCOME_JSONISSUE,
        .outcome_JsonIssue = json_issue_object(message),
    };
}

static ForgeResult_Double_JsonIssue json_double_issue(const char* message) {
    return (ForgeResult_Double_JsonIssue){
        .tag = ForgeResult_Double_JsonIssue_OUTCOME_JSONISSUE,
        .outcome_JsonIssue = json_issue_object(message),
    };
}

static ForgeResult_Bool_JsonIssue json_bool_issue(const char* message) {
    return (ForgeResult_Bool_JsonIssue){
        .tag = ForgeResult_Bool_JsonIssue_OUTCOME_JSONISSUE,
        .outcome_JsonIssue = json_issue_object(message),
    };
}

static ForgeResult_Int___JsonIssue json_int_array_issue(const char* message) {
    return (ForgeResult_Int___JsonIssue){
        .tag = ForgeResult_Int___JsonIssue_OUTCOME_JSONISSUE,
        .outcome_JsonIssue = json_issue_object(message),
    };
}

static ForgeResult_JsonValue___JsonIssue json_value_array_issue(const char* message) {
    return (ForgeResult_JsonValue___JsonIssue){
        .tag = ForgeResult_JsonValue___JsonIssue_OUTCOME_JSONISSUE,
        .outcome_JsonIssue = json_issue_object(message),
    };
}

static char json_unescape_char(char ch) {
    switch (ch) {
        case '"': return '"';
        case '\\': return '\\';
        case '/': return '/';
        case 'b': return '\b';
        case 'f': return '\f';
        case 'n': return '\n';
        case 'r': return '\r';
        case 't': return '\t';
        default: return ch;
    }
}

static char* json_decode_string(const char** cursor) {
    const char* source = *cursor;
    JsonParser validator = {.cursor = source, .error = NULL};
    if (!json_parse_string_raw(&validator)) {
        return NULL;
    }
    size_t max_len = (size_t)(validator.cursor - source);
    char* result = _forge_alloc(max_len + 1);
    size_t out = 0;
    source += 1;
    while (*source != '"') {
        if (*source == '\\') {
            source += 1;
            if (*source == 'u') {
                result[out] = '?';
                out += 1;
                source += 5;
                continue;
            }
            result[out] = json_unescape_char(*source);
            out += 1;
            source += 1;
            continue;
        }
        result[out] = *source;
        out += 1;
        source += 1;
    }
    result[out] = '\0';
    *cursor = validator.cursor;
    return result;
}

static size_t json_encoded_string_extra_len(unsigned char ch) {
    switch (ch) {
        case '"':
        case '\\':
        case '\b':
        case '\f':
        case '\n':
        case '\r':
        case '\t':
            return 1;
        default:
            return ch < 0x20 ? 5 : 0;
    }
}

static char* json_encode_string(const char* value) {
    static const char* hex = "0123456789abcdef";
    size_t len = 2;
    for (const unsigned char* cursor = (const unsigned char*)value; *cursor != '\0'; cursor += 1) {
        len += 1 + json_encoded_string_extra_len(*cursor);
    }

    char* result = _forge_alloc(len + 1);
    char* out = result;
    *out = '"';
    out += 1;
    for (const unsigned char* cursor = (const unsigned char*)value; *cursor != '\0'; cursor += 1) {
        unsigned char ch = *cursor;
        switch (ch) {
            case '"':
                *out = '\\';
                out += 1;
                *out = '"';
                out += 1;
                break;
            case '\\':
                *out = '\\';
                out += 1;
                *out = '\\';
                out += 1;
                break;
            case '\b':
                *out = '\\';
                out += 1;
                *out = 'b';
                out += 1;
                break;
            case '\f':
                *out = '\\';
                out += 1;
                *out = 'f';
                out += 1;
                break;
            case '\n':
                *out = '\\';
                out += 1;
                *out = 'n';
                out += 1;
                break;
            case '\r':
                *out = '\\';
                out += 1;
                *out = 'r';
                out += 1;
                break;
            case '\t':
                *out = '\\';
                out += 1;
                *out = 't';
                out += 1;
                break;
            default:
                if (ch < 0x20) {
                    *out = '\\';
                    out += 1;
                    *out = 'u';
                    out += 1;
                    *out = '0';
                    out += 1;
                    *out = '0';
                    out += 1;
                    *out = hex[ch >> 4];
                    out += 1;
                    *out = hex[ch & 0x0f];
                    out += 1;
                } else {
                    *out = (char)ch;
                    out += 1;
                }
                break;
        }
    }
    *out = '"';
    out += 1;
    *out = '\0';
    return result;
}

static bool json_skip_value(const char** cursor) {
    JsonParser parser = {.cursor = *cursor, .error = NULL};
    if (!json_parse_value(&parser)) {
        return false;
    }
    *cursor = parser.cursor;
    return true;
}

static struct std_Json_JsonValue* json_value_from_range(const char* start, const char* end) {
    size_t len = (size_t)(end - start);
    char* text = _forge_alloc(len + 1);
    if (len != 0) {
        memcpy(text, start, len);
    }
    text[len] = '\0';
    struct std_Json_JsonValue* value = std_Json_JsonValue_new();
    value->handle = (unsigned long long)(uintptr_t)text;
    return value;
}

static bool json_find_field(struct std_Json_JsonValue* value, const char* name, const char** out) {
    const char* cursor = json_text(value);
    if (cursor == NULL) {
        return false;
    }
    JsonParser parser = {.cursor = cursor, .error = NULL};
    json_skip_ws(&parser);
    if (*parser.cursor != '{') {
        return false;
    }
    parser.cursor += 1;
    json_skip_ws(&parser);
    if (*parser.cursor == '}') {
        return false;
    }
    while (true) {
        json_skip_ws(&parser);
        const char* key_cursor = parser.cursor;
        char* key = json_decode_string(&key_cursor);
        if (key == NULL) {
            return false;
        }
        parser.cursor = key_cursor;
        if (!json_consume(&parser, ':')) {
            return false;
        }
        json_skip_ws(&parser);
        if (strcmp(key, name) == 0) {
            *out = parser.cursor;
            return true;
        }
        const char* value_cursor = parser.cursor;
        if (!json_skip_value(&value_cursor)) {
            return false;
        }
        parser.cursor = value_cursor;
        json_skip_ws(&parser);
        if (*parser.cursor == '}') {
            return false;
        }
        if (*parser.cursor != ',') {
            return false;
        }
        parser.cursor += 1;
    }
}

static bool json_array_start(struct std_Json_JsonValue* value, const char** out) {
    const char* cursor = json_text(value);
    if (cursor == NULL) {
        return false;
    }
    JsonParser parser = {.cursor = cursor, .error = NULL};
    json_skip_ws(&parser);
    if (*parser.cursor != '[') {
        return false;
    }
    parser.cursor += 1;
    json_skip_ws(&parser);
    *out = parser.cursor;
    return true;
}

static ForgeResult_JsonValue_JsonIssue json_value_success(struct std_Json_JsonValue* value) {
    return (ForgeResult_JsonValue_JsonIssue){
        .tag = ForgeResult_JsonValue_JsonIssue_SUCCESS,
        .success = value,
    };
}

ForgeResult_JsonValue_JsonIssue forge_json_parse(const char* text) {
    JsonParser parser = {.cursor = text, .error = NULL};
    if (!json_parse_value(&parser)) {
        return json_value_issue(parser.error == NULL ? "invalid JSON" : parser.error);
    }
    json_skip_ws(&parser);
    if (*parser.cursor != '\0') {
        return json_value_issue("trailing JSON content");
    }
    struct std_Json_JsonValue* value = std_Json_JsonValue_new();
    value->handle = (unsigned long long)(uintptr_t)_forge_string_copy(text);
    return json_value_success(value);
}

char* forge_json_write_string(const char* value) {
    return json_encode_string(value);
}

ForgeResult_JsonValue_JsonIssue forge_json_get(struct std_Json_JsonValue* value, const char* name) {
    const char* cursor = NULL;
    if (!json_find_field(value, name, &cursor)) {
        return json_value_issue("JSON field not found");
    }
    const char* end = cursor;
    if (!json_skip_value(&end)) {
        return json_value_issue("invalid JSON field value");
    }
    return json_value_success(json_value_from_range(cursor, end));
}

ForgeResult_JsonValue_JsonIssue forge_json_at(struct std_Json_JsonValue* value, int index) {
    if (index < 0) {
        return json_value_issue("JSON array index must be non-negative");
    }
    const char* cursor = NULL;
    if (!json_array_start(value, &cursor)) {
        return json_value_issue("JSON value is not an array");
    }
    if (*cursor == ']') {
        return json_value_issue("JSON array index out of range");
    }
    int current = 0;
    while (true) {
        JsonParser element_parser = {.cursor = cursor, .error = NULL};
        json_skip_ws(&element_parser);
        cursor = element_parser.cursor;
        const char* start = cursor;
        const char* end = cursor;
        if (!json_skip_value(&end)) {
            return json_value_issue("invalid JSON array element");
        }
        if (current == index) {
            return json_value_success(json_value_from_range(start, end));
        }
        cursor = end;
        JsonParser parser = {.cursor = cursor, .error = NULL};
        json_skip_ws(&parser);
        cursor = parser.cursor;
        if (*cursor == ']') {
            return json_value_issue("JSON array index out of range");
        }
        if (*cursor != ',') {
            return json_value_issue("invalid JSON array");
        }
        cursor += 1;
        current += 1;
    }
}

ForgeResult_Int_JsonIssue forge_json_length(struct std_Json_JsonValue* value) {
    const char* cursor = NULL;
    if (!json_array_start(value, &cursor)) {
        return json_int_issue("JSON value is not an array");
    }
    if (*cursor == ']') {
        return (ForgeResult_Int_JsonIssue){.tag = ForgeResult_Int_JsonIssue_SUCCESS, .success = 0};
    }
    int count = 0;
    while (true) {
        const char* end = cursor;
        if (!json_skip_value(&end)) {
            return json_int_issue("invalid JSON array element");
        }
        count += 1;
        cursor = end;
        JsonParser parser = {.cursor = cursor, .error = NULL};
        json_skip_ws(&parser);
        cursor = parser.cursor;
        if (*cursor == ']') {
            return (ForgeResult_Int_JsonIssue){.tag = ForgeResult_Int_JsonIssue_SUCCESS, .success = count};
        }
        if (*cursor != ',') {
            return json_int_issue("invalid JSON array");
        }
        cursor += 1;
    }
}

ForgeResult_String_JsonIssue forge_json_as_string(struct std_Json_JsonValue* value) {
    const char* cursor = json_text(value);
    if (cursor == NULL) {
        return json_string_issue("invalid JSON value");
    }
    char* result = json_decode_string(&cursor);
    if (result == NULL) {
        return json_string_issue("JSON value is not a string");
    }
    return (ForgeResult_String_JsonIssue){
        .tag = ForgeResult_String_JsonIssue_SUCCESS,
        .success = result,
    };
}

ForgeResult_Int_JsonIssue forge_json_as_int(struct std_Json_JsonValue* value) {
    const char* cursor = json_text(value);
    if (cursor == NULL) {
        return json_int_issue("invalid JSON value");
    }
    char* end = NULL;
    long parsed = strtol(cursor, &end, 10);
    if (end == cursor || (*end == '.' || *end == 'e' || *end == 'E')) {
        return json_int_issue("JSON value is not an integer");
    }
    return (ForgeResult_Int_JsonIssue){
        .tag = ForgeResult_Int_JsonIssue_SUCCESS,
        .success = (int)parsed,
    };
}

ForgeResult_Double_JsonIssue forge_json_as_double(struct std_Json_JsonValue* value) {
    const char* cursor = json_text(value);
    if (cursor == NULL) {
        return json_double_issue("invalid JSON value");
    }
    char* end = NULL;
    double parsed = strtod(cursor, &end);
    if (end == cursor) {
        return json_double_issue("JSON value is not a number");
    }
    return (ForgeResult_Double_JsonIssue){
        .tag = ForgeResult_Double_JsonIssue_SUCCESS,
        .success = parsed,
    };
}

ForgeResult_Bool_JsonIssue forge_json_as_bool(struct std_Json_JsonValue* value) {
    const char* cursor = json_text(value);
    if (cursor == NULL) {
        return json_bool_issue("invalid JSON value");
    }
    if (strncmp(cursor, "true", 4) == 0) {
        return (ForgeResult_Bool_JsonIssue){.tag = ForgeResult_Bool_JsonIssue_SUCCESS, .success = true};
    }
    if (strncmp(cursor, "false", 5) == 0) {
        return (ForgeResult_Bool_JsonIssue){.tag = ForgeResult_Bool_JsonIssue_SUCCESS, .success = false};
    }
    return json_bool_issue("JSON value is not a boolean");
}

ForgeResult_Bool_JsonIssue forge_json_value_is_null(struct std_Json_JsonValue* value) {
    const char* cursor = json_text(value);
    if (cursor == NULL) {
        return json_bool_issue("invalid JSON value");
    }
    return (ForgeResult_Bool_JsonIssue){
        .tag = ForgeResult_Bool_JsonIssue_SUCCESS,
        .success = strncmp(cursor, "null", 4) == 0,
    };
}

ForgeResult_String_JsonIssue forge_json_get_string(struct std_Json_JsonValue* value, const char* name) {
    ForgeResult_JsonValue_JsonIssue field = forge_json_get(value, name);
    if (field.tag != ForgeResult_JsonValue_JsonIssue_SUCCESS) {
        return json_string_issue(field.outcome_JsonIssue->message);
    }
    return forge_json_as_string(field.success);
}

ForgeResult_Int_JsonIssue forge_json_get_int(struct std_Json_JsonValue* value, const char* name) {
    ForgeResult_JsonValue_JsonIssue field = forge_json_get(value, name);
    if (field.tag != ForgeResult_JsonValue_JsonIssue_SUCCESS) {
        return json_int_issue(field.outcome_JsonIssue->message);
    }
    return forge_json_as_int(field.success);
}

ForgeResult_Double_JsonIssue forge_json_get_double(struct std_Json_JsonValue* value, const char* name) {
    ForgeResult_JsonValue_JsonIssue field = forge_json_get(value, name);
    if (field.tag != ForgeResult_JsonValue_JsonIssue_SUCCESS) {
        return json_double_issue(field.outcome_JsonIssue->message);
    }
    return forge_json_as_double(field.success);
}

ForgeResult_Bool_JsonIssue forge_json_get_bool(struct std_Json_JsonValue* value, const char* name) {
    ForgeResult_JsonValue_JsonIssue field = forge_json_get(value, name);
    if (field.tag != ForgeResult_JsonValue_JsonIssue_SUCCESS) {
        return json_bool_issue(field.outcome_JsonIssue->message);
    }
    return forge_json_as_bool(field.success);
}

ForgeResult_Int___JsonIssue forge_json_get_int_array(struct std_Json_JsonValue* value, const char* name) {
    ForgeResult_JsonValue_JsonIssue field = forge_json_get(value, name);
    if (field.tag != ForgeResult_JsonValue_JsonIssue_SUCCESS) {
        return json_int_array_issue(field.outcome_JsonIssue->message);
    }
    ForgeResult_Int_JsonIssue length = forge_json_length(field.success);
    if (length.tag != ForgeResult_Int_JsonIssue_SUCCESS) {
        return json_int_array_issue(length.outcome_JsonIssue->message);
    }
    ForgeArray_Int result;
    result.len = 0;
    result.cap = (size_t)length.success;
    result.data = _forge_array_new((size_t)length.success, sizeof(int));
    for (int index = 0; index < length.success; index += 1) {
        ForgeResult_JsonValue_JsonIssue item = forge_json_at(field.success, index);
        if (item.tag != ForgeResult_JsonValue_JsonIssue_SUCCESS) {
            return json_int_array_issue(item.outcome_JsonIssue->message);
        }
        ForgeResult_Int_JsonIssue parsed = forge_json_as_int(item.success);
        if (parsed.tag != ForgeResult_Int_JsonIssue_SUCCESS) {
            return json_int_array_issue(parsed.outcome_JsonIssue->message);
        }
        result.data[result.len] = parsed.success;
        result.len += 1;
    }
    return (ForgeResult_Int___JsonIssue){
        .tag = ForgeResult_Int___JsonIssue_SUCCESS,
        .success = result,
    };
}

ForgeResult_JsonValue___JsonIssue forge_json_values(struct std_Json_JsonValue* value) {
    ForgeResult_Int_JsonIssue length = forge_json_length(value);
    if (length.tag != ForgeResult_Int_JsonIssue_SUCCESS) {
        return json_value_array_issue(length.outcome_JsonIssue->message);
    }

    ForgeArray_JsonValue result;
    result.len = 0;
    result.cap = (size_t)length.success;
    result.data = _forge_array_new(
        (size_t)length.success,
        sizeof(struct std_Json_JsonValue*)
    );
    for (int index = 0; index < length.success; index += 1) {
        ForgeResult_JsonValue_JsonIssue item = forge_json_at(value, index);
        if (item.tag != ForgeResult_JsonValue_JsonIssue_SUCCESS) {
            for (size_t cleanup = 0; cleanup < result.len; cleanup += 1) {
                _forge_free_std_Json_JsonValue(result.data[cleanup]);
            }
            free(result.data);
            return json_value_array_issue(item.outcome_JsonIssue->message);
        }
        result.data[result.len] = item.success;
        result.len += 1;
    }
    return (ForgeResult_JsonValue___JsonIssue){
        .tag = ForgeResult_JsonValue___JsonIssue_SUCCESS,
        .success = result,
    };
}

ForgeResult_Bool_JsonIssue forge_json_is_null(struct std_Json_JsonValue* value, const char* name) {
    const char* cursor = NULL;
    if (!json_find_field(value, name, &cursor)) {
        return json_bool_issue("JSON field not found");
    }
    return (ForgeResult_Bool_JsonIssue){
        .tag = ForgeResult_Bool_JsonIssue_SUCCESS,
        .success = strncmp(cursor, "null", 4) == 0,
    };
}
