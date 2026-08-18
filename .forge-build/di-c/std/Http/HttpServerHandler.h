#include "HttpServerResponse.h"

#pragma once

struct std_Http_HttpServerHandler_vtable {
    struct std_Http_HttpServerResponse* (*handle)(void* object, const char* path, const char* body);
};
struct std_Http_HttpServerHandler {
    void* object;
    const struct std_Http_HttpServerHandler_vtable* vtable;
};
