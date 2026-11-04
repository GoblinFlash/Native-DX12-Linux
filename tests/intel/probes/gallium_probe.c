#include <dirent.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <xf86drm.h>

#include "pipe/p_context.h"
#include "pipe/p_screen.h"
#include "pipe/p_state.h"
#include "pipe-loader/pipe_loader.h"
#include "util/u_inlines.h"
#include "compiler/nir/nir_builder.h"
#include "compiler/spirv/nir_spirv.h"
#include "gallium_probe.h"

enum { COUNT = 1024, GUARDS = 16, WORDS = COUNT * 2 + GUARDS };
static const uint32_t sentinel = 0xdeadbeef;
static const uint32_t guard = 0xa5c39e71;

void require(bool ok, const char *message)
{
   if (!ok) {
      fprintf(stderr, "ERROR=%s\n", message);
      exit(2);
   }
}

FILE *artifact(const char *prefix, const char *suffix, const char *mode)
{
   char path[PATH_MAX];
   int n = snprintf(path, sizeof(path), "%s.%s", prefix, suffix);
   require(n > 0 && n < (int)sizeof(path), "artifact path too long");
   FILE *file = fopen(path, mode);
   require(file != NULL, "cannot open artifact");
   return file;
}

static unsigned number(const char *text)
{
   char *end = NULL;
   unsigned long n = strtoul(text, &end, 0);
   require(*text && *end == '\0' && n <= UINT_MAX, "invalid unsigned argument");
   return (unsigned)n;
}

void snapshot(const char *prefix, const char *phase)
{
   FILE *in = fopen("/proc/self/maps", "r");
   require(in != NULL, "cannot inspect process maps");
   FILE *out = artifact(prefix, "maps.txt", "a");
   fprintf(out, "PHASE=%s\n", phase);
   char line[8192];
   while (fgets(line, sizeof(line), in)) {
      require(!strstr(line, "libvulkan") && !strstr(line, "libOpenCL") &&
              !strstr(line, "libRusticl") && !strstr(line, "libigdrcl") &&
              !strstr(line, "libpocl"), "unexpected GPU runtime in maps");
      fputs(line, out);
   }
   fclose(in);
   fclose(out);
   DIR *dir = opendir("/proc/self/fd");
   require(dir != NULL, "cannot inspect process fds");
   out = artifact(prefix, "fdinfo.txt", "a");
   fprintf(out, "PHASE=%s\n", phase);
   struct dirent *entry;
   while ((entry = readdir(dir))) {
      if (entry->d_name[0] == '.')
         continue;
      char path[PATH_MAX], target[PATH_MAX];
      snprintf(path, sizeof(path), "/proc/self/fd/%s", entry->d_name);
      ssize_t len = readlink(path, target, sizeof(target) - 1);
      if (len < 0)
         continue;
      target[len] = '\0';
      if (!strstr(target, "/dev/dri/"))
         continue;
      fprintf(out, "FD=%s TARGET=%s\n", entry->d_name, target);
      snprintf(path, sizeof(path), "/proc/self/fdinfo/%s", entry->d_name);
      in = fopen(path, "r");
      require(in != NULL, "cannot read GPU fdinfo");
      while (fgets(line, sizeof(line), in))
         fputs(line, out);
      fclose(in);
   }
   closedir(dir);
   fclose(out);
}

static nir_shader *control_nir(struct pipe_screen *screen, unsigned slot,
                               unsigned multiplier, unsigned bias)
{
   nir_builder b = nir_builder_init_simple_shader(
      MESA_SHADER_COMPUTE, screen->nir_options[MESA_SHADER_COMPUTE], "m0_control");
   b.shader->info.internal = false;
   b.shader->info.workgroup_size[0] = 64;
   b.shader->info.workgroup_size[1] = 1;
   b.shader->info.workgroup_size[2] = 1;
   b.shader->info.num_ssbos = slot + 1;
   nir_def *i = nir_channel(&b, nir_load_global_invocation_id(&b, 32), 0);
   nir_def *offset = nir_imul_imm(&b, i, 4);
   nir_def *index = nir_imm_int(&b, slot);
   nir_def *input = nir_load_ssbo(&b, 1, 32, index, offset, .align_mul = 4);
   nir_def *value = nir_ixor(&b, nir_iadd_imm(&b, nir_imul_imm(&b, input, multiplier), bias),
                             nir_imul_imm(&b, i, 0x9e3779b9u));
   nir_store_ssbo(&b, value, index, nir_iadd_imm(&b, offset, COUNT * 4),
                  .write_mask = 1, .align_mul = 4);
   return b.shader;
}

struct binding_map {
   unsigned set, binding, slot, resources, descriptors;
};

static bool lower_descriptor(nir_builder *b, nir_intrinsic_instr *intrin, void *data)
{
   struct binding_map *map = data;
   nir_def *replacement = NULL;
   b->cursor = nir_before_instr(&intrin->instr);
   switch (intrin->intrinsic) {
   case nir_intrinsic_vulkan_resource_index:
      require(nir_intrinsic_desc_type(intrin) == nir_descriptor_type_storage_buffer &&
              nir_intrinsic_desc_set(intrin) == map->set &&
              nir_intrinsic_binding(intrin) == map->binding &&
              nir_src_is_const(intrin->src[0]) && nir_src_as_uint(intrin->src[0]) == 0 &&
              intrin->def.num_components == 2 && intrin->def.bit_size == 32,
              "descriptor outside declared single-SSBO mapping");
      replacement = nir_imm_ivec2(b, map->slot, 0);
      map->resources++;
      break;
   case nir_intrinsic_load_vulkan_descriptor:
      require(nir_intrinsic_desc_type(intrin) == nir_descriptor_type_storage_buffer &&
              intrin->def.num_components == 2 && intrin->def.bit_size == 32,
              "unsupported descriptor load");
      replacement = intrin->src[0].ssa;
      map->descriptors++;
      break;
   case nir_intrinsic_vulkan_resource_reindex:
      require(false, "descriptor arrays are outside M0 profile");
      break;
   default:
      return false;
   }
   nir_def_rewrite_uses(&intrin->def, replacement);
   nir_instr_remove(&intrin->instr);
   return true;
}

static void spirv_debug(void *private_data, enum nir_spirv_debug_level level,
                        size_t offset, const char *message)
{
   bool *bad = private_data;
   fprintf(stderr, "SPIRV_IMPORT level=%d offset=%zu %s\n", level, offset, message);
   if (level >= NIR_SPIRV_DEBUG_LEVEL_WARNING)
      *bad = true;
}

static nir_shader *import_spirv(struct pipe_screen *screen, const char *path,
                                struct binding_map *map, const char *prefix)
{
   FILE *file = fopen(path, "rb");
   require(file != NULL, "cannot open SPIR-V input");
   require(fseek(file, 0, SEEK_END) == 0, "SPIR-V seek failed");
   long size = ftell(file);
   require(size >= 20 && size <= 1024 * 1024 && size % 4 == 0, "SPIR-V size outside profile");
   rewind(file);
   uint32_t *words = malloc(size);
   require(words != NULL && fread(words, size, 1, file) == 1, "SPIR-V read failed");
   fclose(file);
   require(words[0] == 0x07230203, "invalid SPIR-V magic");
   size_t count = size / 4;
   unsigned capabilities = 0;
   for (size_t at = 5; at < count;) {
      unsigned length = words[at] >> 16, opcode = words[at] & 0xffff;
      require(length && at + length <= count, "malformed SPIR-V instruction");
      if (opcode == 17) {
         require(length == 2 && words[at + 1] == 1, "only Shader capability is supported");
         capabilities++;
      }
      at += length;
   }
   require(capabilities == 1, "expected one Shader capability");
   bool import_error = false;
   const struct spirv_to_nir_options options = {
      .environment = NIR_SPIRV_VULKAN,
      .ubo_addr_format = nir_address_format_32bit_index_offset,
      .ssbo_addr_format = nir_address_format_32bit_index_offset,
      .shared_addr_format = nir_address_format_32bit_offset,
      .temp_addr_format = nir_address_format_logical,
      .min_ssbo_alignment = 4,
      .skip_os_break_in_debug_build = true,
      .ignore_replacement = true,
      .debug = {.func = spirv_debug, .private_data = &import_error},
   };
   nir_shader *nir = spirv_to_nir(words, count, NULL, MESA_SHADER_COMPUTE, "main",
                                 &options, screen->nir_options[MESA_SHADER_COMPUTE]);
   free(words);
   require(nir != NULL && !import_error, "SPIR-V importer failed or warned");
   FILE *dump = artifact(prefix, "imported.nir.txt", "w");
   nir_print_shader(nir, dump);
   fclose(dump);
   require(nir->info.workgroup_size[0] == 64 && nir->info.workgroup_size[1] == 1 &&
           nir->info.workgroup_size[2] == 1 && !nir->info.workgroup_size_variable,
           "workgroup size outside M0 profile");
   NIR_PASS(_, nir, nir_lower_variable_initializers, nir_var_function_temp);
   NIR_PASS(_, nir, nir_lower_returns);
   NIR_PASS(_, nir, nir_inline_functions);
   NIR_PASS(_, nir, nir_opt_copy_prop);
   NIR_PASS(_, nir, nir_opt_deref);
   nir_remove_non_entrypoints(nir);
   NIR_PASS(_, nir, nir_lower_variable_initializers, ~0);
   NIR_PASS(_, nir, nir_lower_var_copies);
   NIR_PASS(_, nir, nir_lower_vars_to_ssa);
   NIR_PASS(_, nir, nir_opt_constant_folding);
   nir_foreach_variable_with_modes(var, nir, nir_var_mem_ssbo) {
      require(var->data.descriptor_set == map->set && var->data.binding == map->binding,
              "SSBO variable outside declared mapping");
   }
   NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_descriptor,
            nir_metadata_control_flow, map);
   require(map->resources && map->descriptors, "missing SSBO descriptor path");
   NIR_PASS(_, nir, nir_lower_explicit_io, nir_var_mem_ssbo,
            nir_address_format_32bit_index_offset);
   NIR_PASS(_, nir, nir_lower_system_values);
   NIR_PASS(_, nir, nir_opt_constant_folding);
   NIR_PASS(_, nir, nir_opt_copy_prop);
   NIR_PASS(_, nir, nir_opt_constant_folding);
   NIR_PASS(_, nir, nir_opt_dce);
   dump = artifact(prefix, "adapted.nir.txt", "w");
   nir_print_shader(nir, dump);
   fclose(dump);
   unsigned loads = 0, stores = 0;
   nir_foreach_function_impl(impl, nir) {
      nir_foreach_block(block, impl) {
         nir_foreach_instr(instr, block) {
            if (instr->type != nir_instr_type_intrinsic)
               continue;
            nir_intrinsic_instr *in = nir_instr_as_intrinsic(instr);
            int source = -1;
            switch (in->intrinsic) {
            case nir_intrinsic_load_ssbo: source = 0; loads++; break;
            case nir_intrinsic_store_ssbo: source = 1; stores++; break;
            case nir_intrinsic_vulkan_resource_index:
            case nir_intrinsic_load_vulkan_descriptor:
            case nir_intrinsic_vulkan_resource_reindex:
            case nir_intrinsic_load_deref:
            case nir_intrinsic_store_deref:
               require(false, "unlowered resource access");
               break;
            default: break;
            }
            if (source >= 0)
               require(nir_src_is_const(in->src[source]) &&
                       nir_src_as_uint(in->src[source]) == map->slot,
                       "SSBO index differs from mapped Gallium slot");
         }
      }
   }
   require(loads == 1 && stores == 1 && nir->info.num_ssbos == 1 &&
           nir->info.num_ubos == 0 && nir->info.num_images == 0 &&
           nir->info.num_textures == 0 && nir->info.shared_size == 0,
           "shader resources outside M0 profile");
   nir->info.num_ssbos = map->slot + 1;
   printf("descriptor_set=%u\ndescriptor_binding=%u\nresource_indices_lowered=%u\n"
          "descriptor_loads_lowered=%u\nssbo_loads=%u\nssbo_stores=%u\n",
          map->set, map->binding, map->resources, map->descriptors, loads, stores);
   return nir;
}

int main(int argc, char **argv)
{
   setvbuf(stdout, NULL, _IONBF, 0);
   require(argc == 12,
           "usage: probe nir|spirv shader|- artifact-prefix seed multiplier bias set binding slot dispatch|no-dispatch|wrong-buffer device");
   const char *mode = argv[1], *prefix = argv[3], *action = argv[10];
   unsigned seed = number(argv[4]), multiplier = number(argv[5]), bias = number(argv[6]);
   unsigned slot = number(argv[9]);
   require(slot < 8, "slot outside M0 profile");
   require(!strcmp(action, "dispatch") || !strcmp(action, "no-dispatch") ||
           !strcmp(action, "wrong-buffer"), "unknown dispatch action");
   bool dispatch = strcmp(action, "no-dispatch") != 0;
   printf("mode=%s\nseed=%u\nmultiplier=%u\nbias=%u\nslot=%u\naction=%s\n",
          mode, seed, multiplier, bias, slot, action);
   int fd = open(argv[11], O_RDWR | O_CLOEXEC);
   require(fd >= 0, "cannot open requested GPU");
   drmDevicePtr drm = NULL;
   require(drmGetDevice2(fd, 0, &drm) == 0, "drmGetDevice2 failed");
   require(drm->bustype == DRM_BUS_PCI && drm->deviceinfo.pci->vendor_id == 0x8086 &&
           drm->deviceinfo.pci->device_id == 0x46a6 && drm->businfo.pci->domain == 0 &&
           drm->businfo.pci->bus == 0 && drm->businfo.pci->dev == 2 &&
           drm->businfo.pci->func == 0, "GPU identity mismatch");
   printf("gpu=8086:46a6\npci=0000:00:02.0\nrender_node=%s\n",
          drm->nodes[DRM_NODE_RENDER]);
   drmFreeDevice(&drm);
   drmVersionPtr version = drmGetVersion(fd);
   require(version && !strcmp(version->name, "i915"), "expected i915 kernel driver");
   drmFreeVersion(version);
   struct pipe_loader_device *device = NULL;
   require(pipe_loader_drm_probe_fd(&device, fd, false), "DRM loader probe failed");
   require(!strcmp(device->driver_name, "iris"), "expected Gallium iris");
   struct pipe_screen *screen = pipe_loader_create_screen(device, false);
   require(screen != NULL, "Iris screen creation failed");
   require(screen->caps.vendor_id == 0x8086 && screen->caps.device_id == 0x46a6,
           "Iris screen PCI mismatch");
   printf("screen=%s\ndriver=iris\n", screen->get_name(screen));
   struct pipe_context *ctx = screen->context_create(screen, NULL, PIPE_CONTEXT_COMPUTE_ONLY);
   require(ctx != NULL, "Iris context creation failed");
   glsl_type_singleton_init_or_ref();
   if (!strcmp(mode, "root-cbv") || !strcmp(mode, "descriptor-table") ||
       !strcmp(mode, "placed-alias")) {
      int result = m0b_run(screen, ctx, mode, prefix, seed, multiplier, action);
      ctx->destroy(ctx);
      screen->destroy(screen);
      pipe_loader_release(&device, 1);
      close(fd);
      glsl_type_singleton_decref();
      return result;
   }
   require(!strcmp(mode, "nir") || !strcmp(mode, "spirv"), "unknown shader mode");
   struct binding_map map = {.set = number(argv[7]), .binding = number(argv[8]), .slot = slot};
   nir_shader *nir = !strcmp(mode, "nir") ? control_nir(screen, slot, multiplier, bias) :
                                           import_spirv(screen, argv[2], &map, prefix);
   nir_shader_gather_info(nir, nir_shader_get_entrypoint(nir));
   nir_validate_shader(nir, "M0 control input");
   screen->finalize_nir(screen, nir, true);
   nir_validate_shader(nir, "M0 finalized");
   FILE *dump = artifact(prefix, "nir.txt", "w");
   nir_print_shader(nir, dump);
   fclose(dump);
   struct pipe_compute_state cs = {.ir_type = PIPE_SHADER_IR_NIR, .prog = nir};
   void *shader = ctx->create_compute_state(ctx, &cs);
   require(shader != NULL, "create_compute_state failed");
   ctx->bind_compute_state(ctx, shader);
   uint32_t initial[WORDS], readback[WORDS];
   for (unsigned i = 0; i < WORDS; i++)
      initial[i] = i < COUNT ? ((i * 17 + seed) ^ (i >> 2)) :
                   i < COUNT * 2 ? sentinel : guard;
   struct pipe_resource *buffer = pipe_buffer_create(screen, PIPE_BIND_SHADER_BUFFER,
                                                      PIPE_USAGE_DEFAULT, sizeof(initial));
   struct pipe_resource *decoy = pipe_buffer_create(screen, PIPE_BIND_SHADER_BUFFER,
                                                     PIPE_USAGE_DEFAULT, sizeof(initial));
   require(buffer && decoy, "GPU buffer allocation failed");
   pipe_buffer_write(ctx, buffer, 0, sizeof(initial), initial);
   pipe_buffer_write(ctx, decoy, 0, sizeof(initial), initial);
   struct pipe_shader_buffer binding = {
      .buffer = !strcmp(action, "wrong-buffer") ? decoy : buffer,
      .buffer_offset = 0, .buffer_size = sizeof(initial),
   };
   ctx->set_shader_buffers(ctx, MESA_SHADER_COMPUTE, slot, 1, &binding, 1);
   struct pipe_fence_handle *upload_fence = NULL;
   ctx->flush(ctx, &upload_fence, 0);
   require(upload_fence && screen->fence_finish(screen, ctx, upload_fence, 10000000000ull),
           "upload fence timeout");
   screen->fence_reference(screen, &upload_fence, NULL);
   snapshot(prefix, "before-dispatch");
   if (dispatch) {
      struct pipe_grid_info grid = {
         .work_dim = 1, .block = {64, 1, 1}, .grid = {COUNT / 64, 1, 1},
      };
      ctx->launch_grid(ctx, &grid);
      ctx->memory_barrier(ctx, PIPE_BARRIER_SHADER_BUFFER | PIPE_BARRIER_UPDATE_BUFFER);
   }
   struct pipe_fence_handle *fence = NULL;
   ctx->flush(ctx, &fence, 0);
   require(fence && screen->fence_finish(screen, ctx, fence, 10000000000ull),
           "dispatch fence timeout");
   printf("dispatch_submitted=%u\nfence_complete=1\n", dispatch);
   screen->fence_reference(screen, &fence, NULL);
   struct pipe_transfer *transfer = NULL;
   void *mapped = pipe_buffer_map_range(ctx, buffer, 0, sizeof(readback), PIPE_MAP_READ, &transfer);
   require(mapped != NULL, "readback map failed");
   memcpy(readback, mapped, sizeof(readback));
   pipe_buffer_unmap(ctx, transfer);
   snapshot(prefix, "after-readback");
   unsigned reset = ctx->get_device_reset_status ? ctx->get_device_reset_status(ctx) : UINT_MAX;
   printf("context_reset_status=%u\n", reset);
   require(reset == PIPE_NO_RESET, "context reset or unavailable reset status");
   FILE *raw = artifact(prefix, "output.bin", "wb");
   require(fwrite(readback, sizeof(readback), 1, raw) == 1, "cannot save readback");
   fclose(raw);
   unsigned mismatches = 0, input_changes = 0, guard_changes = 0;
   for (unsigned i = 0; i < COUNT; i++) {
      uint32_t expected = (initial[i] * multiplier + bias) ^ (i * 0x9e3779b9u);
      mismatches += readback[COUNT + i] != expected;
      input_changes += readback[i] != initial[i];
   }
   for (unsigned i = COUNT * 2; i < WORDS; i++)
      guard_changes += readback[i] != guard;
   printf("checked=%u\nmismatches=%u\ninput_changes=%u\nguard_changes=%u\nfirst=%"PRIu32"\nlast=%"PRIu32"\n",
          COUNT, mismatches, input_changes, guard_changes, readback[COUNT], readback[COUNT * 2 - 1]);
   ctx->set_shader_buffers(ctx, MESA_SHADER_COMPUTE, slot, 1, NULL, 0);
   ctx->bind_compute_state(ctx, NULL);
   ctx->delete_compute_state(ctx, shader);
   pipe_resource_reference(&buffer, NULL);
   pipe_resource_reference(&decoy, NULL);
   ctx->destroy(ctx);
   screen->destroy(screen);
   pipe_loader_release(&device, 1);
   close(fd);
   glsl_type_singleton_decref();
   bool pass = !mismatches && !input_changes && !guard_changes;
   printf("result=%s\n", pass ? "PASS" : "FAIL_RESULT");
   return pass ? 0 : 3;
}
