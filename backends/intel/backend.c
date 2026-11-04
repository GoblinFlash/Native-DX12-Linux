#include "backend.h"
#include "../../include/ndx_evidence.h"
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>
#include <xf86drm.h>
#include <drm_fourcc.h>
#include <spirv-tools/libspirv.h>
#include "dxil_spirv_c.h"
#include "pipe/p_context.h"
#include "pipe/p_screen.h"
#include "pipe/p_state.h"
#include "frontend/winsys_handle.h"
#include "pipe-loader/pipe_loader.h"
#include "util/u_inlines.h"
#include "compiler/nir/nir_builder.h"
#include "compiler/spirv/nir_spirv.h"
#include "compiler/spirv/spirv.h"

struct ndx_backend {
   int fd;
   struct pipe_loader_device *loader;
   struct pipe_screen *screen;
   struct pipe_context *ctx;
   bool glsl_ref;
   unsigned shader_count;
   unsigned dump_count;
   unsigned reset_status;
};

static void ndx_record_reset(void *data, enum pipe_reset_status status)
{
   struct ndx_backend *b = data;
   /* This backend requires Iris/i915. Its failed-submit callback can report
    * NO_RESET when reset statistics are unavailable; healthy polls do not. */
   if (status == PIPE_NO_RESET) status = PIPE_UNKNOWN_CONTEXT_RESET;
   if (!b->reset_status)
      b->reset_status = status;
}

void ndx_backend_destroy(struct ndx_backend *b)
{
   if (!b) return;
   if (b->ctx) b->ctx->destroy(b->ctx);
   if (b->screen) b->screen->destroy(b->screen);
   if (b->loader) pipe_loader_release(&b->loader, 1);
   if (b->fd >= 0) close(b->fd);
   if (b->glsl_ref) glsl_type_singleton_decref();
   free(b);
}

struct ndx_backend *ndx_backend_create(const char *node)
{
   struct ndx_backend *b = calloc(1, sizeof(*b));
   if (!b) return NULL;
   b->fd = open(node, O_RDWR | O_CLOEXEC);
   if (b->fd < 0) goto fail;
   drmDevicePtr drm = NULL;
   if (drmGetDevice2(b->fd, 0, &drm)) goto fail;
   bool exact = drm->bustype == DRM_BUS_PCI &&
      drm->deviceinfo.pci->vendor_id == 0x8086 && drm->deviceinfo.pci->device_id == 0x46a6 &&
      drm->businfo.pci->domain == 0 && drm->businfo.pci->bus == 0 &&
      drm->businfo.pci->dev == 2 && drm->businfo.pci->func == 0;
   drmFreeDevice(&drm);
   if (!exact) goto fail;
   drmVersionPtr version = drmGetVersion(b->fd);
   bool i915 = version && !strcmp(version->name, "i915");
   if (version) drmFreeVersion(version);
   if (!i915 || !pipe_loader_drm_probe_fd(&b->loader, b->fd, false)) goto fail;
   if (strcmp(b->loader->driver_name, "iris")) goto fail;
   b->screen = pipe_loader_create_screen(b->loader, false);
   if (!b->screen || b->screen->caps.vendor_id != 0x8086 ||
       b->screen->caps.device_id != 0x46a6) goto fail;
   b->ctx = b->screen->context_create(b->screen, NULL, 0);
   if (!b->ctx || !b->ctx->get_device_reset_status ||
       !b->ctx->set_device_reset_callback) goto fail;
   const struct pipe_device_reset_callback reset = {
      .reset = ndx_record_reset, .data = b,
   };
   b->ctx->set_device_reset_callback(b->ctx, &reset);
   glsl_type_singleton_init_or_ref();
   b->glsl_ref = true;
   printf("gpu=8086:46a6\npci=0000:00:02.0\ndriver=iris\nrender_node=%s\nscreen=%s\n",
          node, b->screen->get_name(b->screen));
   return b;
fail:
   ndx_backend_destroy(b);
   return NULL;
}

void *ndx_buffer_create(struct ndx_backend *b, unsigned bytes, unsigned heap)
{
   struct pipe_resource desc = {
      .target = PIPE_BUFFER, .format = PIPE_FORMAT_R8_UNORM,
      .width0 = bytes, .height0 = 1, .depth0 = 1, .array_size = 1,
      .bind = PIPE_BIND_SHADER_BUFFER | PIPE_BIND_INDEX_BUFFER | PIPE_BIND_GLOBAL | (heap ? PIPE_BIND_SHARED : 0),
      .usage = heap == 1 ? PIPE_USAGE_STAGING : heap == 2 ? PIPE_USAGE_STREAM : PIPE_USAGE_DEFAULT,
      .flags = PIPE_RESOURCE_FLAG_FIXED_ADDRESS,
   };
   return b->screen->resource_create(b->screen, &desc);
}
void ndx_buffer_destroy(void *buffer)
{
   struct pipe_resource *r = buffer;
   pipe_resource_reference(&r, NULL);
}
void *ndx_buffer_map(struct ndx_backend *b, void *buffer, unsigned bytes, bool read, void **transfer)
{
   struct pipe_transfer *t = NULL;
   void *p = pipe_buffer_map_range(b->ctx, buffer, 0, bytes,
                                  (read ? PIPE_MAP_READ : PIPE_MAP_WRITE) |
                                  PIPE_MAP_UNSYNCHRONIZED | PIPE_MAP_DIRECTLY, &t);
   *transfer = t;
   return p;
}
void ndx_buffer_unmap(struct ndx_backend *b, void *transfer) { pipe_buffer_unmap(b->ctx, transfer); }
uint64_t ndx_buffer_address(struct ndx_backend *b, void *buffer)
{
   return b->screen->resource_get_address(b->screen, buffer);
}
void ndx_copy(struct ndx_backend *b, void *dst, unsigned dst_offset, void *src, unsigned src_offset, unsigned bytes)
{
   const struct pipe_box box = {.x = src_offset, .width = bytes, .height = 1, .depth = 1};
   b->ctx->resource_copy_region(b->ctx, dst, 0, dst_offset, 0, 0, src, 0, &box);
}
void ndx_barrier(struct ndx_backend *b) { b->ctx->memory_barrier(b->ctx, PIPE_BARRIER_ALL); }
void *ndx_flush(struct ndx_backend *b)
{
   struct pipe_fence_handle *f = NULL;
   b->ctx->flush(b->ctx, &f, 0);
   return f;
}
bool ndx_wait(struct ndx_backend *b, void *fence, uint64_t timeout)
{
   return fence && b->screen->fence_finish(b->screen, b->ctx, fence, timeout);
}
void ndx_fence_destroy(struct ndx_backend *b, void *fence)
{
   struct pipe_fence_handle *f = fence;
   b->screen->fence_reference(b->screen, &f, NULL);
}
unsigned ndx_reset_status(struct ndx_backend *b)
{
   if (!b->reset_status) {
      unsigned status = b->ctx->get_device_reset_status ?
         b->ctx->get_device_reset_status(b->ctx) : UINT32_MAX;
      /* A synchronous driver callback may already have latched the reset. */
      if (!b->reset_status) b->reset_status = status;
   }
   return b->reset_status;
}
void ndx_dispatch(struct ndx_backend *b, void *shader, void *buffer,
                  unsigned offset, unsigned bytes, unsigned groups)
{
   struct pipe_shader_buffer binding = {.buffer = buffer, .buffer_offset = offset, .buffer_size = bytes};
   b->ctx->set_shader_buffers(b->ctx, MESA_SHADER_COMPUTE, 0, 1, &binding, 1);
   b->ctx->bind_compute_state(b->ctx, shader);
   struct pipe_grid_info grid = {.work_dim = 1, .block = {64, 1, 1}, .grid = {groups, 1, 1}};
   b->ctx->launch_grid(b->ctx, &grid);
   ndx_barrier(b);
   b->ctx->set_shader_buffers(b->ctx, MESA_SHADER_COMPUTE, 0, 1, NULL, 0);
   b->ctx->bind_compute_state(b->ctx, NULL);
}
void ndx_shader_destroy(struct ndx_backend *b, void *shader) { b->ctx->delete_compute_state(b->ctx, shader); }

struct mapping { unsigned space, reg, resources, descriptors; bool bad; };
static dxil_spv_bool remap_uav(void *data, const dxil_spv_uav_d3d_binding *in, dxil_spv_uav_vulkan_binding *out)
{
   struct mapping *m = data;
   const dxil_spv_d3d_binding *r = &in->d3d_binding;
   if (in->has_counter || r->stage != DXIL_SPV_STAGE_COMPUTE || r->range_size != 1 ||
       r->register_space != m->space || r->register_index != m->reg ||
       (r->kind != DXIL_SPV_RESOURCE_KIND_RAW_BUFFER &&
        r->kind != DXIL_SPV_RESOURCE_KIND_STRUCTURED_BUFFER)) {
      m->bad = true;
      return 0;
   }
   *out = (dxil_spv_uav_vulkan_binding){0};
   out->buffer_binding.descriptor_type = DXIL_SPV_VULKAN_DESCRIPTOR_TYPE_SSBO;
   return 1;
}
static dxil_spv_bool reject_srv(void *d, const dxil_spv_d3d_binding *a, dxil_spv_srv_vulkan_binding *b) { (void)d; (void)a; (void)b; return 0; }
static dxil_spv_bool reject_cbv(void *d, const dxil_spv_d3d_binding *a, dxil_spv_cbv_vulkan_binding *b) { (void)d; (void)a; (void)b; return 0; }
static dxil_spv_bool reject_sampler(void *d, const dxil_spv_d3d_binding *a, dxil_spv_vulkan_binding *b) { (void)d; (void)a; (void)b; return 0; }
static bool lower_descriptor(nir_builder *b, nir_intrinsic_instr *in, void *data)
{
   struct mapping *m = data;
   nir_def *replacement = NULL;
   b->cursor = nir_before_instr(&in->instr);
   switch (in->intrinsic) {
   case nir_intrinsic_vulkan_resource_index:
      if (nir_intrinsic_desc_type(in) != nir_descriptor_type_storage_buffer ||
          nir_intrinsic_desc_set(in) != 0 || nir_intrinsic_binding(in) != 0 ||
          !nir_src_is_const(in->src[0]) || nir_src_as_uint(in->src[0]) != 0 ||
          in->def.num_components != 2 || in->def.bit_size != 32) { m->bad = true; return false; }
      replacement = nir_imm_ivec2(b, 0, 0);
      m->resources++;
      break;
   case nir_intrinsic_load_vulkan_descriptor:
      if (nir_intrinsic_desc_type(in) != nir_descriptor_type_storage_buffer ||
          in->def.num_components != 2 || in->def.bit_size != 32) { m->bad = true; return false; }
      replacement = in->src[0].ssa;
      m->descriptors++;
      break;
   case nir_intrinsic_vulkan_resource_reindex:
      m->bad = true; return false;
   default: return false;
   }
   nir_def_rewrite_uses(&in->def, replacement);
   nir_instr_remove(&in->instr);
   return true;
}
static void import_debug(void *data, enum nir_spirv_debug_level level, size_t offset, const char *message)
{
   fprintf(stderr, "NDX12_SPIRV level=%d offset=%zu %s\n", level, offset, message);
   if (level >= NIR_SPIRV_DEBUG_LEVEL_WARNING) *(bool *)data = true;
}
struct dump_outputs {
   struct ndx_evidence_file files[3];
   char paths[3][4096];
   size_t count;
};
static bool dump_begin(struct dump_outputs *out, struct ndx_backend *b,
                       const char *first, const char *second, bool table)
{
   const char *prefix = getenv("NDX12_DUMP_PREFIX");
   if (!prefix) return true;
   if (b->dump_count == UINT_MAX) {
      fprintf(stderr, "NDX12_DUMP_COUNTER_EXHAUSTED\n");
      errno = EOVERFLOW;
      return false;
   }
   const unsigned dump_index = b->dump_count++;
   const char *suffixes[3] = {first, second, "table-import.nir.txt"};
   out->count = table ? 3 : 2;
   for (size_t i = 0; i < out->count; i++) {
      int n = snprintf(out->paths[i], sizeof(out->paths[i]), "%s.shader%u.%s", prefix, dump_index, suffixes[i]);
      if (n < 0 || n >= (int)sizeof(out->paths[i])) return false;
      out->files[i].path = out->paths[i];
   }
   if (ndx_evidence_reserve(out->files, out->count)) {
      fprintf(stderr, "NDX12_DUMP_RESERVATION_FAILED errno=%d\n", errno);
      return false;
   }
   return true;
}
static bool dump(struct dump_outputs *out, unsigned slot, const void *data, size_t bytes, nir_shader *nir)
{
   if (!out->count) return true;
   if (slot >= out->count || !out->files[slot].stream) return false;
   FILE *f = out->files[slot].stream;
   if (nir) {
      nir_print_shader(nir, f);
      return !ferror(f) && !fflush(f) && !fsync(fileno(f));
   }
   return !ndx_evidence_write(f, data, bytes);
}

void *ndx_shader_create(struct ndx_backend *b, const void *dxil, size_t bytes, unsigned space, unsigned reg)
{
   dxil_spv_parsed_blob blob = NULL;
   dxil_spv_converter converter = NULL;
   nir_shader *nir = NULL;
   void *shader = NULL;
   struct mapping map = {.space = space, .reg = reg};
   if (!dxil || bytes < 32 || bytes > 1024 * 1024 || memcmp(dxil, "DXBC", 4)) return NULL;
   struct dump_outputs outputs = {0};
   if (!dump_begin(&outputs, b, "spv", "nir.txt", false)) return NULL;
   dxil_spv_begin_thread_allocator_context();
   if (dxil_spv_parse_dxil_blob(dxil, bytes, &blob) != DXIL_SPV_SUCCESS ||
       dxil_spv_parsed_blob_get_shader_stage(blob) != DXIL_SPV_STAGE_COMPUTE ||
       dxil_spv_create_converter(blob, &converter) != DXIL_SPV_SUCCESS) goto done;
   dxil_spv_converter_set_entry_point(converter, "main");
   dxil_spv_converter_set_uav_remapper(converter, remap_uav, &map);
   dxil_spv_converter_set_srv_remapper(converter, reject_srv, NULL);
   dxil_spv_converter_set_cbv_remapper(converter, reject_cbv, NULL);
   dxil_spv_converter_set_sampler_remapper(converter, reject_sampler, NULL);
   dxil_spv_option_ssbo_alignment alignment = {{DXIL_SPV_OPTION_SSBO_ALIGNMENT}, 4};
   dxil_spv_option_physical_storage_buffer physical = {{DXIL_SPV_OPTION_PHYSICAL_STORAGE_BUFFER}, 0};
   dxil_spv_option_compute_shader_derivatives derivatives = {{DXIL_SPV_OPTION_COMPUTE_SHADER_DERIVATIVES}, 0, 0};
   if (dxil_spv_converter_add_option(converter, &alignment.base) != DXIL_SPV_SUCCESS ||
       dxil_spv_converter_add_option(converter, &physical.base) != DXIL_SPV_SUCCESS ||
       dxil_spv_converter_add_option(converter, &derivatives.base) != DXIL_SPV_SUCCESS ||
       dxil_spv_converter_run(converter) != DXIL_SPV_SUCCESS || map.bad) goto done;
   dxil_spv_compiled_spirv spirv;
   if (dxil_spv_converter_get_compiled_spirv(converter, &spirv) != DXIL_SPV_SUCCESS ||
       spirv.size < 20 || spirv.size > 1024 * 1024 || spirv.size % 4) goto done;
   const uint32_t *words = spirv.data;
   unsigned capabilities = 0;
   for (size_t at = 5; at < spirv.size / 4;) {
      unsigned n = words[at] >> 16, opcode = words[at] & 0xffff;
      if (!n || n > spirv.size / 4 - at) goto done;
      if (opcode == 17) {
         if (n != 2 || words[at + 1] != 1) goto done;
         capabilities++;
      }
      at += n;
   }
   if (capabilities != 1) goto done;
   spv_context val = spvContextCreate(SPV_ENV_VULKAN_1_3);
   spv_validator_options opts = spvValidatorOptionsCreate();
   spvValidatorOptionsSetScalarBlockLayout(opts, true);
   spv_const_binary_t code = {words, spirv.size / 4};
   spv_diagnostic diagnostic = NULL;
   spv_result_t validated = spvValidateWithOptions(val, opts, &code, &diagnostic);
   if (diagnostic) fprintf(stderr, "NDX12_VALIDATION=%s\n", diagnostic->error);
   spvDiagnosticDestroy(diagnostic);
   spvValidatorOptionsDestroy(opts);
   spvContextDestroy(val);
   if (validated != SPV_SUCCESS) goto done;
   if (!dump(&outputs, 0, spirv.data, spirv.size, NULL)) goto done;
   bool import_error = false;
   const struct spirv_to_nir_options options = {
      .environment = NIR_SPIRV_VULKAN,
      .ubo_addr_format = nir_address_format_32bit_index_offset,
      .ssbo_addr_format = nir_address_format_32bit_index_offset,
      .shared_addr_format = nir_address_format_32bit_offset,
      .temp_addr_format = nir_address_format_logical, .min_ssbo_alignment = 4,
      .skip_os_break_in_debug_build = true, .ignore_replacement = true,
      .debug = {.func = import_debug, .private_data = &import_error},
   };
   nir = spirv_to_nir(words, spirv.size / 4, NULL, MESA_SHADER_COMPUTE, "main",
                      &options, b->screen->nir_options[MESA_SHADER_COMPUTE]);
   if (!nir || import_error || nir->info.workgroup_size[0] != 64 ||
       nir->info.workgroup_size[1] != 1 || nir->info.workgroup_size[2] != 1 ||
       nir->info.workgroup_size_variable) goto done;
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
   nir_foreach_variable_with_modes(var, nir, nir_var_mem_ssbo)
      if (var->data.descriptor_set || var->data.binding) goto done;
   NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_descriptor, nir_metadata_control_flow, &map);
   if (map.bad || !map.resources || !map.descriptors) goto done;
   NIR_PASS(_, nir, nir_lower_explicit_io, nir_var_mem_ssbo, nir_address_format_32bit_index_offset);
   NIR_PASS(_, nir, nir_lower_system_values);
   NIR_PASS(_, nir, nir_opt_constant_folding);
   NIR_PASS(_, nir, nir_opt_copy_prop);
   NIR_PASS(_, nir, nir_opt_constant_folding);
   NIR_PASS(_, nir, nir_opt_dce);
   unsigned loads = 0, stores = 0;
   nir_foreach_function_impl(impl, nir) {
      nir_foreach_block(block, impl) {
         nir_foreach_instr(instr, block) {
            if (instr->type != nir_instr_type_intrinsic) continue;
            nir_intrinsic_instr *in = nir_instr_as_intrinsic(instr);
            int source = -1;
            switch (in->intrinsic) {
            case nir_intrinsic_load_ssbo: source = 0; loads++; break;
            case nir_intrinsic_store_ssbo: source = 1; stores++; break;
            case nir_intrinsic_vulkan_resource_index:
            case nir_intrinsic_load_vulkan_descriptor:
            case nir_intrinsic_vulkan_resource_reindex:
            case nir_intrinsic_load_deref:
            case nir_intrinsic_store_deref: goto done;
            default: break;
            }
            if (source >= 0 && (!nir_src_is_const(in->src[source]) || nir_src_as_uint(in->src[source]))) goto done;
         }
      }
   }
   if (loads != 1 || stores != 1 || nir->info.num_ssbos != 1 || nir->info.num_ubos ||
       nir->info.num_images || nir->info.num_textures || nir->info.shared_size) goto done;
   nir_shader_gather_info(nir, nir_shader_get_entrypoint(nir));
   nir_validate_shader(nir, "ndx12 imported compute");
   b->screen->finalize_nir(b->screen, nir, true);
   nir_validate_shader(nir, "ndx12 finalized compute");
   if (!dump(&outputs, 1, NULL, 0, nir) || ndx_evidence_close(outputs.files, outputs.count)) goto done;
   struct pipe_compute_state state = {.ir_type = PIPE_SHADER_IR_NIR, .prog = nir};
   shader = b->ctx->create_compute_state(b->ctx, &state);
   nir = NULL;
   if (shader) { b->shader_count++; printf("dxil_compiled_in_process=1\n"); }
done:
   ndx_evidence_close(outputs.files, outputs.count);
   if (nir) ralloc_free(nir);
   if (converter) dxil_spv_converter_free(converter);
   if (blob) dxil_spv_parsed_blob_free(blob);
   dxil_spv_end_thread_allocator_context();
   return shader;
}

void *ndx_texture_create(struct ndx_backend *b, unsigned width, unsigned height)
{
   const struct pipe_resource desc = {
      .target = PIPE_TEXTURE_2D, .format = PIPE_FORMAT_R8G8B8A8_UNORM,
      .width0 = width, .height0 = height, .depth0 = 1, .array_size = 1,
      .bind = PIPE_BIND_RENDER_TARGET | PIPE_BIND_SAMPLER_VIEW, .usage = PIPE_USAGE_DEFAULT,
   };
   if (!b->screen->is_format_supported(b->screen, desc.format, desc.target, 1, 1, desc.bind))
      return NULL;
   return b->screen->resource_create(b->screen, &desc);
}

void *ndx_present_create(struct ndx_backend *b, unsigned width, unsigned height)
{
   const struct pipe_resource desc = {
      .target = PIPE_TEXTURE_2D, .format = PIPE_FORMAT_R8G8B8A8_UNORM,
      .width0 = width, .height0 = height, .depth0 = 1, .array_size = 1,
      .bind = PIPE_BIND_RENDER_TARGET | PIPE_BIND_SAMPLER_VIEW | PIPE_BIND_SHARED,
      .usage = PIPE_USAGE_DEFAULT,
   };
   const uint64_t modifier = DRM_FORMAT_MOD_LINEAR;
   return b->screen->resource_create_with_modifiers(b->screen, &desc, &modifier, 1);
}

int ndx_present_export(struct ndx_backend *b, void *texture, unsigned *stride, unsigned *offset)
{
   struct winsys_handle handle = {.type = WINSYS_HANDLE_TYPE_FD};
   if (!b->screen->resource_get_handle(b->screen, b->ctx, texture, &handle,
                                      PIPE_HANDLE_USAGE_EXPLICIT_FLUSH)) return -1;
   if (handle.modifier != DRM_FORMAT_MOD_LINEAR || ((struct pipe_resource *)texture)->format != PIPE_FORMAT_R8G8B8A8_UNORM ||
       !handle.stride || fcntl(handle.handle, F_SETFD, FD_CLOEXEC) < 0) {
      close(handle.handle); return -1;
   }
   *stride = handle.stride; *offset = handle.offset;
   return handle.handle;
}

void ndx_present_flush(struct ndx_backend *b, void *texture)
{
   b->ctx->flush_resource(b->ctx, texture);
   ndx_barrier(b);
}

void ndx_clear_target(struct ndx_backend *b, void *texture, const float color[4])
{
   struct pipe_resource *r = texture;
   struct pipe_framebuffer_state fb = {.width = r->width0, .height = r->height0, .nr_cbufs = 1};
   fb.cbufs[0] = (struct pipe_surface){.texture = r, .format = r->format};
   b->ctx->set_framebuffer_state(b->ctx, &fb);
   union pipe_color_union value;
   memcpy(value.f, color, sizeof(value.f));
   b->ctx->clear(b->ctx, PIPE_CLEAR_COLOR0, PIPE_MASK_RGBA, 0, NULL, &value, 0, 0);
   ndx_barrier(b);
   fb = (struct pipe_framebuffer_state){0};
   b->ctx->set_framebuffer_state(b->ctx, &fb);
}

void *ndx_depth_create(struct ndx_backend *b, unsigned width, unsigned height)
{
   const struct pipe_resource desc = {
      .target = PIPE_TEXTURE_2D, .format = PIPE_FORMAT_Z32_FLOAT,
      .width0 = width, .height0 = height, .depth0 = 1, .array_size = 1,
      .bind = PIPE_BIND_DEPTH_STENCIL, .usage = PIPE_USAGE_DEFAULT,
   };
   if (!b->screen->is_format_supported(b->screen, desc.format, desc.target, 1, 1, desc.bind))
      return NULL;
   return b->screen->resource_create(b->screen, &desc);
}

void ndx_clear_depth(struct ndx_backend *b, void *texture, float depth)
{
   struct pipe_resource *r = texture;
   struct pipe_framebuffer_state fb = {.width = r->width0, .height = r->height0};
   fb.zsbuf = (struct pipe_surface){.texture = r, .format = r->format};
   b->ctx->set_framebuffer_state(b->ctx, &fb);
   b->ctx->clear(b->ctx, PIPE_CLEAR_DEPTH, 0, 0, NULL, NULL, depth, 0);
   ndx_barrier(b);
   fb = (struct pipe_framebuffer_state){0};
   b->ctx->set_framebuffer_state(b->ctx, &fb);
}

bool ndx_copy_texture(struct ndx_backend *b, void *dst, unsigned offset, unsigned row_pitch, void *src, bool upload)
{
   struct pipe_resource *texture = upload ? dst : src;
   struct pipe_resource *buffer = upload ? src : dst;
   struct winsys_handle handle = {.type = WINSYS_HANDLE_TYPE_FD};
   if (!b->screen->resource_get_handle(b->screen, b->ctx, buffer, &handle, PIPE_HANDLE_USAGE_SHADER_WRITE))
      return false;
   if (handle.offset) { close(handle.handle); return false; }
   handle.format = PIPE_FORMAT_R8G8B8A8_UNORM;
   handle.modifier = DRM_FORMAT_MOD_LINEAR;
   handle.offset = offset;
   handle.stride = row_pitch;
   const struct pipe_resource desc = {
      .target = PIPE_TEXTURE_2D, .format = PIPE_FORMAT_R8G8B8A8_UNORM,
      .width0 = texture->width0, .height0 = texture->height0, .depth0 = 1, .array_size = 1,
      .bind = PIPE_BIND_RENDER_TARGET | PIPE_BIND_SAMPLER_VIEW | PIPE_BIND_SHARED, .usage = PIPE_USAGE_STAGING,
      .flags = PIPE_RESOURCE_FLAG_FIXED_ADDRESS,
   };
   struct pipe_resource *alias = b->screen->resource_from_handle(b->screen, &desc, &handle,
                                                               PIPE_HANDLE_USAGE_SHADER_WRITE);
   close(handle.handle);
   if (!alias) return false;
   const bool same_address = ndx_buffer_address(b, alias) == ndx_buffer_address(b, buffer) + offset;
   if (same_address) {
      const struct pipe_box box = {.width = texture->width0, .height = texture->height0, .depth = 1};
      b->ctx->resource_copy_region(b->ctx, upload ? texture : alias, 0, 0, 0, 0, upload ? alias : texture, 0, &box);
      ndx_barrier(b);
   }
   pipe_resource_reference(&alias, NULL);
   return same_address;
}

struct graphics_mapping {
   const struct ndx_texture_bindings *bindings;
   unsigned textures, samplers, cbvs;
   bool bad;
};
static dxil_spv_bool remap_varying(void *data, const dxil_spv_d3d_shader_stage_io *in,
                                  dxil_spv_vulkan_shader_stage_io *out)
{
   struct graphics_mapping *m = data;
   if (!m->bindings || !in->semantic || strcasecmp(in->semantic, "TEXCOORD") || in->semantic_index != 0) {
      m->bad = true; return 0;
   }
   *out = (dxil_spv_vulkan_shader_stage_io){.location = 0};
   return 1;
}
static dxil_spv_bool remap_texture(void *data, const dxil_spv_d3d_binding *in, dxil_spv_srv_vulkan_binding *out)
{
   struct graphics_mapping *m = data;
   if (!m->bindings || in->stage != DXIL_SPV_STAGE_PIXEL || in->range_size != (m->bindings->table4 ? 4u : 1u) ||
       in->kind != DXIL_SPV_RESOURCE_KIND_TEXTURE_2D ||
       in->register_space != m->bindings->srv_space || in->register_index != m->bindings->srv_reg) {
      m->bad = true; return 0;
   }
   *out = (dxil_spv_srv_vulkan_binding){0};
   out->buffer_binding.binding = NDX_TEXTURE_SLOT;
   m->textures++;
   return 1;
}
static dxil_spv_bool remap_graphics_sampler(void *data, const dxil_spv_d3d_binding *in, dxil_spv_vulkan_binding *out)
{
   struct graphics_mapping *m = data;
   if (!m->bindings || in->stage != DXIL_SPV_STAGE_PIXEL || in->range_size != 1 ||
       in->kind != DXIL_SPV_RESOURCE_KIND_SAMPLER ||
       in->register_space != m->bindings->sampler_space || in->register_index != m->bindings->sampler_reg) {
      m->bad = true; return 0;
   }
   *out = (dxil_spv_vulkan_binding){.binding = NDX_SAMPLER_SLOT};
   m->samplers++;
   return 1;
}

static dxil_spv_bool remap_graphics_cbv(void *data, const dxil_spv_d3d_binding *in, dxil_spv_cbv_vulkan_binding *out)
{
   struct graphics_mapping *m = data;
   if (!m->bindings || !m->bindings->table4 || in->stage != DXIL_SPV_STAGE_PIXEL ||
       in->range_size != 1 || in->kind != DXIL_SPV_RESOURCE_KIND_CONSTANT_BUFFER ||
       in->register_space || in->register_index) {
      m->bad = true; return 0;
   }
   *out = (dxil_spv_cbv_vulkan_binding){0};
   out->vulkan.uniform_binding.descriptor_type = DXIL_SPV_VULKAN_DESCRIPTOR_TYPE_IDENTITY;
   m->cbvs++;
   return 1;
}
static bool lower_graphics_cbv(nir_builder *b, nir_intrinsic_instr *in, void *data)
{
   struct graphics_mapping *m = data;
   nir_def *value = NULL;
   b->cursor = nir_before_instr(&in->instr);
   switch (in->intrinsic) {
   case nir_intrinsic_vulkan_resource_index:
      if (!m->cbvs || nir_intrinsic_desc_type(in) != nir_descriptor_type_uniform_buffer ||
          nir_intrinsic_desc_set(in) || nir_intrinsic_binding(in) ||
          !nir_src_is_const(in->src[0]) || nir_src_as_uint(in->src[0]) ||
          in->def.num_components != 2 || in->def.bit_size != 32) { m->bad = true; return false; }
      value = nir_imm_ivec2(b, 0, 0); break;
   case nir_intrinsic_load_vulkan_descriptor:
      if (!m->cbvs || nir_intrinsic_desc_type(in) != nir_descriptor_type_uniform_buffer ||
          in->def.num_components != 2 || in->def.bit_size != 32) { m->bad = true; return false; }
      value = in->src[0].ssa; break;
   case nir_intrinsic_vulkan_resource_reindex: m->bad = true; return false;
   default: return false;
   }
   nir_def_rewrite_uses(&in->def, value);
   nir_instr_remove(&in->instr);
   return true;
}
static bool table_index(nir_scalar index)
{
   if (nir_scalar_is_const(index)) return nir_scalar_as_uint(index) < 4;
   if (nir_def_instr(index.def)->type != nir_instr_type_alu) return false;
   nir_alu_instr *alu = nir_instr_as_alu(nir_def_instr(index.def));
   if (alu->op != nir_op_iand) return false;
   nir_scalar a = nir_scalar_chase_alu_src(index, 0), b = nir_scalar_chase_alu_src(index, 1);
   if (nir_scalar_is_const(a)) { nir_scalar t = a; a = b; b = t; }
   if (!nir_scalar_is_const(b) || nir_scalar_as_uint(b) != 3 || a.comp != 0 ||
       nir_def_instr(a.def)->type != nir_instr_type_intrinsic) return false;
   nir_intrinsic_instr *load = nir_instr_as_intrinsic(nir_def_instr(a.def));
   return load->intrinsic == nir_intrinsic_load_ubo && load->def.bit_size == 32 &&
          nir_src_is_const(load->src[0]) && !nir_src_as_uint(load->src[0]) &&
          nir_src_is_const(load->src[1]) && !nir_src_as_uint(load->src[1]);
}

static void *graphics_shader(struct ndx_backend *b, const void *dxil, size_t bytes,
                              mesa_shader_stage stage, const struct ndx_texture_bindings *bindings)
{
   dxil_spv_parsed_blob blob = NULL;
   dxil_spv_converter converter = NULL;
   nir_shader *nir = NULL;
   void *shader = NULL;
   const dxil_spv_shader_stage expected = stage == MESA_SHADER_VERTEX ? DXIL_SPV_STAGE_VERTEX : DXIL_SPV_STAGE_PIXEL;
   if (!dxil || bytes < 32 || bytes > 1024 * 1024 || memcmp(dxil, "DXBC", 4)) return NULL;
   struct dump_outputs outputs = {0};
   if (!dump_begin(&outputs, b, stage == MESA_SHADER_VERTEX ? "vs.spv" : "ps.spv",
                   stage == MESA_SHADER_VERTEX ? "vs.nir.txt" : "ps.nir.txt",
                   bindings && bindings->table4)) return NULL;
   dxil_spv_begin_thread_allocator_context();
   if (dxil_spv_parse_dxil_blob(dxil, bytes, &blob) != DXIL_SPV_SUCCESS ||
       dxil_spv_parsed_blob_get_shader_stage(blob) != expected ||
       dxil_spv_create_converter(blob, &converter) != DXIL_SPV_SUCCESS) goto done;
   struct mapping reject = {0};
   struct graphics_mapping mapping = {.bindings = bindings};
   if (bindings) {
      if (stage == MESA_SHADER_VERTEX)
         dxil_spv_converter_set_stage_output_remapper(converter, remap_varying, &mapping);
      else
         dxil_spv_converter_set_stage_input_remapper(converter, remap_varying, &mapping);
   }
   dxil_spv_converter_set_entry_point(converter, "main");
   dxil_spv_converter_set_uav_remapper(converter, remap_uav, &reject);
   dxil_spv_converter_set_srv_remapper(converter, remap_texture, &mapping);
   dxil_spv_converter_set_cbv_remapper(converter, remap_graphics_cbv, &mapping);
   dxil_spv_converter_set_sampler_remapper(converter, remap_graphics_sampler, &mapping);
   dxil_spv_option_physical_storage_buffer physical = {{DXIL_SPV_OPTION_PHYSICAL_STORAGE_BUFFER}, 0};
   if (dxil_spv_converter_add_option(converter, &physical.base) != DXIL_SPV_SUCCESS ||
       dxil_spv_converter_run(converter) != DXIL_SPV_SUCCESS || reject.bad || mapping.bad) goto done;
   const bool sampled = bindings && stage == MESA_SHADER_FRAGMENT;
   if (mapping.textures != (unsigned)sampled || mapping.samplers != (unsigned)sampled || mapping.cbvs > 1) goto done;
   dxil_spv_compiled_spirv spirv;
   if (dxil_spv_converter_get_compiled_spirv(converter, &spirv) != DXIL_SPV_SUCCESS ||
       spirv.size < 20 || spirv.size > 1024 * 1024 || spirv.size % 4) goto done;
   const uint32_t *words = spirv.data;
   unsigned capabilities = 0;
   for (size_t at = 5; at < spirv.size / 4;) {
      unsigned count = words[at] >> 16;
      if (!count || count > spirv.size / 4 - at) goto done;
      if ((words[at] & 0xffff) == 17) {
         if (count != 2 || (words[at + 1] != SpvCapabilityShader &&
             !(stage == MESA_SHADER_VERTEX && words[at + 1] == SpvCapabilityDrawParameters) &&
             !(sampled && bindings->table4 && words[at + 1] == SpvCapabilitySampledImageArrayDynamicIndexing))) goto done;
         capabilities++;
      }
      at += count;
   }
   if (!capabilities || capabilities > ((stage == MESA_SHADER_VERTEX || (sampled && bindings->table4)) ? 2u : 1u)) goto done;
   spv_context validation = spvContextCreate(SPV_ENV_VULKAN_1_3);
   spv_const_binary_t code = {words, spirv.size / 4};
   spv_diagnostic diagnostic = NULL;
   spv_result_t valid = spvValidate(validation, &code, &diagnostic);
   if (diagnostic) fprintf(stderr, "NDX12_GRAPHICS_VALIDATION=%s\n", diagnostic->error);
   spvDiagnosticDestroy(diagnostic);
   spvContextDestroy(validation);
   if (valid != SPV_SUCCESS) goto done;
   if (!dump(&outputs, 0, spirv.data, spirv.size, NULL)) goto done;
   bool import_error = false;
   const struct spirv_to_nir_options options = {
      .environment = NIR_SPIRV_VULKAN, .temp_addr_format = nir_address_format_logical,
      .ubo_addr_format = nir_address_format_32bit_index_offset,
      .skip_os_break_in_debug_build = true, .ignore_replacement = true,
      .debug = {.func = import_debug, .private_data = &import_error},
   };
   nir = spirv_to_nir(words, spirv.size / 4, NULL, stage, "main", &options, b->screen->nir_options[stage]);
   if (!nir || import_error) goto done;
   NIR_PASS(_, nir, nir_lower_variable_initializers, nir_var_function_temp);
   NIR_PASS(_, nir, nir_lower_returns);
   NIR_PASS(_, nir, nir_inline_functions);
   nir_remove_non_entrypoints(nir);
   NIR_PASS(_, nir, nir_lower_variable_initializers, ~0);
   NIR_PASS(_, nir, nir_lower_var_copies);
   NIR_PASS(_, nir, nir_lower_vars_to_ssa);
   NIR_PASS(_, nir, nir_lower_system_values);
   NIR_PASS(_, nir, nir_opt_copy_prop);
   NIR_PASS(_, nir, nir_opt_constant_folding);
   NIR_PASS(_, nir, nir_opt_dce);
   if (sampled && bindings->table4) {
      nir_foreach_variable_with_modes(var, nir, nir_var_mem_ubo)
         if (var->data.descriptor_set || var->data.binding) goto done;
      NIR_PASS(_, nir, nir_shader_intrinsics_pass, lower_graphics_cbv, nir_metadata_control_flow, &mapping);
      if (mapping.bad) goto done;
      NIR_PASS(_, nir, nir_lower_explicit_io, nir_var_mem_ubo, nir_address_format_32bit_index_offset);
      NIR_PASS(_, nir, nir_opt_constant_folding);
      NIR_PASS(_, nir, nir_opt_copy_prop);
      NIR_PASS(_, nir, nir_opt_constant_folding);
      NIR_PASS(_, nir, nir_opt_algebraic);
      NIR_PASS(_, nir, nir_opt_constant_folding);
      NIR_PASS(_, nir, nir_opt_dce);
      nir_foreach_function_impl(impl, nir) {
         nir_foreach_block(block, impl) {
            nir_foreach_instr(instr, block) {
               if (instr->type != nir_instr_type_intrinsic) continue;
               nir_intrinsic_instr *in = nir_instr_as_intrinsic(instr);
               switch (in->intrinsic) {
               case nir_intrinsic_vulkan_resource_index:
               case nir_intrinsic_load_vulkan_descriptor:
               case nir_intrinsic_vulkan_resource_reindex: goto done;
               case nir_intrinsic_load_ubo:
                  if (!mapping.cbvs || in->def.bit_size != 32 || in->def.num_components > 4 ||
                      !nir_src_is_const(in->src[0]) || nir_src_as_uint(in->src[0]) ||
                      !nir_src_is_const(in->src[1]) || nir_src_as_uint(in->src[1]) > 16 - in->def.num_components * 4)
                     goto done;
                  break;
               default: break;
               }
            }
         }
      }
      if (!dump(&outputs, 2, NULL, 0, nir)) goto done;
   }
   if (sampled) {
      unsigned images = 0, samplers = 0;
      bool indirect_texture = false;
      nir_foreach_variable_with_modes(var, nir, nir_var_uniform) {
         if (var->data.descriptor_set != 0) goto done;
         const struct glsl_type *type = var->type;
         if (bindings->table4 && var->data.binding == NDX_TEXTURE_SLOT) {
            if (!glsl_type_is_array(type) || glsl_get_length(type) != 4) goto done;
            type = glsl_get_array_element(type);
         }
         if (glsl_type_is_texture(type) && var->data.binding == NDX_TEXTURE_SLOT &&
             glsl_get_sampler_dim(type) == GLSL_SAMPLER_DIM_2D &&
             !glsl_sampler_type_is_array(type) && glsl_get_sampler_result_type(type) == GLSL_TYPE_FLOAT) images++;
         else if (glsl_type_is_bare_sampler(var->type) && var->data.binding == NDX_SAMPLER_SLOT) samplers++;
         else goto done;
      }
      if (images != 1 || samplers != 1) goto done;
      NIR_PASS(_, nir, nir_opt_deref);
      nir_foreach_function_impl(impl, nir) {
         nir_foreach_block(block, impl) {
            nir_foreach_instr(instr, block) {
               if (instr->type != nir_instr_type_tex) continue;
               nir_tex_instr *tex = nir_instr_as_tex(instr);
               const int image_src = nir_tex_instr_src_index(tex, nir_tex_src_texture_deref);
               const int sampler_src = nir_tex_instr_src_index(tex, nir_tex_src_sampler_deref);
               if (tex->op != (bindings->table4 ? nir_texop_txl : nir_texop_tex) || image_src < 0 || sampler_src < 0 ||
                   tex->texture_non_uniform || tex->sampler_non_uniform ||
                   tex->sampler_dim != GLSL_SAMPLER_DIM_2D || tex->is_array || tex->is_shadow) goto done;
               nir_deref_instr *image = nir_def_as_deref(tex->src[image_src].src.ssa);
               nir_deref_instr *sampler = nir_def_as_deref(tex->src[sampler_src].src.ssa);
               if (bindings->table4) {
                  const int lod = nir_tex_instr_src_index(tex, nir_tex_src_lod);
                  if (lod < 0 || !nir_src_is_const(tex->src[lod].src) || nir_src_as_float(tex->src[lod].src) != 0 ||
                      image->deref_type != nir_deref_type_array || !table_index(nir_get_scalar(image->arr.index.ssa, 0))) {
                     fprintf(stderr, "NDX12_TABLE_INDEX_REJECT\n"); goto done;
                  }
                  indirect_texture |= !nir_src_is_const(image->arr.index);
                  image = nir_deref_instr_parent(image);
               }
               if (image->deref_type != nir_deref_type_var || sampler->deref_type != nir_deref_type_var ||
                   image->var->data.binding != NDX_TEXTURE_SLOT || sampler->var->data.binding != NDX_SAMPLER_SLOT) goto done;
            }
         }
      }
      NIR_PASS(_, nir, nir_lower_samplers);
      NIR_PASS(_, nir, nir_opt_dce);
      /* finalize_nir folds a dynamic texture base into its offset. Iris then
       * indexes from slot zero and requires an uncompressed prefix, including
       * the unused null slots below our range. The checked index stays 3..6. */
      for (unsigned i = indirect_texture ? 0 : NDX_TEXTURE_SLOT;
           i < NDX_TEXTURE_SLOT + (bindings->table4 ? 4u : 1u); ++i)
         BITSET_SET(nir->info.textures_used, i);
      BITSET_SET(nir->info.samplers_used, NDX_SAMPLER_SLOT);
   }
   nir_shader_gather_info(nir, nir_shader_get_entrypoint(nir));
   const uint64_t varying = bindings ? BITFIELD64_BIT(VARYING_SLOT_VAR0) : 0;
   if (nir->info.num_ssbos || nir->info.num_ubos != mapping.cbvs || nir->info.num_images ||
       (!sampled && nir->info.num_textures) ||
       nir->info.inputs_read != (stage == MESA_SHADER_FRAGMENT ? varying : 0) ||
       nir->info.outputs_written != (stage == MESA_SHADER_VERTEX ? VARYING_BIT_POS | varying : BITFIELD64_BIT(FRAG_RESULT_DATA0))) {
      fprintf(stderr, "NDX12_GRAPHICS_INTERFACE stage=%u in=%llx out=%llx textures=%u ssbos=%u ubos=%u images=%u\n",
              stage, (unsigned long long)nir->info.inputs_read, (unsigned long long)nir->info.outputs_written,
              nir->info.num_textures, nir->info.num_ssbos, nir->info.num_ubos, nir->info.num_images);
      goto done;
   }
   if (bindings) {
      unsigned varyings = 0;
      nir_foreach_variable_with_modes(var, nir, stage == MESA_SHADER_VERTEX ? nir_var_shader_out : nir_var_shader_in) {
         if (var->data.location == VARYING_SLOT_VAR0) {
            if (var->type != glsl_vec2_type() || (var->data.interpolation != INTERP_MODE_SMOOTH &&
                                               var->data.interpolation != INTERP_MODE_NONE)) {
               fprintf(stderr, "NDX12_GRAPHICS_VARYING stage=%u type=%s interpolation=%u\n",
                       stage, glsl_get_type_name(var->type), var->data.interpolation);
               goto done;
            }
            varyings++;
         }
      }
      if (varyings != 1) {
         fprintf(stderr, "NDX12_GRAPHICS_VARYING stage=%u count=%u\n", stage, varyings);
         goto done;
      }
   }
   nir_assign_io_var_locations(nir, nir_var_shader_in);
   nir_assign_io_var_locations(nir, nir_var_shader_out);
   nir->info.name = ralloc_strdup(nir, stage == MESA_SHADER_VERTEX ? "ndx12-dxil-vs" : "ndx12-dxil-ps");
   nir->info.separate_shader = true;
   b->screen->finalize_nir(b->screen, nir, true);
   nir_validate_shader(nir, "ndx12 graphics import");
   if (!dump(&outputs, 1, NULL, 0, nir) || ndx_evidence_close(outputs.files, outputs.count)) goto done;
   struct pipe_shader_state state = {.type = PIPE_SHADER_IR_NIR, .ir.nir = nir};
   shader = stage == MESA_SHADER_VERTEX ? b->ctx->create_vs_state(b->ctx, &state) :
                                        b->ctx->create_fs_state(b->ctx, &state);
   nir = NULL;
   if (shader) { b->shader_count++; printf("dxil_%s_compiled_in_process=1\n", stage == MESA_SHADER_VERTEX ? "vs" : "ps"); }
done:
   ndx_evidence_close(outputs.files, outputs.count);
   if (nir) ralloc_free(nir);
   if (converter) dxil_spv_converter_free(converter);
   if (blob) dxil_spv_parsed_blob_free(blob);
   dxil_spv_end_thread_allocator_context();
   return shader;
}

struct ndx_graphics { void *vs, *ps, *blend, *rasterizer, *depth, *elements; };
void ndx_graphics_destroy(struct ndx_backend *b, void *pipeline)
{
   struct ndx_graphics *p = pipeline;
   if (!p) return;
   if (p->vs) b->ctx->delete_vs_state(b->ctx, p->vs);
   if (p->ps) b->ctx->delete_fs_state(b->ctx, p->ps);
   if (p->blend) b->ctx->delete_blend_state(b->ctx, p->blend);
   if (p->rasterizer) b->ctx->delete_rasterizer_state(b->ctx, p->rasterizer);
   if (p->depth) b->ctx->delete_depth_stencil_alpha_state(b->ctx, p->depth);
   if (p->elements) b->ctx->delete_vertex_elements_state(b->ctx, p->elements);
   free(p);
}
void *ndx_graphics_create(struct ndx_backend *b, const void *vs, size_t vs_bytes, const void *ps, size_t ps_bytes,
                          const struct ndx_texture_bindings *bindings, const struct ndx_depth_state *z)
{
   struct ndx_graphics *p = calloc(1, sizeof(*p));
   if (!p) return NULL;
   p->vs = graphics_shader(b, vs, vs_bytes, MESA_SHADER_VERTEX, bindings);
   if (!p->vs) goto fail;
   p->ps = graphics_shader(b, ps, ps_bytes, MESA_SHADER_FRAGMENT, bindings);
   if (!p->ps) goto fail;
   const struct pipe_blend_state blend = {.rt[0].colormask = PIPE_MASK_RGBA};
   const struct pipe_depth_stencil_alpha_state depth = {
      .depth_enabled = z->enabled, .depth_writemask = z->enabled && z->write,
      .depth_func = z->func == NDX_DEPTH_LEQUAL ? PIPE_FUNC_LEQUAL : PIPE_FUNC_LESS,
   };
   const struct pipe_rasterizer_state rasterizer = {
      .cull_face = PIPE_FACE_NONE, .fill_front = PIPE_POLYGON_MODE_FILL, .fill_back = PIPE_POLYGON_MODE_FILL,
      .scissor = true, .half_pixel_center = true, .bottom_edge_rule = false,
      .depth_clip_near = true, .depth_clip_far = true, .clip_halfz = true, .line_width = 1, .point_size = 1,
   };
   p->blend = b->ctx->create_blend_state(b->ctx, &blend);
   p->depth = b->ctx->create_depth_stencil_alpha_state(b->ctx, &depth);
   p->rasterizer = b->ctx->create_rasterizer_state(b->ctx, &rasterizer);
   p->elements = b->ctx->create_vertex_elements_state(b->ctx, 0, NULL);
   if (p->blend && p->depth && p->rasterizer && p->elements) return p;
fail:
   ndx_graphics_destroy(b, p);
   return NULL;
}
static bool draw_textures(struct ndx_backend *b, void *pipeline, void *target,
              const float viewport[6], const unsigned scissor[4], unsigned vertices,
              void *const *textures, unsigned count, void *constants, unsigned constants_offset,
              bool repeat_u, bool repeat_v, void *depth, const struct ndx_index_view *indices)
{
   struct ndx_graphics *p = pipeline;
   struct pipe_sampler_view *views[4] = {0};
   void *sampler = NULL;
   if (count) {
      const struct pipe_sampler_view desc = {
         .format = PIPE_FORMAT_R8G8B8A8_UNORM, .target = PIPE_TEXTURE_2D,
         .swizzle_r = PIPE_SWIZZLE_X, .swizzle_g = PIPE_SWIZZLE_Y,
         .swizzle_b = PIPE_SWIZZLE_Z, .swizzle_a = PIPE_SWIZZLE_W,
      };
      const struct pipe_sampler_state state = {
         .wrap_s = repeat_u ? PIPE_TEX_WRAP_REPEAT : PIPE_TEX_WRAP_CLAMP_TO_EDGE,
         .wrap_t = repeat_v ? PIPE_TEX_WRAP_REPEAT : PIPE_TEX_WRAP_CLAMP_TO_EDGE,
         .wrap_r = PIPE_TEX_WRAP_CLAMP_TO_EDGE,
         .min_img_filter = PIPE_TEX_FILTER_NEAREST, .mag_img_filter = PIPE_TEX_FILTER_NEAREST,
         .min_mip_filter = PIPE_TEX_MIPFILTER_NEAREST,
      };
      bool valid = true;
      for (unsigned i = 0; i < count; ++i) {
         views[i] = b->ctx->create_sampler_view(b->ctx, textures[i], &desc);
         valid &= views[i] != NULL;
      }
      sampler = b->ctx->create_sampler_state(b->ctx, &state);
      if (!valid || !sampler) {
         for (unsigned i = 0; i < count; ++i) pipe_sampler_view_reference(&views[i], NULL);
         if (sampler) b->ctx->delete_sampler_state(b->ctx, sampler);
         return false;
      }
      b->ctx->set_sampler_views(b->ctx, MESA_SHADER_FRAGMENT, NDX_TEXTURE_SLOT, count, 0, views);
      b->ctx->bind_sampler_states(b->ctx, MESA_SHADER_FRAGMENT, NDX_SAMPLER_SLOT, 1, &sampler);
   }
   if (constants) {
      const struct pipe_constant_buffer cb = {.buffer = constants, .buffer_offset = constants_offset, .buffer_size = 16};
      b->ctx->set_constant_buffer(b->ctx, MESA_SHADER_FRAGMENT, 0, &cb);
   }
   struct pipe_resource *r = target;
   struct pipe_framebuffer_state fb = {.width = r->width0, .height = r->height0, .nr_cbufs = 1};
   fb.cbufs[0] = (struct pipe_surface){.texture = r, .format = r->format};
   if (depth) {
      struct pipe_resource *z = depth;
      fb.zsbuf = (struct pipe_surface){.texture = z, .format = z->format};
   }
   b->ctx->set_framebuffer_state(b->ctx, &fb);
   b->ctx->bind_vs_state(b->ctx, p->vs);
   b->ctx->bind_fs_state(b->ctx, p->ps);
   b->ctx->bind_blend_state(b->ctx, p->blend);
   b->ctx->bind_depth_stencil_alpha_state(b->ctx, p->depth);
   b->ctx->bind_rasterizer_state(b->ctx, p->rasterizer);
   b->ctx->bind_vertex_elements_state(b->ctx, p->elements);
   b->ctx->set_vertex_buffers(b->ctx, 0, NULL);
   b->ctx->set_sample_mask(b->ctx, ~0u);
   const struct pipe_viewport_state vp = {
      .scale = {viewport[2] / 2, -viewport[3] / 2, viewport[5] - viewport[4]},
      .translate = {viewport[0] + viewport[2] / 2, viewport[1] + viewport[3] / 2, viewport[4]},
   };
   const struct pipe_scissor_state sc = {scissor[0], scissor[1], scissor[2], scissor[3]};
   b->ctx->set_viewport_states(b->ctx, 0, 1, &vp);
   b->ctx->set_scissor_states(b->ctx, 0, 1, &sc);
   const struct pipe_draw_info info = {
      .mode = MESA_PRIM_TRIANGLES, .instance_count = 1,
      .index_size = indices ? indices->size : 0,
      .index.resource = indices ? indices->buffer : NULL,
   };
   const struct pipe_draw_start_count_bias draw = {
      .count = vertices, .start = indices ? indices->offset / indices->size + indices->first : 0,
      .index_bias = indices ? indices->bias : 0,
   };
   b->ctx->draw_vbo(b->ctx, &info, 0, NULL, &draw, 1);
   ndx_barrier(b);
   if (count) {
      b->ctx->set_sampler_views(b->ctx, MESA_SHADER_FRAGMENT, NDX_TEXTURE_SLOT, 0, count, NULL);
      void *empty = NULL;
      b->ctx->bind_sampler_states(b->ctx, MESA_SHADER_FRAGMENT, NDX_SAMPLER_SLOT, 1, &empty);
      for (unsigned i = 0; i < count; ++i) pipe_sampler_view_reference(&views[i], NULL);
      b->ctx->delete_sampler_state(b->ctx, sampler);
   }
   if (constants) b->ctx->set_constant_buffer(b->ctx, MESA_SHADER_FRAGMENT, 0, NULL);
   b->ctx->bind_vs_state(b->ctx, NULL);
   b->ctx->bind_fs_state(b->ctx, NULL);
   b->ctx->bind_blend_state(b->ctx, NULL);
   b->ctx->bind_depth_stencil_alpha_state(b->ctx, NULL);
   b->ctx->bind_rasterizer_state(b->ctx, NULL);
   b->ctx->bind_vertex_elements_state(b->ctx, NULL);
   fb = (struct pipe_framebuffer_state){0};
   b->ctx->set_framebuffer_state(b->ctx, &fb);
   return true;
}

bool ndx_draw(struct ndx_backend *b, void *pipeline, void *target,
              const float viewport[6], const unsigned scissor[4], unsigned vertices,
              void *texture, bool repeat_u, bool repeat_v, void *depth, const struct ndx_index_view *indices)
{
   return draw_textures(b, pipeline, target, viewport, scissor, vertices, &texture, texture ? 1 : 0,
                        NULL, 0, repeat_u, repeat_v, depth, indices);
}
bool ndx_draw_table(struct ndx_backend *b, void *pipeline, void *target,
                    const float viewport[6], const unsigned scissor[4], unsigned vertices,
                    const struct ndx_texture_table *table, bool repeat_u, bool repeat_v,
                    void *depth, const struct ndx_index_view *indices)
{
   if (!table || !table->constants) return false;
   for (unsigned i = 0; i < 4; ++i) if (!table->textures[i]) return false;
   return draw_textures(b, pipeline, target, viewport, scissor, vertices, table->textures, 4,
                        table->constants, table->constants_offset, repeat_u, repeat_v, depth, indices);
}
