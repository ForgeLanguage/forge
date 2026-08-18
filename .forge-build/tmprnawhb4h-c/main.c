#include "stdlib.h"
#include "main.h"
#include "forge_runtime.h"

#include <stdio.h>
#include <stdlib.h>

#ifndef FORGEARRAY_INT_DEFINED
#define FORGEARRAY_INT_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    int* data;
} ForgeArray_Int;
#endif

static ForgeArray_Int ForgeArray_Int_new(size_t capacity) {
    ForgeArray_Int array;
    array.len = 0;
    array.cap = capacity;
    array.data = _forge_array_new(capacity, sizeof(int));
    return array;
}

static void ForgeArray_Int_push(ForgeArray_Int* array, int value) {
    if (array->len == array->cap) {
        _forge_array_grow((void**)&array->data, &array->cap, sizeof(int));
    }
    array->data[array->len] = value;
    array->len += 1;
}

int abs(int);

typedef struct {
    int arg0;
    int result;
} ForgeAsyncNative_abs_Int_Int_Context;

static void ForgeAsyncNative_abs_Int_Int_run(void* raw_context) {
    ForgeAsyncNative_abs_Int_Int_Context* context = raw_context;
    context->result = abs(context->arg0);
}

int main(void) {
    ForgeArray_Int forge_tmp_array0 = ForgeArray_Int_new(2);
    ForgeArray_Int_push(&forge_tmp_array0, -1);
    ForgeArray_Int_push(&forge_tmp_array0, -2);
    ForgeArray_Int values = forge_tmp_array0;
    ForgeArray_Int pending = ForgeArray_Int_new(values.len);
    ForgeAsyncNative_abs_Int_Int_Context* forge_tmp_async_contexts1 = _forge_alloc(sizeof(ForgeAsyncNative_abs_Int_Int_Context) * values.len);
    _ForgeAsyncTask** forge_tmp_async_tasks2 = _forge_alloc(sizeof(_ForgeAsyncTask*) * values.len);
    for (size_t _forge_i = 0; _forge_i < values.len; _forge_i += 1) {
        forge_tmp_async_contexts1[_forge_i].arg0 = values.data[_forge_i];
        forge_tmp_async_tasks2[_forge_i] = _forge_async_task_new(ForgeAsyncNative_abs_Int_Int_run, &forge_tmp_async_contexts1[_forge_i]);
        _forge_async_task_start(forge_tmp_async_tasks2[_forge_i]);
    }
    for (size_t _forge_i = 0; _forge_i < values.len; _forge_i += 1) {
        _forge_async_task_await(forge_tmp_async_tasks2[_forge_i]);
        ForgeArray_Int_push(&pending, forge_tmp_async_contexts1[_forge_i].result);
        _forge_async_task_free(forge_tmp_async_tasks2[_forge_i]);
    }
    free(forge_tmp_async_tasks2);
    free(forge_tmp_async_contexts1);
    ForgeArray_Int results = pending;
    printf("%d\n", results.data[1]);
    free(results.data);
    free(values.data);
    return 0;
}
