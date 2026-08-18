#include "forge_std_net.h"
#include "forge_std_string.h"
#include "BundleFirst.h"
#include "../std/Di/Definition.h"
#include "../Logger.h"
#include "../forge_runtime.h"

#include <stdbool.h>
#include <stdlib.h>

void _forge_free_BundleFirst_BundleFirst_Defs(struct BundleFirst_BundleFirst_Defs* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}

struct BundleFirst_BundleFirst_Defs BundleFirst_BundleFirst_defs(void) {
    return (struct BundleFirst_BundleFirst_Defs){.logger = (struct std_Di_Definition_Logger){.asSingle = true, .asEager = false, .instance = Logger_new()}};
}

struct BundleFirst_BundleFirst* BundleFirst_BundleFirst_new(void) {
    struct BundleFirst_BundleFirst* this = _forge_alloc(sizeof(struct BundleFirst_BundleFirst));
    return this;
}

void _forge_free_BundleFirst_BundleFirst(struct BundleFirst_BundleFirst* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
