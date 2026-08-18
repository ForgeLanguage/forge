#include "forge_std_net.h"
#include "forge_std_string.h"
#include "NetworkIssue.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Net_NetworkIssue* std_Net_NetworkIssue_new(void) {
    struct std_Net_NetworkIssue* this = _forge_alloc(sizeof(struct std_Net_NetworkIssue));
    return this;
}

void _forge_free_std_Net_NetworkIssue(struct std_Net_NetworkIssue* value) {
    if (value == NULL) {
        return;
    }
    free((void*)value->message);
    free(value);
}
