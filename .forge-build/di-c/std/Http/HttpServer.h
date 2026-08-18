#include "HttpIssue.h"
#include "HttpServerHandler.h"
#include "HttpServerResponse.h"
#include "../Net/Network.h"
#include "../Net/NetworkIssue.h"
#include "../Net/TcpStream.h"

#pragma once

#include <stdbool.h>
#include <stdint.h>

struct std_Http_HttpServer {
    char _forge_empty;
};

#ifndef FORGERESULT_VOID_HTTPISSUE_DEFINED
#define FORGERESULT_VOID_HTTPISSUE_DEFINED
typedef enum {
    ForgeResult_Void_HttpIssue_SUCCESS = 0,
    ForgeResult_Void_HttpIssue_OUTCOME_HTTPISSUE = 1
} ForgeResult_Void_HttpIssueTag;

typedef struct {
    uint8_t tag;
    struct std_Http_HttpIssue* outcome_HttpIssue;
} ForgeResult_Void_HttpIssue;
#endif

void _forge_free_std_Http_HttpServer(struct std_Http_HttpServer* value);
ForgeResult_Void_HttpIssue std_Http_HttpServer_serve(int port, struct std_Http_HttpServerHandler handler);
bool std_Http_HttpServer_serveConnection(struct std_Net_TcpStream* stream, struct std_Http_HttpServerHandler handler);
struct std_Http_HttpServer* std_Http_HttpServer_new(void);
