#include "forge_std_net.h"
#include "forge_std_string.h"
#include "Network.h"
#include "TcpStream.h"
#include "TcpListener.h"
#include "NetworkIssue.h"
#include "../../forge_runtime.h"

#include <stdlib.h>

struct std_Net_Network* std_Net_Network_new(void) {
    struct std_Net_Network* this = _forge_alloc(sizeof(struct std_Net_Network));
    return this;
}

void _forge_free_std_Net_Network(struct std_Net_Network* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
