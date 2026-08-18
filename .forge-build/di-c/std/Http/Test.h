#include "HttpServerHandler.h"

#pragma once

struct std_Http_Test {
    struct std_Http_HttpServerHandler user;
};

void _forge_free_std_Http_Test(struct std_Http_Test* value);
struct std_Http_Test* std_Http_Test_new(struct std_Http_HttpServerHandler user);
