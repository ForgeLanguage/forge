#include "app.h"
#include "forge_runtime.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#ifndef FORGEARRAY_FILE_DEFINED
#define FORGEARRAY_FILE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    struct app_File** data;
} ForgeArray_File;
#endif

static ForgeArray_File ForgeArray_File_new(size_t capacity) {
    ForgeArray_File array;
    array.len = 0;
    array.cap = capacity;
    array.data = _forge_array_new(capacity, sizeof(struct app_File*));
    return array;
}

static void ForgeArray_File_push(ForgeArray_File* array, struct app_File* value) {
    if (array->len == array->cap) {
        _forge_array_grow((void**)&array->data, &array->cap, sizeof(struct app_File*));
    }
    array->data[array->len] = value;
    array->len += 1;
}

#ifndef FORGERESULT_FILE___PATTERNMISMATCH_DEFINED
#define FORGERESULT_FILE___PATTERNMISMATCH_DEFINED
typedef enum {
    ForgeResult_File___PatternMismatch_SUCCESS = 0,
    ForgeResult_File___PatternMismatch_OUTCOME_PATTERNMISMATCH = 1
} ForgeResult_File___PatternMismatchTag;

typedef struct {
    uint8_t tag;
    ForgeArray_File success;
    struct ForgePatternMismatch* outcome_PatternMismatch;
} ForgeResult_File___PatternMismatch;
#endif

struct app_File* app_File_new(int value) {
    struct app_File* this = _forge_alloc(sizeof(struct app_File));
    this->value = value;
    return this;
}

void _forge_free_app_File(struct app_File* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}

ForgeArray_File shortFiles(void) {
    ForgeArray_File forge_tmp_array0 = ForgeArray_File_new(1);
    ForgeArray_File_push(&forge_tmp_array0, app_File_new(1));
    return forge_tmp_array0;
}

int useOwnedFallback(ForgeArray_File files) {
    int forge_tmp_return7;
    int forge_tmp_array_owned1 = 0;
    ForgeResult_File___PatternMismatch forge_tmp_outcome3;
    ForgeArray_File forge_tmp_array_pattern4 = files;
    if (forge_tmp_array_pattern4.len >= 1) {
        forge_tmp_outcome3 = (ForgeResult_File___PatternMismatch){.tag = ForgeResult_File___PatternMismatch_SUCCESS, .success = forge_tmp_array_pattern4};
    } else {
        forge_tmp_outcome3 = (ForgeResult_File___PatternMismatch){.tag = ForgeResult_File___PatternMismatch_OUTCOME_PATTERNMISMATCH, .outcome_PatternMismatch = NULL};
    }
    ForgeResult_File___PatternMismatch forge_tmp_outcome2 = forge_tmp_outcome3;
    ForgeArray_File forge_tmp_catch5;
    if (forge_tmp_outcome2.tag == ForgeResult_File___PatternMismatch_SUCCESS) {
        forge_tmp_catch5 = forge_tmp_outcome2.success;
        forge_tmp_array_owned1 = 0;
    } else if (forge_tmp_outcome2.tag == ForgeResult_File___PatternMismatch_OUTCOME_PATTERNMISMATCH) {
        struct ForgePatternMismatch* issue = forge_tmp_outcome2.outcome_PatternMismatch;
    ForgeArray_File forge_tmp_array6 = ForgeArray_File_new(1);
    ForgeArray_File_push(&forge_tmp_array6, app_File_new(7));
        forge_tmp_catch5 = forge_tmp_array6;
        forge_tmp_array_owned1 = 1;
    } else {
        abort();
    }
    ForgeArray_File forge_destructure_source0 = forge_tmp_catch5;
    struct app_File* first = forge_destructure_source0.data[0];
    forge_tmp_return7 = first->value;
    goto cleanup;
    cleanup:
    if (forge_tmp_array_owned1) {
        for (size_t _forge_i = 0; _forge_i < forge_destructure_source0.len; _forge_i += 1) {
            _forge_free_app_File(forge_destructure_source0.data[_forge_i]);
        }
        free(forge_destructure_source0.data);
    }
    return forge_tmp_return7;
}

int useBorrowedFallback(ForgeArray_File files) {
    int forge_tmp_return13;
    int forge_tmp_array_owned8 = 0;
    ForgeResult_File___PatternMismatch forge_tmp_outcome10;
    ForgeArray_File forge_tmp_array_pattern11 = shortFiles();
    if (forge_tmp_array_pattern11.len >= 2) {
        forge_tmp_outcome10 = (ForgeResult_File___PatternMismatch){.tag = ForgeResult_File___PatternMismatch_SUCCESS, .success = forge_tmp_array_pattern11};
    } else {
        for (size_t _forge_i = 0; _forge_i < forge_tmp_array_pattern11.len; _forge_i += 1) {
            _forge_free_app_File(forge_tmp_array_pattern11.data[_forge_i]);
        }
        free(forge_tmp_array_pattern11.data);
        forge_tmp_outcome10 = (ForgeResult_File___PatternMismatch){.tag = ForgeResult_File___PatternMismatch_OUTCOME_PATTERNMISMATCH, .outcome_PatternMismatch = NULL};
    }
    ForgeResult_File___PatternMismatch forge_tmp_outcome9 = forge_tmp_outcome10;
    ForgeArray_File forge_tmp_catch12;
    if (forge_tmp_outcome9.tag == ForgeResult_File___PatternMismatch_SUCCESS) {
        forge_tmp_catch12 = forge_tmp_outcome9.success;
        forge_tmp_array_owned8 = 1;
    } else if (forge_tmp_outcome9.tag == ForgeResult_File___PatternMismatch_OUTCOME_PATTERNMISMATCH) {
        struct ForgePatternMismatch* issue = forge_tmp_outcome9.outcome_PatternMismatch;
        forge_tmp_catch12 = files;
        forge_tmp_array_owned8 = 0;
    } else {
        abort();
    }
    ForgeArray_File forge_destructure_source1 = forge_tmp_catch12;
    struct app_File* first = forge_destructure_source1.data[0];
    struct app_File* second = forge_destructure_source1.data[1];
    forge_tmp_return13 = first->value + second->value;
    goto cleanup;
    cleanup:
    if (forge_tmp_array_owned8) {
        for (size_t _forge_i = 0; _forge_i < forge_destructure_source1.len; _forge_i += 1) {
            _forge_free_app_File(forge_destructure_source1.data[_forge_i]);
        }
        free(forge_destructure_source1.data);
    }
    return forge_tmp_return13;
}

int main(void) {
    ForgeArray_File forge_tmp_array14 = ForgeArray_File_new(0);
    ForgeArray_File empty = forge_tmp_array14;
    printf("%d\n", useOwnedFallback(empty));
    ForgeArray_File forge_tmp_array15 = ForgeArray_File_new(2);
    ForgeArray_File_push(&forge_tmp_array15, app_File_new(20));
    ForgeArray_File_push(&forge_tmp_array15, app_File_new(22));
    ForgeArray_File fallback = forge_tmp_array15;
    printf("%d\n", useBorrowedFallback(fallback));
    for (size_t _forge_i = 0; _forge_i < fallback.len; _forge_i += 1) {
        _forge_free_app_File(fallback.data[_forge_i]);
    }
    free(fallback.data);
    for (size_t _forge_i = 0; _forge_i < empty.len; _forge_i += 1) {
        _forge_free_app_File(empty.data[_forge_i]);
    }
    free(empty.data);
    return 0;
}
