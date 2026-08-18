#include "forge_std_net.h"
#include "forge_std_string.h"
#include "Test.h"
#include "HttpServerHandler.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Http_Test* std_Http_Test_new(struct std_Http_HttpServerHandler user) {
    struct std_Http_Test* this = _forge_alloc(sizeof(struct std_Http_Test));
    this->user = user;
    return this;
}

void _forge_free_std_Http_Test(struct std_Http_Test* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
