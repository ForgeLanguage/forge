#pragma once

struct BundleInterface_vtable {
    char _forge_empty;
};
struct BundleInterface {
    void* object;
    const struct BundleInterface_vtable* vtable;
};
