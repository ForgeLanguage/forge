#include "forge_std_net.h"
#include "forge_std_string.h"
#include "DiContainer.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Di_DiContainer* std_Di_DiContainer_new(void) {
    struct std_Di_DiContainer* this = _forge_alloc(sizeof(struct std_Di_DiContainer));
    return this;
}

void _forge_free_std_Di_DiContainer(struct std_Di_DiContainer* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
