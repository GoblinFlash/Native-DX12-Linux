#ifndef NDX_CORE_NIR_EMITTER_H
#define NDX_CORE_NIR_EMITTER_H
#include "prepared_shader.h"
#include <stdbool.h>
struct nir_shader_compiler_options;
struct core_module;
/* Private trusted-adapter input, never deserialized from shader/user JSON.
 * The emitter copies options and rejects non-NULL callback data. Function
 * pointers must belong to the trusted, process-lifetime linked Mesa cohort. */
struct core_build_profile {
   const char *mesa_revision;
   const char *profile;
   const struct nir_shader_compiler_options *options;
   uint64_t adapter_identity;
   unsigned stage, logical_resource_abi;
};
int core_emit(const struct core_prepared *, const struct core_build_profile *,
              struct core_module **, char error[256]);
void core_module_destroy(struct core_module **);
unsigned core_live_modules(void);
bool core_module_is_n0(const struct core_module *);
#endif
