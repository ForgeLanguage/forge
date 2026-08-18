#include "forge_std_net.h"
#include "forge_std_string.h"
#include "Logger.h"
#include "forge_runtime.h"

#include <stdlib.h>

struct Logger* Logger_new(void) {
    struct Logger* this = _forge_alloc(sizeof(struct Logger));
    return this;
}

void _forge_free_Logger(struct Logger* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
