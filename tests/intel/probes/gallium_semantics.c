#include <inttypes.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <drm_fourcc.h>

#include "pipe/p_context.h"
#include "pipe/p_screen.h"
#include "pipe/p_state.h"
#include "frontend/winsys_handle.h"
#include "util/u_inlines.h"
#include "compiler/nir/nir_builder.h"
#include "gallium_probe.h"

enum { SMALL_COUNT = 1024, GUARD_COUNT = 16, ALIGNMENT = 65536 };
static const uint32_t unset = 0xdeadbeef;
static const uint32_t canary = 0xa5c39e71;

static struct pipe_resource *buffer_new(struct pipe_screen *screen, unsigned bytes,
                                        unsigned bind, unsigned flags)
{
   struct pipe_resource description = {
      .target = PIPE_BUFFER, .format = PIPE_FORMAT_R8_UNORM,
      .width0 = bytes, .height0 = 1, .depth0 = 1, .array_size = 1,
      .usage = PIPE_USAGE_DEFAULT, .bind = bind, .flags = flags,
   };
   struct pipe_resource *resource = screen->resource_create(screen, &description);
   require(resource != NULL, "M0b buffer allocation failed");
   return resource;
}

static void finish(struct pipe_context *ctx)
{
   struct pipe_fence_handle *fence = NULL;
   ctx->flush(ctx, &fence, 0);
   require(fence && ctx->screen->fence_finish(ctx->screen, ctx, fence, 10000000000ull),
           "M0b fence timeout");
   ctx->screen->fence_reference(ctx->screen, &fence, NULL);
}

static void bind_ssbo_range(struct pipe_context *ctx, unsigned slot,
                            struct pipe_resource *resource, unsigned offset,
                            unsigned bytes, bool write)
{
   struct pipe_shader_buffer binding = {
      .buffer = resource, .buffer_offset = offset, .buffer_size = bytes,
   };
   ctx->set_shader_buffers(ctx, MESA_SHADER_COMPUTE, slot, 1, &binding, write ? 1 : 0);
}

static void bind_ssbo(struct pipe_context *ctx, unsigned slot,
                      struct pipe_resource *resource, unsigned bytes, bool write)
{
   bind_ssbo_range(ctx, slot, resource, 0, bytes, write);
}

static void read_buffer(struct pipe_context *ctx, struct pipe_resource *resource,
                         void *destination, unsigned bytes)
{
   struct pipe_transfer *transfer = NULL;
   void *map = pipe_buffer_map_range(ctx, resource, 0, bytes, PIPE_MAP_READ, &transfer);
   require(map != NULL, "M0b buffer map failed");
   memcpy(destination, map, bytes);
   pipe_buffer_unmap(ctx, transfer);
}

static void dump_nir(const char *prefix, const char *name, const char *stage, nir_shader *nir)
{
   char suffix[128];
   snprintf(suffix, sizeof(suffix), "%s.%s.nir.txt", name, stage);
   FILE *out = artifact(prefix, suffix, "w");
   nir_print_shader(nir, out);
   fclose(out);
}

static nir_builder shader_new(struct pipe_screen *screen, const char *name, unsigned ssbos)
{
   nir_builder b = nir_builder_init_simple_shader(
      MESA_SHADER_COMPUTE, screen->nir_options[MESA_SHADER_COMPUTE], "%s", name);
   b.shader->info.internal = false;
   b.shader->info.workgroup_size[0] = 64;
   b.shader->info.workgroup_size[1] = 1;
   b.shader->info.workgroup_size[2] = 1;
   b.shader->info.num_ssbos = ssbos;
   return b;
}

static void *shader_create(struct pipe_context *ctx, nir_shader *nir,
                           const char *prefix, const char *name)
{
   nir_shader_gather_info(nir, nir_shader_get_entrypoint(nir));
   nir_validate_shader(nir, "M0b frontend");
   dump_nir(prefix, name, "input", nir);
   ctx->screen->finalize_nir(ctx->screen, nir, true);
   nir_validate_shader(nir, "M0b finalized");
   dump_nir(prefix, name, "final", nir);
   struct pipe_compute_state state = {.ir_type = PIPE_SHADER_IR_NIR, .prog = nir};
   void *shader = ctx->create_compute_state(ctx, &state);
   require(shader != NULL, "M0b create_compute_state failed");
   return shader;
}

static void dispatch(struct pipe_context *ctx, void *shader, unsigned count, bool submit)
{
   ctx->bind_compute_state(ctx, shader);
   if (submit) {
      struct pipe_grid_info grid = {
         .work_dim = 1, .block = {64, 1, 1}, .grid = {count / 64, 1, 1},
      };
      ctx->launch_grid(ctx, &grid);
      ctx->memory_barrier(ctx, PIPE_BARRIER_ALL);
   }
}

static void output_reset(struct pipe_context *ctx, struct pipe_resource *resource, unsigned count)
{
   uint32_t *words = malloc((count + GUARD_COUNT) * 4);
   require(words != NULL, "M0b host allocation failed");
   for (unsigned i = 0; i < count + GUARD_COUNT; i++)
      words[i] = i < count ? unset : canary;
   pipe_buffer_write(ctx, resource, 0, (count + GUARD_COUNT) * 4, words);
   free(words);
}

static unsigned output_check(struct pipe_context *ctx, struct pipe_resource *resource,
                              const uint32_t *expected, unsigned count,
                              const char *prefix, unsigned phase)
{
   uint32_t *words = malloc((count + GUARD_COUNT) * 4);
   require(words != NULL, "M0b readback allocation failed");
   read_buffer(ctx, resource, words, (count + GUARD_COUNT) * 4);
   char suffix[64];
   snprintf(suffix, sizeof(suffix), "phase%u.bin", phase);
   FILE *raw = artifact(prefix, suffix, "wb");
   require(fwrite(words, (count + GUARD_COUNT) * 4, 1, raw) == 1, "M0b save readback failed");
   fclose(raw);
   unsigned mismatch = 0, guard_changes = 0, sentinels = 0;
   for (unsigned i = 0; i < count; i++) {
      mismatch += words[i] != expected[i];
      sentinels += words[i] == unset;
   }
   for (unsigned i = count; i < count + GUARD_COUNT; i++)
      guard_changes += words[i] != canary;
   printf("phase%u_checked=%u\nphase%u_mismatches=%u\nphase%u_sentinels=%u\n"
          "phase%u_guard_changes=%u\nphase%u_first=%"PRIu32"\nphase%u_last=%"PRIu32"\n",
          phase, count, phase, mismatch, phase, sentinels, phase, guard_changes,
          phase, words[0], phase, words[count - 1]);
   free(words);
   require(!guard_changes, "M0b output guard changed");
   return mismatch;
}

static uint32_t mix(uint32_t value, unsigned i)
{
   return (value * 3u + 11u) ^ (i * 0x9e3779b9u);
}

static unsigned root_cbv(struct pipe_screen *screen, struct pipe_context *ctx,
                          const char *prefix, unsigned seed, const char *action)
{
   enum { SOURCE_WORDS = 2048, OFFSET_A = 256, OFFSET_B = 512 };
   struct pipe_resource *sources[2];
   for (unsigned n = 0; n < 2; n++)
      sources[n] = buffer_new(screen, SOURCE_WORDS * 4, PIPE_BIND_GLOBAL,
                              PIPE_RESOURCE_FLAG_FIXED_ADDRESS);
   uint32_t inputs[2][SOURCE_WORDS];
   for (unsigned n = 0; n < 2; n++) {
      for (unsigned i = 0; i < SOURCE_WORDS; i++)
         inputs[n][i] = (i * (17u + n * 14u) + seed + n * 19u) ^ (i >> 2);
      pipe_buffer_write(ctx, sources[n], 0, sizeof(inputs[n]), inputs[n]);
   }
   uint64_t base[2] = {screen->resource_get_address(screen, sources[0]),
                        screen->resource_get_address(screen, sources[1])};
   require(base[0] && base[1] && base[0] != base[1], "M0b missing/distinct GPU addresses");
   uint64_t addresses[2] = {OFFSET_A, OFFSET_B};
   uint32_t *handles[2] = {(uint32_t *)&addresses[0], (uint32_t *)&addresses[1]};
   ctx->set_global_binding(ctx, 0, 2, sources, handles);
   require(addresses[0] == base[0] + OFFSET_A && addresses[1] == base[1] + OFFSET_B,
           "set_global_binding address differs from resource_get_address");
   require(!(addresses[0] & 255) && !(addresses[1] & 255), "root CBV address not 256-byte aligned");
   printf("root_base_a=%"PRIu64"\nroot_base_b=%"PRIu64"\nroot_address_a=%"PRIu64"\nroot_address_b=%"PRIu64"\n",
          base[0], base[1], addresses[0], addresses[1]);
   nir_builder b = shader_new(screen, "m0b_root_cbv_address", 1);
   b.shader->info.num_ubos = 1;
   nir_def *i = nir_channel(&b, nir_load_global_invocation_id(&b, 32), 0);
   nir_def *root = nir_load_ubo(&b, 1, 64, nir_imm_int(&b, 0), nir_imm_int(&b, 0),
                               .align_mul = 8, .range = 8);
   nir_def *address = nir_iadd(&b, root, nir_u2u64(&b, nir_imul_imm(&b, i, 4)));
   nir_def *value = nir_load_global_constant(&b, 1, 32, address, .align_mul = 4);
   nir_def *result = nir_ixor(&b, nir_iadd_imm(&b, nir_imul_imm(&b, value, 3), 11),
                              nir_imul_imm(&b, i, 0x9e3779b9u));
   nir_store_ssbo(&b, result, nir_imm_int(&b, 0), nir_imul_imm(&b, i, 4),
                  .write_mask = 1, .align_mul = 4);
   void *shader = shader_create(ctx, b.shader, prefix, "root-cbv");
   struct pipe_resource *output = buffer_new(screen, (SMALL_COUNT + GUARD_COUNT) * 4,
                                            PIPE_BIND_SHADER_BUFFER, 0);
   struct pipe_resource *root_data = buffer_new(screen, 256, PIPE_BIND_CONSTANT_BUFFER, 0);
   output_reset(ctx, output, SMALL_COUNT);
   finish(ctx);
   snapshot(prefix, "before-dispatch");
   unsigned mismatches = 0;
   for (unsigned phase = 0; phase < 3; phase++) {
      if (phase == 2) {
         for (unsigned i = 0; i < SOURCE_WORDS; i++)
            inputs[0][i] ^= 0x13579bdfu;
         ctx->invalidate_resource(ctx, sources[0]);
         pipe_buffer_write(ctx, sources[0], 0, sizeof(inputs[0]), inputs[0]);
      }
      unsigned chosen = phase == 1 ? 1 : 0;
      unsigned actual = !strcmp(action, "wrong-buffer") ? 1 - chosen : chosen;
      uint64_t pointer = addresses[actual];
      pipe_buffer_write(ctx, root_data, 0, sizeof(pointer), &pointer);
      struct pipe_constant_buffer root_binding = {.buffer = root_data, .buffer_size = 256};
      ctx->set_constant_buffer(ctx, MESA_SHADER_COMPUTE, 0, &root_binding);
      output_reset(ctx, output, SMALL_COUNT);
      bind_ssbo(ctx, 0, output, output->width0, true);
      dispatch(ctx, shader, SMALL_COUNT, strcmp(action, "no-dispatch") != 0);
      finish(ctx);
      require(base[0] == screen->resource_get_address(screen, sources[0]) &&
              base[1] == screen->resource_get_address(screen, sources[1]),
              "fixed GPU virtual address changed");
      uint32_t expected[SMALL_COUNT];
      unsigned source_offset = chosen ? OFFSET_B / 4 : OFFSET_A / 4;
      for (unsigned i = 0; i < SMALL_COUNT; i++)
         expected[i] = mix(inputs[chosen][source_offset + i], i);
      printf("phase%u_root_address=%"PRIu64"\n", phase, pointer);
      mismatches += output_check(ctx, output, expected, SMALL_COUNT, prefix, phase);
   }
   snapshot(prefix, "after-readback");
   printf("address_stable=1\naddress_rebound=1\nphases=3\n");
   ctx->set_constant_buffer(ctx, MESA_SHADER_COMPUTE, 0, NULL);
   ctx->set_global_binding(ctx, 0, 2, NULL, NULL);
   ctx->set_shader_buffers(ctx, MESA_SHADER_COMPUTE, 0, 1, NULL, 0);
   ctx->bind_compute_state(ctx, NULL);
   ctx->delete_compute_state(ctx, shader);
   pipe_resource_reference(&output, NULL);
   pipe_resource_reference(&root_data, NULL);
   for (unsigned n = 0; n < 2; n++)
      pipe_resource_reference(&sources[n], NULL);
   return mismatches;
}

static unsigned descriptor_table(struct pipe_screen *screen, struct pipe_context *ctx,
                                 const char *prefix, unsigned seed, const char *action)
{
   struct pipe_resource *resources[4];
   uint32_t inputs[4][SMALL_COUNT], selectors[SMALL_COUNT];
   for (unsigned n = 0; n < 4; n++) {
      resources[n] = buffer_new(screen, SMALL_COUNT * 4, PIPE_BIND_SHADER_BUFFER, 0);
      for (unsigned i = 0; i < SMALL_COUNT; i++)
         inputs[n][i] = (n + 1) * 100003u + seed * 13u + i * (n + 7u);
      pipe_buffer_write(ctx, resources[n], 0, sizeof(inputs[n]), inputs[n]);
   }
   struct pipe_resource *selection = buffer_new(screen, sizeof(selectors), PIPE_BIND_SHADER_BUFFER, 0);
   struct pipe_resource *output = buffer_new(screen, (SMALL_COUNT + GUARD_COUNT) * 4,
                                            PIPE_BIND_SHADER_BUFFER, 0);
   nir_builder b = shader_new(screen, "m0b_nonuniform_descriptor_table", 6);
   nir_def *i = nir_channel(&b, nir_load_global_invocation_id(&b, 32), 0);
   nir_def *offset = nir_imul_imm(&b, i, 4);
   nir_def *index = nir_load_ssbo(&b, 1, 32, nir_imm_int(&b, 4), offset, .align_mul = 4);
   index = nir_iand_imm(&b, index, 3);
   nir_def *value = nir_load_ssbo(&b, 1, 32, index, offset,
                                 .access = ACCESS_NON_UNIFORM, .align_mul = 4);
   nir_def *result = nir_ixor(&b, nir_iadd(&b, nir_imul_imm(&b, value, 7), index),
                              nir_imul_imm(&b, i, 0x9e3779b9u));
   nir_store_ssbo(&b, result, nir_imm_int(&b, 5), offset, .write_mask = 1, .align_mul = 4);
   dump_nir(prefix, "table", "nonuniform", b.shader);
   const nir_lower_non_uniform_access_options options = {.types = nir_lower_non_uniform_ssbo_access};
   require(nir_lower_non_uniform_access(b.shader, &options), "nonuniform SSBO lowering did not run");
   void *shader = shader_create(ctx, b.shader, prefix, "table");
   output_reset(ctx, output, SMALL_COUNT);
   finish(ctx);
   snapshot(prefix, "before-dispatch");
   unsigned mismatches = 0;
   const unsigned permutations[2][4] = {{0, 1, 2, 3}, {2, 0, 3, 1}};
   for (unsigned phase = 0; phase < 2; phase++) {
      uint32_t expected[SMALL_COUNT];
      for (unsigned i = 0; i < SMALL_COUNT; i++) {
         selectors[i] = (i * 3u + (i >> 2) + seed + phase) & 3;
         unsigned selected = permutations[phase][selectors[i]];
         expected[i] = (inputs[selected][i] * 7u + selectors[i]) ^ (i * 0x9e3779b9u);
      }
      pipe_buffer_write(ctx, selection, 0, sizeof(selectors), selectors);
      for (unsigned slot = 0; slot < 4; slot++) {
         unsigned actual = !strcmp(action, "wrong-buffer") ? 0 : permutations[phase][slot];
         bind_ssbo(ctx, slot, resources[actual], resources[actual]->width0, false);
      }
      output_reset(ctx, output, SMALL_COUNT);
      bind_ssbo(ctx, 4, selection, selection->width0, false);
      bind_ssbo(ctx, 5, output, output->width0, true);
      dispatch(ctx, shader, SMALL_COUNT, strcmp(action, "no-dispatch") != 0);
      finish(ctx);
      mismatches += output_check(ctx, output, expected, SMALL_COUNT, prefix, phase);
   }
   snapshot(prefix, "after-readback");
   printf("nonuniform_indexing=1\nfrontend_waterfall_lowering=1\ntable_resources=4\nphases=2\n");
   ctx->set_shader_buffers(ctx, MESA_SHADER_COMPUTE, 0, 6, NULL, 0);
   ctx->bind_compute_state(ctx, NULL);
   ctx->delete_compute_state(ctx, shader);
   for (unsigned n = 0; n < 4; n++)
      pipe_resource_reference(&resources[n], NULL);
   pipe_resource_reference(&selection, NULL);
   pipe_resource_reference(&output, NULL);
   return mismatches;
}

static unsigned placed_alias(struct pipe_screen *screen, struct pipe_context *ctx,
                             const char *prefix, unsigned seed, unsigned variant,
                             const char *action)
{
   const unsigned size = 2 * ALIGNMENT;
   require(variant == 0 || variant == 1 || variant == 3 || variant == 4,
           "unknown placed-alias variant; size compensation is unsupported");
   const unsigned offset = variant == 3 ? 2 * ALIGNMENT : variant ? ALIGNMENT : 0;
   const unsigned binding_offset = variant == 4 ? 4096 : 0;
   const unsigned bound_size = variant == 4 ? ALIGNMENT : size;
   const unsigned heap_bytes = offset + size + ALIGNMENT;
   const unsigned count = bound_size / 4;
   struct pipe_resource *heap = buffer_new(screen, heap_bytes,
      PIPE_BIND_SHADER_BUFFER | PIPE_BIND_SHARED | PIPE_BIND_GLOBAL,
      PIPE_RESOURCE_FLAG_FIXED_ADDRESS);
   uint32_t *heap_words = malloc(heap_bytes);
   uint32_t *expected = malloc(size);
   require(heap_words && expected, "alias host allocation failed");
   for (unsigned i = 0; i < heap_bytes / 4; i++)
      heap_words[i] = canary;
   pipe_buffer_write(ctx, heap, 0, heap_bytes, heap_words);
   finish(ctx);
   struct winsys_handle handle = {.type = WINSYS_HANDLE_TYPE_FD};
   require(screen->resource_get_handle(screen, ctx, heap, &handle, PIPE_HANDLE_USAGE_SHADER_WRITE),
           "Iris dma-buf export failed");
   require(handle.offset == 0, "heap dma-buf has unexpected suballocation offset");
   handle.modifier = DRM_FORMAT_MOD_INVALID;
   struct pipe_memory_object *memory = screen->memobj_create_from_handle(screen, &handle, false);
   close(handle.handle);
   require(memory != NULL, "Iris dma-buf memobj import failed");
   struct pipe_resource description = {
      .target = PIPE_BUFFER, .format = PIPE_FORMAT_R8_UNORM, .width0 = size,
      .height0 = 1, .depth0 = 1, .array_size = 1,
      .usage = PIPE_USAGE_DEFAULT, .bind = PIPE_BIND_SHADER_BUFFER | PIPE_BIND_GLOBAL,
      .flags = PIPE_RESOURCE_FLAG_FIXED_ADDRESS,
   };
   struct pipe_resource *a = screen->resource_from_memobj(screen, &description, memory, offset);
   struct pipe_resource *b = screen->resource_from_memobj(screen, &description, memory, offset);
   require(a && b && a != b, "placed buffer resource creation failed");
   struct pipe_resource *decoy = buffer_new(screen, size, PIPE_BIND_SHADER_BUFFER, 0);
   pipe_buffer_write(ctx, decoy, 0, size, heap_words);
   uint64_t heap_address = screen->resource_get_address(screen, heap);
   uint64_t a_address = screen->resource_get_address(screen, a);
   uint64_t b_address = screen->resource_get_address(screen, b);
   require(a_address == b_address && a_address == heap_address + offset,
           "placed aliases do not share requested GPU address");
   printf("heap_address=%"PRIu64"\nalias_a_address=%"PRIu64"\nalias_b_address=%"PRIu64"\n"
          "placement_offset=%u\nresource_bytes=%u\nheap_bytes=%u\n"
          "ssbo_size_compensation=0\nssbo_binding_offset=%u\nssbo_bound_bytes=%u\n",
          heap_address, a_address, b_address, offset, size, heap_bytes,
          binding_offset, bound_size);
   struct pipe_resource *output = buffer_new(screen, bound_size + GUARD_COUNT * 4,
                                            PIPE_BIND_SHADER_BUFFER, 0);
   nir_builder w = shader_new(screen, "m0b_alias_write", 1);
   w.shader->info.num_ubos = 1;
   nir_def *i = nir_channel(&w, nir_load_global_invocation_id(&w, 32), 0);
   nir_def *key = nir_load_ubo(&w, 1, 32, nir_imm_int(&w, 0), nir_imm_int(&w, 0),
                              .align_mul = 4, .range = 4);
   nir_def *value = nir_ixor(&w, nir_iadd(&w, nir_imul_imm(&w, i, 17), key),
                             nir_imm_int(&w, 0x2468ace0));
   nir_store_ssbo(&w, value, nir_imm_int(&w, 0), nir_imul_imm(&w, i, 4),
                  .align_mul = 4, .write_mask = 1);
   void *writer = shader_create(ctx, w.shader, prefix, "alias-write");
   nir_builder r = shader_new(screen, "m0b_alias_read", 2);
   nir_def *j = nir_channel(&r, nir_load_global_invocation_id(&r, 32), 0);
   nir_def *byte = nir_imul_imm(&r, j, 4);
   nir_def *read = nir_load_ssbo(&r, 1, 32, nir_imm_int(&r, 0), byte, .align_mul = 4);
   nir_store_ssbo(&r, read, nir_imm_int(&r, 1), byte, .align_mul = 4, .write_mask = 1);
   void *reader = shader_create(ctx, r.shader, prefix, "alias-read");
   output_reset(ctx, output, count);
   finish(ctx);
   snapshot(prefix, "before-dispatch");
   unsigned mismatches = 0;
   for (unsigned phase = 0; phase < 2; phase++) {
      uint32_t key_value = seed + phase * 101u;
      struct pipe_constant_buffer key_binding = {.user_buffer = &key_value, .buffer_size = sizeof(key_value)};
      ctx->set_constant_buffer(ctx, MESA_SHADER_COMPUTE, 0, &key_binding);
      output_reset(ctx, output, count);
      struct pipe_resource *write_view = phase ? b : a;
      struct pipe_resource *read_view = phase ? a : b;
      if (!strcmp(action, "wrong-buffer"))
         read_view = decoy;
      bind_ssbo_range(ctx, 0, write_view, binding_offset, bound_size, true);
      dispatch(ctx, writer, count, strcmp(action, "no-dispatch") != 0);
      ctx->memory_barrier(ctx, PIPE_BARRIER_ALL);
      bind_ssbo_range(ctx, 0, read_view, binding_offset, bound_size, false);
      bind_ssbo(ctx, 1, output, output->width0, true);
      dispatch(ctx, reader, count, strcmp(action, "no-dispatch") != 0);
      finish(ctx);
      for (unsigned k = 0; k < count; k++)
         expected[k] = (k * 17u + key_value) ^ 0x2468ace0u;
      mismatches += output_check(ctx, output, expected, count, prefix, phase);
   }
   read_buffer(ctx, heap, heap_words, heap_bytes);
   FILE *raw = artifact(prefix, "heap.bin", "wb");
   require(fwrite(heap_words, heap_bytes, 1, raw) == 1, "save heap readback failed");
   fclose(raw);
   unsigned outside_changes = 0, outside_bound_changes = 0;
   for (unsigned k = 0; k < heap_bytes / 4; k++)
      if (k < offset / 4 || k >= (offset + size) / 4)
         outside_changes += heap_words[k] != canary;
   for (unsigned k = 0; k < heap_bytes / 4; k++)
      if (k < (offset + binding_offset) / 4 ||
          k >= (offset + binding_offset + bound_size) / 4)
         outside_bound_changes += heap_words[k] != canary;
   printf("heap_outside_changes=%u\nheap_outside_bound_changes=%u\nphases=2\n",
          outside_changes, outside_bound_changes);
   require(!outside_changes && !outside_bound_changes, "writes outside bound placed range");
   snapshot(prefix, "after-readback");
   ctx->set_constant_buffer(ctx, MESA_SHADER_COMPUTE, 0, NULL);
   ctx->set_shader_buffers(ctx, MESA_SHADER_COMPUTE, 0, 2, NULL, 0);
   ctx->bind_compute_state(ctx, NULL);
   ctx->delete_compute_state(ctx, writer);
   ctx->delete_compute_state(ctx, reader);
   pipe_resource_reference(&a, NULL);
   pipe_resource_reference(&b, NULL);
   pipe_resource_reference(&decoy, NULL);
   pipe_resource_reference(&output, NULL);
   screen->memobj_destroy(screen, memory);
   pipe_resource_reference(&heap, NULL);
   free(heap_words);
   free(expected);
   return mismatches;
}

int m0b_run(struct pipe_screen *screen, struct pipe_context *ctx, const char *mode,
            const char *prefix, unsigned seed, unsigned variant, const char *action)
{
   printf("max_shader_buffers=%u\nmax_constant_buffers=%u\naddress_bits=%u\n"
          "bindless_texture_cap=%u\ntexture_handle_api=%u\nimage_handle_api=%u\n",
          screen->shader_caps[MESA_SHADER_COMPUTE].max_shader_buffers,
          screen->shader_caps[MESA_SHADER_COMPUTE].max_const_buffers,
          screen->compute_caps.address_bits, screen->caps.bindless_texture,
          ctx->create_texture_handle != NULL, ctx->create_image_handle != NULL);
   unsigned mismatches;
   if (!strcmp(mode, "root-cbv")) {
      if (!screen->resource_get_address || !ctx->set_global_binding) {
         puts("result=BLOCKED\nblocker=missing GPU address or global binding API");
         return 4;
      }
      mismatches = root_cbv(screen, ctx, prefix, seed, action);
   } else if (!strcmp(mode, "descriptor-table")) {
      if (screen->shader_caps[MESA_SHADER_COMPUTE].max_shader_buffers < 6) {
         puts("result=BLOCKED\nblocker=less than six SSBO slots");
         return 4;
      }
      mismatches = descriptor_table(screen, ctx, prefix, seed, action);
   } else {
      if (!screen->memobj_create_from_handle || !screen->resource_from_memobj ||
          !screen->resource_get_address) {
         puts("result=BLOCKED\nblocker=missing memory-object placement API");
         return 4;
      }
      mismatches = placed_alias(screen, ctx, prefix, seed, variant, action);
   }
   unsigned reset = ctx->get_device_reset_status ? ctx->get_device_reset_status(ctx) : UINT32_MAX;
   require(reset == PIPE_NO_RESET, "M0b context reset or missing reset status");
   printf("context_reset_status=%u\nfence_complete=1\ndispatch_submitted=%u\n"
          "total_mismatches=%u\nresult=%s\n", reset, strcmp(action, "no-dispatch") != 0,
          mismatches, mismatches ? "FAIL_RESULT" : "PASS");
   return mismatches ? 3 : 0;
}
