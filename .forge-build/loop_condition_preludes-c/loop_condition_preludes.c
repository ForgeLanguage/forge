#include "loop_condition_preludes.h"
#include "forge_runtime.h"

#include <stdbool.h>
#include <stdio.h>

int main(void) {
    int whileIndex = 0;
    int forge_tmp_loop_result0;
    bool forge_tmp_loop_has_value1 = false;
    while (true) {
        bool forge_tmp_loop_result2;
        bool forge_tmp_loop_has_value3 = false;
        while (true) {
            bool forge_tmp_loop_condition4 = false;
            if (!forge_tmp_loop_condition4) break;
            {
                    forge_tmp_loop_result2 = false;
            forge_tmp_loop_has_value3 = true;
            break;
                }
        }
        if (!forge_tmp_loop_has_value3) {
            forge_tmp_loop_result2 = whileIndex < 2;
        }
        bool forge_tmp_loop_condition5 = forge_tmp_loop_result2;
        if (!forge_tmp_loop_condition5) break;
        {
                whileIndex++;
                if (whileIndex > 5) {
                    forge_tmp_loop_result0 = 99;
        forge_tmp_loop_has_value1 = true;
        break;
                }
            }
    }
    if (!forge_tmp_loop_has_value1) {
        forge_tmp_loop_result0 = whileIndex;
    }
    int fromWhile = forge_tmp_loop_result0;
    int doIndex = 0;
    int forge_tmp_loop_result6;
    bool forge_tmp_loop_has_value7 = false;
    do {
        {
                doIndex++;
                if (doIndex > 5) {
                    forge_tmp_loop_result6 = 99;
        forge_tmp_loop_has_value7 = true;
        break;
                }
            }
        bool forge_tmp_loop_result8;
        bool forge_tmp_loop_has_value9 = false;
        while (true) {
            bool forge_tmp_loop_condition10 = false;
            if (!forge_tmp_loop_condition10) break;
            {
                    forge_tmp_loop_result8 = false;
            forge_tmp_loop_has_value9 = true;
            break;
                }
        }
        if (!forge_tmp_loop_has_value9) {
            forge_tmp_loop_result8 = doIndex < 2;
        }
        bool forge_tmp_loop_condition11 = forge_tmp_loop_result8;
        if (!forge_tmp_loop_condition11) break;
    } while (true);
    if (!forge_tmp_loop_has_value7) {
        forge_tmp_loop_result6 = doIndex;
    }
    int fromDo = forge_tmp_loop_result6;
    printf("%d\n", fromWhile);
    printf("%d\n", fromDo);
    return 0;
}
