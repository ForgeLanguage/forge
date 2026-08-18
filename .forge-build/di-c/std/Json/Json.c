#include "forge_std_net.h"
#include "forge_std_string.h"
#include "Json.h"
#include "JsonIssue.h"
#include "JsonValue.h"
#include "../../forge_runtime.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

static char* _forge_Double_to_string(double value) {
    int len = snprintf(NULL, 0, "%g", (double)value);
    char* result = _forge_alloc((size_t)len + 1);
    snprintf(result, (size_t)len + 1, "%g", (double)value);
    return result;
}

static char* _forge_Int_to_string(int value) {
    int len = snprintf(NULL, 0, "%lld", (long long)value);
    char* result = _forge_alloc((size_t)len + 1);
    snprintf(result, (size_t)len + 1, "%lld", (long long)value);
    return result;
}

#ifndef FORGEARRAY_BOOL_DEFINED
#define FORGEARRAY_BOOL_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    bool* data;
} ForgeArray_Bool;
#endif

#ifndef FORGEARRAY_DOUBLE_DEFINED
#define FORGEARRAY_DOUBLE_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    double* data;
} ForgeArray_Double;
#endif

#ifndef FORGEARRAY_INT_DEFINED
#define FORGEARRAY_INT_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    int* data;
} ForgeArray_Int;
#endif

#ifndef FORGEARRAY_STRING_DEFINED
#define FORGEARRAY_STRING_DEFINED
typedef struct {
    size_t len;
    size_t cap;
    const char** data;
} ForgeArray_String;
#endif

ForgeResult_String_JsonIssue std_Json_Json_readString(struct std_Json_JsonValue* value) {
    ForgeResult_String_JsonIssue forge_tmp_outcome0 = forge_json_as_string(value);
    if (forge_tmp_outcome0.tag == ForgeResult_String_JsonIssue_OUTCOME_JSONISSUE) {
        return (ForgeResult_String_JsonIssue){.tag = ForgeResult_String_JsonIssue_OUTCOME_JSONISSUE, .outcome_JsonIssue = forge_tmp_outcome0.outcome_JsonIssue};
    }
    if (forge_tmp_outcome0.tag != ForgeResult_String_JsonIssue_SUCCESS) {
        abort();
    }
    char* forge_tmp_string1 = _forge_string_copy(forge_tmp_outcome0.success);
    return (ForgeResult_String_JsonIssue){.tag = ForgeResult_String_JsonIssue_SUCCESS, .success = forge_tmp_string1};
}

ForgeResult_Int_JsonIssue std_Json_Json_readInt(struct std_Json_JsonValue* value) {
    ForgeResult_Int_JsonIssue forge_tmp_outcome2 = forge_json_as_int(value);
    if (forge_tmp_outcome2.tag == ForgeResult_Int_JsonIssue_OUTCOME_JSONISSUE) {
        return (ForgeResult_Int_JsonIssue){.tag = ForgeResult_Int_JsonIssue_OUTCOME_JSONISSUE, .outcome_JsonIssue = forge_tmp_outcome2.outcome_JsonIssue};
    }
    if (forge_tmp_outcome2.tag != ForgeResult_Int_JsonIssue_SUCCESS) {
        abort();
    }
    return (ForgeResult_Int_JsonIssue){.tag = ForgeResult_Int_JsonIssue_SUCCESS, .success = forge_tmp_outcome2.success};
}

ForgeResult_Double_JsonIssue std_Json_Json_readDouble(struct std_Json_JsonValue* value) {
    ForgeResult_Double_JsonIssue forge_tmp_outcome3 = forge_json_as_double(value);
    if (forge_tmp_outcome3.tag == ForgeResult_Double_JsonIssue_OUTCOME_JSONISSUE) {
        return (ForgeResult_Double_JsonIssue){.tag = ForgeResult_Double_JsonIssue_OUTCOME_JSONISSUE, .outcome_JsonIssue = forge_tmp_outcome3.outcome_JsonIssue};
    }
    if (forge_tmp_outcome3.tag != ForgeResult_Double_JsonIssue_SUCCESS) {
        abort();
    }
    return (ForgeResult_Double_JsonIssue){.tag = ForgeResult_Double_JsonIssue_SUCCESS, .success = forge_tmp_outcome3.success};
}

ForgeResult_Bool_JsonIssue std_Json_Json_readBool(struct std_Json_JsonValue* value) {
    ForgeResult_Bool_JsonIssue forge_tmp_outcome4 = forge_json_as_bool(value);
    if (forge_tmp_outcome4.tag == ForgeResult_Bool_JsonIssue_OUTCOME_JSONISSUE) {
        return (ForgeResult_Bool_JsonIssue){.tag = ForgeResult_Bool_JsonIssue_OUTCOME_JSONISSUE, .outcome_JsonIssue = forge_tmp_outcome4.outcome_JsonIssue};
    }
    if (forge_tmp_outcome4.tag != ForgeResult_Bool_JsonIssue_SUCCESS) {
        abort();
    }
    return (ForgeResult_Bool_JsonIssue){.tag = ForgeResult_Bool_JsonIssue_SUCCESS, .success = forge_tmp_outcome4.success};
}

char* std_Json_Json_writeInt(int value) {
    char* forge_tmp_string5 = _forge_Int_to_string(value);
    return forge_tmp_string5;
}

char* std_Json_Json_writeDouble(double value) {
    char* forge_tmp_string6 = _forge_Double_to_string(value);
    return forge_tmp_string6;
}

char* std_Json_Json_writeBool(bool value) {
    if (value) {
        char* forge_tmp_string7 = _forge_string_copy("true");
        return forge_tmp_string7;
    }
    char* forge_tmp_string8 = _forge_string_copy("false");
    return forge_tmp_string8;
}

char* std_Json_Json_writeStringArray(ForgeArray_String values) {
    char* forge_tmp_return17;
    char* forge_tmp_string9 = _forge_string_copy("[");
    char* result = forge_tmp_string9;
    char* forge_tmp_string10 = _forge_string_copy("");
    char* separator = forge_tmp_string10;
    {
        int forge_for_index0 = 0;
        while (true) {
    bool forge_tmp_loop_condition11 = forge_for_index0 < (int)values.len;
    if (!forge_tmp_loop_condition11) break;
    {
                char* forge_tmp_string12 = _forge_string_copy(values.data[forge_for_index0]);
                char* value = forge_tmp_string12;
                char* forge_tmp_string13 = forge_json_write_string(value);
                char* forge_tmp_string14 = _forge_string_concat(3, result, separator, forge_tmp_string13);
                free((void*)result);
                result = forge_tmp_string14;
                free(forge_tmp_string13);
                char* forge_tmp_string15 = _forge_string_copy(",");
                free((void*)separator);
                separator = forge_tmp_string15;
                forge_for_index0 = forge_for_index0 + 1;
                free((void*)value);
            }
}
    }
    char* forge_tmp_string16 = _forge_string_concat(2, result, "]");
    forge_tmp_return17 = forge_tmp_string16;
    goto cleanup;
    cleanup:
    free((void*)separator);
    free((void*)result);
    return forge_tmp_return17;
}

char* std_Json_Json_writeIntArray(ForgeArray_Int values) {
    char* forge_tmp_return25;
    char* forge_tmp_string18 = _forge_string_copy("[");
    char* result = forge_tmp_string18;
    char* forge_tmp_string19 = _forge_string_copy("");
    char* separator = forge_tmp_string19;
    {
        int forge_for_index1 = 0;
        while (true) {
    bool forge_tmp_loop_condition20 = forge_for_index1 < (int)values.len;
    if (!forge_tmp_loop_condition20) break;
    {
                int value = values.data[forge_for_index1];
                char* forge_tmp_string21 = std_Json_Json_writeInt(value);
                char* forge_tmp_string22 = _forge_string_concat(3, result, separator, forge_tmp_string21);
                free((void*)result);
                result = forge_tmp_string22;
                free(forge_tmp_string21);
                char* forge_tmp_string23 = _forge_string_copy(",");
                free((void*)separator);
                separator = forge_tmp_string23;
                forge_for_index1 = forge_for_index1 + 1;
            }
}
    }
    char* forge_tmp_string24 = _forge_string_concat(2, result, "]");
    forge_tmp_return25 = forge_tmp_string24;
    goto cleanup;
    cleanup:
    free((void*)separator);
    free((void*)result);
    return forge_tmp_return25;
}

char* std_Json_Json_writeDoubleArray(ForgeArray_Double values) {
    char* forge_tmp_return33;
    char* forge_tmp_string26 = _forge_string_copy("[");
    char* result = forge_tmp_string26;
    char* forge_tmp_string27 = _forge_string_copy("");
    char* separator = forge_tmp_string27;
    {
        int forge_for_index2 = 0;
        while (true) {
    bool forge_tmp_loop_condition28 = forge_for_index2 < (int)values.len;
    if (!forge_tmp_loop_condition28) break;
    {
                double value = values.data[forge_for_index2];
                char* forge_tmp_string29 = std_Json_Json_writeDouble(value);
                char* forge_tmp_string30 = _forge_string_concat(3, result, separator, forge_tmp_string29);
                free((void*)result);
                result = forge_tmp_string30;
                free(forge_tmp_string29);
                char* forge_tmp_string31 = _forge_string_copy(",");
                free((void*)separator);
                separator = forge_tmp_string31;
                forge_for_index2 = forge_for_index2 + 1;
            }
}
    }
    char* forge_tmp_string32 = _forge_string_concat(2, result, "]");
    forge_tmp_return33 = forge_tmp_string32;
    goto cleanup;
    cleanup:
    free((void*)separator);
    free((void*)result);
    return forge_tmp_return33;
}

char* std_Json_Json_writeBoolArray(ForgeArray_Bool values) {
    char* forge_tmp_return41;
    char* forge_tmp_string34 = _forge_string_copy("[");
    char* result = forge_tmp_string34;
    char* forge_tmp_string35 = _forge_string_copy("");
    char* separator = forge_tmp_string35;
    {
        int forge_for_index3 = 0;
        while (true) {
    bool forge_tmp_loop_condition36 = forge_for_index3 < (int)values.len;
    if (!forge_tmp_loop_condition36) break;
    {
                bool value = values.data[forge_for_index3];
                char* forge_tmp_string37 = std_Json_Json_writeBool(value);
                char* forge_tmp_string38 = _forge_string_concat(3, result, separator, forge_tmp_string37);
                free((void*)result);
                result = forge_tmp_string38;
                free(forge_tmp_string37);
                char* forge_tmp_string39 = _forge_string_copy(",");
                free((void*)separator);
                separator = forge_tmp_string39;
                forge_for_index3 = forge_for_index3 + 1;
            }
}
    }
    char* forge_tmp_string40 = _forge_string_concat(2, result, "]");
    forge_tmp_return41 = forge_tmp_string40;
    goto cleanup;
    cleanup:
    free((void*)separator);
    free((void*)result);
    return forge_tmp_return41;
}

struct std_Json_Json* std_Json_Json_new(void) {
    struct std_Json_Json* this = _forge_alloc(sizeof(struct std_Json_Json));
    return this;
}

void _forge_free_std_Json_Json(struct std_Json_Json* value) {
    if (value == NULL) {
        return;
    }
    free(value);
}
