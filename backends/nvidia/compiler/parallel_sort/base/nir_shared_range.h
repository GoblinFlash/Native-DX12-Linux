/* Bounded unsigned SSA proof for a four-byte shared access. No NIR mutation.
 * Unknown values mean [0, UINT32_MAX], not an assumed valid address. An AND
 * may bound any such value. Context facts come only from the access's own
 * fixed compute group and structured ancestor then arms. No PHI analysis or
 * trust in access alignment promises. Overflow loses the arithmetic bound.
 */
#ifndef NDX_NIR_SHARED_RANGE_H
#define NDX_NIR_SHARED_RANGE_H

struct ndx_u32_range {
   uint32_t max;
   bool aligned4;
};

struct ndx_shared_proof {
   struct ndx_u32_range range;
   unsigned visited;
   bool exhausted;
   unsigned cf_visited, facts, local_bounds, branch_bounds;
};

struct ndx_range_fact { nir_scalar scalar; uint32_t max; };
struct ndx_range_context {
   nir_shader *shader;
   struct ndx_range_fact fact[16];
   unsigned count;
   struct ndx_shared_proof *proof;
};

static bool
ndx_range_context(nir_instr *at, struct ndx_range_context *ctx)
{
   if (!at) return true; /* Context-free arithmetic proof remains supported. */
   if (!at->block || !at->block->impl || !at->block->impl->structured)
      return false;
   nir_function_impl *impl = at->block->impl;
   ctx->shader = impl->function->shader;
   nir_cf_node *child = &at->block->cf_node;
   while (child->parent) {
      if (++ctx->proof->cf_visited > 64) goto exhausted;
      nir_cf_node *parent = child->parent;
      if (parent->type == nir_cf_node_function)
         return parent == &impl->cf_node;
      if (parent->type != nir_cf_node_if) return false;
      nir_cf_node *first = child;
      while (!nir_cf_node_is_first(first)) {
         if (++ctx->proof->cf_visited > 64) goto exhausted;
         first = nir_cf_node_prev(first);
      }
      nir_if *nif = nir_cf_node_as_if(parent);
      /* The condition does not constrain the else arm or a later sibling. */
      if (first == &nir_if_first_then_block(nif)->cf_node) {
         nir_def *condition = nif->condition.ssa;
         nir_instr *instr = nir_def_instr(condition);
         if (condition->num_components == 1 && condition->bit_size == 1 &&
             instr->type == nir_instr_type_alu) {
            nir_alu_instr *alu = nir_instr_as_alu(instr);
            if (alu->op == nir_op_ult) {
               nir_scalar a = nir_get_scalar(alu->src[0].src.ssa, alu->src[0].swizzle[0]);
               nir_scalar b = nir_get_scalar(alu->src[1].src.ssa, alu->src[1].swizzle[0]);
               if (a.def->bit_size == 32 && b.def->bit_size == 32 &&
                   nir_scalar_is_const(b) && nir_scalar_as_uint(b) != 0) {
                  if (ctx->count == ARRAY_SIZE(ctx->fact)) goto exhausted;
                  ctx->fact[ctx->count++] = (struct ndx_range_fact){a, nir_scalar_as_uint(b) - 1};
               }
            }
         }
      }
      child = parent;
   }
   return false;
exhausted:
   ctx->proof->exhausted = true;
   return false;
}

static struct ndx_u32_range ndx_u32_range(nir_scalar scalar, unsigned *budget,
                                        struct ndx_range_context *ctx);

static struct ndx_u32_range
ndx_u32_expression(nir_scalar scalar, unsigned *budget, struct ndx_range_context *ctx)
{
   const struct ndx_u32_range unknown = {UINT32_MAX, false};
   if (nir_scalar_is_const(scalar)) {
      uint32_t value = nir_scalar_as_uint(scalar);
      return (struct ndx_u32_range){value, (value & 3) == 0};
   }
   nir_instr *instr = nir_def_instr(scalar.def);
   if (instr->type == nir_instr_type_intrinsic && ctx->shader) {
      nir_intrinsic_op op = nir_instr_as_intrinsic(instr)->intrinsic;
      const struct shader_info *info = &ctx->shader->info;
      if (info->stage != MESA_SHADER_COMPUTE || info->workgroup_size_variable ||
          !info->workgroup_size[0] || !info->workgroup_size[1] || !info->workgroup_size[2])
         return unknown;
      uint64_t size = (uint64_t)info->workgroup_size[0] * info->workgroup_size[1] * info->workgroup_size[2];
      if (size > UINT32_MAX) return unknown;
      if (op == nir_intrinsic_load_local_invocation_id &&
          scalar.def->num_components == 3 && scalar.comp < 3)
         size = info->workgroup_size[scalar.comp];
      else if (op != nir_intrinsic_load_local_invocation_index || scalar.def->num_components != 1)
         return unknown;
      ctx->proof->local_bounds++;
      return (struct ndx_u32_range){size - 1, size == 1};
   }
   if (instr->type != nir_instr_type_alu) return unknown;
   nir_alu_instr *alu = nir_instr_as_alu(instr);
   /* Chase moves ourselves so every step consumes the same finite budget. */
   if (nir_op_is_vec(alu->op)) {
      nir_alu_src src = alu->src[scalar.comp];
      return ndx_u32_range(nir_get_scalar(src.src.ssa, src.swizzle[0]), budget, ctx);
   }
   switch (alu->op) {
   case nir_op_mov: case nir_op_iand: case nir_op_iadd:
   case nir_op_imul: case nir_op_ishl: break;
   default: return unknown;
   }
   nir_scalar left = nir_get_scalar(alu->src[0].src.ssa, alu->src[0].swizzle[scalar.comp]);
   struct ndx_u32_range a = ndx_u32_range(left, budget, ctx);
   if (alu->op == nir_op_mov) return a;
   nir_scalar right = nir_get_scalar(alu->src[1].src.ssa, alu->src[1].swizzle[scalar.comp]);
   if (alu->op == nir_op_ishl) {
      /* NIR masks shift counts; decline rather than execute an unsafe C shift
       * or treat 32 as multiplication by 2^32. Only literal 0..31 here. */
      if (!right.def || right.def->bit_size != 32 || !nir_scalar_is_const(right))
         return unknown;
      uint32_t shift = nir_scalar_as_uint(right);
      if (shift >= 32 || a.max > (UINT32_MAX >> shift)) return unknown;
      return (struct ndx_u32_range){a.max << shift, a.aligned4 || shift >= 2};
   }
   struct ndx_u32_range b = ndx_u32_range(right, budget, ctx);
   if (alu->op == nir_op_iand)
      return (struct ndx_u32_range){MIN2(a.max, b.max), a.aligned4 || b.aligned4};
   uint64_t maximum = alu->op == nir_op_iadd ? (uint64_t)a.max + b.max :
                                              (uint64_t)a.max * b.max;
   if (maximum > UINT32_MAX) return unknown;
   return (struct ndx_u32_range){(uint32_t)maximum,
      alu->op == nir_op_iadd ? a.aligned4 && b.aligned4 : a.aligned4 || b.aligned4};
}

static struct ndx_u32_range
ndx_u32_range(nir_scalar scalar, unsigned *budget, struct ndx_range_context *ctx)
{
   const struct ndx_u32_range unknown = {UINT32_MAX, false};
   if (!*budget) {
      ctx->proof->exhausted = true;
      return unknown;
   }
   --*budget;
   if (!scalar.def || scalar.def->bit_size != 32 ||
       scalar.comp >= scalar.def->num_components)
      return unknown;
   struct ndx_u32_range range = ndx_u32_expression(scalar, budget, ctx);
   for (unsigned i = 0; i < ctx->count; i++) {
      const struct ndx_range_fact *fact = &ctx->fact[i];
      if (scalar.def == fact->scalar.def && scalar.comp == fact->scalar.comp && fact->max < range.max) {
         range.max = fact->max;
         ctx->proof->branch_bounds++;
      }
   }
   return range;
}

static bool
ndx_shared_access_proven_at(nir_def *offset, uint32_t base, uint32_t bytes,
                            nir_instr *at, struct ndx_shared_proof *proof)
{
   *proof = (struct ndx_shared_proof){.range = {UINT32_MAX, false}};
   if (!offset || offset->num_components != 1 || offset->bit_size != 32 ||
       bytes < 4 || base > bytes - 4 || (base & 3))
      return false;
   struct ndx_range_context ctx = {.proof = proof};
   if (!ndx_range_context(at, &ctx)) return false;
   proof->facts = ctx.count;
   unsigned budget = 64;
   proof->range = ndx_u32_range(nir_get_scalar(offset, 0), &budget, &ctx);
   proof->visited = 64 - budget;
   return !proof->exhausted && proof->range.aligned4 &&
          proof->range.max <= bytes - base - 4;
}

static bool
ndx_shared_access_proven(nir_def *offset, uint32_t base, uint32_t bytes,
                         struct ndx_shared_proof *proof)
{
   return ndx_shared_access_proven_at(offset, base, bytes, NULL, proof);
}

#endif
