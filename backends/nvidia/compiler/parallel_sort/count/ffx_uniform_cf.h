#ifndef NDX_FFX_UNIFORM_CF_012_H
#define NDX_FFX_UNIFORM_CF_012_H

/* SORT-FFX-012 stage 5 (ffx-scatter only): workgroup barriers inside control flow whose every
 * decision is workgroup-uniform. The base rule admits barriers only in top-level blocks.
 *
 * A value is workgroup-uniform when it is built only from constants, undef, the workgroup id and
 * b0 (load_ubo of UBO 0 at a uniform offset), ALU of such values, and phis whose incoming values
 * are uniform and whose join is controlled by a uniform if or a uniform loop. Everything else
 * (local id, subgroup ops, shared/global loads, atomics) is not uniform. Cycles through phis are
 * assumed uniform while being evaluated (optimistic fixpoint, as in divergence analysis); every
 * external input and every control dependence is still checked, and one query fails as a whole
 * on the first non-uniform input, so a cached optimistic answer never survives a failed query.
 *
 * An if is uniform when its condition is. A loop is uniform when every break/continue whose
 * innermost loop it is sits only under ifs (up to that loop) with uniform conditions. A barrier is
 * admitted when every cf ancestor up to the function body is a uniform if or a uniform loop. */

#include "util/set.h"

static bool ffx_cf_uniform(nir_cf_node *node, struct set *visiting);

static bool
ffx_uniform(nir_def *def, struct set *visiting)
{
   nir_instr *instr = nir_def_instr(def);
   if (_mesa_set_search(visiting, instr)) return true;
   _mesa_set_add(visiting, instr);
   switch (instr->type) {
   case nir_instr_type_load_const:
   case nir_instr_type_undef:
      return true;
   case nir_instr_type_alu: {
      nir_alu_instr *alu = nir_instr_as_alu(instr);
      for (unsigned i = 0; i < nir_op_infos[alu->op].num_inputs; i++)
         if (!ffx_uniform(alu->src[i].src.ssa, visiting)) return false;
      return true;
   }
   case nir_instr_type_intrinsic: {
      nir_intrinsic_instr *in = nir_instr_as_intrinsic(instr);
      if (in->intrinsic == nir_intrinsic_load_workgroup_id) return true;
      if (in->intrinsic == nir_intrinsic_load_ubo)
         return nir_src_is_const(in->src[0]) && !nir_src_as_uint(in->src[0]) &&
                ffx_uniform(in->src[1].ssa, visiting);
      return false;
   }
   case nir_instr_type_phi: {
      nir_phi_instr *phi = nir_instr_as_phi(instr);
      nir_foreach_phi_src(s, phi)
         if (!ffx_uniform(s->src.ssa, visiting)) return false;
      nir_cf_node *block = &instr->block->cf_node;
      nir_cf_node *prev = nir_cf_node_prev(block);
      if (prev && prev->type == nir_cf_node_if)
         return ffx_uniform(nir_cf_node_as_if(prev)->condition.ssa, visiting);
      if (prev && prev->type == nir_cf_node_loop)
         return ffx_cf_uniform(prev, visiting);
      if (!prev && block->parent->type == nir_cf_node_loop)
         return ffx_cf_uniform(block->parent, visiting);
      return false;
   }
   default:
      return false;
   }
}

static bool
ffx_cf_uniform(nir_cf_node *node, struct set *visiting)
{
   if (node->type == nir_cf_node_if)
      return ffx_uniform(nir_cf_node_as_if(node)->condition.ssa, visiting);
   if (node->type != nir_cf_node_loop)
      return false;
   if (_mesa_set_search(visiting, node)) return true;
   _mesa_set_add(visiting, node);
   nir_foreach_block_in_cf_node(block, node) {
      nir_foreach_instr(instr, block) {
         if (instr->type != nir_instr_type_jump) continue;
         nir_cf_node *p = block->cf_node.parent;
         while (p && p->type != nir_cf_node_loop) {
            if (p->type != nir_cf_node_if ||
                !ffx_uniform(nir_cf_node_as_if(p)->condition.ssa, visiting))
               return false;
            p = p->parent;
         }
         if (!p) return false;
         /* A jump of an inner loop belongs to that loop; it is checked when that loop is. */
      }
   }
   return true;
}

static bool
ffx_barrier_uniform(nir_function_impl *impl, nir_block *block)
{
   for (nir_cf_node *p = block->cf_node.parent; p && p != &impl->cf_node; p = p->parent) {
      struct set *visiting = _mesa_pointer_set_create(NULL);
      bool ok = ffx_cf_uniform(p, visiting);
      _mesa_set_destroy(visiting, NULL);
      if (!ok) return false;
   }
   return true;
}

/* shared_control_flow (nvidia_shared_lowering.h) with one change: a barrier outside the top level
 * is admitted only under uniform control flow. Calls, other jumps, barrier scopes/semantics and the
 * exact barrier count are checked exactly as in the base rule. */
static bool
ffx_scatter_control_flow(nir_shader *nir, unsigned expected_barriers)
{
   unsigned barriers = 0;
   nir_foreach_function_impl(impl, nir) {
      nir_foreach_block(block, impl) {
         bool in_loop = false;
         for (nir_cf_node *parent = block->cf_node.parent; parent; parent = parent->parent) {
            if (parent->type == nir_cf_node_loop) in_loop = true;
         }
         nir_foreach_instr(instr, block) {
            if (instr->type == nir_instr_type_call)
               return false;
            if (instr->type == nir_instr_type_jump) {
               nir_jump_type jump = nir_instr_as_jump(instr)->type;
               if (!in_loop || (jump != nir_jump_break && jump != nir_jump_continue))
                  return false;
               continue;
            }
            if (instr->type != nir_instr_type_intrinsic) continue;
            nir_intrinsic_instr *in = nir_instr_as_intrinsic(instr);
            if (in->intrinsic != nir_intrinsic_barrier) continue;
            if ((block->cf_node.parent != &impl->cf_node && !ffx_barrier_uniform(impl, block)) ||
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

#endif
