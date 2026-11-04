#ifndef NDX_CORE_INTERNAL_H
#define NDX_CORE_INTERNAL_H
#include "nir_emitter.h"
#include "compiler/nir/nir.h"
enum core_phase { CORE_N0_UNBOUND, CORE_N1_TARGET_BOUND };
/* Internal layout; never a caller-supplied serialized ABI. */
struct core_module {
   nir_shader *nir;
   struct nir_shader_compiler_options options;
   struct core_resource resource;
   uint64_t adapter_identity;
   enum core_phase phase;
   unsigned mapped_resource_id, binding_abi;
};
#endif
