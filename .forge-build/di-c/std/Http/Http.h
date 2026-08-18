#include "HttpIssue.h"
#include "HttpResponse.h"
#include "../Net/Network.h"
#include "../Net/NetworkIssue.h"

#pragma once

#include <stdint.h>

struct std_Http_Http {
    char _forge_empty;
};

#ifndef FORGERESULT_HTTPRESPONSE_HTTPISSUE_DEFINED
#define FORGERESULT_HTTPRESPONSE_HTTPISSUE_DEFINED
typedef enum {
    ForgeResult_HttpResponse_HttpIssue_SUCCESS = 0,
    ForgeResult_HttpResponse_HttpIssue_OUTCOME_HTTPISSUE = 1
} ForgeResult_HttpResponse_HttpIssueTag;

typedef struct {
    uint8_t tag;
    struct std_Http_HttpResponse* success;
    struct std_Http_HttpIssue* outcome_HttpIssue;
} ForgeResult_HttpResponse_HttpIssue;
#endif

#ifndef FORGERESULT_INT_HTTPISSUE_DEFINED
#define FORGERESULT_INT_HTTPISSUE_DEFINED
typedef enum {
    ForgeResult_Int_HttpIssue_SUCCESS = 0,
    ForgeResult_Int_HttpIssue_OUTCOME_HTTPISSUE = 1
} ForgeResult_Int_HttpIssueTag;

typedef struct {
    uint8_t tag;
    int success;
    struct std_Http_HttpIssue* outcome_HttpIssue;
} ForgeResult_Int_HttpIssue;
#endif

void _forge_free_std_Http_Http(struct std_Http_Http* value);
ForgeResult_Int_HttpIssue std_Http_Http_status(const char* url);
ForgeResult_HttpResponse_HttpIssue std_Http_Http_get(const char* url);
struct std_Http_Http* std_Http_Http_new(void);
