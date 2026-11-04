#include "backend_radeonsi.h"
#include "../../include/ndx_evidence.h"
#include "core_internal.h"
#include "cpu_inspect.h"
#include "pipe/p_context.h"
#include "pipe/p_screen.h"
#include "pipe/p_state.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x,id) do {if (!(x)) {fprintf(stderr,"ASSERT:%s\n",id);exit(1);}} while(0)
static unsigned checks, finalize_calls, create_calls;
static nir_shader *retained;
static bool fail_create;
static const nir_shader_compiler_options options={0};
static const struct core_radeonsi_layout layout={1,0,CORE_UAV,0,0,CORE_COMPUTE,3};
static void pass(const char *name) {checks++;printf("PASS:%s\n",name);}
static struct pipe_screen screen_template(void)
{
   return (struct pipe_screen){.nir_options={[MESA_SHADER_COMPUTE]=&options},
      .shader_caps={[MESA_SHADER_COMPUTE]={.max_shader_buffers=4,.supported_irs=1<<PIPE_SHADER_IR_NIR}},
      .caps={.compute=1,.shader_buffer_offset_alignment=4},
      .compute_caps={.max_threads_per_block=1024,.max_block_size={1024,1024,1024}}};
}
static struct core_prepared *prepare(const char *path)
{
   FILE *f=fopen(path,"rb");CHECK(f,"INPUT");unsigned char data[65536];
   size_t n=fread(data,1,sizeof(data),f);CHECK(!ferror(f)&&feof(f),"INPUT_SIZE");fclose(f);
   struct core_prepared *p=NULL;char error[256];
   CHECK(!core_prepare(data,n,&p,error)&&p,"PREPARE");return p;
}
static struct core_module *emit(struct core_radeonsi *a,const struct core_prepared *p)
{
   struct core_module *m=NULL;char e[256];struct core_build_profile profile=core_radeonsi_profile(a);
   CHECK(!core_emit(p,&profile,&m,e)&&m,"EMIT");return m;
}
static void mapped(nir_shader *n)
{
   CHECK(n && n->options==&options,"OPTIONS_LIFETIME");
   CHECK(n->info.stage==MESA_SHADER_COMPUTE && n->info.num_ssbos==4,"MAPPED_COUNT");
   CHECK(n->info.workgroup_size[0]==64 && n->info.workgroup_size[1]==1 && n->info.workgroup_size[2]==1,"LOCAL_SIZE");
   unsigned count=0;
   nir_foreach_function_impl(impl,n) nir_foreach_block(b,impl) nir_foreach_instr(i,b) {
      if(i->type==nir_instr_type_intrinsic){nir_intrinsic_instr *in=nir_instr_as_intrinsic(i);
         if(in->intrinsic==nir_intrinsic_store_ssbo){
            CHECK(nir_src_is_const(in->src[1])&&nir_src_as_uint(in->src[1])==3,"MAPPED_SLOT_3");count++;
         }
      }
   }
   CHECK(count==1,"STORE_COUNT");
}
static void test_caps(void)
{
   struct pipe_screen s=screen_template();
   struct core_radeonsi *a=core_radeonsi_create(&s);CHECK(a,"SUPPORTED_SCREEN");core_radeonsi_destroy(&a);pass("caps-healthy");
   CHECK(!core_radeonsi_create(NULL),"CAP_NULL");pass("caps-null");
   const char *names[]={"caps-options","caps-buffers","caps-ir","caps-threads","caps-x","caps-y","caps-z","caps-alignment-zero","caps-callback-data","caps-compute"};
   for(unsigned i=0;i<10;i++){
      struct pipe_screen bad={.nir_options={[MESA_SHADER_COMPUTE]=&options},
         .shader_caps={[MESA_SHADER_COMPUTE]={.max_shader_buffers=i==1?3:4,
            .supported_irs=i==2?0:1<<PIPE_SHADER_IR_NIR}},
         .caps={.compute=i!=9,.shader_buffer_offset_alignment=i==7?0:4},
         .compute_caps={.max_threads_per_block=i==3?63:1024,
            .max_block_size={i==4?63:1024,i==5?0:1024,i==6?0:1024}}};
      nir_shader_compiler_options opt=options;
      switch(i){case 0:bad.nir_options[MESA_SHADER_COMPUTE]=NULL;break;
      case 1:break;
      case 2:break;
      case 3:case 4:case 5:case 6:case 7:case 9:break;
      case 8:opt.cb_data=&bad;bad.nir_options[MESA_SHADER_COMPUTE]=&opt;break;}
      CHECK(!core_radeonsi_create(&bad),names[i]);pass(names[i]);
   }
}
static void test_lower(struct core_radeonsi *a,struct core_prepared *p,struct pipe_screen *s)
{
   char e[256];struct core_module *m=emit(a,p);nir_shader *n=NULL;
   CHECK(!core_radeonsi_lower(a,&m,&layout,&n,e)&&!m&&n,"LOWER_HEALTHY");mapped(n);
   CHECK(core_live_modules()==0,"CONSUMED_MODULE");ralloc_free(n);pass("lower-healthy");
   struct core_radeonsi *other=core_radeonsi_create(s);CHECK(other,"OTHER");
   const char *ids[]={"owner","phase","version","id","class","space","register","stage","slot",
      "stride","access","array","workgroup","nir-stage","ssbo-count","shared-memory","variable-group","store-binding","store-alignment"};
   for(unsigned i=0;i<19;i++){
      m=emit(a,p);struct core_radeonsi_layout l=layout;
      const char *why=i<2?"OWNER_OR_PHASE":i<12?"LAYOUT":i<17?"NIR_PROFILE":"RESOURCE_MAPPING";
      switch(i){case 1:m->phase=CORE_N1_TARGET_BOUND;break;case 2:l.version++;break;case 3:l.resource_id++;break;
      case 4:l.resource_class=9;break;case 5:l.space++;break;case 6:l.reg++;break;case 7:l.stage=9;break;case 8:l.slot=0;break;
      case 9:m->resource.stride=8;break;case 10:m->resource.access=9;break;case 11:m->resource.array_count=2;break;
      case 12:m->nir->info.workgroup_size[0]=32;break;case 13:m->nir->info.stage=MESA_SHADER_VERTEX;break;
      case 14:m->nir->info.num_ssbos=2;break;case 15:m->nir->info.shared_size=4;break;case 16:m->nir->info.workgroup_size_variable=true;break;
      case 17:case 18:
         nir_foreach_function_impl(impl,m->nir) nir_foreach_block(b,impl) nir_foreach_instr(instr,b){
            if(instr->type==nir_instr_type_intrinsic){nir_intrinsic_instr *in=nir_instr_as_intrinsic(instr);
               if(in->intrinsic==nir_intrinsic_store_ssbo){
                  if(i==17)nir_instr_as_load_const(nir_def_instr(in->src[1].ssa))->value[0].u32=2;
                  else nir_intrinsic_set_align_offset(in,2);
               }
            }
         }break;
      }
      n=(nir_shader *)(uintptr_t)1;
      CHECK(core_radeonsi_lower(i==0?other:a,&m,&l,&n,e)!=0,ids[i]);
      char expected[256];snprintf(expected,sizeof(expected),"RADEONSI_REJECT:%s",why);
      CHECK(!m&&!n&&!strcmp(e,expected)&&core_live_modules()==0,ids[i]);pass(ids[i]);
   }
   m=emit(a,p);CHECK(core_radeonsi_lower(a,&m,NULL,&n,e)&&!m&&!n,"NULL_LAYOUT");pass("null-layout");
   m=emit(a,p);CHECK(core_radeonsi_lower(a,&m,&layout,NULL,e)&&!m,"NULL_OUT");pass("null-output");
   m=emit(a,p);CHECK(core_radeonsi_lower(a,&m,&layout,&n,NULL)&&!m&&!n,"NULL_ERROR");pass("null-error");
   core_radeonsi_destroy(&other);
}
static void test_view(struct core_radeonsi *a,struct pipe_screen *s)
{
   char e[256];struct pipe_resource buffer={.screen=s,.target=PIPE_BUFFER,.bind=PIPE_BIND_SHADER_BUFFER,.width0=4608};
   struct pipe_resource decoy=buffer;
   struct pipe_shader_buffer good={.buffer=&buffer,.buffer_offset=256,.buffer_size=4096};
   CHECK(!core_radeonsi_check_view(a,&layout,3,&good,&buffer,e),"VIEW_HEALTHY");pass("view-healthy");
   const char *ids[]={"view-slot","view-identity","view-size","view-align","view-end","view-overflow","view-target","view-bind","view-screen"};
   for(unsigned i=0;i<9;i++){
      struct pipe_shader_buffer v=good;struct pipe_resource b=buffer;v.buffer=&b;unsigned slot=3;
      switch(i){case 0:slot=0;break;case 1:v.buffer=&decoy;break;case 2:v.buffer_size=4092;break;
      case 3:v.buffer_offset=257;break;case 4:v.buffer_offset=516;break;case 5:v.buffer_offset=UINT32_MAX-3;break;
      case 6:b.target=PIPE_TEXTURE_2D;break;case 7:b.bind=0;break;case 8:b.screen=NULL;break;}
      CHECK(core_radeonsi_check_view(a,&layout,slot,&v,&b,e)&&!strcmp(e,"RADEONSI_REJECT:VIEW"),ids[i]);pass(ids[i]);
   }
   good.buffer_offset=512;CHECK(!core_radeonsi_check_view(a,&layout,3,&good,&buffer,e),"VIEW_EXACT_END");pass("view-exact-end");
}
static void fake_finalize(struct pipe_screen *s,nir_shader *n,bool optimize)
{
   CHECK(s && optimize && !core_live_modules(),"FINALIZE_CONTRACT");mapped(n);finalize_calls++;
}
static void *fake_create(struct pipe_context *c,const struct pipe_compute_state *state)
{
   CHECK(c && finalize_calls==create_calls+1,"FINALIZE_BEFORE_CREATE");
   CHECK(state->ir_type==PIPE_SHADER_IR_NIR && state->static_shared_mem==0,"COMPUTE_STATE_FIELDS");
   create_calls++;mapped((nir_shader *)state->prog);
   if(fail_create)return NULL;
   retained=(nir_shader *)state->prog;return &retained;
}
static void test_state(struct core_radeonsi *a,struct core_prepared *p,struct pipe_screen *s)
{
   s->finalize_nir=fake_finalize;
   struct pipe_context ctx={.screen=s,.create_compute_state=fake_create};char e[256];
   struct core_module *m=emit(a,p);
   CHECK(core_radeonsi_create_state(a,&ctx,&m,&layout,e)==&retained && !m,"STATE_HEALTHY");
   mapped(retained);ralloc_free(retained);retained=NULL;pass("state-healthy");
   fail_create=true;m=emit(a,p);CHECK(!core_radeonsi_create_state(a,&ctx,&m,&layout,e)&&!m&&
      !strcmp(e,"RADEONSI_REJECT:COMPUTE_STATE"),"STATE_ALLOC_FAILURE");pass("state-allocation-failure");fail_create=false;
   struct pipe_screen wrong=screen_template();
   for(unsigned i=0;i<4;i++){
      struct pipe_context c=ctx;s->finalize_nir=fake_finalize;
      if(i==0)c.screen=&wrong;
      if(i==1)c.create_compute_state=NULL;
      if(i==2)s->finalize_nir=NULL;
      unsigned before=create_calls;m=emit(a,p);
      CHECK(!core_radeonsi_create_state(a,i==3?NULL:&c,&m,&layout,e)&&!m&&create_calls==before&&
            !strcmp(e,"RADEONSI_REJECT:CONTEXT"),"STATE_BAD_CONTEXT");pass("state-context-reject");
   }
   s->finalize_nir=fake_finalize;
}
static unsigned bind_calls;
static const struct pipe_shader_buffer *binding;
static void fake_bind(struct pipe_context *ctx,mesa_shader_stage stage,unsigned slot,
                      unsigned count,const struct pipe_shader_buffer *views,unsigned mask)
{
   CHECK(ctx&&stage==MESA_SHADER_COMPUTE&&slot==3&&count==1,"BIND_STAGE_SLOT_COUNT");
   CHECK(mask==1,"BIND_RELATIVE_WRITE_MASK");
   CHECK(views==binding&&views->buffer_offset==256&&views->buffer_size==4096,"BIND_EXACT_VIEW");
   bind_calls++;
}
static void test_bind(struct core_radeonsi *a,struct pipe_screen *s)
{
   struct pipe_context ctx={.screen=s,.set_shader_buffers=fake_bind};
   struct pipe_resource buffer={.screen=s,.target=PIPE_BUFFER,.bind=PIPE_BIND_SHADER_BUFFER,.width0=4608};
   struct pipe_shader_buffer v={.buffer=&buffer,.buffer_offset=256,.buffer_size=4096};
   binding=&v;char e[256];
   CHECK(!core_radeonsi_bind_view(a,&ctx,&layout,&v,&buffer,e)&&bind_calls==1,"BIND_HEALTHY");pass("bind-healthy");
   v.buffer_offset=257;
   CHECK(core_radeonsi_bind_view(a,&ctx,&layout,&v,&buffer,e)&&bind_calls==1,"BIND_INVALID_VIEW");pass("bind-invalid-view");
   v.buffer_offset=256;struct pipe_screen wrong=screen_template();ctx.screen=&wrong;
   CHECK(core_radeonsi_bind_view(a,&ctx,&layout,&v,&buffer,e)&&bind_calls==1,"BIND_FOREIGN_CONTEXT");pass("bind-foreign-context");
   ctx.screen=s;ctx.set_shader_buffers=NULL;
   CHECK(core_radeonsi_bind_view(a,&ctx,&layout,&v,&buffer,e)&&bind_calls==1,"BIND_NO_CALLBACK");pass("bind-no-callback");
}
static void test_inspect(struct core_radeonsi *a,struct core_prepared *p,
                         FILE *nir_out,FILE *raw_out)
{
   struct core_module *m=emit(a,p);nir_shader *n=NULL;char error[256];
   CHECK(!core_radeonsi_lower(a,&m,&layout,&n,error)&&!m,"INSPECT_LOWER");mapped(n);
   uint32_t output[1088];unsigned stores=0;
   CHECK(!inspect_nir(n,output,&stores),"INSPECT_EXECUTION");
   FILE *f=nir_out;nir_print_shader(n,f);
   CHECK(!ferror(f)&&fflush(f)==0&&fsync(fileno(f))==0,"NIR_WRITE");
   CHECK(!ndx_evidence_write(raw_out,output,sizeof(output)),"RAW_WRITE");
   printf("STORES=%u EVALUATOR=CPU_ONLY LOGICAL_INVOCATIONS=1088\n",stores);
   ralloc_free(n);pass("inspect");
}
int main(int argc,char **argv)
{
   CHECK(argc==3||argc==5,"USAGE");
   struct ndx_evidence_file outputs[2]={{0}};
   if(!strcmp(argv[1],"inspect")){
      CHECK(argc==5,"INSPECT_USAGE");outputs[0].path=argv[3];outputs[1].path=argv[4];
      CHECK(!ndx_evidence_reserve(outputs,2),"OUTPUT_RESERVATION");
   }
   glsl_type_singleton_init_or_ref();
   struct pipe_screen screen=screen_template();struct core_radeonsi *a=core_radeonsi_create(&screen);CHECK(a,"ADAPTER");
   struct core_prepared *p=prepare(argv[2]);
   if(!strcmp(argv[1],"inspect")){CHECK(argc==5,"INSPECT_USAGE");test_inspect(a,p,outputs[0].stream,outputs[1].stream);CHECK(!ndx_evidence_close(outputs,2),"OUTPUT_CLOSE");}
   else if(!strcmp(argv[1],"caps"))test_caps();
   else if(!strcmp(argv[1],"lower"))test_lower(a,p,&screen);
   else if(!strcmp(argv[1],"view"))test_view(a,&screen);
   else if(!strcmp(argv[1],"bind"))test_bind(a,&screen);
   else if(!strcmp(argv[1],"state"))test_state(a,p,&screen);
   else CHECK(false,"GROUP");
   core_prepared_destroy(&p);core_radeonsi_destroy(&a);CHECK(!core_live_modules(),"MODULE_LEAK");
   glsl_type_singleton_decref();printf("CHECKS=%u GPU=NOT_RUN CALLBACKS=CPU_DOUBLES\n",checks);return 0;
}
