#ifndef NDX_PREPARED_SHADER_H
#define NDX_PREPARED_SHADER_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define CORE_PROFILE "DXIL_COMPUTE_UAV32_DIAMOND_V1"
#define CORE_MESA_REVISION "d1e369d8a63eb82ba277e4e25d35982ce2760204"
enum direct_op { D_CONST, D_TID_X, D_ADD, D_MUL, D_XOR, D_AND, D_OR,
                 D_ULT, D_IF, D_STORE, D_ENDIF };
enum core_resource_class { CORE_UAV = 1 };
enum core_access { CORE_WRITE = 1 };
enum core_stage { CORE_COMPUTE = 1 };
struct core_resource {
    uint32_t id, resource_class, space, reg, array_count, stride, access, stage;
};
struct direct_instruction { uint32_t op, a, b, literal; };
struct direct_program {
    uint32_t local_size[3], count;
    struct core_resource resource;
    struct direct_instruction instructions[256];
};
/* Opaque, immutable, value-owned representation. No LLVMBC/NAK objects escape.
 * Getter pointers are borrowed until core_prepared_destroy; input may be freed
 * immediately after core_prepare. Failure publishes NULL, never partial state. */
struct core_prepared;
int core_prepare(const void *, size_t, struct core_prepared **, char error[256]);
const struct direct_program *core_prepared_program(const struct core_prepared *);
const uint8_t *core_prepared_source(const struct core_prepared *, size_t *);
const char *core_prepared_profile(const struct core_prepared *);
void core_prepared_destroy(struct core_prepared **);
#ifdef __cplusplus
}
#endif
#endif
