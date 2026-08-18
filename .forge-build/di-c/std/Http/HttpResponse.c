#include "forge_std_net.h"
#include "forge_std_string.h"
#include "HttpResponse.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Http_HttpResponse* std_Http_HttpResponse_new(int status, const char* body) {
    struct std_Http_HttpResponse* this = _forge_alloc(sizeof(struct std_Http_HttpResponse));
    this->status = status;
    this->body = _forge_string_copy(body);
    return this;
}

void _forge_free_std_Http_HttpResponse(struct std_Http_HttpResponse* value) {
    if (value == NULL) {
        return;
    }
    free((void*)value->body);
    free(value);
}
