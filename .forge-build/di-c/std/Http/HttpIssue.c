#include "forge_std_net.h"
#include "forge_std_string.h"
#include "HttpIssue.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Http_HttpIssue* std_Http_HttpIssue_new(const char* message) {
    struct std_Http_HttpIssue* this = _forge_alloc(sizeof(struct std_Http_HttpIssue));
    this->message = _forge_string_copy(message);
    return this;
}

void _forge_free_std_Http_HttpIssue(struct std_Http_HttpIssue* value) {
    if (value == NULL) {
        return;
    }
    free((void*)value->message);
    free(value);
}
