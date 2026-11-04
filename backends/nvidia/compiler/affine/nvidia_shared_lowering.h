/* Private helpers for the explicitly selected SHARED-002 compiler profiles. */
static void
shared_var_info(const struct glsl_type *type, unsigned *size, unsigned *align)
{
   unsigned component = glsl_type_is_boolean(type) ? 4 : glsl_get_bit_size(type) / 8;
   *size = component * glsl_get_vector_elements(type);
   *align = component;
}

static bool
shared_control_flow(nir_shader *nir, unsigned expected_barriers)
{
   unsigned barriers = 0;
   nir_foreach_function_impl(impl, nir) {
      nir_foreach_block(block, impl) {
         for (nir_cf_node *parent = block->cf_node.parent; parent; parent = parent->parent) {
            if (parent->type == nir_cf_node_loop) return false;
         }
         nir_foreach_instr(instr, block) {
            if (instr->type == nir_instr_type_jump || instr->type == nir_instr_type_call)
               return false;
            if (instr->type != nir_instr_type_intrinsic) continue;
            nir_intrinsic_instr *in = nir_instr_as_intrinsic(instr);
            if (in->intrinsic != nir_intrinsic_barrier) continue;
            if (block->cf_node.parent != &impl->cf_node ||
                nir_intrinsic_execution_scope(in) != SCOPE_WORKGROUP ||
                nir_intrinsic_memory_scope(in) != SCOPE_WORKGROUP ||
                nir_intrinsic_memory_modes(in) != nir_var_mem_shared ||
                nir_intrinsic_memory_semantics(in) != NIR_MEMORY_ACQ_REL)
               return false;
            barriers++;
         }
      }
   }
   return barriers == expected_barriers;
}

static bool
shared_intrinsic_allowed(nir_intrinsic_instr *in)
{
   switch (in->intrinsic) {
   case nir_intrinsic_barrier:
   case nir_intrinsic_load_shared:
   case nir_intrinsic_store_shared:
      return true;
   case nir_intrinsic_ssbo_atomic:
   case nir_intrinsic_shared_atomic:
      return in->def.num_components == 1 && in->def.bit_size == 32 &&
             nir_intrinsic_atomic_op(in) == nir_atomic_op_iadd &&
             nir_def_is_unused(&in->def);
   default:
      return false;
   }
}

static bool
lower_shared_operations(nir_builder *b, nir_intrinsic_instr *in, void *data)
{
   struct lowering *s = data;
   bool global = in->intrinsic == nir_intrinsic_ssbo_atomic;
   bool atomic = global || in->intrinsic == nir_intrinsic_shared_atomic;
   bool load = in->intrinsic == nir_intrinsic_load_shared;
   bool store = in->intrinsic == nir_intrinsic_store_shared;
   if (!atomic && !load && !store) return false;
   if (in->num_components != 1 ||
       (store ? in->src[0].ssa->bit_size : in->def.bit_size) != 32 ||
       (store && nir_intrinsic_write_mask(in) != 1) ||
       (atomic && (nir_intrinsic_atomic_op(in) != nir_atomic_op_iadd ||
                   !nir_def_is_unused(&in->def))) ||
       (global && nir_intrinsic_offset_shift(in) != 0)) {
      s->bad = true;
      return false;
   }
   unsigned slot = 0, base = 0;
   if (global) {
      nir_scalar binding = nir_scalar_resolved(in->src[0].ssa, 0);
      if (!nir_scalar_is_const(binding) || nir_scalar_as_uint(binding) >= 3) {
         s->bad = true;
         return false;
      }
      slot = nir_scalar_as_uint(binding);
   } else {
      base = nir_intrinsic_base(in);
      if (s->shared_bytes < 4 || base > s->shared_bytes - 4 || base % 4) {
         s->bad = true;
         return false;
      }
   }
   b->cursor = nir_before_instr(&in->instr);
   nir_def *offset = in->src[global || store ? 1 : 0].ssa;
   nir_def *valid, *address = NULL;
   if (global) {
      nir_def *va = nir_ldc_nv(b, 1, 64, nir_imm_int(b, 0),
                             nir_imm_int(b, 16 * slot), .align_mul = 8);
      nir_def *size = nir_ldc_nv(b, 1, 32, nir_imm_int(b, 0),
                               nir_imm_int(b, 16 * slot + 8), .align_mul = 4);
      address = nir_iadd(b, va, nir_u2u64(b, offset));
      valid = nir_iand(b, nir_uge(b, size, nir_imm_int(b, 4)),
                      nir_uge(b, nir_iadd_imm(b, size, -4), offset));
      valid = nir_iand(b, valid, nir_uge(b, address, va));
      valid = nir_iand(b, valid, nir_ieq_imm(b, nir_iand_imm(b, va, 3), 0));
   } else {
      valid = nir_uge(b, nir_imm_int(b, s->shared_bytes - base - 4), offset);
   }
   valid = nir_iand(b, valid, nir_ieq_imm(b, nir_iand_imm(b, offset, 3), 0));
   nir_push_if(b, valid);
   if (global) {
      nir_global_atomic(b, 32, address, in->src[2].ssa,
                        .access = nir_intrinsic_access(in), .atomic_op = nir_atomic_op_iadd);
      s->global_atomics++;
      s->reads[slot]++;
      s->writes[slot]++;
   } else if (atomic) {
      nir_shared_atomic(b, 32, offset, in->src[1].ssa, .base = base,
                        .access = nir_intrinsic_access(in), .atomic_op = nir_atomic_op_iadd);
      s->shared_atomics++;
   } else if (store) {
      nir_store_shared(b, in->src[0].ssa, offset, .base = base,
                       .align_mul = 4, .write_mask = 1, .access = nir_intrinsic_access(in));
      s->shared_stores++;
   } else {
      nir_def *value = nir_load_shared(b, 1, 32, offset, .base = base,
                                      .align_mul = 4, .access = nir_intrinsic_access(in));
      nir_push_else(b, NULL);
      nir_def *zero = nir_imm_int(b, 0);
      nir_pop_if(b, NULL);
      nir_def_rewrite_uses(&in->def, nir_if_phi(b, value, zero));
      s->shared_loads++;
   }
   if (!load) nir_pop_if(b, NULL);
   nir_instr_remove(&in->instr);
   return true;
}
