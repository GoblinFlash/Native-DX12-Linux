#include "core_internal.h"
#include "compiler/nir/nir_builder.h"
#include "util/ralloc.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

static atomic_uint live_modules;
static nir_shader *
emit_nir(const struct direct_program *p, const struct nir_shader_compiler_options *options)
{
   nir_builder b = nir_builder_init_simple_shader(MESA_SHADER_COMPUTE,
                                                  options, "direct DXIL");
   nir_def *v[256] = {0};
   for (unsigned i = 0; i < 3; i++)
      b.shader->info.workgroup_size[i] = p->local_size[i];
   b.shader->info.num_ssbos = 1;
   for (unsigned i = 0; i < p->count; i++) {
      const struct direct_instruction *in = &p->instructions[i];
      switch (in->op) {
      case D_CONST: v[i] = nir_imm_int(&b, in->literal); break;
      case D_TID_X: v[i] = nir_channel(&b, nir_load_global_invocation_id(&b, 32), 0); break;
      case D_ADD: v[i] = nir_iadd(&b, v[in->a], v[in->b]); break;
      case D_MUL: v[i] = nir_imul(&b, v[in->a], v[in->b]); break;
      case D_XOR: v[i] = nir_ixor(&b, v[in->a], v[in->b]); break;
      case D_AND: v[i] = nir_iand(&b, v[in->a], v[in->b]); break;
      case D_OR: v[i] = nir_ior(&b, v[in->a], v[in->b]); break;
      case D_ULT: v[i] = nir_ult(&b, v[in->a], v[in->b]); break;
      case D_IF: nir_push_if(&b, v[in->a]); break;
      case D_ENDIF: nir_pop_if(&b, NULL); break;
      case D_STORE:
         /* This scalar32 ABI has a 32-bit byte offset. Reject elements whose
          * four bytes cannot be represented before narrowing index * stride.
          * The adapter still enforces the actual resource view bounds. */
         nir_push_if(&b, nir_ult(&b, v[in->a], nir_imm_int(&b, 0x40000000)));
         nir_store_ssbo(&b, v[in->b], nir_imm_int(&b, p->resource.id),
                        nir_imul_imm(&b, v[in->a], 4), .align_mul = 4, .write_mask = 1);
         nir_pop_if(&b, NULL);
         break;
      default: ralloc_free(b.shader); return NULL;
      }
   }
   nir_shader_gather_info(b.shader, nir_shader_get_entrypoint(b.shader));
   nir_validate_shader(b.shader, "direct DXIL import");
   return b.shader;
}


int core_emit(const struct core_prepared *prepared,
              const struct core_build_profile *profile,
              struct core_module **out, char error[256])
{
   if (out) *out = NULL;
   if (!error) return 1;
   const struct direct_program *p = core_prepared_program(prepared);
   if (!out || !p || !profile || !profile->mesa_revision || !profile->profile ||
       strcmp(profile->mesa_revision, CORE_MESA_REVISION) ||
       strcmp(profile->profile, CORE_PROFILE) || !profile->options ||
       profile->options->cb_data ||
       !profile->adapter_identity || profile->stage != CORE_COMPUTE ||
       profile->logical_resource_abi != 1) {
      snprintf(error, 256, "CORE_REJECT:BUILD_PROFILE"); return 1;
   }
   if (p->resource.id != 0 || p->resource.resource_class != CORE_UAV ||
       p->resource.space != 0 || p->resource.reg != 0 ||
       p->resource.array_count != 1 || p->resource.stride != 4 ||
       p->resource.access != CORE_WRITE || p->resource.stage != CORE_COMPUTE ||
       p->local_size[0] != 64 || p->local_size[1] != 1 || p->local_size[2] != 1 ||
       p->count == 0 || p->count > 256) {
      snprintf(error, 256, "CORE_REJECT:PREPARED_PROFILE"); return 1;
   }
   struct core_module *m = calloc(1, sizeof(*m));
   if (!m) { snprintf(error, 256, "CORE_REJECT:ALLOCATION"); return 1; }
   m->options = *profile->options;
   m->resource = p->resource;
   m->adapter_identity = profile->adapter_identity;
   m->phase = CORE_N0_UNBOUND;
   m->nir = emit_nir(p, &m->options);
   if (!m->nir) { free(m); snprintf(error, 256, "CORE_REJECT:EMISSION"); return 1; }
   atomic_fetch_add(&live_modules, 1);
   *out = m;
   return 0;
}
void core_module_destroy(struct core_module **module)
{
   if (!module || !*module) return;
   struct core_module *m = *module;
   *module = NULL;
   ralloc_free(m->nir);
   free(m);
   atomic_fetch_sub(&live_modules, 1);
}
unsigned core_live_modules(void) { return atomic_load(&live_modules); }
bool core_module_is_n0(const struct core_module *m)
{ return m && m->phase == CORE_N0_UNBOUND; }
