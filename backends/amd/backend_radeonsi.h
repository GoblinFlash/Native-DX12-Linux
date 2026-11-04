#ifndef NDX_CORE_RADEONSI_H
#define NDX_CORE_RADEONSI_H
#include "nir_emitter.h"
struct pipe_screen;
struct pipe_context;
struct pipe_shader_buffer;
struct pipe_resource;
struct nir_shader;
struct core_radeonsi;
struct core_radeonsi_layout {
   unsigned version, resource_id, resource_class, space, reg, stage, slot;
};
/* Trusted in-process API: the caller establishes RadeonSI/device provenance.
 * The screen and its options must outlive the adapter and all returned shaders.
 * This bounded profile maps one writable uint UAV u0/space0 to Gallium slot 3.
 * A returned compute state may still be compiling asynchronously. */
struct core_radeonsi *core_radeonsi_create(struct pipe_screen *);
void core_radeonsi_destroy(struct core_radeonsi **);
struct core_build_profile core_radeonsi_profile(const struct core_radeonsi *);
/* Consumes *module on every path. Success transfers NIR ownership to the caller;
 * failure leaves *out NULL. Pointers must be live objects, not untrusted bytes. */
int core_radeonsi_lower(struct core_radeonsi *, struct core_module **,
                        const struct core_radeonsi_layout *, struct nir_shader **, char error[256]);
/* Consumes module; on success pinned RadeonSI owns NIR. On allocation failure
 * this adapter frees NIR, as required by si_create_compute_state_for_nir. */
void *core_radeonsi_create_state(struct core_radeonsi *, struct pipe_context *,
                                struct core_module **, const struct core_radeonsi_layout *, char error[256]);
int core_radeonsi_check_view(const struct core_radeonsi *, const struct core_radeonsi_layout *,
                             unsigned bound_slot, const struct pipe_shader_buffer *,
                             const struct pipe_resource *expected, char error[256]);
/* Caller retains its resource reference. Gallium retains a binding reference.
 * This does not dispatch, wait for compilation or establish completion. */
int core_radeonsi_bind_view(const struct core_radeonsi *, struct pipe_context *,
                            const struct core_radeonsi_layout *, const struct pipe_shader_buffer *,
                            const struct pipe_resource *expected, char error[256]);
#endif
