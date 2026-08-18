#include "forge_std_net.h"
#include "forge_std_string.h"
#include "TcpListener.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Net_TcpListener* std_Net_TcpListener_new(void) {
    struct std_Net_TcpListener* this = _forge_alloc(sizeof(struct std_Net_TcpListener));
    return this;
}

void _forge_free_std_Net_TcpListener(struct std_Net_TcpListener* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
