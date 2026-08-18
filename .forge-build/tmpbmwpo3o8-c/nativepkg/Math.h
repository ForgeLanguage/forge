#pragma once

struct nativepkg_Math {
    char _forge_empty;
};

void _forge_free_nativepkg_Math(struct nativepkg_Math* value);
int native_answer(void);
struct nativepkg_Math* nativepkg_Math_new(void);
