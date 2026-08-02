#include "forge_runtime.h"
#include "std/Net/Network.h"
#include "std/Net/NetworkIssue.h"
#include "std/Net/TcpListener.h"
#include "std/Net/TcpStream.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static ForgeResult_TcpStream_NetworkIssue forge_net_stream_issue(const char* message) {
    struct std_Net_NetworkIssue* issue = std_Net_NetworkIssue_new();
    issue->message = _forge_string_copy(message);
    return (ForgeResult_TcpStream_NetworkIssue){
        .tag = ForgeResult_TcpStream_NetworkIssue_OUTCOME_NETWORKISSUE,
        .outcome_NetworkIssue = issue,
    };
}

static ForgeResult_TcpListener_NetworkIssue forge_net_listener_issue(const char* message) {
    struct std_Net_NetworkIssue* issue = std_Net_NetworkIssue_new();
    issue->message = _forge_string_copy(message);
    return (ForgeResult_TcpListener_NetworkIssue){
        .tag = ForgeResult_TcpListener_NetworkIssue_OUTCOME_NETWORKISSUE,
        .outcome_NetworkIssue = issue,
    };
}

static ForgeResult_Byte___NetworkIssue forge_net_bytes_issue(const char* message) {
    struct std_Net_NetworkIssue* issue = std_Net_NetworkIssue_new();
    issue->message = _forge_string_copy(message);
    return (ForgeResult_Byte___NetworkIssue){
        .tag = ForgeResult_Byte___NetworkIssue_OUTCOME_NETWORKISSUE,
        .outcome_NetworkIssue = issue,
    };
}

static ForgeResult_Int_NetworkIssue forge_net_int_issue(const char* message) {
    struct std_Net_NetworkIssue* issue = std_Net_NetworkIssue_new();
    issue->message = _forge_string_copy(message);
    return (ForgeResult_Int_NetworkIssue){
        .tag = ForgeResult_Int_NetworkIssue_OUTCOME_NETWORKISSUE,
        .outcome_NetworkIssue = issue,
    };
}

ForgeResult_TcpListener_NetworkIssue forge_net_listen_tcp(int port) {
    if (port < 0 || port > 65535) {
        return forge_net_listener_issue("port must be between 0 and 65535");
    }

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        return forge_net_listener_issue(strerror(errno));
    }

    int reuse = 1;
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse)) != 0) {
        int error = errno;
        close(fd);
        return forge_net_listener_issue(strerror(error));
    }

    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons((uint16_t)port);

    if (bind(fd, (struct sockaddr*)&address, sizeof(address)) != 0) {
        int error = errno;
        close(fd);
        return forge_net_listener_issue(strerror(error));
    }
    if (listen(fd, 16) != 0) {
        int error = errno;
        close(fd);
        return forge_net_listener_issue(strerror(error));
    }

    struct std_Net_TcpListener* listener = std_Net_TcpListener_new();
    listener->handle = fd;
    return (ForgeResult_TcpListener_NetworkIssue){
        .tag = ForgeResult_TcpListener_NetworkIssue_SUCCESS,
        .success = listener,
    };
}

ForgeResult_TcpStream_NetworkIssue forge_net_accept_tcp(struct std_Net_TcpListener* listener) {
    if (listener == NULL || listener->handle < 0) {
        return forge_net_stream_issue("invalid TCP listener");
    }

    int fd;
    do {
        fd = accept(listener->handle, NULL, NULL);
    } while (fd < 0 && errno == EINTR);
    if (fd < 0) {
        return forge_net_stream_issue(strerror(errno));
    }

    struct std_Net_TcpStream* stream = std_Net_TcpStream_new();
    stream->handle = fd;
    return (ForgeResult_TcpStream_NetworkIssue){
        .tag = ForgeResult_TcpStream_NetworkIssue_SUCCESS,
        .success = stream,
    };
}

ForgeResult_TcpStream_NetworkIssue forge_net_connect_tcp(const char* host, int port) {
    char service[16];
    snprintf(service, sizeof(service), "%d", port);

    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    struct addrinfo* addresses = NULL;
    int status = getaddrinfo(host, service, &hints, &addresses);
    if (status != 0) {
        return forge_net_stream_issue(gai_strerror(status));
    }

    int fd = -1;
    for (struct addrinfo* cursor = addresses; cursor != NULL; cursor = cursor->ai_next) {
        fd = socket(cursor->ai_family, cursor->ai_socktype, cursor->ai_protocol);
        if (fd < 0) {
            continue;
        }
        if (connect(fd, cursor->ai_addr, cursor->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(addresses);

    if (fd < 0) {
        return forge_net_stream_issue(strerror(errno));
    }

    struct std_Net_TcpStream* stream = std_Net_TcpStream_new();
    stream->handle = fd;
    return (ForgeResult_TcpStream_NetworkIssue){
        .tag = ForgeResult_TcpStream_NetworkIssue_SUCCESS,
        .success = stream,
    };
}

ForgeResult_Byte___NetworkIssue forge_net_read(struct std_Net_TcpStream* stream, int max_bytes) {
    if (stream == NULL || stream->handle < 0) {
        return forge_net_bytes_issue("invalid TCP stream");
    }
    if (max_bytes < 0) {
        return forge_net_bytes_issue("maxBytes must be non-negative");
    }

    ForgeArray_Byte result;
    result.len = 0;
    result.cap = (size_t)max_bytes;
    result.data = _forge_array_new((size_t)max_bytes, sizeof(signed char));
    if (max_bytes == 0) {
        return (ForgeResult_Byte___NetworkIssue){
            .tag = ForgeResult_Byte___NetworkIssue_SUCCESS,
            .success = result,
        };
    }

    ssize_t count = recv(stream->handle, result.data, (size_t)max_bytes, 0);
    if (count < 0) {
        free(result.data);
        return forge_net_bytes_issue(strerror(errno));
    }
    result.len = (size_t)count;
    return (ForgeResult_Byte___NetworkIssue){
        .tag = ForgeResult_Byte___NetworkIssue_SUCCESS,
        .success = result,
    };
}

ForgeResult_Int_NetworkIssue forge_net_write(struct std_Net_TcpStream* stream, ForgeArray_Byte bytes) {
    if (stream == NULL || stream->handle < 0) {
        return forge_net_int_issue("invalid TCP stream");
    }

    size_t sent = 0;
    while (sent < bytes.len) {
        ssize_t count = send(stream->handle, bytes.data + sent, bytes.len - sent, 0);
        if (count < 0) {
            return forge_net_int_issue(strerror(errno));
        }
        if (count == 0) {
            return forge_net_int_issue("socket write returned zero bytes");
        }
        sent += (size_t)count;
    }

    return (ForgeResult_Int_NetworkIssue){
        .tag = ForgeResult_Int_NetworkIssue_SUCCESS,
        .success = (int)sent,
    };
}

void forge_net_close_listener(struct std_Net_TcpListener* listener) {
    if (listener == NULL || listener->handle < 0) {
        return;
    }
    close(listener->handle);
    listener->handle = -1;
}

void forge_net_close(struct std_Net_TcpStream* stream) {
    if (stream == NULL || stream->handle < 0) {
        return;
    }
    close(stream->handle);
    stream->handle = -1;
}
