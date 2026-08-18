#include "forge_std_net.h"
#include "forge_std_string.h"
#include "Http.h"
#include "HttpIssue.h"
#include "HttpResponse.h"
#include "../Net/Network.h"
#include "../Net/NetworkIssue.h"
#include "../../forge_runtime.h"

#include <stdbool.h>
#include <stdlib.h>

#ifndef FORGEARRAY_BYTE_DEFINED
#define FORGEARRAY_BYTE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    signed char* data;
} ForgeArray_Byte;
#endif

ForgeResult_TcpStream_NetworkIssue forge_net_connect_tcp(const char*, int);

typedef struct {
    const char* arg0;
    int arg1;
    ForgeResult_TcpStream_NetworkIssue result;
} ForgeAsyncNative_forge_net_connect_tcp_TcpStream_String_Int_Context;

static void ForgeAsyncNative_forge_net_connect_tcp_TcpStream_String_Int_run(void* raw_context) {
    ForgeAsyncNative_forge_net_connect_tcp_TcpStream_String_Int_Context* context = raw_context;
    context->result = forge_net_connect_tcp(context->arg0, context->arg1);
}

ForgeResult_Byte___NetworkIssue forge_net_read(struct std_Net_TcpStream*, int);

typedef struct {
    struct std_Net_TcpStream* arg0;
    int arg1;
    ForgeResult_Byte___NetworkIssue result;
} ForgeAsyncNative_forge_net_read_Byte___TcpStream_Int_Context;

static void ForgeAsyncNative_forge_net_read_Byte___TcpStream_Int_run(void* raw_context) {
    ForgeAsyncNative_forge_net_read_Byte___TcpStream_Int_Context* context = raw_context;
    context->result = forge_net_read(context->arg0, context->arg1);
}

ForgeResult_Int_NetworkIssue forge_net_write(struct std_Net_TcpStream*, ForgeArray_Byte);

typedef struct {
    struct std_Net_TcpStream* arg0;
    ForgeArray_Byte arg1;
    ForgeResult_Int_NetworkIssue result;
} ForgeAsyncNative_forge_net_write_Int_TcpStream_Byte___Context;

static void ForgeAsyncNative_forge_net_write_Int_TcpStream_Byte___run(void* raw_context) {
    ForgeAsyncNative_forge_net_write_Int_TcpStream_Byte___Context* context = raw_context;
    context->result = forge_net_write(context->arg0, context->arg1);
}

ForgeResult_HttpResponse_HttpIssue std_Http_Http_get(const char*);

typedef struct {
    const char* arg0;
    ForgeResult_HttpResponse_HttpIssue result;
} ForgeAsyncNative_std_Http_Http_get_HttpResponse_String_Context;

static void ForgeAsyncNative_std_Http_Http_get_HttpResponse_String_run(void* raw_context) {
    ForgeAsyncNative_std_Http_Http_get_HttpResponse_String_Context* context = raw_context;
    context->result = std_Http_Http_get(context->arg0);
}

ForgeResult_Int_HttpIssue std_Http_Http_status(const char* url) {
    ForgeAsyncNative_std_Http_Http_get_HttpResponse_String_Context forge_tmp_async_context1;
    forge_tmp_async_context1.arg0 = url;
    _ForgeAsyncTask* forge_tmp_async_task2 = _forge_async_task_new(ForgeAsyncNative_std_Http_Http_get_HttpResponse_String_run, &forge_tmp_async_context1);
    _forge_async_task_start(forge_tmp_async_task2);
    _forge_async_task_await(forge_tmp_async_task2);
    _forge_async_task_free(forge_tmp_async_task2);
    ForgeResult_HttpResponse_HttpIssue forge_tmp_outcome0 = forge_tmp_async_context1.result;
    if (forge_tmp_outcome0.tag == ForgeResult_HttpResponse_HttpIssue_OUTCOME_HTTPISSUE) {
        return (ForgeResult_Int_HttpIssue){.tag = ForgeResult_Int_HttpIssue_OUTCOME_HTTPISSUE, .outcome_HttpIssue = forge_tmp_outcome0.outcome_HttpIssue};
    }
    if (forge_tmp_outcome0.tag != ForgeResult_HttpResponse_HttpIssue_SUCCESS) {
        abort();
    }
    struct std_Http_HttpResponse* response = forge_tmp_outcome0.success;
    ForgeResult_Int_HttpIssue forge_tmp_return3 = (ForgeResult_Int_HttpIssue){.tag = ForgeResult_Int_HttpIssue_SUCCESS, .success = response->status};
    _forge_free_std_Http_HttpResponse(response);
    return forge_tmp_return3;
}

ForgeResult_HttpResponse_HttpIssue std_Http_Http_get(const char* url) {
    int schemeEnd = forge_string_index_of(url, "http://");
    if (schemeEnd != 0) {
        return (ForgeResult_HttpResponse_HttpIssue){.tag = ForgeResult_HttpResponse_HttpIssue_OUTCOME_HTTPISSUE, .outcome_HttpIssue = std_Http_HttpIssue_new("only http:// URLs are supported")};
    }
    char* afterScheme = forge_string_substring(url, 7, forge_string_length(url));
    int slash = forge_string_index_of(afterScheme, "/");
    int slashEnd = slash >= 0 ? slash : forge_string_length(afterScheme);
    char* hostPort = forge_string_substring(afterScheme, 0, slashEnd);
    char* path;
    if (slash >= 0) {
        path = forge_string_substring(afterScheme, slash, forge_string_length(afterScheme));
    } else {
        char* forge_tmp_string4 = _forge_string_copy("/");
        path = forge_tmp_string4;
    }
    int colon = forge_string_index_of(hostPort, ":");
    int hostEnd = colon >= 0 ? colon : forge_string_length(hostPort);
    char* host = forge_string_substring(hostPort, 0, hostEnd);
    int port = 80;
    if (colon >= 0) {
        char* forge_tmp_string5 = forge_string_substring(hostPort, colon + 1, forge_string_length(hostPort));
        port = forge_string_parse_int(forge_tmp_string5);
        free(forge_tmp_string5);
    }
    ForgeAsyncNative_forge_net_connect_tcp_TcpStream_String_Int_Context forge_tmp_async_context7;
    forge_tmp_async_context7.arg0 = host;
    forge_tmp_async_context7.arg1 = port;
    _ForgeAsyncTask* forge_tmp_async_task8 = _forge_async_task_new(ForgeAsyncNative_forge_net_connect_tcp_TcpStream_String_Int_run, &forge_tmp_async_context7);
    _forge_async_task_start(forge_tmp_async_task8);
    _forge_async_task_await(forge_tmp_async_task8);
    _forge_async_task_free(forge_tmp_async_task8);
    ForgeResult_TcpStream_NetworkIssue forge_tmp_outcome6 = forge_tmp_async_context7.result;
    struct std_Net_TcpStream* forge_tmp_catch9;
    if (forge_tmp_outcome6.tag == ForgeResult_TcpStream_NetworkIssue_SUCCESS) {
        forge_tmp_catch9 = forge_tmp_outcome6.success;
    } else if (forge_tmp_outcome6.tag == ForgeResult_TcpStream_NetworkIssue_OUTCOME_NETWORKISSUE) {
        struct std_Net_NetworkIssue* issue = forge_tmp_outcome6.outcome_NetworkIssue;
        ForgeResult_HttpResponse_HttpIssue forge_tmp_return10 = (ForgeResult_HttpResponse_HttpIssue){.tag = ForgeResult_HttpResponse_HttpIssue_OUTCOME_HTTPISSUE, .outcome_HttpIssue = std_Http_HttpIssue_new(issue->message)};
        free((void*)host);
        free((void*)path);
        free((void*)hostPort);
        free((void*)afterScheme);
        return forge_tmp_return10;
    } else {
        abort();
    }
    struct std_Net_TcpStream* stream = forge_tmp_catch9;
    char* forge_tmp_string11 = _forge_string_concat(7, "GET ", path, " HTTP/1.0\r\n", "Host: ", host, "\r\n", "Connection: close\r\n\r\n");
    char* request = forge_tmp_string11;
    ForgeAsyncNative_forge_net_write_Int_TcpStream_Byte___Context forge_tmp_async_context13;
    forge_tmp_async_context13.arg0 = stream;
    ForgeArray_Byte forge_tmp_array14 = forge_string_to_bytes(request);
    forge_tmp_async_context13.arg1 = forge_tmp_array14;
    _ForgeAsyncTask* forge_tmp_async_task15 = _forge_async_task_new(ForgeAsyncNative_forge_net_write_Int_TcpStream_Byte___run, &forge_tmp_async_context13);
    _forge_async_task_start(forge_tmp_async_task15);
    _forge_async_task_await(forge_tmp_async_task15);
    _forge_async_task_free(forge_tmp_async_task15);
    ForgeResult_Int_NetworkIssue forge_tmp_outcome12 = forge_tmp_async_context13.result;
    int forge_tmp_catch16;
    if (forge_tmp_outcome12.tag == ForgeResult_Int_NetworkIssue_SUCCESS) {
        forge_tmp_catch16 = forge_tmp_outcome12.success;
    } else if (forge_tmp_outcome12.tag == ForgeResult_Int_NetworkIssue_OUTCOME_NETWORKISSUE) {
        struct std_Net_NetworkIssue* issue = forge_tmp_outcome12.outcome_NetworkIssue;
        ForgeResult_HttpResponse_HttpIssue forge_tmp_return17 = (ForgeResult_HttpResponse_HttpIssue){.tag = ForgeResult_HttpResponse_HttpIssue_OUTCOME_HTTPISSUE, .outcome_HttpIssue = std_Http_HttpIssue_new(issue->message)};
        free((void*)request);
        free((void*)host);
        free((void*)path);
        free((void*)hostPort);
        free((void*)afterScheme);
        _forge_free_std_Net_TcpStream(stream);
        return forge_tmp_return17;
    } else {
        abort();
    }
    int written = forge_tmp_catch16;
    free(forge_tmp_array14.data);
    char* forge_tmp_string18 = _forge_string_copy("");
    char* raw = forge_tmp_string18;
    bool done = false;
    while (true) {
    bool forge_tmp_loop_condition19 = !done;
    if (!forge_tmp_loop_condition19) break;
    {
            ForgeAsyncNative_forge_net_read_Byte___TcpStream_Int_Context forge_tmp_async_context21;
            forge_tmp_async_context21.arg0 = stream;
            forge_tmp_async_context21.arg1 = 4096;
            _ForgeAsyncTask* forge_tmp_async_task22 = _forge_async_task_new(ForgeAsyncNative_forge_net_read_Byte___TcpStream_Int_run, &forge_tmp_async_context21);
            _forge_async_task_start(forge_tmp_async_task22);
            _forge_async_task_await(forge_tmp_async_task22);
            _forge_async_task_free(forge_tmp_async_task22);
            ForgeResult_Byte___NetworkIssue forge_tmp_outcome20 = forge_tmp_async_context21.result;
            ForgeArray_Byte forge_tmp_catch23;
            if (forge_tmp_outcome20.tag == ForgeResult_Byte___NetworkIssue_SUCCESS) {
                forge_tmp_catch23 = forge_tmp_outcome20.success;
            } else if (forge_tmp_outcome20.tag == ForgeResult_Byte___NetworkIssue_OUTCOME_NETWORKISSUE) {
                struct std_Net_NetworkIssue* issue = forge_tmp_outcome20.outcome_NetworkIssue;
                ForgeResult_HttpResponse_HttpIssue forge_tmp_return24 = (ForgeResult_HttpResponse_HttpIssue){.tag = ForgeResult_HttpResponse_HttpIssue_OUTCOME_HTTPISSUE, .outcome_HttpIssue = std_Http_HttpIssue_new(issue->message)};
                free((void*)raw);
                free((void*)request);
                free((void*)host);
                free((void*)path);
                free((void*)hostPort);
                free((void*)afterScheme);
                _forge_free_std_Net_TcpStream(stream);
                return forge_tmp_return24;
            } else {
                abort();
            }
            ForgeArray_Byte chunk = forge_tmp_catch23;
            if ((int)chunk.len == 0) {
                done = true;
            } else {
                char* forge_tmp_string25 = forge_string_from_bytes(chunk);
                char* forge_tmp_string26 = _forge_string_concat(2, raw, forge_tmp_string25);
                free((void*)raw);
                raw = forge_tmp_string26;
                free(forge_tmp_string25);
            }
            free(chunk.data);
        }
}
    forge_net_close(stream);
    char* statusText = forge_string_substring(raw, 9, 12);
    int status = forge_string_parse_int(statusText);
    int separator = forge_string_index_of(raw, "\r\n\r\n");
    char* forge_tmp_string27 = _forge_string_copy("");
    char* body = forge_tmp_string27;
    if (separator >= 0) {
        free((void*)body);
        body = forge_string_substring(raw, separator + 4, forge_string_length(raw));
    }
    ForgeResult_HttpResponse_HttpIssue forge_tmp_return28 = (ForgeResult_HttpResponse_HttpIssue){.tag = ForgeResult_HttpResponse_HttpIssue_SUCCESS, .success = std_Http_HttpResponse_new(status, body)};
    free((void*)body);
    free((void*)statusText);
    free((void*)raw);
    free((void*)request);
    free((void*)host);
    free((void*)path);
    free((void*)hostPort);
    free((void*)afterScheme);
    _forge_free_std_Net_TcpStream(stream);
    return forge_tmp_return28;
}

struct std_Http_Http* std_Http_Http_new(void) {
    struct std_Http_Http* this = _forge_alloc(sizeof(struct std_Http_Http));
    return this;
}

void _forge_free_std_Http_Http(struct std_Http_Http* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
