#include "Vector2Int.h"
#include "../forge_runtime.h"

#include <stdlib.h>

struct Math_Vector2Int* Math_Vector2Int_new(int x, int y) {
    struct Math_Vector2Int* this = _forge_alloc(sizeof(struct Math_Vector2Int));
    this->x = x;
    this->y = y;
    return this;
}

void _forge_free_Math_Vector2Int(struct Math_Vector2Int* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
