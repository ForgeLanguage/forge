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
    ForgeAsyncNative_abs_Int_Int_Context forge_tmp_async_context0;
    forge_tmp_async_context0.arg0 = -7;
    _ForgeAsyncTask* forge_tmp_async_task1 = _forge_async_task_new(ForgeAsyncNative_abs_Int_Int_run, &forge_tmp_async_context0);
    _forge_async_task_start(forge_tmp_async_task1);
    _forge_async_task_await(forge_tmp_async_task1);
    _forge_async_task_free(forge_tmp_async_task1);
    printf("%d\n", forge_tmp_async_context0.result);
    return 0;
}
