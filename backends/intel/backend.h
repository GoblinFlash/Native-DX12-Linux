#ifndef NDX12_BACKEND_H
#define NDX12_BACKEND_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
struct ndx_backend;
struct ndx_backend *ndx_backend_create(const char *node);
void ndx_backend_destroy(struct ndx_backend *b);
void *ndx_buffer_create(struct ndx_backend *b, unsigned bytes, unsigned heap);
void ndx_buffer_destroy(void *buffer);
void *ndx_buffer_map(struct ndx_backend *b, void *buffer, unsigned bytes, bool read, void **transfer);
void ndx_buffer_unmap(struct ndx_backend *b, void *transfer);
uint64_t ndx_buffer_address(struct ndx_backend *b, void *buffer);
void ndx_copy(struct ndx_backend *b, void *dst, unsigned dst_offset, void *src, unsigned src_offset, unsigned bytes);
void ndx_barrier(struct ndx_backend *b);
void *ndx_shader_create(struct ndx_backend *b, const void *dxil, size_t bytes, unsigned space, unsigned reg);
void ndx_shader_destroy(struct ndx_backend *b, void *shader);
void ndx_dispatch(struct ndx_backend *b, void *shader, void *buffer, unsigned offset, unsigned bytes, unsigned groups);
void *ndx_flush(struct ndx_backend *b);
bool ndx_wait(struct ndx_backend *b, void *fence, uint64_t timeout);
void ndx_fence_destroy(struct ndx_backend *b, void *fence);
unsigned ndx_reset_status(struct ndx_backend *b);
void *ndx_texture_create(struct ndx_backend *b, unsigned width, unsigned height);
void *ndx_present_create(struct ndx_backend *b, unsigned width, unsigned height);
int ndx_present_export(struct ndx_backend *b, void *texture, unsigned *stride, unsigned *offset);
void ndx_present_flush(struct ndx_backend *b, void *texture);
void *ndx_depth_create(struct ndx_backend *b, unsigned width, unsigned height);
void ndx_clear_target(struct ndx_backend *b, void *texture, const float color[4]);
void ndx_clear_depth(struct ndx_backend *b, void *texture, float depth);
bool ndx_copy_texture(struct ndx_backend *b, void *dst, unsigned offset, unsigned row_pitch, void *src, bool upload);
struct ndx_texture_bindings {
   unsigned srv_space, srv_reg, sampler_space, sampler_reg;
   bool table4;
};
enum { NDX_TEXTURE_SLOT = 3, NDX_SAMPLER_SLOT = 5 };
enum ndx_depth_func { NDX_DEPTH_LESS, NDX_DEPTH_LEQUAL };
struct ndx_depth_state { bool enabled, write; enum ndx_depth_func func; };
struct ndx_index_view {
   void *buffer;
   unsigned size, offset, first;
   int bias;
};
void *ndx_graphics_create(struct ndx_backend *b, const void *vs, size_t vs_bytes, const void *ps, size_t ps_bytes,
                          const struct ndx_texture_bindings *bindings, const struct ndx_depth_state *depth);
void ndx_graphics_destroy(struct ndx_backend *b, void *pipeline);
bool ndx_draw(struct ndx_backend *b, void *pipeline, void *target,
              const float viewport[6], const unsigned scissor[4], unsigned vertices,
              void *texture, bool repeat_u, bool repeat_v, void *depth, const struct ndx_index_view *indices);
struct ndx_texture_table {
   void *textures[4];
   void *constants;
   unsigned constants_offset;
};
bool ndx_draw_table(struct ndx_backend *b, void *pipeline, void *target,
                    const float viewport[6], const unsigned scissor[4], unsigned vertices,
                    const struct ndx_texture_table *table, bool repeat_u, bool repeat_v,
                    void *depth, const struct ndx_index_view *indices);
#ifdef __cplusplus
}
#endif
#endif
