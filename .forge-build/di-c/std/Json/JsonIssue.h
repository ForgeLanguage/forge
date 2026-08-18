#pragma once

struct std_Json_JsonIssue {
    const char* message;
};

void _forge_free_std_Json_JsonIssue(struct std_Json_JsonIssue* value);
struct std_Json_JsonIssue* std_Json_JsonIssue_new(void);
