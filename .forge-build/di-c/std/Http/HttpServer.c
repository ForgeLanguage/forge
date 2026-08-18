#include "forge_std_net.h"
#include "forge_std_string.h"
#include "HttpServer.h"
#include "HttpIssue.h"
#include "HttpServerHandler.h"
#include "HttpServerResponse.h"
#include "../Net/Network.h"
#include "../Net/NetworkIssue.h"
#include "../Net/TcpStream.h"
#include "../../forge_runtime.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static char* _forge_Int_to_string(int value) {
    int len = snprintf(NULL, 0, "%lld", (long long)value);
    char* result = _forge_alloc((size_t)len + 1);
    snprintf(result, (size_t)len + 1, "%lld", (long long)value);
    return result;
}

#ifndef FORGEARRAY_BYTE_DEFINED
#define FORGEARRAY_BYTE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    signed char* data;
} ForgeArray_Byte;
#endif

#ifndef FORGEARRAY_STRING_DEFINED
#define FORGEARRAY_STRING_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    const char** data;
} ForgeArray_String;
#endif

#ifndef FORGERESULT_STRING___PATTERNMISMATCH_DEFINED
#define FORGERESULT_STRING___PATTERNMISMATCH_DEFINED
typedef enum {
    ForgeResult_String___PatternMismatch_SUCCESS = 0,
    ForgeResult_String___PatternMismatch_OUTCOME_PATTERNMISMATCH = 1
} ForgeResult_String___PatternMismatchTag;

typedef struct {
    uint8_t tag;
    ForgeArray_String success;
    struct ForgePatternMismatch* outcome_PatternMismatch;
} ForgeResult_String___PatternMismatch;
#endif

ForgeResult_TcpStream_NetworkIssue forge_net_accept_tcp(struct std_Net_TcpListener*);

typedef struct {
    struct std_Net_TcpListener* arg0;
    ForgeResult_TcpStream_NetworkIssue result;
} ForgeAsyncNative_forge_net_accept_tcp_TcpStream_TcpListener_Context;

static void ForgeAsyncNative_forge_net_accept_tcp_TcpStream_TcpListener_run(void* raw_context) {
    ForgeAsyncNative_forge_net_accept_tcp_TcpStream_TcpListener_Context* context = raw_context;
    context->result = forge_net_accept_tcp(context->arg0);
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

bool std_Http_HttpServer_serveConnection(struct std_Net_TcpStream*, struct std_Http_HttpServerHandler);

typedef struct {
    struct std_Net_TcpStream* arg0;
    struct std_Http_HttpServerHandler arg1;
    bool result;
} ForgeAsyncNative_std_Http_HttpServer_serveConnection_Bool_TcpStream_HttpServerHandler_Context;

static void ForgeAsyncNative_std_Http_HttpServer_serveConnection_Bool_TcpStream_HttpServerHandler_run(void* raw_context) {
    ForgeAsyncNative_std_Http_HttpServer_serveConnection_Bool_TcpStream_HttpServerHandler_Context* context = raw_context;
    context->result = std_Http_HttpServer_serveConnection(context->arg0, context->arg1);
}

ForgeResult_Void_HttpIssue std_Http_HttpServer_serve(int port, struct std_Http_HttpServerHandler handler) {
    ForgeResult_TcpListener_NetworkIssue forge_tmp_outcome0 = forge_net_listen_tcp(port);
    struct std_Net_TcpListener* forge_tmp_catch1;
    if (forge_tmp_outcome0.tag == ForgeResult_TcpListener_NetworkIssue_SUCCESS) {
        forge_tmp_catch1 = forge_tmp_outcome0.success;
    } else if (forge_tmp_outcome0.tag == ForgeResult_TcpListener_NetworkIssue_OUTCOME_NETWORKISSUE) {
        struct std_Net_NetworkIssue* issue = forge_tmp_outcome0.outcome_NetworkIssue;
        return (ForgeResult_Void_HttpIssue){.tag = ForgeResult_Void_HttpIssue_OUTCOME_HTTPISSUE, .outcome_HttpIssue = std_Http_HttpIssue_new(issue->message)};
    } else {
        abort();
    }
    struct std_Net_TcpListener* listener = forge_tmp_catch1;
    while (true) {
    bool forge_tmp_loop_condition2 = true;
    if (!forge_tmp_loop_condition2) break;
    {
            ForgeAsyncNative_forge_net_accept_tcp_TcpStream_TcpListener_Context forge_tmp_async_context4;
            forge_tmp_async_context4.arg0 = listener;
            _ForgeAsyncTask* forge_tmp_async_task5 = _forge_async_task_new(ForgeAsyncNative_forge_net_accept_tcp_TcpStream_TcpListener_run, &forge_tmp_async_context4);
            _forge_async_task_start(forge_tmp_async_task5);
            _forge_async_task_await(forge_tmp_async_task5);
            _forge_async_task_free(forge_tmp_async_task5);
            ForgeResult_TcpStream_NetworkIssue forge_tmp_outcome3 = forge_tmp_async_context4.result;
            struct std_Net_TcpStream* forge_tmp_catch6;
            if (forge_tmp_outcome3.tag == ForgeResult_TcpStream_NetworkIssue_SUCCESS) {
                forge_tmp_catch6 = forge_tmp_outcome3.success;
            } else if (forge_tmp_outcome3.tag == ForgeResult_TcpStream_NetworkIssue_OUTCOME_NETWORKISSUE) {
                struct std_Net_NetworkIssue* issue = forge_tmp_outcome3.outcome_NetworkIssue;
                forge_net_close_listener(listener);
                ForgeResult_Void_HttpIssue forge_tmp_return7 = (ForgeResult_Void_HttpIssue){.tag = ForgeResult_Void_HttpIssue_OUTCOME_HTTPISSUE, .outcome_HttpIssue = std_Http_HttpIssue_new(issue->message)};
                _forge_free_std_Net_TcpListener(listener);
                return forge_tmp_return7;
            } else {
                abort();
            }
            struct std_Net_TcpStream* stream = forge_tmp_catch6;
            ForgeAsyncNative_std_Http_HttpServer_serveConnection_Bool_TcpStream_HttpServerHandler_Context forge_tmp_async_context8;
            forge_tmp_async_context8.arg0 = stream;
            forge_tmp_async_context8.arg1 = handler;
            _ForgeAsyncTask* forge_tmp_async_task9 = _forge_async_task_new(ForgeAsyncNative_std_Http_HttpServer_serveConnection_Bool_TcpStream_HttpServerHandler_run, &forge_tmp_async_context8);
            _forge_async_task_start(forge_tmp_async_task9);
            _forge_async_task_await(forge_tmp_async_task9);
            _forge_async_task_free(forge_tmp_async_task9);
            bool served = forge_tmp_async_context8.result;
        }
}
    _forge_free_std_Net_TcpListener(listener);
    return (ForgeResult_Void_HttpIssue){.tag = ForgeResult_Void_HttpIssue_SUCCESS};
}

bool std_Http_HttpServer_serveConnection(struct std_Net_TcpStream* stream, struct std_Http_HttpServerHandler handler) {
    bool forge_tmp_return42;
    char* forge_tmp_string10 = _forge_string_copy("");
    char* raw = forge_tmp_string10;
    int headerEnd = -1;
    int bodyLength = 0;
    const char* forge_tmp_loop_result11;
    bool forge_tmp_loop_has_value12 = false;
    while (true) {
        bool forge_tmp_loop_condition22 = true;
        if (!forge_tmp_loop_condition22) break;
        {
                ForgeAsyncNative_forge_net_read_Byte___TcpStream_Int_Context forge_tmp_async_context14;
                forge_tmp_async_context14.arg0 = stream;
                forge_tmp_async_context14.arg1 = 4096;
                _ForgeAsyncTask* forge_tmp_async_task15 = _forge_async_task_new(ForgeAsyncNative_forge_net_read_Byte___TcpStream_Int_run, &forge_tmp_async_context14);
                _forge_async_task_start(forge_tmp_async_task15);
                _forge_async_task_await(forge_tmp_async_task15);
                _forge_async_task_free(forge_tmp_async_task15);
                ForgeResult_Byte___NetworkIssue forge_tmp_outcome13 = forge_tmp_async_context14.result;
                ForgeArray_Byte forge_tmp_catch16;
                if (forge_tmp_outcome13.tag == ForgeResult_Byte___NetworkIssue_SUCCESS) {
                    forge_tmp_catch16 = forge_tmp_outcome13.success;
                } else if (forge_tmp_outcome13.tag == ForgeResult_Byte___NetworkIssue_OUTCOME_NETWORKISSUE) {
                    struct std_Net_NetworkIssue* issue = forge_tmp_outcome13.outcome_NetworkIssue;
                    forge_net_close(stream);
                    bool forge_tmp_return17 = false;
                    free((void*)raw);
                    _forge_free_std_Net_TcpStream(stream);
                    return forge_tmp_return17;
                } else {
                    abort();
                }
                ForgeArray_Byte chunk = forge_tmp_catch16;
                if ((int)chunk.len == 0) {
                    free(chunk.data);
        break;
                }
                char* forge_tmp_string18 = forge_string_from_bytes(chunk);
                char* forge_tmp_string19 = _forge_string_concat(2, raw, forge_tmp_string18);
                free((void*)raw);
                raw = forge_tmp_string19;
                free(forge_tmp_string18);
                if (headerEnd < 0) {
                    headerEnd = forge_string_index_of(raw, "\r\n\r\n");
                    if (headerEnd >= 0) {
                        const char* contentLengthMarker = "Content-Length: ";
                        int contentLengthStart = forge_string_index_of(raw, contentLengthMarker);
                        if ((contentLengthStart >= 0) && (contentLengthStart < headerEnd)) {
                            int lengthStart = contentLengthStart + forge_string_length(contentLengthMarker);
                            char* lengthTail = forge_string_substring(raw, lengthStart, headerEnd);
                            int lengthEnd = forge_string_index_of(lengthTail, "\r\n");
                            char* lengthText;
                            if (lengthEnd >= 0) {
                                lengthText = forge_string_substring(lengthTail, 0, lengthEnd);
                            } else {
                                char* forge_tmp_string20 = _forge_string_copy(lengthTail);
                                lengthText = forge_tmp_string20;
                            }
                            bodyLength = forge_string_parse_int(lengthText);
                            free((void*)lengthText);
                            free((void*)lengthTail);
                        }
                    }
                }
                if ((headerEnd >= 0) && (forge_string_length(raw) >= ((headerEnd + 4) + bodyLength))) {
                    char* forge_tmp_string21 = _forge_string_copy(raw);
        forge_tmp_loop_result11 = forge_tmp_string21;
        forge_tmp_loop_has_value12 = true;
        free(chunk.data);
        break;
                }
                free(chunk.data);
            }
    }
    if (!forge_tmp_loop_has_value12) {
        forge_tmp_loop_result11 = NULL;
    }
    char* request = forge_tmp_loop_result11;
    if (request != NULL) {
        int requestLineEnd = forge_string_index_of(request, "\r\n");
        char* requestLine = forge_string_substring(request, 0, requestLineEnd);
        ForgeArray_String parts = forge_string_split(requestLine, " ", 3);
        int forge_tmp_array_owned23 = 0;
        ForgeResult_String___PatternMismatch forge_tmp_outcome25;
        ForgeArray_String forge_tmp_array_pattern26 = parts;
        if (forge_tmp_array_pattern26.len >= 3) {
            forge_tmp_outcome25 = (ForgeResult_String___PatternMismatch){.tag = ForgeResult_String___PatternMismatch_SUCCESS, .success = forge_tmp_array_pattern26};
        } else {
            forge_tmp_outcome25 = (ForgeResult_String___PatternMismatch){.tag = ForgeResult_String___PatternMismatch_OUTCOME_PATTERNMISMATCH, .outcome_PatternMismatch = NULL};
        }
        ForgeResult_String___PatternMismatch forge_tmp_outcome24 = forge_tmp_outcome25;
        ForgeArray_String forge_tmp_catch27;
        if (forge_tmp_outcome24.tag == ForgeResult_String___PatternMismatch_SUCCESS) {
            forge_tmp_catch27 = forge_tmp_outcome24.success;
            forge_tmp_array_owned23 = 0;
        } else if (forge_tmp_outcome24.tag == ForgeResult_String___PatternMismatch_OUTCOME_PATTERNMISMATCH) {
            struct ForgePatternMismatch* issue = forge_tmp_outcome24.outcome_PatternMismatch;
            forge_net_close(stream);
            bool forge_tmp_return28 = false;
            free((void*)requestLine);
            free((void*)request);
            free((void*)raw);
            for (size_t _forge_i = 0; _forge_i < parts.len; _forge_i += 1) {
                free((void*)parts.data[_forge_i]);
            }
            free(parts.data);
            _forge_free_std_Net_TcpStream(stream);
            return forge_tmp_return28;
        } else {
            abort();
        }
        ForgeArray_String forge_destructure_source0 = forge_tmp_catch27;
        char* forge_tmp_string29 = _forge_string_copy(forge_destructure_source0.data[0]);
        char* method = forge_tmp_string29;
        char* forge_tmp_string30 = _forge_string_copy(forge_destructure_source0.data[1]);
        char* path = forge_tmp_string30;
        char* forge_tmp_string31 = _forge_string_copy(forge_destructure_source0.data[2]);
        char* protocol = forge_tmp_string31;
        char* body = forge_string_substring(request, headerEnd + 4, forge_string_length(request));
        struct std_Http_HttpServerResponse* response = handler.vtable->handle(handler.object, path, body);
        ForgeArray_Byte responseBytes = forge_string_to_bytes(response->body);
        char* forge_tmp_string32 = _forge_Int_to_string(response->status);
        char* forge_tmp_string33 = _forge_Int_to_string((int)responseBytes.len);
        char* forge_tmp_string34 = _forge_string_concat(8, "HTTP/1.1 ", forge_tmp_string32, " \r\n", "Content-Type: application/json\r\n", "Content-Length: ", forge_tmp_string33, "\r\n", "Connection: close\r\n\r\n");
        char* responseHead = forge_tmp_string34;
        free(forge_tmp_string32);
        free(forge_tmp_string33);
        ForgeAsyncNative_forge_net_write_Int_TcpStream_Byte___Context forge_tmp_async_context36;
        forge_tmp_async_context36.arg0 = stream;
        char* forge_tmp_string37 = _forge_string_concat(2, responseHead, response->body);
        ForgeArray_Byte forge_tmp_array38 = forge_string_to_bytes(forge_tmp_string37);
        forge_tmp_async_context36.arg1 = forge_tmp_array38;
        _ForgeAsyncTask* forge_tmp_async_task39 = _forge_async_task_new(ForgeAsyncNative_forge_net_write_Int_TcpStream_Byte___run, &forge_tmp_async_context36);
        _forge_async_task_start(forge_tmp_async_task39);
        _forge_async_task_await(forge_tmp_async_task39);
        _forge_async_task_free(forge_tmp_async_task39);
        ForgeResult_Int_NetworkIssue forge_tmp_outcome35 = forge_tmp_async_context36.result;
        int forge_tmp_catch40;
        if (forge_tmp_outcome35.tag == ForgeResult_Int_NetworkIssue_SUCCESS) {
            forge_tmp_catch40 = forge_tmp_outcome35.success;
        } else if (forge_tmp_outcome35.tag == ForgeResult_Int_NetworkIssue_OUTCOME_NETWORKISSUE) {
            struct std_Net_NetworkIssue* issue = forge_tmp_outcome35.outcome_NetworkIssue;
            forge_net_close(stream);
            bool forge_tmp_return41 = false;
            free((void*)responseHead);
            free((void*)body);
            free((void*)protocol);
            free((void*)path);
            free((void*)method);
            free((void*)requestLine);
            free((void*)request);
            free((void*)raw);
            free(responseBytes.data);
            if (forge_tmp_array_owned23) {
                for (size_t _forge_i = 0; _forge_i < forge_destructure_source0.len; _forge_i += 1) {
                    free((void*)forge_destructure_source0.data[_forge_i]);
                }
                free(forge_destructure_source0.data);
            }
            for (size_t _forge_i = 0; _forge_i < parts.len; _forge_i += 1) {
                free((void*)parts.data[_forge_i]);
            }
            free(parts.data);
            _forge_free_std_Http_HttpServerResponse(response);
            _forge_free_std_Net_TcpStream(stream);
            return forge_tmp_return41;
        } else {
            abort();
        }
        int written = forge_tmp_catch40;
        free(forge_tmp_string37);
        free(forge_tmp_array38.data);
        free((void*)responseHead);
        free((void*)body);
        free((void*)protocol);
        free((void*)path);
        free((void*)method);
        free((void*)requestLine);
        free(responseBytes.data);
        if (forge_tmp_array_owned23) {
            for (size_t _forge_i = 0; _forge_i < forge_destructure_source0.len; _forge_i += 1) {
                free((void*)forge_destructure_source0.data[_forge_i]);
            }
            free(forge_destructure_source0.data);
        }
        for (size_t _forge_i = 0; _forge_i < parts.len; _forge_i += 1) {
            free((void*)parts.data[_forge_i]);
        }
        free(parts.data);
        _forge_free_std_Http_HttpServerResponse(response);
    }
    forge_net_close(stream);
    forge_tmp_return42 = true;
    goto cleanup;
    cleanup:
    free((void*)request);
    free((void*)raw);
    _forge_free_std_Net_TcpStream(stream);
    return forge_tmp_return42;
}

struct std_Http_HttpServer* std_Http_HttpServer_new(void) {
    struct std_Http_HttpServer* this = _forge_alloc(sizeof(struct std_Http_HttpServer));
    return this;
}

void _forge_free_std_Http_HttpServer(struct std_Http_HttpServer* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
