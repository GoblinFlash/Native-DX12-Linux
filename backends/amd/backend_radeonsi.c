#include "backend_radeonsi.h"
#include "core_internal.h"
#include "pipe/p_screen.h"
#include <stdlib.h>
#include <stdatomic.h>
#include <stdio.h>
#include "compiler/nir/nir_builder.h"
#include "pipe/p_context.h"
#include "pipe/p_state.h"
struct core_radeonsi {struct pipe_screen *screen; uint64_t identity;};
static atomic_uint_fast64_t next_identity=UINT64_C(0x5241445300000001);
struct core_radeonsi *core_radeonsi_create(struct pipe_screen *s)
{
   if (!s || !s->caps.compute || !s->nir_options[MESA_SHADER_COMPUTE] ||
       s->nir_options[MESA_SHADER_COMPUTE]->cb_data ||
       s->shader_caps[MESA_SHADER_COMPUTE].max_shader_buffers < 4 ||
       !(s->shader_caps[MESA_SHADER_COMPUTE].supported_irs & (1 << PIPE_SHADER_IR_NIR)) ||
       s->compute_caps.max_threads_per_block < 64 || s->compute_caps.max_block_size[0] < 64 ||
       s->compute_caps.max_block_size[1] < 1 || s->compute_caps.max_block_size[2] < 1 ||
       !s->caps.shader_buffer_offset_alignment)
      return NULL;
   struct core_radeonsi *a = calloc(1, sizeof(*a));
   if (a) {
      a->screen = s;
      a->identity = atomic_fetch_add(&next_identity, 1);
   }
   return a;
}
void core_radeonsi_destroy(struct core_radeonsi **a) {if(a){free(*a);*a=NULL;}}
struct core_build_profile core_radeonsi_profile(const struct core_radeonsi *a)
{
   return (struct core_build_profile){.mesa_revision=CORE_MESA_REVISION,.profile=CORE_PROFILE,
      .options=a?a->screen->nir_options[MESA_SHADER_COMPUTE]:NULL,
      .adapter_identity=a?a->identity:0,.stage=CORE_COMPUTE,.logical_resource_abi=1};
}
static int reject(struct core_module **owned, char error[256], const char *why)
{
   if (error) snprintf(error,256,"RADEONSI_REJECT:%s",why);
   core_module_destroy(owned);
   return 1;
}
static bool valid_layout(const struct core_radeonsi_layout *l)
{
   return l && l->version==1 && l->resource_id==0 && l->resource_class==CORE_UAV &&
      l->space==0 && l->reg==0 && l->stage==CORE_COMPUTE && l->slot==3;
}
static bool map_store(nir_builder *b,nir_intrinsic_instr *in,void *data)
{
   if(in->intrinsic!=nir_intrinsic_store_ssbo)return false;
   b->cursor=nir_before_instr(&in->instr);
   nir_src_rewrite(&in->src[1],nir_imm_int(b,*(unsigned *)data));
   return true;
}
int core_radeonsi_lower(struct core_radeonsi *a,struct core_module **owned,
                        const struct core_radeonsi_layout *l,nir_shader **out,char error[256])
{
   if(out)*out=NULL;
   if(error)error[0]=0;
   struct core_module *m=owned?*owned:NULL;
   if(!a||!m||!m->nir||!out||!error||m->adapter_identity!=a->identity||m->phase!=CORE_N0_UNBOUND)
      return reject(owned,error,"OWNER_OR_PHASE");
   if(!valid_layout(l)||m->resource.id!=0||m->resource.resource_class!=CORE_UAV||
      m->resource.space!=0||m->resource.reg!=0||m->resource.array_count!=1||
      m->resource.stride!=4||m->resource.access!=CORE_WRITE||m->resource.stage!=CORE_COMPUTE)
      return reject(owned,error,"LAYOUT");
   nir_shader *n=m->nir;
   if(n->info.stage!=MESA_SHADER_COMPUTE||n->info.workgroup_size[0]!=64||
      n->info.workgroup_size[1]!=1||n->info.workgroup_size[2]!=1||n->info.workgroup_size_variable||
      n->info.num_ssbos!=1||n->info.num_ubos||n->info.num_images||n->info.num_textures||n->info.shared_size)
      return reject(owned,error,"NIR_PROFILE");
   unsigned stores=0;
   nir_foreach_function_impl(impl,n) nir_foreach_block(block,impl) nir_foreach_instr(instr,block) {
      if(instr->type!=nir_instr_type_intrinsic)continue;
      nir_intrinsic_instr *in=nir_instr_as_intrinsic(instr);
      if(in->intrinsic==nir_intrinsic_load_global_invocation_id)continue;
      if(in->intrinsic!=nir_intrinsic_store_ssbo||!nir_src_is_const(in->src[1])||
         nir_src_as_uint(in->src[1])!=0||in->src[0].ssa->bit_size!=32||in->num_components!=1||
         nir_intrinsic_write_mask(in)!=1||nir_intrinsic_align_mul(in)<4||
         (nir_intrinsic_align_offset(in)&3))
         return reject(owned,error,"RESOURCE_MAPPING");
      stores++;
   }
   if(stores!=1)return reject(owned,error,"RESOURCE_MAPPING");
   unsigned slot=l->slot;
   NIR_PASS(_,n,nir_shader_intrinsics_pass,map_store,nir_metadata_control_flow,&slot);
   nir_shader_gather_info(n,nir_shader_get_entrypoint(n));
   n->info.num_ssbos=slot+1;
   n->info.internal=false;
   n->options=a->screen->nir_options[MESA_SHADER_COMPUTE];
   nir_validate_shader(n,"CORE RadeonSI mapping");
   m->nir=NULL;
   core_module_destroy(owned);
   *out=n;
   return 0;
}
void *core_radeonsi_create_state(struct core_radeonsi *a,struct pipe_context *ctx,
                                struct core_module **m,const struct core_radeonsi_layout *l,char error[256])
{
   if(!a||!ctx||ctx->screen!=a->screen||!a->screen->finalize_nir||!ctx->create_compute_state) {
      reject(m,error,"CONTEXT");
      return NULL;
   }
   nir_shader *n=NULL;
   if(core_radeonsi_lower(a,m,l,&n,error))return NULL;
   a->screen->finalize_nir(a->screen,n,true);
   nir_validate_shader(n,"CORE RadeonSI finalized");
   struct pipe_compute_state state={.ir_type=PIPE_SHADER_IR_NIR,.prog=n};
   void *shader=ctx->create_compute_state(ctx,&state);
   if(!shader) {
      ralloc_free(n);
      if(error)snprintf(error,256,"RADEONSI_REJECT:COMPUTE_STATE");
   }
   return shader;
}
int core_radeonsi_check_view(const struct core_radeonsi *a,const struct core_radeonsi_layout *l,
                             unsigned slot,const struct pipe_shader_buffer *view,
                             const struct pipe_resource *expected,char error[256])
{
   if(error)error[0]=0;
   if(!a||!valid_layout(l)||slot!=l->slot||!view||!expected||!error||
      view->buffer!=expected||expected->screen!=a->screen||expected->target!=PIPE_BUFFER||!(expected->bind&PIPE_BIND_SHADER_BUFFER)||
      view->buffer_size!=4096||!a->screen->caps.shader_buffer_offset_alignment||
      view->buffer_offset%a->screen->caps.shader_buffer_offset_alignment||
      (view->buffer_offset&3)||
      (uint64_t)view->buffer_offset+view->buffer_size>expected->width0) {
      if(error)snprintf(error,256,"RADEONSI_REJECT:VIEW");
      return 1;
   }
   return 0;
}

int core_radeonsi_bind_view(const struct core_radeonsi *a,struct pipe_context *ctx,
                            const struct core_radeonsi_layout *l,const struct pipe_shader_buffer *v,
                            const struct pipe_resource *expected,char error[256])
{
   if(!a||!ctx||ctx->screen!=a->screen||!ctx->set_shader_buffers) {
      if(error)snprintf(error,256,"RADEONSI_REJECT:CONTEXT");
      return 1;
   }
   if(core_radeonsi_check_view(a,l,l?l->slot:0,v,expected,error))return 1;
   /* Gallium's mask indexes the supplied array, not absolute binding slots. */
   ctx->set_shader_buffers(ctx,MESA_SHADER_COMPUTE,l->slot,1,v,1);
   return 0;
}
