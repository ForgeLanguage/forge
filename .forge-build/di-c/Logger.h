#pragma once

struct Logger {
    char _forge_empty;
};

void _forge_free_Logger(struct Logger* value);
struct Logger* Logger_new(void);
