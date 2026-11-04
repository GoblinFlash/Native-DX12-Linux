#ifndef NDX_DXIL_SHARED_PROGRAM_H
#define NDX_DXIL_SHARED_PROGRAM_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define DS_MAX_OPS 1024
enum ds_op {
    DS_CONST, DS_TID, DS_LOCAL, DS_GROUP, DS_PARAM,
    DS_ADD, DS_SUB, DS_MUL, DS_AND, DS_OR, DS_XOR, DS_SHL, DS_USHR,
    DS_EQ, DS_NE, DS_ULT, DS_ULE, DS_UGT, DS_UGE,
    DS_IF, DS_ENDIF, DS_PHI, DS_LOAD, DS_STORE,
    DS_SHARED_LOAD, DS_SHARED_STORE, DS_SHARED_ADD, DS_GLOBAL_ADD, DS_BARRIER
};
struct ds_instruction { uint32_t op, bits, a, b, c, literal; };
struct ds_program {
    uint32_t count, local[3], shared_bytes, uavs, barriers, param_mask;
    uint32_t reads[3], writes[3];
    struct ds_instruction instructions[DS_MAX_OPS];
};
/* Value-owned output; failure leaves it zero. No LLVM/parser object escapes. */
int ds_parse(const void *bytes, size_t size, struct ds_program *out, char error[256]);
#ifdef __cplusplus
}
#endif
#endif
