#include "stdlib.h"
#include "main.h"
#include "forge_runtime.h"

#include <stdio.h>

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
    ForgeAsyncNative_abs_Int_Int_Context pending_context;
    pending_context.arg0 = -7;
    _ForgeAsyncTask* pending = _forge_async_task_new(ForgeAsyncNative_abs_Int_Int_run, &pending_context);
    _forge_async_task_start(pending);
    _forge_async_task_await(pending);
    _forge_async_task_free(pending);
    printf("%d\n", pending_context.result);
    return 0;
}
