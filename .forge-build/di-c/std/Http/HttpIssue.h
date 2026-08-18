#pragma once

struct std_Http_HttpIssue {
    const char* message;
};

void _forge_free_std_Http_HttpIssue(struct std_Http_HttpIssue* value);
struct std_Http_HttpIssue* std_Http_HttpIssue_new(const char* message);
