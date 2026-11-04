/* Reuse the normal CB0 and guarded memory lowering, not its SPIR-V entrypoint.
 * Function-section GC removes legacy_spirv_main and its import/validation calls. */
int legacy_spirv_main(int argc, char **argv);
#define main legacy_spirv_main
#include "../nvidia_batch_compile.c"
#undef main
#include "program.h"

static nir_def *
structured_byte_offset(nir_builder *b, nir_def *index)
{
   /* Preserve the original u32 index's range before multiplying by stride.
    * A 32-bit view size cannot admit offset 0xfffffffc: even UINT32_MAX
    * has size - 4 == 0xfffffffb. Existing load/store/atomic guards thus
    * reject the sentinel, returning zero for loads and suppressing writes. */
   return nir_bcsel(b, nir_ult(b, index, nir_imm_int(b, 0x40000000)),
                   nir_imul_imm(b, index, 4), nir_imm_int(b, 0xfffffffc));
}

static nir_shader *
emit_program(const struct ds_program *p, struct nak_compiler *nak)
{
   nir_builder b = nir_builder_init_simple_shader(MESA_SHADER_COMPUTE,
                                                 nak_nir_options(nak), "direct-dxil-shared");
   nir_shader *nir = b.shader;
   for (unsigned k = 0; k < 3; k++) nir->info.workgroup_size[k] = p->local[k];
   nir->info.num_ssbos = p->uavs;
   nir->info.num_ubos = 1;
   /* preprocess barrier-mode analysis operates on derefs, before explicit IO. */
   nir_variable *shared = p->shared_bytes ? nir_variable_create(nir, nir_var_mem_shared,
      glsl_array_type(glsl_uint_type(), p->shared_bytes / 4, 0), "dxil_shared") : NULL;
   nir_def *v[DS_MAX_OPS] = {0};
   /* LLVM constants dominate all blocks, including the bypass side of a phi. */
   for (unsigned i = 0; i < p->count; i++)
      if (p->instructions[i].op == DS_CONST)
         v[i] = nir_imm_intN_t(&b, p->instructions[i].literal, p->instructions[i].bits);
   for (unsigned i = 0; i < p->count; i++) {
      const struct ds_instruction *x = &p->instructions[i];
      nir_def *a = v[x->a], *rhs = v[x->b], *value = NULL;
      switch (x->op) {
      case DS_CONST: continue;
      case DS_TID: value = nir_channel(&b, nir_load_global_invocation_id(&b, 32), x->literal); break;
      case DS_LOCAL: value = nir_channel(&b, nir_load_local_invocation_id(&b), x->literal); break;
      case DS_GROUP: value = nir_channel(&b, nir_load_workgroup_id(&b), x->literal); break;
      case DS_PARAM:
         value = nir_load_ubo(&b, 1, 32, nir_imm_int(&b, 0), nir_imm_int(&b, 4*x->literal),
                              .align_mul = 4, .range_base = 4*x->literal, .range = 4); break;
      case DS_ADD: value = nir_iadd(&b, a, rhs); break;
      case DS_SUB: value = nir_isub(&b, a, rhs); break;
      case DS_MUL: value = nir_imul(&b, a, rhs); break;
      case DS_AND: value = nir_iand(&b, a, rhs); break;
      case DS_OR: value = nir_ior(&b, a, rhs); break;
      case DS_XOR: value = nir_ixor(&b, a, rhs); break;
      case DS_SHL: value = nir_ishl(&b, a, rhs); break;
      case DS_USHR: value = nir_ushr(&b, a, rhs); break;
      case DS_EQ: value = nir_ieq(&b, a, rhs); break;
      case DS_NE: value = nir_ine(&b, a, rhs); break;
      case DS_ULT: value = nir_ult(&b, a, rhs); break;
      case DS_ULE: value = nir_uge(&b, rhs, a); break;
      case DS_UGT: value = nir_ult(&b, rhs, a); break;
      case DS_UGE: value = nir_uge(&b, a, rhs); break;
      case DS_IF: nir_push_if(&b, a); break;
      case DS_ENDIF: nir_pop_if(&b, NULL); break;
      case DS_PHI: value = nir_if_phi(&b, a, rhs); break;
      case DS_LOAD:
         value = nir_load_ssbo(&b, 1, 32, nir_imm_int(&b, x->literal), structured_byte_offset(&b, a),
                              .align_mul = 4, .access = ACCESS_NON_WRITEABLE); break;
      case DS_STORE:
         nir_store_ssbo(&b, rhs, nir_imm_int(&b, x->literal), structured_byte_offset(&b, a),
                        .align_mul = 4, .write_mask = 1, .access = ACCESS_NON_READABLE); break;
      case DS_SHARED_LOAD:
         value = nir_load_deref(&b, nir_build_deref_array(&b, nir_build_deref_var(&b, shared), a)); break;
      case DS_SHARED_STORE:
         nir_store_deref(&b, nir_build_deref_array(&b, nir_build_deref_var(&b, shared), a), rhs, 1); break;
      case DS_SHARED_ADD:
         nir_deref_atomic(&b, 32, &nir_build_deref_array(&b, nir_build_deref_var(&b, shared), a)->def,
                          rhs, .atomic_op = nir_atomic_op_iadd); break;
      case DS_GLOBAL_ADD:
         nir_ssbo_atomic(&b, 32, nir_imm_int(&b, x->literal), structured_byte_offset(&b, a), rhs,
                         .atomic_op = nir_atomic_op_iadd, .access = ACCESS_COHERENT); break;
      case DS_BARRIER:
         nir_barrier(&b, .execution_scope = SCOPE_WORKGROUP, .memory_scope = SCOPE_WORKGROUP,
                     .memory_semantics = NIR_MEMORY_ACQ_REL, .memory_modes = nir_var_mem_shared); break;
      default: ralloc_free(nir); return NULL;
      }
      v[i] = value;
   }
   nir_validate_shader(nir, "direct DXIL emission");
   return nir;
}

int main(int argc, char **argv)
{
   if (argc != 4) { fprintf(stderr, "usage: direct-compile profile input.dxil output-prefix\n"); return 2; }
   const char *requested = argv[1], *input = argv[2], *prefix = argv[3];
   const char *error = "INPUT";
   int rc = 1; FILE *f = NULL; void *bytes = NULL;
   struct nak_compiler *nak = NULL; struct nak_shader_bin *bin = NULL; nir_shader *nir = NULL;
   struct ds_program p = {0}; char diagnostic[256] = {0};
   glsl_type_singleton_init_or_ref();
   f = fopen(input, "rb"); if (!f) goto done;
   if (fseek(f, 0, SEEK_END)) goto done;
   long size = ftell(f); if (size < 32 || size > 1024*1024 || fseek(f, 0, SEEK_SET)) goto done;
   bytes = malloc(size); if (!bytes || fread(bytes, 1, size, f) != (size_t)size) goto done;
   fclose(f); f = NULL;
   if (ds_parse(bytes, size, &p, diagnostic)) { error = diagnostic; goto done; }
   error = "OUTPUT";
   f = output_file(prefix, "program.bin");
   if (!f || fwrite(&p, 1, sizeof(p), f) != sizeof(p)) goto done;
   if (fclose(f)) { f = NULL; goto done; } f = NULL;
   const unsigned sm = 89;
   struct nv_device_info device = {
      .type = NV_DEVICE_TYPE_DIS, .device_id = 0x2684, .chipset = 0x192,
      .sm = 89, .cls_compute = 0xc9c0, .max_warps_per_mp = 48,
      .max_smem_per_wg_kB = 100, .sm_smem_size_count = 6,
      .sm_smem_sizes_kB = {0, 8, 16, 32, 64, 100},
   };
   nak = nak_compiler_create(&device); error = "NAK_CREATE"; if (!nak) goto done;
   nir = emit_program(&p, nak); error = "EMIT"; if (!nir) goto done;
   const struct profile *profile = select_profile(nir, requested);
   error = "DIRECT_PROFILE";
   const bool affine = profile == &profiles[5];
   if (!profile || (!profile->shared_profile && !affine) || p.shared_bytes != profile->shared_bytes ||
       p.barriers != profile->barriers || p.param_mask != profile->param_mask) goto done;
   if (affine && (p.uavs != 2 || p.reads[0] != 1 || p.reads[1] || p.reads[2] ||
                  p.writes[0] || p.writes[1] != 1 || p.writes[2])) goto done;
   if (!dump_nir(prefix, "import.nir", nir)) goto done;
   nak_preprocess_nir(nir, nak);
   const nir_lower_compute_system_values_options csv = {0};
   NIR_PASS(_, nir, nir_lower_compute_system_values, &csv);
   NIR_PASS(_, nir, nir_lower_vars_to_explicit_types, nir_var_mem_shared, shared_var_info);
   NIR_PASS(_, nir, nir_lower_explicit_io, nir_var_mem_shared, nir_address_format_32bit_offset);
   error = "SHARED_LAYOUT";
   if (nir->info.shared_size != p.shared_bytes) goto done;
   NIR_PASS(_, nir, nir_opt_constant_folding);
   NIR_PASS(_, nir, nir_opt_copy_prop);
   NIR_PASS(_, nir, nir_opt_dce);
   error = "CONTROL_FLOW_PROFILE";
   if (!dump_nir(prefix, "prestore.nir", nir)) goto done;
   if (!shared_control_flow(nir, profile->barriers)) goto done;
   struct lowering lower = {.params = true, .shared_bytes = p.shared_bytes};
   NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_params, nir_metadata_control_flow, &lower);
   NIR_PASS(_, nir, nir_opt_dce);
   NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_shared_operations, nir_metadata_none, &lower);
   NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_buffer, nir_metadata_none, &lower);
   error = "RESOURCE_EFFECT_PROFILE";
   if (lower.bad || lower.param_mask != profile->param_mask || lower.loads != profile->loads ||
       lower.stores != profile->stores || lower.shared_atomics != profile->shared_atomics ||
       lower.global_atomics != profile->global_atomics) goto done;
   for (unsigned k = 0; k < 3; k++)
      if (lower.reads[k] != p.reads[k] || lower.writes[k] != p.writes[k]) goto done;
   nir->info.num_ssbos = 0; nir->info.num_ubos = 0; nir->info.io_lowered = true;
   if (!dump_nir(prefix, "buffer.nir", nir)) goto done;
   nak_lower_nir_before_linking(nir, nak);
   nir_shader_gather_info(nir, nir_shader_get_entrypoint(nir));
   nir_validate_shader(nir, "direct DXIL guarded NAK");
   if (!dump_nir(prefix, "lowered.nir", nir)) goto done;
   bin = nak_compile_shader(nir, true, nak, 0, NULL, false);
   error = "NAK_COMPILE";
   if (!bin || !bin->code || !bin->code_size || !bin->asm_str || bin->info.sm != sm ||
       bin->info.stage != MESA_SHADER_COMPUTE) goto done;
   error = "SHADER_METADATA_PROFILE";
   if (sizeof(bin->info) != 864 || bin->code_size > 8192 || bin->code_size % 16 ||
       !bin->info.num_gprs || bin->info.num_gprs > 64 ||
       bin->info.cs.local_size[0] != profile->local[0] || bin->info.cs.local_size[1] != profile->local[1] || bin->info.cs.local_size[2] != profile->local[2] ||
       bin->info.cs.smem_size != p.shared_bytes || bin->info.slm_size || bin->info.crs_size ||
       bin->info.num_spills_to_mem || bin->info.num_fills_from_mem ||
       bin->info.num_control_barriers != (p.barriers ? 1u : 0u) || bin->info.max_warps_per_sm != 48)
      goto done;
   /* Output block below shares the established synthetic QMD and metadata
    * layout; the receipt identifies this separate direct-input compiler. */
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
   f = output_file(prefix, "qmd");
   if (!f || fwrite(qmd, 1, sizeof(qmd), f) != sizeof(qmd)) goto done;
   if (fclose(f)) { f = NULL; goto done; } f = NULL;
   f = output_file(prefix, "bin");
   if (!f || fwrite(bin->code, 1, bin->code_size, f) != bin->code_size) goto done;
   if (fclose(f)) { f = NULL; goto done; } f = NULL;
   f = output_file(prefix, "nak.txt");
   if (!f || fputs(bin->asm_str, f) < 0) goto done;
   if (fclose(f)) { f = NULL; goto done; } f = NULL;
   f = output_file(prefix, "info.bin");
   if (!f || fwrite(&bin->info, 1, sizeof(bin->info), f) != sizeof(bin->info)) goto done;
   if (fclose(f)) { f = NULL; goto done; } f = NULL;
   const struct nak_shader_info *info = &bin->info;
   printf("{\"schema\":\"ndx12.direct.%s.compiler.v1\",\"scope\":\"CPU_ONLY\","
          "\"profile\":\"%s\",\"cb0\":{\"layout\":\"%s\","
          "\"bytes\":80,\"qmd_bytes\":128,\"params_offset\":48,\"param_mask\":%u},\"bindings\":[",
          profile->shared_profile ? "shared" : "batch", profile->name,
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
   free(bytes);
   glsl_type_singleton_decref();
   return rc;
}
