#include "Vector2Int.h"

#pragma once

struct Math_Figure {
    char _forge_empty;
};

void _forge_free_Math_Figure(struct Math_Figure* value);
int Math_Figure_sum(struct Math_Vector2Int* point);
struct Math_Figure* Math_Figure_new(void);
