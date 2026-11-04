#include "prepared_shader.h"
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
    direct_program &program;
    std::unordered_map<const Value *, uint32_t> values;
    const CallInst *handle = nullptr;
    unsigned handles=0, tids=0, stores=0;

    uint32_t append(unsigned op, unsigned a=0, unsigned b=0, unsigned literal=0)
    {
        require(program.count < 256, "INSTRUCTION_BUDGET");
        const auto id = program.count++;
        program.instructions[id] = {op, a, b, literal};
        return id;
    }
    uint32_t value(const Value *v)
    {
        if (dyn_cast<ConstantInt>(v))
            return append(D_CONST, 0, 0, static_cast<uint32_t>(integer(v, 32)));
        const auto it = values.find(v);
        require(it != values.end(), "UNDEFINED_OR_UNSUPPORTED_VALUE");
        return it->second;
    }
    void instruction(Instruction &in, bool body)
    {
        if (auto *c = dyn_cast<CallInst>(&in)) {
            auto *f = c->getCalledFunction();
            require(f, "INDIRECT_CALL");
            const auto &name = f->getName();
            if (name == "dx.op.createHandle") {
                require(!body && c->getNumArgOperands() == 5, "HANDLE_SHAPE");
                require(integer(c->getArgOperand(0),32)==57 &&
                        integer(c->getArgOperand(1),8)==1 &&
                        integer(c->getArgOperand(2),32)==0 &&
                        integer(c->getArgOperand(3),32)==0 &&
                        integer(c->getArgOperand(4),1)==0, "HANDLE_BINDING");
                require(++handles == 1, "MULTIPLE_HANDLES");
                handle = c;
            } else if (name == "dx.op.threadId.i32") {
                require(!body && c->getNumArgOperands()==2 &&
                        integer(c->getArgOperand(0),32)==93 &&
                        integer(c->getArgOperand(1),32)==0 &&
                        int_type(c->getType(),32), "THREAD_ID");
                require(++tids == 1, "MULTIPLE_THREAD_IDS");
                values[c] = append(D_TID_X);
            } else if (name == "dx.op.bufferStore.i32") {
                require(body && c->getNumArgOperands()==9 &&
                        integer(c->getArgOperand(0),32)==69 &&
                        c->getArgOperand(1)==handle && handle &&
                        integer(c->getArgOperand(3),32)==0 &&
                        integer(c->getArgOperand(8),8)==1, "STORE_SHAPE");
                for (unsigned i=5;i<8;i++)
                    require(isa<UndefValue>(c->getArgOperand(i)), "STORE_UNUSED_LANE");
                require(++stores == 1, "MULTIPLE_STORES");
                const auto index=value(c->getArgOperand(2));
                const auto data=value(c->getArgOperand(4));
                append(D_STORE,index,data);
            } else throw reject("UNSUPPORTED_DXIL_CALL");
        } else if (auto *b = dyn_cast<BinaryOperator>(&in)) {
            require(int_type(b->getType(),32), "ARITHMETIC_TYPE");
            unsigned op;
            switch (b->getOpcode()) {
            case Instruction::Add: op=D_ADD; break;
            case Instruction::Mul: op=D_MUL; break;
            case Instruction::Xor: op=D_XOR; break;
            case Instruction::And: op=D_AND; break;
            case Instruction::Or: op=D_OR; break;
            default: throw reject("UNSUPPORTED_BINARY");
            }
            const auto a=value(b->getOperand(0));
            const auto rhs=value(b->getOperand(1));
            values[b]=append(op,a,rhs);
        } else if (auto *c = dyn_cast<ICmpInst>(&in)) {
            require(!body && c->getPredicate()==Instruction::ICMP_ULT &&
                    int_type(c->getOperand(0)->getType(),32) &&
                    int_type(c->getOperand(1)->getType(),32), "COMPARE_PROFILE");
            const auto a=value(c->getOperand(0));
            const auto rhs=value(c->getOperand(1));
            values[c]=append(D_ULT,a,rhs);
        } else throw reject("UNSUPPORTED_INSTRUCTION");
    }
    void parse(Module &m)
    {
        require(m.global_begin()==m.global_end(), "GLOBALS_UNSUPPORTED");
        auto *sm=named(m,"dx.shaderModel",3);
        require(mdstring(sm->getOperand(0),"cs") && mdint(sm->getOperand(1))==6 &&
                mdint(sm->getOperand(2))==0, "STAGE_OR_MODEL");
        auto *ver=named(m,"dx.version",2);
        require(mdint(ver->getOperand(0))==1 && mdint(ver->getOperand(1))==0,"DXIL_VERSION");
        auto *ep=named(m,"dx.entryPoints",5);
        auto *fn= m.getFunction("main");
        auto *epfn=dyn_cast<ConstantAsMetadata>(&ep->getOperand(0));
        require(fn && epfn && epfn->getValue()==fn && mdstring(ep->getOperand(1),"main") &&
                !ep->getOperand(2) && fn->arg_begin()==fn->arg_end(), "ENTRY_POINT");
        unsigned implementations=0;
        for (auto *f:m) { require(f==fn,"EXTRA_FUNCTION"); implementations++; }
        require(implementations==1,"ENTRY_COUNT");
        auto *resources=named(m,"dx.resources",4);
        require(&ep->getOperand(3)==resources, "ENTRY_RESOURCE_MISMATCH");
        require(!resources->getOperand(0) && !resources->getOperand(2) &&
                !resources->getOperand(3),"RESOURCE_CLASSES");
        auto *uavs=node(resources->getOperand(1),1);
        auto *u=node(uavs->getOperand(0),11);
        require(mdint(u->getOperand(0))==0 && mdint(u->getOperand(3))==0 &&
                mdint(u->getOperand(4))==0 && mdint(u->getOperand(5))==1 &&
                mdint(u->getOperand(6))==12 && mdint(u->getOperand(7),1)==0 &&
                mdint(u->getOperand(8),1)==0 && mdint(u->getOperand(9),1)==0,"RESOURCE_PROFILE");
        program.resource = {0, CORE_UAV,
            static_cast<uint32_t>(mdint(u->getOperand(3))),
            static_cast<uint32_t>(mdint(u->getOperand(4))),
            1, 4, CORE_WRITE, CORE_COMPUTE};
        auto *stride=node(u->getOperand(10),2);
        require(mdint(stride->getOperand(0))==1 && mdint(stride->getOperand(1))==4,"STRUCTURED_STRIDE");
        auto *props=node(ep->getOperand(4),4);
        require(mdint(props->getOperand(0))==0 && mdint(props->getOperand(1),64)==16 &&
                mdint(props->getOperand(2))==4,"SHADER_PROPERTIES");
        auto *group=node(props->getOperand(3),3);
        for (unsigned i=0;i<3;i++) program.local_size[i]=static_cast<uint32_t>(mdint(group->getOperand(i)));
        require(program.local_size[0]==64 && program.local_size[1]==1 &&
                program.local_size[2]==1,"LOCAL_SIZE_PROFILE");
        std::vector<BasicBlock *> blocks;
        for (auto &b:*fn) blocks.push_back(&b);
        require(blocks.size()==3,"CONTROL_FLOW_PROFILE");
        auto *entry=blocks[0]; auto *body=blocks[1]; auto *merge=blocks[2];
        auto *branch=dyn_cast<BranchInst>(entry->getTerminator());
        auto *end=dyn_cast<BranchInst>(body->getTerminator());
        auto *ret=dyn_cast<ReturnInst>(merge->getTerminator());
        require(branch && branch->isConditional() && branch->getSuccessor(0)==body &&
                branch->getSuccessor(1)==merge && end && !end->isConditional() &&
                end->getSuccessor(0)==merge && ret && !ret->getReturnValue(),"CONTROL_FLOW_PROFILE");
        for (auto &i:*entry) if (&i!=branch) instruction(i,false);
        require(int_type(branch->getCondition()->getType(),1),"CONDITION_TYPE");
        append(D_IF,value(branch->getCondition()));
        for (auto &i:*body) if (&i!=end) instruction(i,true);
        append(D_ENDIF);
        for (auto &i:*merge) require(&i==ret,"MERGE_INSTRUCTION");
        require(handles==1 && tids==1 && stores==1,"REQUIRED_EFFECTS");
    }
};
}

static int parse_program(const void *bytes, size_t size, direct_program *out, char error[256])
{
    try {
        require(bytes && out && size>=32 && size<=1024*1024,"CONTAINER_SIZE");
        const auto *p=static_cast<const uint8_t *>(bytes);
        require(!std::memcmp(p,"DXBC",4) && u32(p,size,20)==1 && u32(p,size,24)==size,"CONTAINER_HEADER");
        const auto count=u32(p,size,28);
        require(count && count<=32 && 32+4*count<=size,"CONTAINER_TABLE");
        std::vector<std::pair<size_t,size_t>> ranges;
        const uint8_t *bc=nullptr; size_t bc_size=0;
        for (unsigned i=0;i<count;i++) {
            const size_t o=u32(p,size,32+4*i), n=u32(p,size,o+4);
            require(o>=32+4*count && o%4==0 && o<=size && size-o>=8 && n<=size-o-8,"PART_RANGE");
            for (const auto &range:ranges)
                require(o+8+n<=range.first || range.second<=o,"PART_OVERLAP");
            ranges.emplace_back(o,o+8+n);
            if (std::memcmp(p+o,"DXIL",4)) continue;
            require(!bc && n>=24,"DXIL_PART");
            const auto *h=p+o+8;
            require(u32(h,n,0)==0x00050060 && u32(h,n,4)*uint64_t(4)==n &&
                    !std::memcmp(h+8,"DXIL",4) && u32(h,n,12)==0x100,"PROGRAM_HEADER");
            const size_t offset=8+uint64_t(u32(h,n,16));
            bc_size=u32(h,n,20);
            require(offset>=24 && offset<=n && bc_size<=n-offset && bc_size>=4,"BITCODE_RANGE");
            bc=h+offset;
            require(!std::memcmp(bc,"BC\xc0\xde",4),"BITCODE_MAGIC");
        }
        require(bc,"DXIL_MISSING");
        allocator_scope allocations;
        LLVMBC::LLVMContext context;
        auto *module=LLVMBC::parseIR(context,bc,bc_size);
        require(module,"BITCODE_PARSE");
        direct_program candidate{};
        importer translation{candidate, {}};
        translation.parse(*module);
        *out=candidate;
        return 0;
    } catch (const std::exception &e) {
        std::snprintf(error,256,"DIRECT_REJECT:%s",e.what());
        return 1;
    }
}

struct core_prepared {
    std::vector<uint8_t> source;
    direct_program program{};
};

extern "C" int core_prepare(const void *bytes, size_t size,
                             core_prepared **out, char error[256])
{
    if (out) *out = nullptr;
    if (!error) return 1;
    error[0] = 0;
    try {
        require(bytes && out && size >= 32 && size <= 1024*1024, "CONTAINER_SIZE");
        auto result = std::make_unique<core_prepared>();
        const auto *input = static_cast<const uint8_t *>(bytes);
        result->source.assign(input, input + size);
        if (parse_program(result->source.data(), size, &result->program, error)) return 1;
        *out = result.release();
        return 0;
    } catch (const std::exception &e) {
        std::snprintf(error, 256, "DIRECT_REJECT:%s", e.what());
        return 1;
    } catch (...) {
        std::snprintf(error, 256, "DIRECT_REJECT:INTERNAL_EXCEPTION");
        return 1;
    }
}
extern "C" const direct_program *core_prepared_program(const core_prepared *p)
{ return p ? &p->program : nullptr; }
extern "C" const uint8_t *core_prepared_source(const core_prepared *p, size_t *size)
{
    if (size) *size = p ? p->source.size() : 0;
    return p ? p->source.data() : nullptr;
}
extern "C" const char *core_prepared_profile(const core_prepared *p)
{ return p ? CORE_PROFILE : nullptr; }
extern "C" void core_prepared_destroy(core_prepared **p)
{
    if (!p) return;
    delete *p;
    *p = nullptr;
}
