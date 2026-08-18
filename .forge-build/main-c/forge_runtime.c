#include "forge_runtime.h"

#include <stdbool.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <pthread.h>
#include <unistd.h>
#endif

struct _ForgeAsyncTask {
    _forge_async_job_fn run;
    void* context;
    bool complete;
    bool started;
    struct _ForgeAsyncTask* next;
};

#ifdef _WIN32

static CRITICAL_SECTION _forge_async_mutex;
static CONDITION_VARIABLE _forge_async_work_cond;
static CONDITION_VARIABLE _forge_async_complete_cond;
static INIT_ONCE _forge_async_init_once = INIT_ONCE_STATIC_INIT;
static _ForgeAsyncTask* _forge_async_queue_head = NULL;
static _ForgeAsyncTask* _forge_async_queue_tail = NULL;
static bool _forge_async_workers_started = false;

#else

static pthread_mutex_t _forge_async_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t _forge_async_work_cond = PTHREAD_COND_INITIALIZER;
static pthread_cond_t _forge_async_complete_cond = PTHREAD_COND_INITIALIZER;
static _ForgeAsyncTask* _forge_async_queue_head = NULL;
static _ForgeAsyncTask* _forge_async_queue_tail = NULL;
static bool _forge_async_workers_started = false;

#endif

void* _forge_alloc(size_t size) {
    void* result = malloc(size == 0 ? 1 : size);
    if (result == NULL) {
        abort();
    }
    return result;
}

void* _forge_realloc(void* pointer, size_t size) {
    void* result = realloc(pointer, size == 0 ? 1 : size);
    if (result == NULL) {
        abort();
    }
    return result;
}

void* _forge_array_new(size_t capacity, size_t element_size) {
    return capacity == 0 ? NULL : _forge_alloc(element_size * capacity);
}

void _forge_array_grow(void** data, size_t* cap, size_t element_size) {
    size_t next = *cap == 0 ? 1 : *cap * 2;
    *data = _forge_realloc(*data, element_size * next);
    *cap = next;
}

char* _forge_string_copy(const char* value) {
    size_t len = strlen(value);
    char* result = _forge_alloc(len + 1);
    memcpy(result, value, len + 1);
    return result;
}

char* _forge_string_concat(size_t count, ...) {
    va_list args;
    size_t len = 0;
    va_start(args, count);
    for (size_t i = 0; i < count; i += 1) {
        len += strlen(va_arg(args, const char*));
    }
    va_end(args);

    char* result = _forge_alloc(len + 1);
    char* cursor = result;
    va_start(args, count);
    for (size_t i = 0; i < count; i += 1) {
        const char* part = va_arg(args, const char*);
        size_t part_len = strlen(part);
        memcpy(cursor, part, part_len);
        cursor += part_len;
    }
    va_end(args);
    *cursor = '\0';
    return result;
}

#ifdef _WIN32

static void _forge_async_abort_on_false(BOOL ok) {
    if (!ok) {
        abort();
    }
}

static BOOL CALLBACK _forge_async_init(PINIT_ONCE init_once, PVOID parameter, PVOID* context) {
    (void)init_once;
    (void)parameter;
    (void)context;
    InitializeCriticalSection(&_forge_async_mutex);
    InitializeConditionVariable(&_forge_async_work_cond);
    InitializeConditionVariable(&_forge_async_complete_cond);
    return TRUE;
}

static void _forge_async_ensure_initialized(void) {
    _forge_async_abort_on_false(
        InitOnceExecuteOnce(&_forge_async_init_once, _forge_async_init, NULL, NULL)
    );
}

#endif

#ifndef _WIN32

static void _forge_async_abort_on_error(int status) {
    if (status != 0) {
        abort();
    }
}

#endif

static size_t _forge_async_worker_count(void) {
    const char* configured = getenv("FORGE_ASYNC_THREADS");
    if (configured != NULL && configured[0] != '\0') {
        char* end = NULL;
        unsigned long parsed = strtoul(configured, &end, 10);
        if (parsed > 0 && end != configured && *end == '\0') {
            return (size_t)parsed;
        }
    }

#ifdef _WIN32
    SYSTEM_INFO info;
    GetSystemInfo(&info);
    if (info.dwNumberOfProcessors > 0) {
        return (size_t)info.dwNumberOfProcessors;
    }
#else
    long processors = sysconf(_SC_NPROCESSORS_ONLN);
    if (processors > 0) {
        return (size_t)processors;
    }
#endif
    return 4;
}

static _ForgeAsyncTask* _forge_async_pop_task(void) {
    _ForgeAsyncTask* task = _forge_async_queue_head;
    if (task == NULL) {
        return NULL;
    }
    _forge_async_queue_head = task->next;
    if (_forge_async_queue_head == NULL) {
        _forge_async_queue_tail = NULL;
    }
    task->next = NULL;
    return task;
}

static void _forge_async_run_task(_ForgeAsyncTask* task) {
    task->run(task->context);

#ifdef _WIN32
    _forge_async_ensure_initialized();
    EnterCriticalSection(&_forge_async_mutex);
    task->complete = true;
    WakeAllConditionVariable(&_forge_async_complete_cond);
    LeaveCriticalSection(&_forge_async_mutex);
#else
    _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
    task->complete = true;
    _forge_async_abort_on_error(pthread_cond_broadcast(&_forge_async_complete_cond));
    _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
#endif
}

#ifdef _WIN32

static DWORD WINAPI _forge_async_worker_run(LPVOID unused) {
    (void)unused;
    for (;;) {
        _forge_async_ensure_initialized();
        EnterCriticalSection(&_forge_async_mutex);
        while (_forge_async_queue_head == NULL) {
            SleepConditionVariableCS(&_forge_async_work_cond, &_forge_async_mutex, INFINITE);
        }

        _ForgeAsyncTask* task = _forge_async_pop_task();
        LeaveCriticalSection(&_forge_async_mutex);
        _forge_async_run_task(task);
    }
    return 0;
}

#else

static void* _forge_async_worker_run(void* unused) {
    (void)unused;
    for (;;) {
        _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
        while (_forge_async_queue_head == NULL) {
            _forge_async_abort_on_error(
                pthread_cond_wait(&_forge_async_work_cond, &_forge_async_mutex)
            );
        }

        _ForgeAsyncTask* task = _forge_async_pop_task();
        _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
        _forge_async_run_task(task);
    }
    return NULL;
}

#endif

static void _forge_async_start_workers(void) {
    if (_forge_async_workers_started) {
        return;
    }

    size_t worker_count = _forge_async_worker_count();
    for (size_t i = 0; i < worker_count; i += 1) {
#ifdef _WIN32
        HANDLE worker = CreateThread(NULL, 0, _forge_async_worker_run, NULL, 0, NULL);
        if (worker == NULL) {
            abort();
        }
        CloseHandle(worker);
#else
        pthread_t worker;
        _forge_async_abort_on_error(pthread_create(&worker, NULL, _forge_async_worker_run, NULL));
        _forge_async_abort_on_error(pthread_detach(worker));
#endif
    }
    _forge_async_workers_started = true;
}

_ForgeAsyncTask* _forge_async_task_new(_forge_async_job_fn run, void* context) {
    if (run == NULL) {
        abort();
    }
    _ForgeAsyncTask* task = _forge_alloc(sizeof(_ForgeAsyncTask));
    task->run = run;
    task->context = context;
    task->complete = false;
    task->started = false;
    task->next = NULL;
    return task;
}

void _forge_async_task_start(_ForgeAsyncTask* task) {
    if (task == NULL) {
        abort();
    }
#ifdef _WIN32
    _forge_async_ensure_initialized();
    EnterCriticalSection(&_forge_async_mutex);
#else
    _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
#endif
    if (task->started) {
        abort();
    }
    _forge_async_start_workers();
    task->started = true;
    if (_forge_async_queue_tail == NULL) {
        _forge_async_queue_head = task;
        _forge_async_queue_tail = task;
    } else {
        _forge_async_queue_tail->next = task;
        _forge_async_queue_tail = task;
    }
#ifdef _WIN32
    WakeConditionVariable(&_forge_async_work_cond);
    LeaveCriticalSection(&_forge_async_mutex);
#else
    _forge_async_abort_on_error(pthread_cond_signal(&_forge_async_work_cond));
    _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
#endif
}

void _forge_async_task_await(_ForgeAsyncTask* task) {
    if (task == NULL) {
        abort();
    }
#ifdef _WIN32
    _forge_async_ensure_initialized();
    EnterCriticalSection(&_forge_async_mutex);
#else
    _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
#endif
    if (!task->started) {
        abort();
    }
    while (!task->complete) {
        _ForgeAsyncTask* next = _forge_async_pop_task();
        if (next != NULL) {
#ifdef _WIN32
            LeaveCriticalSection(&_forge_async_mutex);
            _forge_async_run_task(next);
            EnterCriticalSection(&_forge_async_mutex);
#else
            _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
            _forge_async_run_task(next);
            _forge_async_abort_on_error(pthread_mutex_lock(&_forge_async_mutex));
#endif
        } else {
#ifdef _WIN32
            SleepConditionVariableCS(&_forge_async_complete_cond, &_forge_async_mutex, INFINITE);
#else
            _forge_async_abort_on_error(
                pthread_cond_wait(&_forge_async_complete_cond, &_forge_async_mutex)
            );
#endif
        }
    }
#ifdef _WIN32
    LeaveCriticalSection(&_forge_async_mutex);
#else
    _forge_async_abort_on_error(pthread_mutex_unlock(&_forge_async_mutex));
#endif
}

void _forge_async_task_free(_ForgeAsyncTask* task) {
    if (task == NULL) {
        return;
    }
    if (task->started) {
        _forge_async_task_await(task);
    }
    free(task);
}
