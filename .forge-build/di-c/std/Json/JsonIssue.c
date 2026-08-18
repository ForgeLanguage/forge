#include "forge_std_net.h"
#include "forge_std_string.h"
#include "JsonIssue.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Json_JsonIssue* std_Json_JsonIssue_new(void) {
    struct std_Json_JsonIssue* this = _forge_alloc(sizeof(struct std_Json_JsonIssue));
    return this;
}

void _forge_free_std_Json_JsonIssue(struct std_Json_JsonIssue* value) {
    if (value == NULL) {
        return;
    }
    free((void*)value->message);
    free(value);
}
