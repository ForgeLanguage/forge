#pragma once

#include <stdlib.h>

#ifndef FORGEARRAY_FILE_DEFINED
#define FORGEARRAY_FILE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    struct app_File** data;
} ForgeArray_File;
#endif

struct app_File {
    int value;
};

#ifndef FORGEARRAY_FILE_DEFINED
#define FORGEARRAY_FILE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    struct app_File** data;
} ForgeArray_File;
#endif

void _forge_free_app_File(struct app_File* value);
struct app_File* app_File_new(int value);
ForgeArray_File shortFiles(void);
int useOwnedFallback(ForgeArray_File files);
int useBorrowedFallback(ForgeArray_File files);
int main(void);
