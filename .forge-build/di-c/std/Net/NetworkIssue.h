#pragma once

struct std_Net_NetworkIssue {
    const char* message;
};

void _forge_free_std_Net_NetworkIssue(struct std_Net_NetworkIssue* value);
struct std_Net_NetworkIssue* std_Net_NetworkIssue_new(void);
