#include "program.h"
#include <unordered_set>
#include <memory>
#include "module.hpp"
#include "context.hpp"
#include "function.hpp"
#include "instruction.hpp"
#include "cast.hpp"
#include "type.hpp"
#include "thread_local_allocator.hpp"
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <unordered_map>
#include <vector>

namespace {
using namespace LLVMBC;
class reject : public std::runtime_error {
public:
    explicit reject(const char *s) : std::runtime_error(s) {}
};
void require(bool ok, const char *s) { if (!ok) throw reject(s); }
struct allocator_scope {
    allocator_scope() { dxil_spv::begin_thread_allocator_context(); }
    ~allocator_scope() { dxil_spv::end_thread_allocator_context(); }
};
uint32_t u32(const uint8_t *data, size_t size, size_t offset)
{
    require(offset <= size && size - offset >= 4, "CONTAINER_RANGE");
    return uint32_t(data[offset]) | uint32_t(data[offset+1]) << 8 |
           uint32_t(data[offset+2]) << 16 | uint32_t(data[offset+3]) << 24;
}
bool int_type(const Type *type, unsigned bits)
{
    const auto *i = dyn_cast<IntegerType>(type);
    return i && i->getBitWidth() == bits;
}
uint64_t integer(const Value *v, unsigned bits)
{
    const auto *c = dyn_cast<ConstantInt>(v);
    require(c && int_type(c->getType(), bits), "INTEGER_TYPE");
    return c->getUniqueInteger().getZExtValue();
}
MDNode *node(MDOperand &m, unsigned operands)
{
    auto *n = dyn_cast<MDNode>(&m);
    require(n && n->getNumOperands() == operands, "METADATA_SHAPE");
    return n;
}
uint64_t mdint(MDOperand &m, unsigned bits=32)
{
    auto *c = dyn_cast<ConstantAsMetadata>(&m);
    require(c, "METADATA_INTEGER");
    return integer(c->getValue(), bits);
}
bool mdstring(MDOperand &m, const char *value)
{
    auto *s = dyn_cast<MDString>(&m);
    return s && s->getString() == value;
}
MDNode *named(Module &m, const char *name, unsigned operands)
{
    auto *n = m.getNamedMetadata(name);
    require(n && n->getNumOperands() == 1, "METADATA_MISSING");
    return node(*n->getOperand(0), operands);
}

struct importer {
    ds_program &p;
    Function *fn = nullptr;
    const GlobalVariable *shared = nullptr;
    std::unordered_map<const Value *, uint32_t> values, pointers, handles;
    struct aggregate { bool cb; uint32_t value; };
    std::unordered_map<const Value *, aggregate> aggregates;
    std::unordered_set<const BasicBlock *> visited;

    uint32_t emit(unsigned op, unsigned bits=32, unsigned a=0, unsigned b=0,
                  unsigned c=0, unsigned literal=0)
    {
        require(p.count < DS_MAX_OPS, "INSTRUCTION_BUDGET");
        auto id=p.count++;
        p.instructions[id]={op,bits,a,b,c,literal};
        return id;
    }
    unsigned width(const Value *v)
    {
        auto *t=dyn_cast<IntegerType>(v->getType());
        require(t && (t->getBitWidth()==32 || t->getBitWidth()==1),"SCALAR_TYPE");
        return t->getBitWidth();
    }
    uint32_t value(const Value *v)
    {
        auto old=values.find(v);
        if (old!=values.end()) return old->second;
        if (isa<ConstantInt>(v)) {
            auto bits=width(v);
            auto id=emit(DS_CONST,bits,0,0,0,uint32_t(integer(v,bits)));
            values.emplace(v,id);
            return id;
        }
        throw reject("UNDEFINED_OR_UNSUPPORTED_VALUE");
    }
    uint32_t scalar(const Value *v) { require(width(v)==32,"SCALAR32"); return value(v); }
    bool unused(const Value *v)
    {
        for (auto &bb:*fn) for (auto &i:bb) {
            for (unsigned k=0;k<i.getNumOperands();k++) if (i.getOperand(k)==v) return false;
            if (auto *phi=dyn_cast<PHINode>(&i))
                for (unsigned k=0;k<phi->getNumIncomingValues();k++)
                    if (phi->getIncomingValue(k)==v) return false;
        }
        return true;
    }
    uint32_t ptr(const Value *v)
    {
        auto found=pointers.find(v);
        if (found!=pointers.end()) return found->second;
        auto *e=dyn_cast<ConstantExpr>(v);
        require(e && e->getOpcode()==Instruction::GetElementPtr &&
                e->getNumOperands()==3 && e->getOperand(0)==shared && shared &&
                integer(e->getOperand(1),32)==0,"SHARED_POINTER");
        require(integer(e->getOperand(2),32)<p.shared_bytes/4,"SHARED_CONSTANT_INDEX");
        return scalar(e->getOperand(2));
    }
    unsigned handle(const Value *v, bool cb=false)
    {
        auto it=handles.find(v);
        require(it!=handles.end() && (cb ? it->second==3 : it->second<p.uavs),"HANDLE_CLASS");
        return it->second;
    }
    void call(CallInst &c, bool body)
    {
        auto *f=c.getCalledFunction(); require(f,"INDIRECT_CALL");
        const auto &name=f->getName();
        auto arg=[&](unsigned k) { require(k<c.getNumArgOperands(),"CALL_ARITY"); return c.getArgOperand(k); };
        auto shape=[&](unsigned count,unsigned opcode) {
            require(c.getNumArgOperands()==count && integer(arg(0),32)==opcode,"CALL_SHAPE");
        };
        if (name=="dx.op.createHandle") {
            shape(5,57); require(!body,"DYNAMIC_HANDLE");
            unsigned cls=integer(arg(1),8), index=integer(arg(2),32);
            require(integer(arg(3),32)==index && integer(arg(4),1)==0,"HANDLE_BINDING");
            require((cls==1 && index<p.uavs) || (cls==2 && index==0),"HANDLE_PROFILE");
            handles.emplace(&c,cls==2 ? 3 : index);
        } else if (name=="dx.op.threadId.i32" || name=="dx.op.threadIdInGroup.i32" || name=="dx.op.groupId.i32") {
            unsigned op=name=="dx.op.threadId.i32" ? DS_TID : name=="dx.op.groupId.i32" ? DS_GROUP : DS_LOCAL;
            shape(2,op==DS_TID ? 93 : op==DS_GROUP ? 94 : 95);
            require(!body && int_type(c.getType(),32) && integer(arg(1),32)<3,"SYSTEM_VALUE");
            values[&c]=emit(op,32,0,0,0,integer(arg(1),32));
        } else if (name=="dx.op.cbufferLoadLegacy.i32") {
            shape(3,59); handle(arg(1),true);
            auto row=integer(arg(2),32); require(row<2,"PARAMETER_RANGE");
            aggregates.emplace(&c,aggregate{true,uint32_t(4*row)});
        } else if (name=="dx.op.bufferLoad.i32") {
            shape(4,68); auto slot=handle(arg(1));
            require(integer(arg(3),32)==0,"STRUCTURED_BYTE_OFFSET");
            auto id=emit(DS_LOAD,32,scalar(arg(2)),0,0,slot);
            aggregates.emplace(&c,aggregate{false,id}); p.reads[slot]++;
        } else if (name=="dx.op.bufferStore.i32") {
            shape(9,69); auto slot=handle(arg(1));
            require(integer(arg(3),32)==0 && integer(arg(8),8)==1,"STORE_SHAPE");
            for (unsigned k=5;k<8;k++) require(isa<UndefValue>(arg(k)),"STORE_UNUSED_LANE");
            auto index=scalar(arg(2)), data=scalar(arg(4));
            emit(DS_STORE,32,index,data,0,slot); p.writes[slot]++;
        } else if (name=="dx.op.atomicBinOp.i32") {
            shape(7,78); auto slot=handle(arg(1));
            require(integer(arg(2),32)==0 && integer(arg(4),32)==0 &&
                    isa<UndefValue>(arg(5)) && unused(&c),"GLOBAL_ATOMIC_PROFILE");
            auto index=scalar(arg(3)), data=scalar(arg(6));
            emit(DS_GLOBAL_ADD,32,index,data,0,slot); p.reads[slot]++; p.writes[slot]++;
        } else if (name=="dx.op.barrier") {
            shape(2,80); require(!body && integer(arg(1),32)==9,"BARRIER_CONVERGENCE_OR_MODE");
            emit(DS_BARRIER); p.barriers++;
        } else throw reject("UNSUPPORTED_DXIL_CALL");
    }
    void instruction(Instruction &in, bool body)
    {
        if (auto *c=dyn_cast<CallInst>(&in)) call(*c,body);
        else if (auto *e=dyn_cast<ExtractValueInst>(&in)) {
            require(int_type(e->getType(),32) && e->getNumIndices()==1,"EXTRACT_TYPE");
            auto it=aggregates.find(e->getAggregateOperand());
            require(it!=aggregates.end(),"EXTRACT_AGGREGATE");
            auto lane=e->getIndices()[0]; auto &a=it->second;
            if (a.cb) {
                require(lane<4,"PARAMETER_LANE"); auto word=a.value+lane;
                values[e]=emit(DS_PARAM,32,0,0,0,word); p.param_mask|=1u<<word;
            } else { require(lane==0,"BUFFER_LOAD_LANE"); values[e]=a.value; }
        } else if (auto *b=dyn_cast<BinaryOperator>(&in)) {
            auto bits=width(b); unsigned op;
            switch(b->getOpcode()) {
            case Instruction::Add:op=DS_ADD;break; case Instruction::Sub:op=DS_SUB;break;
            case Instruction::Mul:op=DS_MUL;break; case Instruction::And:op=DS_AND;break;
            case Instruction::Or:op=DS_OR;break; case Instruction::Xor:op=DS_XOR;break;
            case Instruction::Shl:op=DS_SHL;break; case Instruction::LShr:op=DS_USHR;break;
            default:throw reject("UNSUPPORTED_BINARY");
            }
            require(width(b->getOperand(0))==bits && width(b->getOperand(1))==bits &&
                    (bits==32 || op==DS_AND || op==DS_OR || op==DS_XOR),"BINARY_TYPES");
            auto a=value(b->getOperand(0)), rhs=value(b->getOperand(1));
            values[b]=emit(op,bits,a,rhs);
        } else if (auto *c=dyn_cast<ICmpInst>(&in)) {
            unsigned op;
            switch(c->getPredicate()) {
            case Instruction::ICMP_EQ:op=DS_EQ;break; case Instruction::ICMP_NE:op=DS_NE;break;
            case Instruction::ICMP_ULT:op=DS_ULT;break; case Instruction::ICMP_ULE:op=DS_ULE;break;
            case Instruction::ICMP_UGT:op=DS_UGT;break; case Instruction::ICMP_UGE:op=DS_UGE;break;
            default:throw reject("COMPARE_PROFILE");
            }
            auto a=scalar(c->getOperand(0)), b=scalar(c->getOperand(1)); values[c]=emit(op,1,a,b);
        } else if (auto *g=dyn_cast<GetElementPtrInst>(&in)) {
            require(shared && g->getNumOperands()==3 && g->getOperand(0)==shared &&
                    integer(g->getOperand(1),32)==0,"SHARED_GEP");
            pointers[g]=scalar(g->getOperand(2));
        } else if (auto *l=dyn_cast<LoadInst>(&in)) {
            require(int_type(l->getType(),32),"SHARED_LOAD_TYPE");
            values[l]=emit(DS_SHARED_LOAD,32,ptr(l->getPointerOperand()));
        } else if (auto *s=dyn_cast<StoreInst>(&in)) {
            auto index=ptr(s->getOperand(1)), data=scalar(s->getOperand(0));
            emit(DS_SHARED_STORE,32,index,data);
        } else if (auto *a=dyn_cast<AtomicRMWInst>(&in)) {
            require(a->getOperation()==AtomicRMWInst::BinOp::Add && unused(a),"SHARED_ATOMIC_PROFILE");
            auto index=ptr(a->getPointerOperand()), data=scalar(a->getValOperand());
            emit(DS_SHARED_ADD,32,index,data);
        } else throw reject("UNSUPPORTED_INSTRUCTION");
    }
    void parse(Module &m)
    {
        auto *sm=named(m,"dx.shaderModel",3);
        require(mdstring(sm->getOperand(0),"cs") && mdint(sm->getOperand(1))==6 &&
                mdint(sm->getOperand(2))==0,"STAGE_OR_MODEL");
        auto *ver=named(m,"dx.version",2);
        require(mdint(ver->getOperand(0))==1 && mdint(ver->getOperand(1))==0,"DXIL_VERSION");
        auto *ep=named(m,"dx.entryPoints",5); fn=m.getFunction("main");
        auto *epfn=dyn_cast<ConstantAsMetadata>(&ep->getOperand(0));
        require(fn && epfn && epfn->getValue()==fn && mdstring(ep->getOperand(1),"main") &&
                !ep->getOperand(2) && fn->arg_begin()==fn->arg_end(),"ENTRY_POINT");
        unsigned implementations=0;
        for (auto *f:m) { require(f==fn,"EXTRA_FUNCTION"); implementations++; }
        require(implementations==1,"ENTRY_COUNT");
        auto *resources=named(m,"dx.resources",4);
        require(&ep->getOperand(3)==resources && !resources->getOperand(0) &&
                !resources->getOperand(3),"RESOURCE_CLASSES");
        auto *uavs=dyn_cast<MDNode>(&resources->getOperand(1));
        require(uavs && uavs->getNumOperands()>=1 && uavs->getNumOperands()<=3,"UAV_COUNT");
        p.uavs=uavs->getNumOperands();
        for (unsigned i=0;i<p.uavs;i++) {
            auto *u=node(uavs->getOperand(i),11);
            require(mdint(u->getOperand(0))==i && mdint(u->getOperand(3))==0 &&
                    mdint(u->getOperand(4))==i && mdint(u->getOperand(5))==1 &&
                    mdint(u->getOperand(6))==12 && mdint(u->getOperand(7),1)==0 &&
                    mdint(u->getOperand(8),1)==0 && mdint(u->getOperand(9),1)==0,"RESOURCE_PROFILE");
            auto *stride=node(u->getOperand(10),2);
            require(mdint(stride->getOperand(0))==1 && mdint(stride->getOperand(1))==4,"STRUCTURED_STRIDE");
        }
        auto *cb=node(node(resources->getOperand(2),1)->getOperand(0),8);
        require(mdint(cb->getOperand(0))==0 && mdint(cb->getOperand(3))==0 &&
                mdint(cb->getOperand(4))==0 && mdint(cb->getOperand(5))==1 &&
                mdint(cb->getOperand(6))==32 && !cb->getOperand(7),"CBV_PROFILE");
        auto *props=node(ep->getOperand(4),4);
        require(mdint(props->getOperand(0))==0 && mdint(props->getOperand(1),64)==16 &&
                mdint(props->getOperand(2))==4,"SHADER_PROPERTIES");
        auto *group=node(props->getOperand(3),3);
        for(unsigned i=0;i<3;i++) p.local[i]=mdint(group->getOperand(i));
        require(((p.local[0]==8 && p.local[1]==8) || (p.local[0]==128 && p.local[1]==1)) && p.local[2]==1,"LOCAL_SIZE_PROFILE");
        for (auto it=m.global_begin();it!=m.global_end();++it) {
            auto &g=*it; auto *pt=dyn_cast<PointerType>(g.getType());
            require(!shared && pt && pt->getAddressSpace()==3 && !g.hasInitializer() && !g.isConstant(),"SHARED_GLOBAL");
            auto *array=dyn_cast<ArrayType>(pt->getElementType());
            require(array && int_type(array->getArrayElementType(),32) &&
                    (array->getArrayNumElements()==16 || array->getArrayNumElements()==64),"SHARED_ARRAY");
            shared=&g; p.shared_bytes=4*array->getArrayNumElements();
        }
        std::vector<BasicBlock *> blocks; for (auto &b:*fn) blocks.push_back(&b);
        require(!blocks.empty() && blocks.size()<=32,"CONTROL_FLOW_BUDGET");
        auto *current=blocks[0];
        while (true) {
            require(visited.insert(current).second,"CONTROL_FLOW_CYCLE");
            auto *term=current->getTerminator();
            for(auto &i:*current) if (&i!=term) {
                if (isa<PHINode>(&i)) require(values.count(&i),"UNSTRUCTURED_PHI");
                else instruction(i,false);
            }
            if(auto *ret=dyn_cast<ReturnInst>(term)) { require(!ret->getReturnValue(),"RETURN_VALUE"); break; }
            auto *br=dyn_cast<BranchInst>(term);
            require(br && br->isConditional(),"CONTROL_FLOW_PROFILE");
            auto *body=br->getSuccessor(0), *merge=br->getSuccessor(1);
            require(body!=merge && visited.insert(body).second,"CONTROL_FLOW_BODY");
            auto *end=dyn_cast<BranchInst>(body->getTerminator());
            require(end && !end->isConditional() && end->getSuccessor(0)==merge,"CONTROL_FLOW_DIAMOND");
            require(width(br->getCondition())==1,"CONDITION_TYPE"); emit(DS_IF,1,value(br->getCondition()));
            const auto root_values=values;
            const auto root_pointers=pointers;
            const auto root_aggregates=aggregates;
            for(auto &i:*body) if (&i!=end) instruction(i,true);
            emit(DS_ENDIF);
            for(auto &i:*merge) if(auto *phi=dyn_cast<PHINode>(&i)) {
                require(phi->getNumIncomingValues()==2,"PHI_ARITY");
                int yes=-1,no=-1;
                for(unsigned k=0;k<2;k++) {
                    if(phi->getIncomingBlock(k)==body) yes=k;
                    if(phi->getIncomingBlock(k)==current) no=k;
                }
                require(yes>=0 && no>=0,"PHI_PREDECESSORS");
                require(isa<ConstantInt>(phi->getIncomingValue(no)) ||
                        root_values.count(phi->getIncomingValue(no)),"PHI_BYPASS_DOMINANCE");
                auto a=value(phi->getIncomingValue(yes)), b=value(phi->getIncomingValue(no));
                require(width(phi->getIncomingValue(yes))==width(phi) && width(phi->getIncomingValue(no))==width(phi),"PHI_TYPES");
                values[phi]=emit(DS_PHI,width(phi),a,b);
            }
            /* Body definitions only escape through the merge's phis. Reject a
             * malformed cross-edge reference before constructing NIR. */
            for (auto it=values.begin();it!=values.end();) {
                if (root_values.count(it->first) || isa<ConstantInt>(it->first) || isa<PHINode>(it->first)) {
                    ++it;
                } else it=values.erase(it);
            }
            pointers=root_pointers; aggregates=root_aggregates;
            current=merge;
        }
        require(visited.size()==blocks.size(),"UNREACHABLE_OR_EXTRA_BLOCK");
        require(p.param_mask && p.reads[0] && (p.writes[1] || p.writes[2]),"REQUIRED_EFFECTS");
    }
};
}

extern "C" int ds_parse(const void *bytes, size_t size, ds_program *out, char error[256])
{
    if (out) *out={};
    if (!error) return 1;
    error[0]=0;
    try {
        require(bytes && out && size>=32 && size<=1024*1024,"CONTAINER_SIZE");
        const auto *p=static_cast<const uint8_t *>(bytes);
        require(!std::memcmp(p,"DXBC",4) && u32(p,size,20)==1 && u32(p,size,24)==size,"CONTAINER_HEADER");
        const auto count=u32(p,size,28);
        require(count && count<=32 && 32+4*count<=size,"CONTAINER_TABLE");
        std::vector<std::pair<size_t,size_t>> ranges;
        const uint8_t *bc=nullptr; size_t bc_size=0;
        for(unsigned i=0;i<count;i++) {
            const size_t o=u32(p,size,32+4*i), n=u32(p,size,o+4);
            require(o>=32+4*count && o%4==0 && o<=size && size-o>=8 && n<=size-o-8,"PART_RANGE");
            for(const auto &r:ranges) require(o+8+n<=r.first || r.second<=o,"PART_OVERLAP");
            ranges.emplace_back(o,o+8+n);
            if(std::memcmp(p+o,"DXIL",4)) continue;
            require(!bc && n>=24,"DXIL_PART"); const auto *h=p+o+8;
            require(u32(h,n,0)==0x00050060 && uint64_t(u32(h,n,4))*4==n &&
                    !std::memcmp(h+8,"DXIL",4) && u32(h,n,12)==0x100,"PROGRAM_HEADER");
            const size_t offset=8+uint64_t(u32(h,n,16)); bc_size=u32(h,n,20);
            require(offset>=24 && offset<=n && bc_size<=n-offset && bc_size>=4,"BITCODE_RANGE");
            bc=h+offset; require(!std::memcmp(bc,"BC\xc0\xde",4),"BITCODE_MAGIC");
        }
        require(bc,"DXIL_MISSING"); allocator_scope allocations; LLVMContext context;
        auto *module=parseIR(context,bc,bc_size); require(module,"BITCODE_PARSE");
        ds_program candidate{}; importer translation{candidate}; translation.parse(*module);
        *out=candidate; return 0;
    } catch(const std::exception &e) { std::snprintf(error,256,"DIRECT_REJECT:%s",e.what()); }
      catch(...) { std::snprintf(error,256,"DIRECT_REJECT:INTERNAL_EXCEPTION"); }
    return 1;
}

