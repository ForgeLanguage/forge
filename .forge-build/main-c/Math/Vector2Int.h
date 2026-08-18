#pragma once

struct Math_Vector2Int {
    int x;
    int y;
};

void _forge_free_Math_Vector2Int(struct Math_Vector2Int* value);
struct Math_Vector2Int* Math_Vector2Int_new(int x, int y);
