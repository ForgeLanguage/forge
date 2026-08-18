#pragma once

struct std_Net_TcpStream {
    int handle;
};

void _forge_free_std_Net_TcpStream(struct std_Net_TcpStream* value);
struct std_Net_TcpStream* std_Net_TcpStream_new(void);
