#include "../std/Di/Definition.h"
#include "../Logger.h"

#pragma once

#include <stdbool.h>

struct std_Di_Definition_Logger {
    bool asSingle;
    bool asEager;
    struct Logger* instance;
};
struct BundleFirst_BundleFirst_Defs {
    struct std_Di_Definition_Logger logger;
};
struct BundleFirst_BundleFirst {
    char _forge_empty;
};

void _forge_free_BundleFirst_BundleFirst_Defs(struct BundleFirst_BundleFirst_Defs* value);
void _forge_free_BundleFirst_BundleFirst(struct BundleFirst_BundleFirst* value);
struct BundleFirst_BundleFirst_Defs BundleFirst_BundleFirst_defs(void);
struct BundleFirst_BundleFirst* BundleFirst_BundleFirst_new(void);
