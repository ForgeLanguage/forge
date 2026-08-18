#pragma once

struct std_Json_JsonValue {
    unsigned long long handle;
};

void _forge_free_std_Json_JsonValue(struct std_Json_JsonValue* value);
struct std_Json_JsonValue* std_Json_JsonValue_new(void);
