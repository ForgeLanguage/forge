#pragma once

struct std_Net_TcpListener {
    int handle;
};

void _forge_free_std_Net_TcpListener(struct std_Net_TcpListener* value);
struct std_Net_TcpListener* std_Net_TcpListener_new(void);
