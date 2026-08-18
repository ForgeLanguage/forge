#include "JsonIssue.h"
#include "JsonValue.h"

#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#ifndef FORGEARRAY_BOOL_DEFINED
#define FORGEARRAY_BOOL_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    bool* data;
} ForgeArray_Bool;
#endif

#ifndef FORGEARRAY_DOUBLE_DEFINED
#define FORGEARRAY_DOUBLE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    double* data;
} ForgeArray_Double;
#endif

#ifndef FORGEARRAY_INT_DEFINED
#define FORGEARRAY_INT_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    int* data;
} ForgeArray_Int;
#endif

#ifndef FORGEARRAY_JSONVALUE_DEFINED
#define FORGEARRAY_JSONVALUE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    struct std_Json_JsonValue** data;
} ForgeArray_JsonValue;
#endif

#ifndef FORGEARRAY_STRING_DEFINED
#define FORGEARRAY_STRING_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    const char** data;
} ForgeArray_String;
#endif

struct std_Json_Json {
    char _forge_empty;
};

#ifndef FORGEARRAY_BOOL_DEFINED
#define FORGEARRAY_BOOL_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    bool* data;
} ForgeArray_Bool;
#endif

#ifndef FORGEARRAY_DOUBLE_DEFINED
#define FORGEARRAY_DOUBLE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    double* data;
} ForgeArray_Double;
#endif

#ifndef FORGEARRAY_INT_DEFINED
#define FORGEARRAY_INT_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    int* data;
} ForgeArray_Int;
#endif

#ifndef FORGEARRAY_JSONVALUE_DEFINED
#define FORGEARRAY_JSONVALUE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    struct std_Json_JsonValue** data;
} ForgeArray_JsonValue;
#endif

#ifndef FORGEARRAY_STRING_DEFINED
#define FORGEARRAY_STRING_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    const char** data;
} ForgeArray_String;
#endif

#ifndef FORGERESULT_BOOL_JSONISSUE_DEFINED
#define FORGERESULT_BOOL_JSONISSUE_DEFINED
typedef enum {
    ForgeResult_Bool_JsonIssue_SUCCESS = 0,
    ForgeResult_Bool_JsonIssue_OUTCOME_JSONISSUE = 1
} ForgeResult_Bool_JsonIssueTag;

typedef struct {
    uint8_t tag;
    bool success;
    struct std_Json_JsonIssue* outcome_JsonIssue;
} ForgeResult_Bool_JsonIssue;
#endif

#ifndef FORGERESULT_DOUBLE_JSONISSUE_DEFINED
#define FORGERESULT_DOUBLE_JSONISSUE_DEFINED
typedef enum {
    ForgeResult_Double_JsonIssue_SUCCESS = 0,
    ForgeResult_Double_JsonIssue_OUTCOME_JSONISSUE = 1
} ForgeResult_Double_JsonIssueTag;

typedef struct {
    uint8_t tag;
    double success;
    struct std_Json_JsonIssue* outcome_JsonIssue;
} ForgeResult_Double_JsonIssue;
#endif

#ifndef FORGERESULT_INT_JSONISSUE_DEFINED
#define FORGERESULT_INT_JSONISSUE_DEFINED
typedef enum {
    ForgeResult_Int_JsonIssue_SUCCESS = 0,
    ForgeResult_Int_JsonIssue_OUTCOME_JSONISSUE = 1
} ForgeResult_Int_JsonIssueTag;

typedef struct {
    uint8_t tag;
    int success;
    struct std_Json_JsonIssue* outcome_JsonIssue;
} ForgeResult_Int_JsonIssue;
#endif

#ifndef FORGERESULT_INT___JSONISSUE_DEFINED
#define FORGERESULT_INT___JSONISSUE_DEFINED
typedef enum {
    ForgeResult_Int___JsonIssue_SUCCESS = 0,
    ForgeResult_Int___JsonIssue_OUTCOME_JSONISSUE = 1
} ForgeResult_Int___JsonIssueTag;

typedef struct {
    uint8_t tag;
    ForgeArray_Int success;
    struct std_Json_JsonIssue* outcome_JsonIssue;
} ForgeResult_Int___JsonIssue;
#endif

#ifndef FORGERESULT_JSONVALUE_JSONISSUE_DEFINED
#define FORGERESULT_JSONVALUE_JSONISSUE_DEFINED
typedef enum {
    ForgeResult_JsonValue_JsonIssue_SUCCESS = 0,
    ForgeResult_JsonValue_JsonIssue_OUTCOME_JSONISSUE = 1
} ForgeResult_JsonValue_JsonIssueTag;

typedef struct {
    uint8_t tag;
    struct std_Json_JsonValue* success;
    struct std_Json_JsonIssue* outcome_JsonIssue;
} ForgeResult_JsonValue_JsonIssue;
#endif

#ifndef FORGERESULT_JSONVALUE___JSONISSUE_DEFINED
#define FORGERESULT_JSONVALUE___JSONISSUE_DEFINED
typedef enum {
    ForgeResult_JsonValue___JsonIssue_SUCCESS = 0,
    ForgeResult_JsonValue___JsonIssue_OUTCOME_JSONISSUE = 1
} ForgeResult_JsonValue___JsonIssueTag;

typedef struct {
    uint8_t tag;
    ForgeArray_JsonValue success;
    struct std_Json_JsonIssue* outcome_JsonIssue;
} ForgeResult_JsonValue___JsonIssue;
#endif

#ifndef FORGERESULT_STRING_JSONISSUE_DEFINED
#define FORGERESULT_STRING_JSONISSUE_DEFINED
typedef enum {
    ForgeResult_String_JsonIssue_SUCCESS = 0,
    ForgeResult_String_JsonIssue_OUTCOME_JSONISSUE = 1
} ForgeResult_String_JsonIssueTag;

typedef struct {
    uint8_t tag;
    char* success;
    struct std_Json_JsonIssue* outcome_JsonIssue;
} ForgeResult_String_JsonIssue;
#endif

void _forge_free_std_Json_Json(struct std_Json_Json* value);
ForgeResult_JsonValue_JsonIssue forge_json_parse(const char* text);
ForgeResult_JsonValue_JsonIssue forge_json_get(struct std_Json_JsonValue* value, const char* name);
ForgeResult_JsonValue_JsonIssue forge_json_at(struct std_Json_JsonValue* value, int index);
ForgeResult_Int_JsonIssue forge_json_length(struct std_Json_JsonValue* value);
ForgeResult_String_JsonIssue forge_json_as_string(struct std_Json_JsonValue* value);
ForgeResult_Int_JsonIssue forge_json_as_int(struct std_Json_JsonValue* value);
ForgeResult_Double_JsonIssue forge_json_as_double(struct std_Json_JsonValue* value);
ForgeResult_Bool_JsonIssue forge_json_as_bool(struct std_Json_JsonValue* value);
ForgeResult_Bool_JsonIssue forge_json_value_is_null(struct std_Json_JsonValue* value);
ForgeResult_String_JsonIssue forge_json_get_string(struct std_Json_JsonValue* value, const char* name);
ForgeResult_Int_JsonIssue forge_json_get_int(struct std_Json_JsonValue* value, const char* name);
ForgeResult_Double_JsonIssue forge_json_get_double(struct std_Json_JsonValue* value, const char* name);
ForgeResult_Bool_JsonIssue forge_json_get_bool(struct std_Json_JsonValue* value, const char* name);
ForgeResult_Int___JsonIssue forge_json_get_int_array(struct std_Json_JsonValue* value, const char* name);
ForgeResult_JsonValue___JsonIssue forge_json_values(struct std_Json_JsonValue* value);
ForgeResult_Bool_JsonIssue forge_json_is_null(struct std_Json_JsonValue* value, const char* name);
char* forge_json_write_string(const char* value);
ForgeResult_String_JsonIssue std_Json_Json_readString(struct std_Json_JsonValue* value);
ForgeResult_Int_JsonIssue std_Json_Json_readInt(struct std_Json_JsonValue* value);
ForgeResult_Double_JsonIssue std_Json_Json_readDouble(struct std_Json_JsonValue* value);
ForgeResult_Bool_JsonIssue std_Json_Json_readBool(struct std_Json_JsonValue* value);
char* std_Json_Json_writeInt(int value);
char* std_Json_Json_writeDouble(double value);
char* std_Json_Json_writeBool(bool value);
char* std_Json_Json_writeStringArray(ForgeArray_String values);
char* std_Json_Json_writeIntArray(ForgeArray_Int values);
char* std_Json_Json_writeDoubleArray(ForgeArray_Double values);
char* std_Json_Json_writeBoolArray(ForgeArray_Bool values);
struct std_Json_Json* std_Json_Json_new(void);
