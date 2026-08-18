#include "Figure.h"
#include "Vector2Int.h"
#include "../forge_runtime.h"

#include <stdlib.h>

int Math_Figure_sum(struct Math_Vector2Int* point) {
    return point->x + point->y;
}

struct Math_Figure* Math_Figure_new(void) {
    struct Math_Figure* this = _forge_alloc(sizeof(struct Math_Figure));
    return this;
}

void _forge_free_Math_Figure(struct Math_Figure* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
