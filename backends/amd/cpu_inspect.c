#include "cpu_inspect.h"
#include <stdlib.h>
#include <string.h>
/* Test-only evaluator adapted from CORE-001 nir_cpu_oracle.c (see REPORT).
 * Evaluate actual post-adapter NIR. Python owns HLSL-derived expected values.
 * This is neither a GPU emulator nor an execution fallback. */
struct evaluation { uint32_t (*ssa)[4]; uint32_t *output; unsigned tid, stores; };
static bool
evaluate_list(struct exec_list *list, struct evaluation *e)
{
   foreach_list_typed(nir_cf_node, node, node, list) {
      if (node->type == nir_cf_node_if) {
         nir_if *n = nir_cf_node_as_if(node);
         if (!evaluate_list(e->ssa[n->condition.ssa->index][0] ? &n->then_list : &n->else_list, e))
            return false;
         continue;
      }
      if (node->type != nir_cf_node_block) return false;
      nir_foreach_instr(instr, nir_cf_node_as_block(node)) {
         if (instr->type == nir_instr_type_load_const) {
            nir_load_const_instr *c = nir_instr_as_load_const(instr);
            if (c->def.num_components > 4 || c->def.bit_size > 32) return false;
            for (unsigned j = 0; j < c->def.num_components; j++)
               e->ssa[c->def.index][j] = c->value[j].u32;
         } else if (instr->type == nir_instr_type_alu) {
            nir_alu_instr *a = nir_instr_as_alu(instr);
            if (a->def.num_components != 1 || a->def.bit_size > 32) return false;
            uint32_t x = e->ssa[a->src[0].src.ssa->index][a->src[0].swizzle[0]];
            uint32_t y = nir_op_infos[a->op].num_inputs > 1 ?
               e->ssa[a->src[1].src.ssa->index][a->src[1].swizzle[0]] : 0;
            uint32_t z;
            switch (a->op) {
            case nir_op_mov: z = x; break;
            case nir_op_iadd: z = x + y; break;
            case nir_op_imul: z = x * y; break;
            case nir_op_ixor: z = x ^ y; break;
            case nir_op_iand: z = x & y; break;
            case nir_op_ior: z = x | y; break;
            case nir_op_ishl: z = x << (y & 31); break;
            case nir_op_ult: z = x < y; break;
            case nir_op_uge: z = x >= y; break;
            default: return false;
            }
            e->ssa[a->def.index][0] = z;
         } else if (instr->type == nir_instr_type_intrinsic) {
            nir_intrinsic_instr *in = nir_instr_as_intrinsic(instr);
            if (in->intrinsic == nir_intrinsic_load_global_invocation_id) {
               e->ssa[in->def.index][0] = e->tid;
               e->ssa[in->def.index][1] = e->ssa[in->def.index][2] = 0;
            } else if (in->intrinsic == nir_intrinsic_store_ssbo) {
               uint32_t binding = e->ssa[in->src[1].ssa->index][0];
               uint32_t offset = e->ssa[in->src[2].ssa->index][0];
               if (binding != 3 || offset % 4 || offset / 4 >= 1024 ||
                   in->num_components != 1 || nir_intrinsic_write_mask(in) != 1) return false;
               e->output[32 + offset / 4] = e->ssa[in->src[0].ssa->index][0];
               e->stores++;
            } else return false;
         } else return false;
      }
   }
   return true;
}


int inspect_nir(nir_shader *n, uint32_t output[1088], unsigned *stores)
{
   if (!n || !output || !stores) return 1;
   nir_function_impl *impl = nir_shader_get_entrypoint(n);
   nir_index_ssa_defs(impl);
   struct evaluation e = {.output = output};
   e.ssa = calloc(impl->ssa_alloc, sizeof(*e.ssa));
   if (!e.ssa) return 1;
   for (unsigned i = 0; i < 1088; i++) output[i] = 0xc0decafe;
   bool ok = true;
   for (e.tid = 0; e.tid < 1088; e.tid++) {
      memset(e.ssa, 0, impl->ssa_alloc * sizeof(*e.ssa));
      if (!evaluate_list(&impl->body, &e)) { ok = false; break; }
   }
   free(e.ssa);
   *stores = e.stores;
   return ok ? 0 : 1;
}
