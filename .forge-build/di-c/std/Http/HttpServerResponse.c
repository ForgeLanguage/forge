#include "forge_std_net.h"
#include "forge_std_string.h"
#include "HttpServerResponse.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Http_HttpServerResponse* std_Http_HttpServerResponse_new(int status, const char* body) {
    struct std_Http_HttpServerResponse* this = _forge_alloc(sizeof(struct std_Http_HttpServerResponse));
    this->status = status;
    this->body = _forge_string_copy(body);
    return this;
}

void _forge_free_std_Http_HttpServerResponse(struct std_Http_HttpServerResponse* value) {
    if (value == NULL) {
        return;
    }
    free((void*)value->body);
    free(value);
}
