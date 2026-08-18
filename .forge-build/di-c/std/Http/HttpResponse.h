#pragma once

struct std_Http_HttpResponse {
    int status;
    const char* body;
};

void _forge_free_std_Http_HttpResponse(struct std_Http_HttpResponse* value);
struct std_Http_HttpResponse* std_Http_HttpResponse_new(int status, const char* body);
