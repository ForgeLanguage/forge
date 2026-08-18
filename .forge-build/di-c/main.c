#include "forge_std_net.h"
#include "forge_std_string.h"
#include "main.h"
#include "BundleFirst/BundleFirst.h"
#include "Logger.h"
#include "std/Di/DiContainer.h"
#include "forge_runtime.h"

#include <stdlib.h>

int main(void) {
    struct std_Di_DiContainer* container = std_Di_DiContainer_new();
    struct BundleFirst_BundleFirst_Defs defs = BundleFirst_BundleFirst_defs();
    DiContainer_apply__Defs__Config_1(defs);
    DiContainer_build__nongeneric__Config_1();
    struct Logger* logger = DiContainer_resolve__Logger__Config_1();
    _forge_free_Logger(logger);
    _forge_free_std_Di_DiContainer(container);
    return 0;
}

void DiContainer_apply__Defs__Config_1(struct BundleFirst_BundleFirst_Defs defs) {}

void DiContainer_build__nongeneric__Config_1(void) {}

struct Logger* DiContainer_resolve__Logger__Config_1(void) {
    return Logger_new();
}
