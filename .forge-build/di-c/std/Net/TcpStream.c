#include "forge_std_net.h"
#include "forge_std_string.h"
#include "TcpStream.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Net_TcpStream* std_Net_TcpStream_new(void) {
    struct std_Net_TcpStream* this = _forge_alloc(sizeof(struct std_Net_TcpStream));
    return this;
}

void _forge_free_std_Net_TcpStream(struct std_Net_TcpStream* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
