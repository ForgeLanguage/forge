#pragma once

#include <stdbool.h>
#include <stddef.h>

#ifndef FORGEARRAY_BYTE_DEFINED
#define FORGEARRAY_BYTE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    signed char* data;
} ForgeArray_Byte;
#endif

#ifndef FORGEARRAY_STRING_DEFINED
#define FORGEARRAY_STRING_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    const char** data;
} ForgeArray_String;
#endif

int forge_string_length(const char* text);
bool forge_string_is_empty(const char* text);
ForgeArray_Byte forge_string_to_bytes(const char* text);
int forge_string_index_of(const char* text, const char* needle);
bool forge_string_contains(const char* text, const char* needle);
bool forge_string_starts_with(const char* text, const char* prefix);
bool forge_string_ends_with(const char* text, const char* suffix);
char* forge_string_substring(const char* text, int start, int end);
char* forge_string_trim(const char* text);
char* forge_string_to_lower_case(const char* text);
char* forge_string_to_upper_case(const char* text);
char* forge_string_replace(const char* text, const char* old, const char* replacement);
ForgeArray_String forge_string_split(
    const char* text,
    const char* separator,
    int limit
);
int forge_string_parse_int(const char* text);
char* forge_string_from_bytes(ForgeArray_Byte bytes);
char* forge_string_from_int(int value);
