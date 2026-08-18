#include "TcpStream.h"
#include "TcpListener.h"
#include "NetworkIssue.h"

#pragma once

#include <stdint.h>
#include <stdlib.h>

#ifndef FORGEARRAY_BYTE_DEFINED
#define FORGEARRAY_BYTE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    signed char* data;
} ForgeArray_Byte;
#endif

struct std_Net_Network {
    char _forge_empty;
};

#ifndef FORGEARRAY_BYTE_DEFINED
#define FORGEARRAY_BYTE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    signed char* data;
} ForgeArray_Byte;
#endif

#ifndef FORGERESULT_BYTE___NETWORKISSUE_DEFINED
#define FORGERESULT_BYTE___NETWORKISSUE_DEFINED
typedef enum {
    ForgeResult_Byte___NetworkIssue_SUCCESS = 0,
    ForgeResult_Byte___NetworkIssue_OUTCOME_NETWORKISSUE = 1
} ForgeResult_Byte___NetworkIssueTag;

typedef struct {
    uint8_t tag;
    ForgeArray_Byte success;
    struct std_Net_NetworkIssue* outcome_NetworkIssue;
} ForgeResult_Byte___NetworkIssue;
#endif

#ifndef FORGERESULT_INT_NETWORKISSUE_DEFINED
#define FORGERESULT_INT_NETWORKISSUE_DEFINED
typedef enum {
    ForgeResult_Int_NetworkIssue_SUCCESS = 0,
    ForgeResult_Int_NetworkIssue_OUTCOME_NETWORKISSUE = 1
} ForgeResult_Int_NetworkIssueTag;

typedef struct {
    uint8_t tag;
    int success;
    struct std_Net_NetworkIssue* outcome_NetworkIssue;
} ForgeResult_Int_NetworkIssue;
#endif

#ifndef FORGERESULT_TCPLISTENER_NETWORKISSUE_DEFINED
#define FORGERESULT_TCPLISTENER_NETWORKISSUE_DEFINED
typedef enum {
    ForgeResult_TcpListener_NetworkIssue_SUCCESS = 0,
    ForgeResult_TcpListener_NetworkIssue_OUTCOME_NETWORKISSUE = 1
} ForgeResult_TcpListener_NetworkIssueTag;

typedef struct {
    uint8_t tag;
    struct std_Net_TcpListener* success;
    struct std_Net_NetworkIssue* outcome_NetworkIssue;
} ForgeResult_TcpListener_NetworkIssue;
#endif

#ifndef FORGERESULT_TCPSTREAM_NETWORKISSUE_DEFINED
#define FORGERESULT_TCPSTREAM_NETWORKISSUE_DEFINED
typedef enum {
    ForgeResult_TcpStream_NetworkIssue_SUCCESS = 0,
    ForgeResult_TcpStream_NetworkIssue_OUTCOME_NETWORKISSUE = 1
} ForgeResult_TcpStream_NetworkIssueTag;

typedef struct {
    uint8_t tag;
    struct std_Net_TcpStream* success;
    struct std_Net_NetworkIssue* outcome_NetworkIssue;
} ForgeResult_TcpStream_NetworkIssue;
#endif

void _forge_free_std_Net_Network(struct std_Net_Network* value);
ForgeResult_TcpListener_NetworkIssue forge_net_listen_tcp(int port);
ForgeResult_TcpStream_NetworkIssue forge_net_accept_tcp(struct std_Net_TcpListener* listener);
ForgeResult_TcpStream_NetworkIssue forge_net_connect_tcp(const char* host, int port);
ForgeResult_Byte___NetworkIssue forge_net_read(struct std_Net_TcpStream* stream, int maxBytes);
ForgeResult_Int_NetworkIssue forge_net_write(struct std_Net_TcpStream* stream, ForgeArray_Byte bytes);
void forge_net_close_listener(struct std_Net_TcpListener* listener);
void forge_net_close(struct std_Net_TcpStream* stream);
struct std_Net_Network* std_Net_Network_new(void);
