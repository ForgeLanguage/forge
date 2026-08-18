#pragma once

struct std_Http_HttpServerResponse {
    int status;
    const char* body;
};

void _forge_free_std_Http_HttpServerResponse(struct std_Http_HttpServerResponse* value);
struct std_Http_HttpServerResponse* std_Http_HttpServerResponse_new(int status, const char* body);
