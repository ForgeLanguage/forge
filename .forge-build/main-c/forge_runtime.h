#pragma once

#include <stddef.h>

typedef struct _ForgeAsyncTask _ForgeAsyncTask;
typedef void (*_forge_async_job_fn)(void* context);

void* _forge_alloc(size_t size);
void* _forge_realloc(void* pointer, size_t size);
void* _forge_array_new(size_t capacity, size_t element_size);
void _forge_array_grow(void** data, size_t* cap, size_t element_size);
char* _forge_string_copy(const char* value);
char* _forge_string_concat(size_t count, ...);
_ForgeAsyncTask* _forge_async_task_new(_forge_async_job_fn run, void* context);
void _forge_async_task_start(_ForgeAsyncTask* task);
void _forge_async_task_await(_ForgeAsyncTask* task);
void _forge_async_task_free(_ForgeAsyncTask* task);
