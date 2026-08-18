#include "forge_runtime.h"
#include "forge_std_string.h"

#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char* forge_string_copy_range(const char* text, size_t start, size_t count) {
    char* result = _forge_alloc(count + 1);
    if (count != 0) {
        memcpy(result, text + start, count);
    }
    result[count] = '\0';
    return result;
}

static bool forge_string_ascii_whitespace(unsigned char value) {
    return value == 0x20 || (value >= 0x09 && value <= 0x0d);
}

static int forge_string_normalize_index(int index, int length) {
    long long normalized = index;
    if (normalized < 0) {
        normalized += length;
    }
    if (normalized < 0) {
        return 0;
    }
    if (normalized > length) {
        return length;
    }
    return (int)normalized;
}

int forge_string_length(const char* text) {
    return (int)strlen(text);
}

bool forge_string_is_empty(const char* text) {
    return text[0] == '\0';
}

ForgeArray_Byte forge_string_to_bytes(const char* text) {
    size_t length = strlen(text);
    ForgeArray_Byte result;
    result.len = length;
    result.cap = length;
    result.data = _forge_array_new(length, sizeof(signed char));
    if (length != 0) {
        memcpy(result.data, text, length);
    }
    return result;
}

bool forge_string_equals(const char* text, const char* other) {
    return strcmp(text, other) == 0;
}

int forge_string_index_of(const char* text, const char* needle) {
    const char* found = strstr(text, needle);
    if (found == NULL) {
        return -1;
    }
    return (int)(found - text);
}

bool forge_string_contains(const char* text, const char* needle) {
    return strstr(text, needle) != NULL;
}

bool forge_string_starts_with(const char* text, const char* prefix) {
    size_t prefix_length = strlen(prefix);
    return strncmp(text, prefix, prefix_length) == 0;
}

bool forge_string_ends_with(const char* text, const char* suffix) {
    size_t text_length = strlen(text);
    size_t suffix_length = strlen(suffix);
    return suffix_length <= text_length
        && memcmp(text + text_length - suffix_length, suffix, suffix_length) == 0;
}

char* forge_string_substring(const char* text, int start, int end) {
    int length = (int)strlen(text);
    start = forge_string_normalize_index(start, length);
    end = forge_string_normalize_index(end, length);
    if (end < start) {
        end = start;
    }
    return forge_string_copy_range(text, (size_t)start, (size_t)(end - start));
}

char* forge_string_trim(const char* text) {
    size_t start = 0;
    size_t end = strlen(text);
    while (start < end && forge_string_ascii_whitespace((unsigned char)text[start])) {
        start += 1;
    }
    while (end > start && forge_string_ascii_whitespace((unsigned char)text[end - 1])) {
        end -= 1;
    }
    return forge_string_copy_range(text, start, end - start);
}

char* forge_string_to_lower_case(const char* text) {
    size_t length = strlen(text);
    char* result = forge_string_copy_range(text, 0, length);
    for (size_t index = 0; index < length; index += 1) {
        unsigned char value = (unsigned char)result[index];
        if (value >= 'A' && value <= 'Z') {
            result[index] = (char)(value + ('a' - 'A'));
        }
    }
    return result;
}

char* forge_string_to_upper_case(const char* text) {
    size_t length = strlen(text);
    char* result = forge_string_copy_range(text, 0, length);
    for (size_t index = 0; index < length; index += 1) {
        unsigned char value = (unsigned char)result[index];
        if (value >= 'a' && value <= 'z') {
            result[index] = (char)(value - ('a' - 'A'));
        }
    }
    return result;
}

char* forge_string_replace(const char* text, const char* old, const char* replacement) {
    size_t text_length = strlen(text);
    size_t old_length = strlen(old);
    size_t replacement_length = strlen(replacement);
    if (old_length == 0) {
        return forge_string_copy_range(text, 0, text_length);
    }

    size_t matches = 0;
    const char* cursor = text;
    while ((cursor = strstr(cursor, old)) != NULL) {
        matches += 1;
        cursor += old_length;
    }

    size_t result_length = text_length;
    if (replacement_length >= old_length) {
        size_t growth = replacement_length - old_length;
        if (growth != 0 && matches > (SIZE_MAX - text_length - 1) / growth) {
            abort();
        }
        result_length += matches * growth;
    } else {
        result_length -= matches * (old_length - replacement_length);
    }

    char* result = _forge_alloc(result_length + 1);
    const char* source = text;
    char* target = result;
    const char* found;
    while ((found = strstr(source, old)) != NULL) {
        size_t prefix_length = (size_t)(found - source);
        memcpy(target, source, prefix_length);
        target += prefix_length;
        memcpy(target, replacement, replacement_length);
        target += replacement_length;
        source = found + old_length;
    }
    strcpy(target, source);
    return result;
}

ForgeArray_String forge_string_split(
    const char* text,
    const char* separator,
    int limit
) {
    size_t separator_length = strlen(separator);
    size_t full_count = 1;
    if (separator_length != 0) {
        const char* cursor = text;
        while ((cursor = strstr(cursor, separator)) != NULL) {
            full_count += 1;
            cursor += separator_length;
        }
    }

    size_t count;
    if (limit >= 0) {
        size_t maximum = limit <= 1 ? 1 : (size_t)limit;
        count = full_count < maximum ? full_count : maximum;
    } else {
        unsigned long long omitted = (unsigned long long)(-(long long)limit);
        count = omitted >= full_count ? 0 : full_count - (size_t)omitted;
    }

    ForgeArray_String result;
    result.len = count;
    result.cap = count;
    result.data = _forge_array_new(count, sizeof(const char*));
    if (count == 0) {
        return result;
    }
    if (separator_length == 0) {
        result.data[0] = _forge_string_copy(text);
        return result;
    }

    const char* start = text;
    size_t index = 0;
    const char* found;
    if (limit < 0) {
        while (index < count) {
            found = strstr(start, separator);
            result.data[index] = forge_string_copy_range(
                start,
                0,
                (size_t)(found - start)
            );
            index += 1;
            start = found + separator_length;
        }
        return result;
    }

    while (index + 1 < count && (found = strstr(start, separator)) != NULL) {
        result.data[index] = forge_string_copy_range(
            start,
            0,
            (size_t)(found - start)
        );
        index += 1;
        start = found + separator_length;
    }
    result.data[index] = _forge_string_copy(start);
    return result;
}

int forge_string_parse_int(const char* text) {
    const unsigned char* cursor = (const unsigned char*)text;
    while (forge_string_ascii_whitespace(*cursor)) {
        cursor += 1;
    }

    bool negative = false;
    if (*cursor == '+' || *cursor == '-') {
        negative = *cursor == '-';
        cursor += 1;
    }
    if (*cursor < '0' || *cursor > '9') {
        return 0;
    }

    unsigned long limit = negative ? (unsigned long)INT_MAX + 1UL : (unsigned long)INT_MAX;
    unsigned long value = 0;
    bool overflow = false;
    while (*cursor >= '0' && *cursor <= '9') {
        unsigned int digit = (unsigned int)(*cursor - '0');
        if (value > (limit - digit) / 10UL) {
            overflow = true;
        } else if (!overflow) {
            value = value * 10UL + digit;
        }
        cursor += 1;
    }
    if (overflow) {
        return negative ? INT_MIN : INT_MAX;
    }
    if (negative && value == (unsigned long)INT_MAX + 1UL) {
        return INT_MIN;
    }
    return negative ? -(int)value : (int)value;
}

char* forge_string_from_bytes(ForgeArray_Byte bytes) {
    size_t length = 0;
    while (length < bytes.len && bytes.data[length] != 0) {
        length += 1;
    }
    return forge_string_copy_range((const char*)bytes.data, 0, length);
}

char* forge_string_from_int(int value) {
    int length = snprintf(NULL, 0, "%d", value);
    char* result = _forge_alloc((size_t)length + 1);
    snprintf(result, (size_t)length + 1, "%d", value);
    return result;
}
