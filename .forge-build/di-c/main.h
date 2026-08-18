#include "BundleFirst/BundleFirst.h"
#include "Logger.h"
#include "std/Di/DiContainer.h"

#pragma once

int main(void);
void DiContainer_apply__Defs__Config_1(struct BundleFirst_BundleFirst_Defs defs);
void DiContainer_build__nongeneric__Config_1(void);
struct Logger* DiContainer_resolve__Logger__Config_1(void);
