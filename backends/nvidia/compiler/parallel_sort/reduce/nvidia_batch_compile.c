/* Derived from PARAM2D-007 compile_nak.c, sha256 5bb66652471a78d845053beb068ed54b8b2ee4eedb79f30569b235645df18541.
 * Maintained batch-specific extension; original input is preserved. */
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <spirv-tools/libspirv.h>
#include "compiler/nir/nir.h"
#include "compiler/nir/nir_builder.h"
#include "compiler/spirv/nir_spirv.h"
#include "nouveau/compiler/nak.h"
#include "nouveau/headers/nv_device_info.h"
#include "util/ralloc.h"

/* NAK requires these consumer-owned symbols. Graphics and printf intrinsics
 * are rejected by this compute-only profile; these layouts are not supported. */
const struct nak_constant_offset_info nak_const_offsets_base = {0};
const struct nak_constant_offset_info nak_const_offsets_turing_graphics = {0};

/* Batch CB0 v2: three {u64 VA,u32 bytes,u32 reserved} records, then eight
 * u32 root constants. Each Dispatch owns an immutable 80-byte snapshot. */
#define CB0_VIEW_BASE 0
#define CB0_VIEW_BYTES 8
#define CB0_PARAMS 48
#define CB0_PARAM_SIZE 128
#define CB0_LEGACY_SIZE 256
/* HLSL b0: eight u32 words, constant offsets only. */
#define B0_BYTES 32

struct lowering {
   bool bad, params, predicated_load;
   unsigned predicated_loads;
   unsigned shared_proven, shared_fallback;
   unsigned descriptors, resources, stores, loads;
   unsigned ubo_descriptors, ubo_resources, param_loads;
   unsigned reads[3], writes[3];
   unsigned param_mask; /* bit k: HLSL b0 byte 4k was read */
   unsigned shared_bytes, shared_loads, shared_stores, shared_atomics, global_atomics;
};

/* Exact admitted compute profiles. Anything else is rejected; the local size
 * and the presence of the b0 CBV are selected from the imported NIR, and the
 * local size is re-checked against the raw nak_shader_info ABI. The grid is
 * the synthetic default QMD grid; for param2d8x8 the runtime replaces it per
 * Dispatch (ceil(width/8), ceil(height/8), 1), 8x8x1 covering 64x64. */
struct profile {
   const char *name;
   uint16_t local[3];
   uint32_t grid[3];
   unsigned loads, stores; /* exact UAV access counts; ~0u = at most one load */
   bool params;            /* one b0 CBV lowered to CB0 bytes 48..79 */
   uint32_t cb0_size;
   bool shared_profile;
   unsigned shared_bytes, barriers, shared_atomics, global_atomics, param_mask;
};

static const struct profile profiles[] = {
   {"batch2d8x8", {8, 8, 1}, {1, 1, 1}, ~0u, 1, true, CB0_PARAM_SIZE},
   {"shared-reduce", {8, 8, 1}, {1, 1, 1}, 1, 1, true, CB0_PARAM_SIZE, true, 256, 7, 0, 0, 0x07},
   {"shared-hist", {8, 8, 1}, {1, 1, 1}, 1, 1, true, CB0_PARAM_SIZE, true, 64, 2, 1, 0, 0x97},
   {"global-hist", {8, 8, 1}, {1, 1, 1}, 1, 0, true, CB0_PARAM_SIZE, true, 0, 0, 0, 1, 0x93},
   {"shared-combine", {8, 8, 1}, {1, 1, 1}, 17, 1, true, CB0_PARAM_SIZE, true, 0, 0, 0, 0, 0xec},
   /* READYMADE-001: adapted MiniEngine GenerateHistogramCS (16x16, 1 KiB shared). */
   {"readymade-hist", {16, 16, 1}, {1, 1, 1}, 1, 0, true, CB0_PARAM_SIZE, true, 1024, 2, 1, 1, 0x03},
   {"readymade-hist-pred-guarded", {16, 16, 1}, {1, 1, 1}, 1, 0, true, CB0_PARAM_SIZE, true, 1024, 2, 1, 1, 0x03},
   /* SORT-FFX-012 stage 2: FidelityFX ParallelSort FPS_CountReduce (128 threads, wave-32 reduce). */
   {"ffx-reduce", {128, 1, 1}, {1, 1, 1}, 4, 1, true, CB0_PARAM_SIZE, true, 512, 1, 0, 0, 0x14},
};

static const struct profile *
select_profile(const nir_shader *nir, const char *requested)
{
   for (unsigned i = 0; i < sizeof(profiles) / sizeof(profiles[0]); i++) {
      const struct profile *p = &profiles[i];
      if (!strcmp(requested, p->name) &&
          nir->info.workgroup_size[0] == p->local[0] &&
          nir->info.workgroup_size[1] == p->local[1] &&
          nir->info.workgroup_size[2] == p->local[2] &&
          (nir->info.num_ubos == 1) == p->params)
         return p;
   }
   return NULL;
}

static bool
lower_descriptor(nir_builder *b, nir_intrinsic_instr *in, void *data)
{
   struct lowering *s = data;
   nir_def *value = NULL;
   b->cursor = nir_before_instr(&in->instr);
   switch (in->intrinsic) {
   case nir_intrinsic_vulkan_resource_index: {
      bool ubo = s->params && nir_intrinsic_desc_type(in) == nir_descriptor_type_uniform_buffer;
      if ((!ubo && nir_intrinsic_desc_type(in) != nir_descriptor_type_storage_buffer) ||
          nir_intrinsic_desc_set(in) ||
          (ubo ? nir_intrinsic_binding(in) != 0 : nir_intrinsic_binding(in) >= 3) ||
          !nir_src_is_const(in->src[0]) || nir_src_as_uint(in->src[0]) ||
          in->def.num_components != 2 || in->def.bit_size != 32) {
         s->bad = true;
         return false;
      }
      value = nir_imm_ivec2(b, nir_intrinsic_binding(in), 0);
      if (ubo) s->ubo_resources++; else s->resources++;
      break;
   }
   case nir_intrinsic_load_vulkan_descriptor: {
      bool ubo = s->params && nir_intrinsic_desc_type(in) == nir_descriptor_type_uniform_buffer;
      if ((!ubo && nir_intrinsic_desc_type(in) != nir_descriptor_type_storage_buffer) ||
          in->def.num_components != 2 || in->def.bit_size != 32) {
         s->bad = true;
         return false;
      }
      value = in->src[0].ssa;
      if (ubo) s->ubo_descriptors++; else s->descriptors++;
      break;
   }
   case nir_intrinsic_vulkan_resource_reindex:
      s->bad = true;
      return false;
   default:
      return false;
   }
   nir_def_rewrite_uses(&in->def, value);
   nir_instr_remove(&in->instr);
   return true;
}

static bool
lower_buffer(nir_builder *b, nir_intrinsic_instr *in, void *data)
{
   struct lowering *s = data;
   bool load = in->intrinsic == nir_intrinsic_load_ssbo;
   if (!load && in->intrinsic != nir_intrinsic_store_ssbo)
      return false;
   nir_scalar binding = nir_scalar_resolved(in->src[load ? 0 : 1].ssa, 0);
   if (!nir_scalar_is_const(binding) || nir_scalar_as_uint(binding) >= 3 ||
       (load ? in->def.bit_size : in->src[0].ssa->bit_size) != 32 ||
       in->num_components != 1 ||
       (!load && nir_intrinsic_write_mask(in) != 1) ||
       nir_intrinsic_align_mul(in) < 4) {
      s->bad = true;
      return false;
   }
   b->cursor = nir_before_instr(&in->instr);
   nir_def *base = nir_ldc_nv(b, 1, 64, nir_imm_int(b, 0), nir_imm_int(b, 16 * nir_scalar_as_uint(binding) + CB0_VIEW_BASE),
                             .align_mul = 8);
   nir_def *size = nir_ldc_nv(b, 1, 32, nir_imm_int(b, 0), nir_imm_int(b, 16 * nir_scalar_as_uint(binding) + CB0_VIEW_BYTES),
                             .align_mul = 4);
   nir_def *offset = in->src[load ? 1 : 2].ssa;
   nir_def *address = nir_iadd(b, base, nir_u2u64(b, offset));
   nir_def *valid = nir_iand(b, nir_uge(b, size, nir_imm_int(b, 4)),
                            nir_uge(b, nir_iadd_imm(b, size, -4), offset));
   valid = nir_iand(b, valid, nir_uge(b, address, base));
   valid = nir_iand(b, valid,
                    nir_ieq_imm(b, nir_iand_imm(b, base, 3), 0));
   valid = nir_iand(b, valid, nir_ieq_imm(b, nir_iand_imm(b, offset, 3), 0));
   if (load && s->predicated_load) {
      nir_def *value = nir_load_global_nv(b, 1, 32, address,
                                          nir_imm_int64(b, 0), valid,
                                          .align_mul = 4,
                                          .access = nir_intrinsic_access(in));
      nir_def_rewrite_uses(&in->def, value);
      s->loads++;
      s->reads[nir_scalar_as_uint(binding)]++;
      s->predicated_loads++;
      nir_instr_remove(&in->instr);
      return true;
   }
   nir_push_if(b, valid);
   if (load) {
      nir_def *value = nir_load_global(b, 1, 32, address, .align_mul = 4,
                                       .access = nir_intrinsic_access(in));
      nir_push_else(b, NULL);
      nir_def *zero = nir_imm_int(b, 0);
      nir_pop_if(b, NULL);
      nir_def_rewrite_uses(&in->def, nir_if_phi(b, value, zero));
      s->loads++;
      s->reads[nir_scalar_as_uint(binding)]++;
   } else {
      nir_store_global(b, in->src[0].ssa, address, .align_mul = 4, .write_mask = 1,
                        .access = nir_intrinsic_access(in));
      nir_pop_if(b, NULL);
      s->stores++;
      s->writes[nir_scalar_as_uint(binding)]++;
   }
   nir_instr_remove(&in->instr);
   return true;
}

/* b0 parameters: load_ubo of the one UBO (block index already lowered to the
 * constant 0) at a constant offset. Each component that is read must be HLSL
 * byte 0..28 and becomes a 32-bit ldc_nv from CB0 byte 48 + that byte;
 * unread components are undef and are not loaded. Anything else is bad. */
static bool
lower_params(nir_builder *b, nir_intrinsic_instr *in, void *data)
{
   struct lowering *s = data;
   if (in->intrinsic != nir_intrinsic_load_ubo)
      return false;
   nir_scalar index = nir_scalar_resolved(in->src[0].ssa, 0);
   if (!s->params || !nir_scalar_is_const(index) || nir_scalar_as_uint(index) ||
       !nir_src_is_const(in->src[1]) || in->def.bit_size != 32 ||
       in->def.num_components > 4) {
      s->bad = true;
      return false;
   }
   uint64_t offset = nir_src_as_uint(in->src[1]);
   nir_component_mask_t read = nir_def_components_read(&in->def);
   b->cursor = nir_before_instr(&in->instr);
   nir_def *comps[4];
   for (unsigned c = 0; c < in->def.num_components; c++) {
      uint64_t byte = offset + 4 * c;
      if (!(read & (1u << c))) {
         comps[c] = nir_undef(b, 1, 32);
         continue;
      }
      if (offset % 4 || byte > B0_BYTES - 4) {
         s->bad = true;
         return false;
      }
      comps[c] = nir_ldc_nv(b, 1, 32, nir_imm_int(b, 0),
                            nir_imm_int(b, CB0_PARAMS + (int)byte), .align_mul = 4);
      s->param_mask |= 1u << (byte / 4);
   }
   nir_def_rewrite_uses(&in->def, nir_vec(b, comps, in->def.num_components));
   nir_instr_remove(&in->instr);
   s->param_loads++;
   return true;
}

/* Integer-only ALU vocabulary of the param profile. The compiler cannot see
 * HLSL member types, so float arithmetic on a b0 word is refused here. */
static bool
param_alu_allowed(nir_op op)
{
   switch (op) {
   case nir_op_mov: case nir_op_vec2: case nir_op_vec3: case nir_op_vec4:
   case nir_op_iadd: case nir_op_imul: case nir_op_ishl: case nir_op_ushr:
   case nir_op_iand: case nir_op_ior: case nir_op_ixor: case nir_op_inot:
   case nir_op_ult: case nir_op_uge: case nir_op_ieq: case nir_op_ine:
   case nir_op_extract_u8: case nir_op_extract_u16: case nir_op_bcsel:
      return true;
   default:
      return false;
   }
}

#include "nvidia_shared_lowering.h"

/* SORT-FFX-012 stage 2: unsigned division admitted only by the subgroup size or a b0 word. */
static bool
ffx_divisor_ok(nir_alu_instr *alu)
{
   if ((alu->op != nir_op_udiv && alu->op != nir_op_umod) || alu->def.bit_size != 32)
      return false;
   nir_scalar d = nir_scalar_chase_movs(nir_scalar_resolved(alu->src[1].src.ssa, alu->src[1].swizzle[0]));
   if (!nir_scalar_is_intrinsic(d))
      return false;
   nir_intrinsic_op op = nir_scalar_intrinsic_op(d);
   return op == nir_intrinsic_load_subgroup_size || op == nir_intrinsic_load_ubo;
}

static void
import_debug(void *data, enum nir_spirv_debug_level level, size_t offset,
             const char *message)
{
   fprintf(stderr, "IMPORT %d at %zu: %s\n", level, offset, message);
   if (level >= NIR_SPIRV_DEBUG_LEVEL_WARNING)
      *(bool *)data = true;
}

static FILE *
output_file(const char *prefix, const char *suffix)
{
   char path[4096];
   int n = snprintf(path, sizeof(path), "%s.%s", prefix, suffix);
   if (n < 0 || (size_t)n >= sizeof(path))
      return NULL;
   return fopen(path, "wx");
}

static bool
dump_nir(const char *prefix, const char *suffix, nir_shader *nir)
{
   FILE *f = output_file(prefix, suffix);
   if (!f) return false;
   nir_print_shader(nir, f);
   bool ok = !ferror(f);
   return fclose(f) == 0 && ok;
}

int
main(int argc, char **argv)
{
   int rc = 1;
   const char *error = "INPUT";
   uint32_t *words = NULL;
   nir_shader *nir = NULL;
   struct nak_compiler *nak = NULL;
   struct nak_shader_bin *bin = NULL;
   FILE *f = NULL;
   unsigned sm = 89;
   const char *requested = "batch2d8x8";
   while (argc >= 5) {
      if (!strcmp(argv[1], "--profile")) {
         requested = argv[2];
      } else if (!strcmp(argv[1], "--sm") &&
                 (!strcmp(argv[2], "86") || !strcmp(argv[2], "89"))) {
         sm = !strcmp(argv[2], "89") ? 89 : 86;
      } else {
         fprintf(stderr, "RTX_REJECT:TARGET_PROFILE\n");
         return 1;
      }
      argc -= 2;
      argv += 2;
   }
   if (argc != 3) {
      fprintf(stderr, "usage: compile-nak [--sm 86|89] [--profile name] input.spv output-prefix\n");
      return 2;
   }
   glsl_type_singleton_init_or_ref();
   f = fopen(argv[1], "rb");
   if (!f) goto done;
   if (fseek(f, 0, SEEK_END)) goto done;
   long size = ftell(f);
   if (size < 20 || size > 1024 * 1024 || size % 4 || fseek(f, 0, SEEK_SET)) goto done;
   words = malloc((size_t)size);
   if (!words || fread(words, 1, size, f) != (size_t)size) goto done;
   fclose(f); f = NULL;
   spv_context ctx = spvContextCreate(SPV_ENV_VULKAN_1_3);
   spv_const_binary_t binary = {words, (size_t)size / 4};
   spv_diagnostic diagnostic = NULL;
   spv_result_t result = spvValidate(ctx, &binary, &diagnostic);
   if (diagnostic) fprintf(stderr, "SPIRV: %s\n", diagnostic->error);
   spvDiagnosticDestroy(diagnostic);
   spvContextDestroy(ctx);
   error = "SPIRV_VALIDATION";
   if (result != SPV_SUCCESS) goto done;
   error = "ENTRY_POINT";
   unsigned entrypoints = 0;
   for (size_t pos = 5; pos < (size_t)size / 4;) {
      unsigned count = words[pos] >> 16;
      unsigned opcode = words[pos] & 0xffff;
      if (!count || count > (size_t)size / 4 - pos) goto done;
      if (opcode == 15) {
         if (count < 5 || words[pos + 1] != 5 ||
             memcmp(words + pos + 3, "main\0", 5)) goto done;
         entrypoints++;
      }
      pos += count;
   }
   if (entrypoints != 1) goto done;
   struct nv_device_info device = {
      .type = NV_DEVICE_TYPE_DIS, .device_id = 0x2684, .chipset = 0x192,
      .sm = 89, .cls_compute = 0xc9c0, .max_warps_per_mp = 48,
      .max_smem_per_wg_kB = 100, .sm_smem_size_count = 6,
      .sm_smem_sizes_kB = {0, 8, 16, 32, 64, 100},
   };
   error = "TARGET_PROFILE";
   if (sm != 89 || sizeof(struct nak_shader_info) != 864) goto done;
   nak = nak_compiler_create(&device);
   error = "NAK_CREATE";
   if (!nak) goto done;
   bool import_error = false;
   const struct spirv_to_nir_options options = {
      .environment = NIR_SPIRV_VULKAN,
      .ssbo_addr_format = nir_address_format_32bit_index_offset,
      .ubo_addr_format = nir_address_format_32bit_index_offset,
      .shared_addr_format = nir_address_format_32bit_offset,
      .temp_addr_format = nir_address_format_logical,
      .min_ssbo_alignment = 4,
      .skip_os_break_in_debug_build = true, .ignore_replacement = true,
      .debug = {.func = import_debug, .private_data = &import_error},
   };
   nir = spirv_to_nir(words, size / 4, NULL, MESA_SHADER_COMPUTE, "main",
                      &options, nak_nir_options(nak));
   error = "COMPUTE_PROFILE";
   if (!nir || import_error || nir->info.stage != MESA_SHADER_COMPUTE ||
       nir->info.workgroup_size_variable ||
       (nir->info.num_ssbos < 1 || nir->info.num_ssbos > 3) || nir->info.num_ubos != 1 || nir->info.num_images ||
       nir->info.num_textures) goto done;
   const struct profile *profile = select_profile(nir, requested);
   bool ffx = profile && !strncmp(profile->name, "ffx-", 4);
   bool ffx_wave = profile && !strcmp(profile->name, "ffx-reduce");
   if (!profile || (!profile->shared_profile && nir->info.shared_size)) goto done;
   /* The b0 UBO variable is checked on the imported NIR: its accesses go
    * through vulkan_resource_index, so later dead-variable removal drops it. */
   error = "RESOURCE_PROFILE";
   unsigned ubo_vars = 0;
   nir_foreach_variable_with_modes(var, nir, nir_var_mem_ubo) {
      if (!profile->params || var->data.descriptor_set || var->data.binding ||
          glsl_get_explicit_size(var->type, false) != 32) {
         fprintf(stderr, "resource profile: ubo set=%u binding=%u size=%u\n",
                 var->data.descriptor_set, var->data.binding,
                 glsl_get_explicit_size(var->type, false));
         goto done;
      }
      ubo_vars++;
   }
   error = "OUTPUT";
   if (!dump_nir(argv[2], "import.nir", nir)) goto done;
   NIR_PASS(_, nir, nir_lower_variable_initializers, nir_var_function_temp);
   NIR_PASS(_, nir, nir_lower_returns);
   NIR_PASS(_, nir, nir_inline_functions);
   NIR_PASS(_, nir, nir_opt_copy_prop);
   NIR_PASS(_, nir, nir_opt_deref);
   nir_remove_non_entrypoints(nir);
   NIR_PASS(_, nir, nir_lower_variable_initializers, ~0);
   nak_preprocess_nir(nir, nak);
   /* READYMADE-001: SV_GroupIndex becomes local-id arithmetic the adapter admits. */
   const nir_lower_compute_system_values_options csv = {.lower_local_invocation_index = true};
   NIR_PASS(_, nir, nir_lower_compute_system_values, &csv);
   error = "RESOURCE_PROFILE";
   nir_foreach_variable_with_modes(var, nir, nir_var_mem_ssbo) {
      if (var->data.descriptor_set || var->data.binding >= 3 ||
          glsl_type_is_array(var->type)) goto done;
   }
   /* Root constants converted to push constants are refused: dxil-spirv's
    * --root-constant mode synthesises the block from the word count and
    * silently reads 0 for HLSL bytes outside it (see MAPPING.md). */
   if (nir->num_uniforms) goto done;
   nir_foreach_variable_with_modes(var, nir, nir_var_mem_push_const) goto done;
   if (ubo_vars != (profile->params ? 1u : 0u)) {
      fprintf(stderr, "resource profile: ubo_vars=%u\n", ubo_vars);
      goto done;
   }
   struct lowering lower = {.params = profile->params,
      .predicated_load = !strcmp(profile->name, "readymade-hist-pred-guarded")};
   NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_descriptor, nir_metadata_control_flow, &lower);
   if (lower.bad || !lower.resources || !lower.descriptors ||
       (profile->params && (!lower.ubo_resources || !lower.ubo_descriptors))) {
      fprintf(stderr, "resource profile: bad=%u ssbo=%u/%u ubo=%u/%u\n", lower.bad,
              lower.resources, lower.descriptors, lower.ubo_resources, lower.ubo_descriptors);
      goto done;
   }
   NIR_PASS(_, nir, nir_lower_explicit_io,
            nir_var_mem_ssbo | (profile->params ? nir_var_mem_ubo : 0),
            nir_address_format_32bit_index_offset);
   if (profile->shared_profile) {
      error = "SHARED_TYPE";
      nir_foreach_variable_with_modes(var, nir, nir_var_mem_shared) {
         const struct glsl_type *leaf = glsl_without_array(var->type);
         if (!glsl_type_is_scalar(leaf) || glsl_get_base_type(leaf) != GLSL_TYPE_UINT)
            goto done;
      }
      NIR_PASS(_, nir, nir_lower_vars_to_explicit_types, nir_var_mem_shared, shared_var_info);
      NIR_PASS(_, nir, nir_lower_explicit_io, nir_var_mem_shared, nir_address_format_32bit_offset);
      error = "SHARED_LAYOUT";
      if (nir->info.shared_size != profile->shared_bytes || nir->info.shared_size > (ffx ? 8192u : 4096u)) goto done;
      lower.shared_bytes = nir->info.shared_size;
   }
   NIR_PASS(_, nir, nir_opt_constant_folding);
   NIR_PASS(_, nir, nir_opt_copy_prop);
   NIR_PASS(_, nir, nir_opt_dce);
   error = "OUTPUT";
   if (!dump_nir(argv[2], "prestore.nir", nir)) goto done;
   /* 005 profiles: straight-line code. param2d8x8: exactly one top-level if
    * (the image bounds test) with straight-line then, an empty else, and both
    * UAV accesses inside it, so threads outside the image make no access. */
   error = "CONTROL_FLOW_PROFILE";
   nir_if *guard = NULL;
   if (profile->shared_profile) {
      if (!shared_control_flow(nir, profile->barriers)) goto done;
   } else {
   nir_foreach_function_impl(profile_impl, nir) {
      foreach_list_typed(nir_cf_node, node, node, &profile_impl->body) {
         if (node->type == nir_cf_node_block) continue;
         if (!profile->params || node->type != nir_cf_node_if || guard) goto done;
         guard = nir_cf_node_as_if(node);
         foreach_list_typed(nir_cf_node, then_node, node, &guard->then_list) {
            if (then_node->type != nir_cf_node_block) goto done;
         }
         foreach_list_typed(nir_cf_node, else_node, node, &guard->else_list) {
            if (else_node->type != nir_cf_node_block ||
                !exec_list_is_empty(&nir_cf_node_as_block(else_node)->instr_list)) goto done;
         }
      }
   }
   if (profile->params && !guard) goto done;
   }
   error = "INTRINSIC_PROFILE";
   unsigned guarded_accesses = 0;
   nir_foreach_function_impl(impl, nir) {
      nir_foreach_block(block, impl) {
         nir_foreach_instr(instr, block) {
            if (instr->type != nir_instr_type_intrinsic) continue;
            nir_intrinsic_instr *in = nir_instr_as_intrinsic(instr);
            switch (in->intrinsic) {
            case nir_intrinsic_load_ssbo:
            case nir_intrinsic_store_ssbo:
               if (profile->shared_profile && nir_intrinsic_offset_shift(in) != 0) goto done;
               if (guard && block->cf_node.parent == &guard->cf_node)
                  guarded_accesses++;
               break;
            case nir_intrinsic_load_workgroup_id:
            case nir_intrinsic_load_local_invocation_id:
               break;
            case nir_intrinsic_load_ubo:
               if (profile->params)
                  break;
               FALLTHROUGH;
            default:
               if (profile->shared_profile && shared_intrinsic_allowed(in)) break;
               if (ffx_wave && ((in->intrinsic == nir_intrinsic_reduce && in->def.bit_size == 32 &&
                                 in->def.num_components == 1 &&
                                 nir_intrinsic_reduction_op(in) == nir_op_iadd &&
                                 nir_intrinsic_cluster_size(in) == 0) ||
                                in->intrinsic == nir_intrinsic_elect ||
                                in->intrinsic == nir_intrinsic_load_subgroup_size)) break;
               fprintf(stderr, "unsupported intrinsic: %s\n", nir_intrinsic_infos[in->intrinsic].name);
               goto done;
            }
         }
      }
   }
   /* Fail closed on instruction kinds this profile never emits (texture ops,
    * calls, derefs, jumps...). The intrinsic filter above ignores them, so a
    * sampled-image shader would otherwise reach NAK and abort in its tex
    * lowering instead of being rejected here. */
   error = "INSTRUCTION_PROFILE";
   nir_foreach_function_impl(kind_impl, nir) {
      nir_foreach_block(kind_block, kind_impl) {
         nir_foreach_instr(kind_instr, kind_block) {
            switch (kind_instr->type) {
            case nir_instr_type_alu:
               if (profile->params && !param_alu_allowed(nir_instr_as_alu(kind_instr)->op) &&
                  !(ffx && nir_instr_as_alu(kind_instr)->op == nir_op_ineg) &&
                  !(ffx_wave && ffx_divisor_ok(nir_instr_as_alu(kind_instr)))) {
                  fprintf(stderr, "unsupported alu op: %s\n",
                          nir_op_infos[nir_instr_as_alu(kind_instr)->op].name);
                  goto done;
               }
               break;
            case nir_instr_type_load_const:
            case nir_instr_type_intrinsic:
            case nir_instr_type_phi:
            case nir_instr_type_undef:
               break;
            case nir_instr_type_jump:
               /* Stage 2a: shared_control_flow admitted only loop break/continue. */
               if (profile->shared_profile &&
                   (nir_instr_as_jump(kind_instr)->type == nir_jump_break ||
                    nir_instr_as_jump(kind_instr)->type == nir_jump_continue))
                  break;
               fprintf(stderr, "unsupported jump\n");
               goto done;
            default:
               fprintf(stderr, "unsupported instruction type: %d\n", (int)kind_instr->type);
               goto done;
            }
         }
      }
   }
   if (profile->params) {
      NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_params, nir_metadata_control_flow, &lower);
      NIR_PASS(_, nir, nir_opt_dce);
      error = "PARAMETER_PROFILE";
      if (lower.bad || !lower.param_loads ||
          (profile->shared_profile ? lower.param_mask != profile->param_mask :
           (!(lower.param_mask & 1) || !(lower.param_mask & 2)))) {
         fprintf(stderr, "parameter profile: bad=%u loads=%u mask=%#x\n",
                 lower.bad, lower.param_loads, lower.param_mask);
         goto done;
      }
   }
   if (profile->shared_profile)
      NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_shared_operations, nir_metadata_none, &lower);
   NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_buffer, nir_metadata_none, &lower);
   error = "STORE_PROFILE";
   if (lower.bad || lower.stores != profile->stores ||
       (profile->shared_profile ?
        (lower.loads != profile->loads || lower.shared_atomics != profile->shared_atomics ||
         lower.global_atomics != profile->global_atomics) :
        (lower.loads < 1 || lower.loads > 8 ||
         (profile->params && guarded_accesses != lower.stores + lower.loads)))) {
      fprintf(stderr, "store profile: bad=%u stores=%u loads=%u resources=%u descriptors=%u guarded=%u\n",
              lower.bad, lower.stores, lower.loads, lower.resources, lower.descriptors,
              guarded_accesses);
      goto done;
   }
   error = "GUARDED_PREDICATED_LOAD_PROFILE";
   if (lower.predicated_load && (lower.predicated_loads != 1 ||
       lower.shared_proven != 2 || lower.shared_fallback != 1)) goto done;
   nir->info.num_ssbos = 0;
   nir->info.num_ubos = 0;
   nir->info.io_lowered = true;
   error = "OUTPUT";
   if (!dump_nir(argv[2], "buffer.nir", nir)) goto done;
   nak_lower_nir_before_linking(nir, nak);
   nir_shader_gather_info(nir, nir_shader_get_entrypoint(nir));
   nir_validate_shader(nir, "RTX compile-only lowered UAV");
   error = "OUTPUT";
   if (!dump_nir(argv[2], "lowered.nir", nir)) goto done;
   bin = nak_compile_shader(nir, true, nak, 0, NULL, false);
   error = "NAK_COMPILE";
   if (!bin || !bin->code || !bin->code_size || bin->info.sm != sm ||
       bin->info.stage != MESA_SHADER_COMPUTE || !bin->asm_str) goto done;
   error = "SHADER_METADATA_PROFILE";
   if (bin->code_size > 8192 || bin->code_size % 16 ||
       !bin->info.num_gprs || bin->info.num_gprs > 64 ||
       bin->info.cs.local_size[0] != profile->local[0] ||
       bin->info.cs.local_size[1] != profile->local[1] ||
       bin->info.cs.local_size[2] != profile->local[2] || bin->info.cs.smem_size != profile->shared_bytes ||
       bin->info.slm_size || bin->info.crs_size ||
       bin->info.num_control_barriers != (profile->barriers ? 1u : 0u) ||
       bin->info.num_spills_to_mem || bin->info.num_fills_from_mem ||
       !bin->info.max_warps_per_sm || bin->info.max_warps_per_sm > 48) goto done;
   const struct nak_qmd_info q = {
      .addr = 0x200000000ull, .smem_size = bin->info.cs.smem_size,
      .global_size = {profile->grid[0], profile->grid[1], profile->grid[2]},
      .num_cbufs = 1, .cbufs = {{.index = 0, .size = profile->cb0_size, .addr = 0x200002000ull}},
   };
   uint32_t qmd[64] = {0};
   error = "QMD_SIZE";
   if (nak_qmd_size_B(&device) != sizeof(qmd)) goto done;
   nak_fill_qmd(&device, &bin->info, &q, qmd, sizeof(qmd));
   error = "OUTPUT";
   f = output_file(argv[2], "qmd");
   if (!f || fwrite(qmd, 1, sizeof(qmd), f) != sizeof(qmd)) goto done;
   if (fclose(f)) { f = NULL; goto done; } f = NULL;
   f = output_file(argv[2], "bin");
   if (!f || fwrite(bin->code, 1, bin->code_size, f) != bin->code_size) goto done;
   if (fclose(f)) { f = NULL; goto done; } f = NULL;
   f = output_file(argv[2], "nak.txt");
   if (!f || fputs(bin->asm_str, f) < 0) goto done;
   if (fclose(f)) { f = NULL; goto done; } f = NULL;
   f = output_file(argv[2], "info.bin");
   if (!f || fwrite(&bin->info, 1, sizeof(bin->info), f) != sizeof(bin->info)) goto done;
   if (fclose(f)) { f = NULL; goto done; } f = NULL;
   const struct nak_shader_info *info = &bin->info;
   printf("{\"schema\":\"ndx12.nvidia.%s.compiler.v1\",\"scope\":\"CPU_ONLY\","
          "\"profile\":\"%s\",\"cb0\":{\"layout\":\"%s\","
          "\"bytes\":80,\"qmd_bytes\":128,\"params_offset\":48,\"param_mask\":%u},\"bindings\":[",
          profile->shared_profile ? "shared.readymade_range_candidate" : "batch.readymade_range_candidate", profile->name,
          profile->shared_profile ? "ndx12.nvidia.shared.cb0.v1" : "ndx12.nvidia.batch.cb0.v2",
          lower.param_mask);
   for (unsigned k = 0, first = 1; k < 3; k++) {
      if (!lower.reads[k] && !lower.writes[k]) continue;
      printf("%s{\"binding\":%u,\"reads\":%u,\"writes\":%u,\"base_offset\":%u,\"size_offset\":%u}",
             first ? "" : ",", k, lower.reads[k], lower.writes[k], 16*k, 16*k+8);
      first = 0;
   }
   printf("],");
   if (profile->shared_profile)
      printf("\"shared_operations\":{\"loads\":%u,\"stores\":%u,\"atomics\":%u,\"global_atomics\":%u,\"barriers\":%u},",
             lower.shared_loads, lower.shared_stores, lower.shared_atomics, lower.global_atomics, profile->barriers);
   printf("\"predicated_loads\":%u,\"input_u8_contract\":false,\"input_u8_proven\":0,", lower.predicated_loads);
   printf("\"shared_range_proof\":{\"proven\":%u,\"fallback\":%u},",
          lower.shared_proven, lower.shared_fallback);
   printf("\"code_bytes\":%u,\"shader_info\":{"
          "\"stage\":%u,\"sm\":%u,\"num_gprs\":%u,"
          "\"num_control_barriers\":%u,\"max_warps_per_sm\":%u,"
          "\"num_instrs\":%u,\"num_static_cycles\":%" PRIu64 ","
          "\"num_spills_to_mem\":%u,\"num_fills_from_mem\":%u,"
          "\"num_spills_to_reg\":%u,\"num_fills_from_reg\":%u,"
          "\"slm_size\":%u,\"crs_size\":%u,"
          "\"cs\":{\"local_size\":[%u,%u,%u],\"smem_size\":%u}},"
          "\"target\":{\"sm\":%u,\"max_warps_per_mp\":48,"
          "\"origin\":\"PINNED_SM89_ARCHITECTURAL_TABLE_NOT_OCCUPANCY_MEASUREMENT\","
          "\"physical_device_verified\":false},"
          "\"gpu\":\"NOT_RUN\",\"dispatch\":\"BLOCKED\",\"dispatchable\":false}\n",
          bin->code_size, info->stage, info->sm, info->num_gprs,
          info->num_control_barriers, info->max_warps_per_sm,
          info->num_instrs, info->num_static_cycles,
          info->num_spills_to_mem, info->num_fills_from_mem,
          info->num_spills_to_reg, info->num_fills_from_reg,
          info->slm_size, info->crs_size,
          info->cs.local_size[0], info->cs.local_size[1], info->cs.local_size[2],
          info->cs.smem_size, sm);
   rc = 0;
done:
   if (rc) fprintf(stderr, "RTX_REJECT:%s\n", error);
   if (f) fclose(f);
   if (bin) nak_shader_bin_destroy(bin);
   if (nir) ralloc_free(nir);
   if (nak) nak_compiler_destroy(nak);
   free(words);
   glsl_type_singleton_decref();
   return rc;
}
