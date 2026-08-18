#include "forge_std_net.h"
#include "forge_std_string.h"
#include "JsonValue.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Json_JsonValue* std_Json_JsonValue_new(void) {
    struct std_Json_JsonValue* this = _forge_alloc(sizeof(struct std_Json_JsonValue));
    return this;
}

void _forge_free_std_Json_JsonValue(struct std_Json_JsonValue* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
