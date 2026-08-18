#include "native_math.h"
#include "Math.h"
#include "../forge_runtime.h"

#include <stdlib.h>

struct nativepkg_Math* nativepkg_Math_new(void) {
    struct nativepkg_Math* this = _forge_alloc(sizeof(struct nativepkg_Math));
    return this;
}

void _forge_free_nativepkg_Math(struct nativepkg_Math* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
