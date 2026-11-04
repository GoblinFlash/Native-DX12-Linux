#define INITGUID
#include "ndx12.h"
#include "backend.h"
#include <algorithm>
#include <atomic>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <thread>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {
constexpr HRESULT unsupported_hr = static_cast<HRESULT>(0x887a0004u);
constexpr unsigned max_buffer = 64u * 1024u * 1024u;
constexpr unsigned descriptor_stride = 32;
std::atomic<UINT64> live_objects{0};
std::atomic<UINT64> next_handle{0x10000};
enum class Kind { device, resource, allocator, list, queue, fence, root, heap, pipeline };
struct Device;
struct Object {
    std::atomic<ULONG> refs{1};
    Device *owner;
    Kind kind;
    Object(Device *d, Kind k);
    virtual ~Object();
    Object(const Object &) = delete;
    Object &operator=(const Object &) = delete;
    virtual void *interface_ptr() = 0;
    ULONG add() { return ++refs; }
    ULONG release() { const ULONG n = --refs; if (!n) delete this; return n; }
};
template<class I> struct Box { I iface; Object *object; };
template<class I> Object *object(I *p) { return reinterpret_cast<Box<I> *>(p)->object; }
template<class I, class V, Kind K> struct Typed : Object {
    using Interface = I;
    using VTable = V;
    inline static V table{};
    Box<I> box;
    explicit Typed(Device *d) : Object(d, K), box{{&table}, this} {}
    void *interface_ptr() override { return &box.iface; }
};
template<class T> class Ref {
    T *p = nullptr;
public:
    Ref() = default;
    explicit Ref(T *v) : p(v) { if (p) p->add(); }
    Ref(const Ref &r) : Ref(r.p) {}
    Ref(Ref &&r) noexcept : p(std::exchange(r.p, nullptr)) {}
    ~Ref() { if (p) p->release(); }
    Ref &operator=(Ref r) noexcept { std::swap(p, r.p); return *this; }
    T *get() const { return p; }
    T *operator->() const { return p; }
    explicit operator bool() const { return p != nullptr; }
};
struct ApiError { HRESULT hr; };
void check(bool ok, HRESULT hr = E_INVALIDARG) { if (!ok) throw ApiError{hr}; }
template<class T, class I> T *as(I *p)
{
    check(p && static_cast<const void *>(p->lpVtbl) == &T::table);
    return static_cast<T *>(object(p));
}
bool iid_equal(REFIID a, REFIID b) { return std::memcmp(&a, &b, sizeof(IID)) == 0; }
struct Heap;
struct Resource;
struct Device : Typed<ID3D12Device, ID3D12DeviceVtbl, Kind::device> {
    ndx_backend *backend = nullptr;
    HRESULT error = S_OK;
    const std::thread::id thread = std::this_thread::get_id();
    unsigned queues = 0;
    std::vector<Heap *> heaps;
    std::vector<Resource *> resources;
    Ndx12Stats stats{1, 0x8086, 0x46a6, 0, 0, 0, 0, 0, 0};
    Ndx12GraphicsStats graphics{1, 0, 0, 0, 0};
    Ndx12PresentStats present{1, 0, 0, 0, 0, 0, 0};
    Device() : Typed(nullptr) {}
    ~Device() override { ndx_backend_destroy(backend); }
};
Object::Object(Device *d, Kind k) : owner(d), kind(k) { ++live_objects; if (owner) owner->add(); }
Object::~Object() { --live_objects; if (owner) owner->release(); }
Device *device_of(Object *o) { return o->kind == Kind::device ? static_cast<Device *>(o) : o->owner; }
void check_thread(Object *o) { check(device_of(o)->thread == std::this_thread::get_id(), E_NOTIMPL); }
void latch(Object *o, HRESULT hr) { auto *d = device_of(o); if (SUCCEEDED(d->error)) d->error = hr; }
template<class R> R failure(Object *o, HRESULT hr)
{
    if constexpr (std::is_same_v<R, HRESULT>) return hr;
    else { latch(o, hr); if constexpr (!std::is_void_v<R>) return R{}; }
}
template<auto F> struct protected_call;
template<class R, class I, class... A, R (*F)(I *, A...)>
struct protected_call<F> {
    static R call(I *self, A... args) noexcept {
        try { check_thread(object(self)); return F(self, args...); }
        catch (const ApiError &e) { return failure<R>(object(self), e.hr); }
        catch (const std::bad_alloc &) { return failure<R>(object(self), E_OUTOFMEMORY); }
        catch (...) { return failure<R>(object(self), E_FAIL); }
    }
};
template<class F> struct unsupported;
template<class R, class I, class... A>
struct unsupported<R (*)(I *, A...)> {
    static R call(I *self, A...) noexcept { return failure<R>(object(self), E_NOTIMPL); }
};
template<class V> V defaults();
#include "vtables.inc"

struct Resource : Typed<ID3D12Resource, ID3D12ResourceVtbl, Kind::resource> {
    D3D12_RESOURCE_DESC desc{};
    D3D12_HEAP_PROPERTIES heap{};
    D3D12_RESOURCE_STATES state{};
    void *buffer = nullptr;
    void *transfer = nullptr;
    bool presentable = false, exported = false, present_busy = false, present_ready = false;
    Resource(Device *d) : Typed(d) {}
    ~Resource() override {
        auto &v = owner->resources; v.erase(std::remove(v.begin(), v.end(), this), v.end());
        if (transfer) ndx_buffer_unmap(owner->backend, transfer);
        if (buffer) {
            if (presentable) ++owner->present.destroyed;
            ndx_buffer_destroy(buffer);
            if (desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER) --owner->stats.live_buffers;
            else if (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) --owner->graphics.live_render_targets;
        }
    }
};
struct Allocator : Typed<ID3D12CommandAllocator, ID3D12CommandAllocatorVtbl, Kind::allocator> {
    UINT64 generation = 0;
    bool recording = false;
    D3D12_COMMAND_LIST_TYPE type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    explicit Allocator(Device *d) : Typed(d) {}
};
struct Root : Typed<ID3D12RootSignature, ID3D12RootSignatureVtbl, Kind::root> {
    unsigned space = 0, reg = 0;
    bool graphics_empty = false;
    bool graphics_texture = false;
    ndx_texture_bindings texture{};
    explicit Root(Device *d) : Typed(d) {}
};
struct Pipeline : Typed<ID3D12PipelineState, ID3D12PipelineStateVtbl, Kind::pipeline> {
    Ref<Root> root;
    void *shader = nullptr;
    bool graphics = false;
    bool depth_target = false;
    explicit Pipeline(Device *d) : Typed(d) {}
    ~Pipeline() override {
        if (shader) {
            if (graphics) ndx_graphics_destroy(owner->backend, shader);
            else ndx_shader_destroy(owner->backend, shader);
        }
    }
};
enum class DescriptorKind { empty, uav, srv, rtv, sampler, dsv };
struct Descriptor {
    Ref<Resource> resource;
    unsigned offset = 0, bytes = 0;
    DescriptorKind kind = DescriptorKind::empty;
    bool repeat_u = false, repeat_v = false;
};
struct Heap : Typed<ID3D12DescriptorHeap, ID3D12DescriptorHeapVtbl, Kind::heap> {
    D3D12_DESCRIPTOR_HEAP_DESC desc{};
    UINT64 start = 0;
    std::vector<Descriptor> descriptors;
    explicit Heap(Device *d) : Typed(d) {}
    ~Heap() override { auto &v = owner->heaps; v.erase(std::remove(v.begin(), v.end(), this), v.end()); }
};
enum class Op { copy, transition, barrier, dispatch, clear, clear_depth, draw, texture_copy };
struct Command {
    Op op{};
    Ref<Resource> src, dst;
    unsigned src_offset = 0, dst_offset = 0, bytes = 0, groups = 0;
    D3D12_RESOURCE_STATES before{}, after{};
    Ref<Pipeline> pipeline;
    Ref<Heap> heap;
    UINT64 handle = 0;
    Ref<Heap> sampler_heap;
    UINT64 sampler_handle = 0;
    unsigned vertices = 0;
    Ref<Resource> depth, index, constants;
    unsigned constants_offset = 0;
    unsigned index_size = 0, index_offset = 0, first_index = 0;
    int base_vertex = 0;
    float clear_depth = 0;
    bool upload = false;
    std::array<float, 6> viewport{};
    std::array<unsigned, 4> scissor{};
    std::array<float, 4> color{};
};
struct List : Typed<ID3D12GraphicsCommandList, ID3D12GraphicsCommandListVtbl, Kind::list> {
    Ref<Allocator> allocator;
    Ref<Pipeline> pipeline;
    Ref<Root> root;
    Ref<Root> graphics_root;
    Ref<Resource> target;
    Ref<Resource> depth, index, constants;
    unsigned constants_offset = 0;
    unsigned index_size = 0, index_offset = 0, index_bytes = 0;
    Ref<Heap> heap;
    Ref<Heap> sampler_heap;
    UINT64 graphics_handle = 0, sampler_handle = 0;
    UINT64 handle = 0, generation = 0;
    bool closed = true;
    HRESULT error = S_OK;
    D3D12_COMMAND_LIST_TYPE type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    std::array<float, 6> viewport{};
    std::array<unsigned, 4> scissor{};
    bool have_viewport = false, have_scissor = false, triangles = false;
    std::vector<Command> commands;
    explicit List(Device *d) : Typed(d) {}
    ~List() override { if (!closed && allocator) allocator->recording = false; }
};
struct Queue : Typed<ID3D12CommandQueue, ID3D12CommandQueueVtbl, Kind::queue> {
    D3D12_COMMAND_QUEUE_DESC desc{};
    explicit Queue(Device *d) : Typed(d) { ++d->queues; }
    ~Queue() override { --owner->queues; }
};
struct Fence : Typed<ID3D12Fence, ID3D12FenceVtbl, Kind::fence> {
    UINT64 completed = 0, pending = 0;
    void *hardware = nullptr;
    explicit Fence(Device *d) : Typed(d) {}
    ~Fence() override { if (hardware) ndx_fence_destroy(owner->backend, hardware); }
};
const IID &own_iid(Kind k)
{
    switch (k) {
    case Kind::device: return IID_ID3D12Device;
    case Kind::resource: return IID_ID3D12Resource;
    case Kind::allocator: return IID_ID3D12CommandAllocator;
    case Kind::list: return IID_ID3D12GraphicsCommandList;
    case Kind::queue: return IID_ID3D12CommandQueue;
    case Kind::fence: return IID_ID3D12Fence;
    case Kind::root: return IID_ID3D12RootSignature;
    case Kind::heap: return IID_ID3D12DescriptorHeap;
    case Kind::pipeline: return IID_ID3D12PipelineState;
    }
    return IID_IUnknown;
}
template<class I> HRESULT query(I *self, REFIID iid, void **out)
{
    check(out, E_POINTER); *out = nullptr;
    Object *o = object(self);
    const bool child = o->kind != Kind::device;
    const bool pageable = child && o->kind != Kind::root && o->kind != Kind::list;
    check(iid_equal(iid, own_iid(o->kind)) || iid_equal(iid, IID_IUnknown) ||
          iid_equal(iid, IID_ID3D12Object) || (child && iid_equal(iid, IID_ID3D12DeviceChild)) ||
          (pageable && iid_equal(iid, IID_ID3D12Pageable)) ||
          (o->kind == Kind::list && iid_equal(iid, IID_ID3D12CommandList)), E_NOINTERFACE);
    o->add(); *out = o->interface_ptr(); return S_OK;
}
template<class I> ULONG add_ref(I *self) { return object(self)->add(); }
template<class I> ULONG release(I *self) { return object(self)->release(); }
template<class I> HRESULT get_device(I *self, REFIID iid, void **out)
{
    return query(&object(self)->owner->box.iface, iid, out);
}
template<class T> void output_for(REFIID iid, const IID &wanted, void **out)
{
    check(out, E_POINTER); *out = nullptr; check(iid_equal(iid, wanted), E_NOINTERFACE);
}
template<class T> HRESULT publish(std::unique_ptr<T> value, void **out)
{
    *out = value->interface_ptr(); value.release(); return S_OK;
}
template<class T, class I> T *owned(Device *d, I *i) { T *p = as<T>(i); check(p->owner == d); return p; }
bool range(UINT64 offset, UINT64 bytes, UINT64 size) { return offset <= size && bytes <= size - offset; }
bool valid_state(D3D12_RESOURCE_STATES s)
{
    return s == D3D12_RESOURCE_STATE_COPY_DEST || s == D3D12_RESOURCE_STATE_COPY_SOURCE ||
           s == D3D12_RESOURCE_STATE_UNORDERED_ACCESS || s == D3D12_RESOURCE_STATE_RENDER_TARGET ||
           s == D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE || s == D3D12_RESOURCE_STATE_INDEX_BUFFER ||
           s == D3D12_RESOURCE_STATE_DEPTH_WRITE;
}
bool state_for(const D3D12_RESOURCE_DESC &desc, D3D12_RESOURCE_STATES state)
{
    return valid_state(state) &&
        (state != D3D12_RESOURCE_STATE_UNORDERED_ACCESS ||
         (desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER && (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS))) &&
        (state != D3D12_RESOURCE_STATE_RENDER_TARGET ||
         (desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET))) &&
        (state != D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE || desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM) &&
        (state != D3D12_RESOURCE_STATE_INDEX_BUFFER || desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER) &&
        (state != D3D12_RESOURCE_STATE_DEPTH_WRITE || (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL));
}
HRESULT create_resource(ID3D12Device *self, const D3D12_HEAP_PROPERTIES *heap,
                        D3D12_HEAP_FLAGS flags, const D3D12_RESOURCE_DESC *desc,
                        D3D12_RESOURCE_STATES initial, const D3D12_CLEAR_VALUE *clear,
                        REFIID iid, void **out)
{
    output_for<Resource>(iid, IID_ID3D12Resource, out);
    auto *d = as<Device>(self);
    check(heap && desc && flags == D3D12_HEAP_FLAG_NONE);
    const bool texture = desc->Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    if (texture) {
        check(desc->Width && desc->Width <= 4096 && desc->Height && desc->Height <= 4096 &&
              desc->DepthOrArraySize == 1 && desc->MipLevels == 1 &&
              desc->SampleDesc.Count == 1 &&
              !desc->SampleDesc.Quality && desc->Layout == D3D12_TEXTURE_LAYOUT_UNKNOWN &&
              (desc->Alignment == 0 || desc->Alignment == 65536) &&
              ((desc->Format == DXGI_FORMAT_R8G8B8A8_UNORM &&
                (desc->Flags == D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET || desc->Flags == D3D12_RESOURCE_FLAG_NONE)) ||
               (desc->Format == DXGI_FORMAT_D32_FLOAT && desc->Flags == D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL)) &&
              heap->Type == D3D12_HEAP_TYPE_DEFAULT);
        check(!clear || (desc->Flags != D3D12_RESOURCE_FLAG_NONE && clear->Format == desc->Format));
        if (clear && desc->Format == DXGI_FORMAT_D32_FLOAT)
            check(std::isfinite(clear->DepthStencil.Depth) && clear->DepthStencil.Depth >= 0 &&
                  clear->DepthStencil.Depth <= 1 && !clear->DepthStencil.Stencil);
    } else {
      check(!clear && desc->Dimension == D3D12_RESOURCE_DIMENSION_BUFFER && desc->Width &&
          desc->Width <= max_buffer && desc->Height == 1 && desc->DepthOrArraySize == 1 &&
          desc->MipLevels == 1 && desc->Format == DXGI_FORMAT_UNKNOWN &&
          desc->SampleDesc.Count == 1 && desc->SampleDesc.Quality == 0 &&
          desc->Layout == D3D12_TEXTURE_LAYOUT_ROW_MAJOR &&
          (desc->Alignment == 0 || desc->Alignment == 65536) &&
          (desc->Flags == D3D12_RESOURCE_FLAG_NONE || desc->Flags == D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS));
    }
    check(heap->CPUPageProperty == D3D12_CPU_PAGE_PROPERTY_UNKNOWN &&
          heap->MemoryPoolPreference == D3D12_MEMORY_POOL_UNKNOWN &&
          heap->CreationNodeMask <= 1 && heap->VisibleNodeMask <= 1);
    check((heap->Type == D3D12_HEAP_TYPE_UPLOAD && initial == D3D12_RESOURCE_STATE_GENERIC_READ && !desc->Flags) ||
          (heap->Type == D3D12_HEAP_TYPE_READBACK && initial == D3D12_RESOURCE_STATE_COPY_DEST && !desc->Flags) ||
          (heap->Type == D3D12_HEAP_TYPE_DEFAULT && state_for(*desc, initial)));
    check(initial != D3D12_RESOURCE_STATE_UNORDERED_ACCESS ||
          (desc->Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS));
    auto r = std::make_unique<Resource>(d);
    r->desc = *desc; r->heap = *heap; r->state = initial;
    r->buffer = texture ? (desc->Format == DXGI_FORMAT_D32_FLOAT ?
                 ndx_depth_create(d->backend, static_cast<unsigned>(desc->Width), desc->Height) :
                 ndx_texture_create(d->backend, static_cast<unsigned>(desc->Width), desc->Height)) :
                 ndx_buffer_create(d->backend, static_cast<unsigned>(desc->Width),
                                 heap->Type == D3D12_HEAP_TYPE_READBACK ? 1 :
                                 heap->Type == D3D12_HEAP_TYPE_UPLOAD ? 2 : 0);
    check(r->buffer, E_OUTOFMEMORY);
    if (!texture) ++d->stats.live_buffers;
    else if (desc->Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ++d->graphics.live_render_targets;
    d->resources.push_back(r.get());
    return publish(std::move(r), out);
}
HRESULT resource_map(ID3D12Resource *self, UINT subresource, const D3D12_RANGE *read, void **out)
{
    check(out, E_POINTER); *out = nullptr;
    auto *r = as<Resource>(self);
    check(!subresource && !r->transfer && r->heap.Type != D3D12_HEAP_TYPE_DEFAULT);
    check(!read || (read->Begin <= read->End && read->End <= r->desc.Width));
    *out = ndx_buffer_map(r->owner->backend, r->buffer, static_cast<unsigned>(r->desc.Width),
                          r->heap.Type == D3D12_HEAP_TYPE_READBACK, &r->transfer);
    check(*out, E_FAIL); ++r->owner->present.cpu_maps; return S_OK;
}
void resource_unmap(ID3D12Resource *self, UINT subresource, const D3D12_RANGE *written)
{
    auto *r = as<Resource>(self);
    check(!subresource && r->transfer && (!written ||
          (written->Begin <= written->End && written->End <= r->desc.Width)));
    ndx_buffer_unmap(r->owner->backend, r->transfer); r->transfer = nullptr;
}
D3D12_RESOURCE_DESC resource_desc(ID3D12Resource *self) { return as<Resource>(self)->desc; }
D3D12_GPU_VIRTUAL_ADDRESS resource_address(ID3D12Resource *self)
{
    auto *r = as<Resource>(self);
    return r->desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER ? ndx_buffer_address(r->owner->backend, r->buffer) : 0;
}
HRESULT heap_properties(ID3D12Resource *self, D3D12_HEAP_PROPERTIES *p, D3D12_HEAP_FLAGS *f)
{
    if (p) *p = as<Resource>(self)->heap;
    if (f) *f = D3D12_HEAP_FLAG_NONE;
    return S_OK;
}
HRESULT create_allocator(ID3D12Device *self, D3D12_COMMAND_LIST_TYPE type, REFIID iid, void **out)
{
    output_for<Allocator>(iid, IID_ID3D12CommandAllocator, out);
    check(type == D3D12_COMMAND_LIST_TYPE_COMPUTE || type == D3D12_COMMAND_LIST_TYPE_DIRECT);
    auto a = std::make_unique<Allocator>(as<Device>(self)); a->type = type;
    return publish(std::move(a), out);
}
HRESULT allocator_reset(ID3D12CommandAllocator *self)
{
    auto *a = as<Allocator>(self); check(!a->recording, E_FAIL); ++a->generation; return S_OK;
}
HRESULT list_reset(ID3D12GraphicsCommandList *self, ID3D12CommandAllocator *allocator, ID3D12PipelineState *pso)
{
    auto *l = as<List>(self); auto *a = owned<Allocator>(l->owner, allocator);
    check(l->closed && !a->recording && l->type == a->type, E_FAIL);
    Pipeline *p = pso ? owned<Pipeline>(l->owner, pso) : nullptr;
    check(!p || !p->graphics || l->type == D3D12_COMMAND_LIST_TYPE_DIRECT);
    l->commands.clear(); l->root = {}; l->heap = {}; l->handle = 0;
    l->sampler_heap = {}; l->graphics_handle = l->sampler_handle = 0;
    l->graphics_root = {}; l->target = {}; l->have_viewport = l->have_scissor = l->triangles = false;
    l->constants = {}; l->constants_offset = 0;
    l->depth = {}; l->index = {}; l->index_size = l->index_offset = l->index_bytes = 0;
    l->pipeline = Ref<Pipeline>(p); l->allocator = Ref<Allocator>(a);
    l->generation = a->generation; l->error = S_OK; l->closed = false; a->recording = true;
    return S_OK;
}
HRESULT create_list(ID3D12Device *self, UINT node, D3D12_COMMAND_LIST_TYPE type,
                    ID3D12CommandAllocator *allocator, ID3D12PipelineState *pso, REFIID iid, void **out)
{
    output_for<List>(iid, IID_ID3D12GraphicsCommandList, out);
    check(!node && (type == D3D12_COMMAND_LIST_TYPE_COMPUTE || type == D3D12_COMMAND_LIST_TYPE_DIRECT));
    auto l = std::make_unique<List>(as<Device>(self));
    l->type = type;
    check(SUCCEEDED(list_reset(&l->box.iface, allocator, pso)), E_FAIL);
    return publish(std::move(l), out);
}
HRESULT close_list(ID3D12GraphicsCommandList *self)
{
    auto *l = as<List>(self); check(!l->closed, E_FAIL);
    l->closed = true; l->allocator->recording = false;
    return FAILED(l->owner->error) ? l->owner->error : l->error;
}
List *recording(ID3D12GraphicsCommandList *self)
{
    auto *l = as<List>(self);
    check(!l->closed && l->allocator->generation == l->generation && SUCCEEDED(l->owner->error), E_FAIL);
    return l;
}
void copy_buffer(ID3D12GraphicsCommandList *self, ID3D12Resource *dst, UINT64 dst_offset,
                 ID3D12Resource *src, UINT64 src_offset, UINT64 bytes)
{
    auto *l = recording(self); auto *s = owned<Resource>(l->owner, src); auto *d = owned<Resource>(l->owner, dst);
    check(s->desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER && d->desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER &&
          s != d && bytes && range(src_offset, bytes, s->desc.Width) && range(dst_offset, bytes, d->desc.Width));
    Command c; c.op = Op::copy; c.src = Ref<Resource>(s); c.dst = Ref<Resource>(d);
    c.src_offset = static_cast<unsigned>(src_offset); c.dst_offset = static_cast<unsigned>(dst_offset);
    c.bytes = static_cast<unsigned>(bytes); l->commands.push_back(std::move(c));
}
void barriers(ID3D12GraphicsCommandList *self, UINT count, const D3D12_RESOURCE_BARRIER *barriers)
{
    auto *l = recording(self); check(count <= 64 && (!count || barriers));
    for (UINT i = 0; i < count; ++i) {
        const auto &b = barriers[i]; check(b.Flags == D3D12_RESOURCE_BARRIER_FLAG_NONE);
        Command c;
        if (b.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION) {
            auto *r = owned<Resource>(l->owner, b.Transition.pResource);
            auto allowed = [&](D3D12_RESOURCE_STATES s) {
                return (r->presentable && r->exported && s == D3D12_RESOURCE_STATE_PRESENT) || state_for(r->desc, s);
            };
            check(r->heap.Type == D3D12_HEAP_TYPE_DEFAULT &&
                  b.Transition.Subresource == D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES &&
                  allowed(b.Transition.StateBefore) && allowed(b.Transition.StateAfter));
            check(l->type == D3D12_COMMAND_LIST_TYPE_DIRECT || r->desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER);
            check((b.Transition.StateBefore != D3D12_RESOURCE_STATE_UNORDERED_ACCESS &&
                   b.Transition.StateAfter != D3D12_RESOURCE_STATE_UNORDERED_ACCESS) ||
                  (r->desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS));
            c.op = Op::transition; c.dst = Ref<Resource>(r);
            c.before = b.Transition.StateBefore; c.after = b.Transition.StateAfter;
        } else {
            check(b.Type == D3D12_RESOURCE_BARRIER_TYPE_UAV);
            c.op = Op::barrier;
            if (b.UAV.pResource) c.dst = Ref<Resource>(owned<Resource>(l->owner, b.UAV.pResource));
        }
        l->commands.push_back(std::move(c));
    }
}
void set_pipeline(ID3D12GraphicsCommandList *self, ID3D12PipelineState *p)
{
    auto *l = recording(self); auto *pipeline = owned<Pipeline>(l->owner, p);
    check(!pipeline->graphics || l->type == D3D12_COMMAND_LIST_TYPE_DIRECT);
    l->pipeline = Ref<Pipeline>(pipeline);
}
void set_root(ID3D12GraphicsCommandList *self, ID3D12RootSignature *p)
{
    auto *l = recording(self); auto *r = owned<Root>(l->owner, p);
    if (l->root.get() != r) l->handle = 0;
    l->root = Ref<Root>(r);
}
void set_heaps(ID3D12GraphicsCommandList *self, UINT count, ID3D12DescriptorHeap *const *heaps)
{
    auto *l = recording(self); check(count <= 2 && (!count || heaps));
    Ref<Heap> resources, samplers;
    for (UINT i = 0; i < count; ++i) {
        auto *h = owned<Heap>(l->owner, heaps[i]);
        check(h->desc.Flags == D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE);
        if (h->desc.Type == D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV) {
            check(!resources); resources = Ref<Heap>(h);
        } else {
            check(h->desc.Type == D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER && !samplers); samplers = Ref<Heap>(h);
        }
    }
    if (l->heap.get() != resources.get()) l->handle = l->graphics_handle = 0;
    if (l->sampler_heap.get() != samplers.get()) l->sampler_handle = 0;
    l->heap = std::move(resources); l->sampler_heap = std::move(samplers);
}
Descriptor &descriptor(Heap *h, UINT64 handle)
{
    check(handle >= h->start && (handle - h->start) % descriptor_stride == 0);
    const UINT64 n = (handle - h->start) / descriptor_stride;
    check(n < h->descriptors.size()); return h->descriptors[static_cast<size_t>(n)];
}
void set_table(ID3D12GraphicsCommandList *self, UINT index, D3D12_GPU_DESCRIPTOR_HANDLE handle)
{
    auto *l = recording(self); check(index == 0 && l->heap && l->root);
    descriptor(l->heap.get(), handle.ptr); l->handle = handle.ptr;
}
void dispatch(ID3D12GraphicsCommandList *self, UINT x, UINT y, UINT z)
{
    auto *l = recording(self);
    check(l->pipeline && !l->pipeline->graphics && l->root && l->heap && l->handle &&
          l->pipeline->root.get() == l->root.get() && x >= 1 && x <= 16 && y == 1 && z == 1);
    Command c; c.op = Op::dispatch; c.pipeline = l->pipeline; c.heap = l->heap; c.handle = l->handle; c.groups = x;
    l->commands.push_back(std::move(c));
}
HRESULT create_queue(ID3D12Device *self, const D3D12_COMMAND_QUEUE_DESC *desc, REFIID iid, void **out)
{
    output_for<Queue>(iid, IID_ID3D12CommandQueue, out);
    auto *d = as<Device>(self);
    check(desc && (desc->Type == D3D12_COMMAND_LIST_TYPE_COMPUTE || desc->Type == D3D12_COMMAND_LIST_TYPE_DIRECT) && desc->Priority == 0 &&
          desc->Flags == D3D12_COMMAND_QUEUE_FLAG_NONE && !desc->NodeMask && !d->queues);
    auto q = std::make_unique<Queue>(d); q->desc = *desc; return publish(std::move(q), out);
}
D3D12_COMMAND_QUEUE_DESC queue_desc(ID3D12CommandQueue *self) { return as<Queue>(self)->desc; }
void execute(ID3D12CommandQueue *self, UINT count, ID3D12CommandList *const *lists)
{
    auto *d = as<Queue>(self)->owner;
    check(count && count <= 16 && lists && SUCCEEDED(d->error));
    std::unordered_map<Resource *, D3D12_RESOURCE_STATES> states;
    auto state = [&](Resource *r) -> D3D12_RESOURCE_STATES & {
        check(!r->present_busy);
        return states.try_emplace(r, r->state).first->second;
    };
    for (UINT n = 0; n < count; ++n) {
        auto *l = owned<List>(d, lists[n]);
        check(l->closed && SUCCEEDED(l->error) && l->allocator->generation == l->generation &&
              l->type == as<Queue>(self)->desc.Type);
        for (const auto &c : l->commands) {
            if (c.op == Op::copy || c.op == Op::texture_copy) {
                check(!c.src->transfer && !c.dst->transfer && state(c.dst.get()) == D3D12_RESOURCE_STATE_COPY_DEST &&
                      (state(c.src.get()) & D3D12_RESOURCE_STATE_COPY_SOURCE));
            } else if (c.op == Op::transition) {
                check(state(c.dst.get()) == c.before); state(c.dst.get()) = c.after;
            } else if (c.op == Op::dispatch) {
                auto &r = descriptor(c.heap.get(), c.handle);
                check(r.kind == DescriptorKind::uav && r.resource && !r.resource->transfer && r.bytes >= 8192 &&
                      state(r.resource.get()) == D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            } else if (c.op == Op::clear || c.op == Op::draw) {
                check(state(c.dst.get()) == D3D12_RESOURCE_STATE_RENDER_TARGET);
                if (c.depth) check(state(c.depth.get()) == D3D12_RESOURCE_STATE_DEPTH_WRITE);
                if (c.index) check(!c.index->transfer && (state(c.index.get()) & D3D12_RESOURCE_STATE_INDEX_BUFFER));
                if (c.op == Op::draw && c.pipeline->root->graphics_texture) {
                    auto &sampler = descriptor(c.sampler_heap.get(), c.sampler_handle);
                    check(sampler.kind == DescriptorKind::sampler);
                    const unsigned count = c.pipeline->root->texture.table4 ? 4 : 1;
                    for (unsigned i = 0; i < count; ++i) {
                        auto &view = descriptor(c.heap.get(), c.handle + i * descriptor_stride);
                        check(view.kind == DescriptorKind::srv && view.resource && !view.resource->transfer &&
                              state(view.resource.get()) == D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE &&
                              view.resource.get() != c.dst.get());
                    }
                    if (c.constants) check(!c.constants->transfer &&
                        (state(c.constants.get()) & D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER));
                }
            } else if (c.op == Op::clear_depth) {
                check(state(c.dst.get()) == D3D12_RESOURCE_STATE_DEPTH_WRITE);
            } else if (c.dst) check(state(c.dst.get()) == D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        }
    }
    for (UINT n = 0; n < count; ++n) {
        for (const auto &c : owned<List>(d, lists[n])->commands) {
            if (c.op == Op::copy) {
                ndx_copy(d->backend, c.dst->buffer, c.dst_offset, c.src->buffer, c.src_offset, c.bytes);
                ++d->stats.copies;
            } else if (c.op == Op::dispatch) {
                auto &r = descriptor(c.heap.get(), c.handle);
                ndx_dispatch(d->backend, c.pipeline->shader, r.resource->buffer, r.offset, r.bytes, c.groups);
                ++d->stats.dispatches;
            } else if (c.op == Op::clear) {
                ndx_clear_target(d->backend, c.dst->buffer, c.color.data()); ++d->graphics.clears;
            } else if (c.op == Op::clear_depth) {
                ndx_clear_depth(d->backend, c.dst->buffer, c.clear_depth); ++d->graphics.clears;
            } else if (c.op == Op::draw) {
                void *texture = nullptr; bool repeat_u = false, repeat_v = false;
                if (c.pipeline->root->graphics_texture) {
                    texture = descriptor(c.heap.get(), c.handle).resource->buffer;
                    const auto &sampler = descriptor(c.sampler_heap.get(), c.sampler_handle);
                    repeat_u = sampler.repeat_u; repeat_v = sampler.repeat_v;
                }
                const ndx_index_view indices{c.index ? c.index->buffer : nullptr, c.index_size,
                                              c.index_offset, c.first_index, c.base_vertex};
                if (c.pipeline->root->texture.table4) {
                    ndx_texture_table table{};
                    for (unsigned i = 0; i < 4; ++i)
                        table.textures[i] = descriptor(c.heap.get(), c.handle + i * descriptor_stride).resource->buffer;
                    table.constants = c.constants->buffer; table.constants_offset = c.constants_offset;
                    check(ndx_draw_table(d->backend, c.pipeline->shader, c.dst->buffer, c.viewport.data(), c.scissor.data(),
                                        c.vertices, &table, repeat_u, repeat_v, c.depth ? c.depth->buffer : nullptr,
                                        c.index ? &indices : nullptr), E_FAIL);
                } else check(ndx_draw(d->backend, c.pipeline->shader, c.dst->buffer, c.viewport.data(), c.scissor.data(),
                                      c.vertices, texture, repeat_u, repeat_v, c.depth ? c.depth->buffer : nullptr,
                                      c.index ? &indices : nullptr), E_FAIL);
                ++d->graphics.draws;
            } else if (c.op == Op::texture_copy) {
                check(ndx_copy_texture(d->backend, c.dst->buffer, c.dst_offset, c.bytes, c.src->buffer, c.upload), E_FAIL);
                ++d->graphics.texture_copies;
            } else if (c.op == Op::transition && c.dst->presentable && c.after == D3D12_RESOURCE_STATE_PRESENT) {
                ndx_present_flush(d->backend, c.dst->buffer);
            } else ndx_barrier(d->backend);
        }
    }
    void *f = ndx_flush(d->backend); ++d->stats.submissions;
    const bool done = ndx_wait(d->backend, f, 10000000000ull);
    if (f) ndx_fence_destroy(d->backend, f);
    d->stats.context_reset_status = ndx_reset_status(d->backend);
    if (!done || d->stats.context_reset_status)
        std::fprintf(stderr, "NDX12_SUBMISSION completed=%u reset_status=%u\n", done, d->stats.context_reset_status);
    check(done && d->stats.context_reset_status == 0, E_FAIL);
    for (const auto &[resource, value] : states) {
        resource->state = value;
        if (resource->presentable) resource->present_ready = value == D3D12_RESOURCE_STATE_PRESENT;
    }
}
HRESULT create_fence(ID3D12Device *self, UINT64 initial, D3D12_FENCE_FLAGS flags, REFIID iid, void **out)
{
    output_for<Fence>(iid, IID_ID3D12Fence, out); check(flags == D3D12_FENCE_FLAG_NONE);
    auto f = std::make_unique<Fence>(as<Device>(self)); f->completed = f->pending = initial;
    return publish(std::move(f), out);
}
UINT64 completed_value(ID3D12Fence *self)
{
    auto *f = as<Fence>(self);
    if (f->hardware && ndx_wait(f->owner->backend, f->hardware, 0)) {
        f->completed = f->pending; ndx_fence_destroy(f->owner->backend, f->hardware); f->hardware = nullptr;
    }
    return f->completed;
}
HRESULT queue_signal(ID3D12CommandQueue *self, ID3D12Fence *fence, UINT64 value)
{
    auto *d = as<Queue>(self)->owner; auto *f = owned<Fence>(d, fence);
    check(SUCCEEDED(d->error) && value > f->pending);
    void *hardware = ndx_flush(d->backend); check(hardware, E_FAIL);
    if (f->hardware) ndx_fence_destroy(d->backend, f->hardware);
    f->hardware = hardware; f->pending = value; return S_OK;
}
uint32_t word(const BYTE *p, size_t size, size_t offset)
{
    check(offset <= size && size - offset >= 4);
    uint32_t v; std::memcpy(&v, p + offset, 4); return v;
}
HRESULT create_root(ID3D12Device *self, UINT node, const void *blob, SIZE_T size, REFIID iid, void **out)
{
    output_for<Root>(iid, IID_ID3D12RootSignature, out);
    check(!node && blob && size >= 32 && size <= 65536);
    auto *data = static_cast<const BYTE *>(blob);
    check(std::memcmp(data, "DXBC", 4) == 0 && word(data, size, 24) == size);
    const unsigned chunks = word(data, size, 28); check(chunks && chunks <= 16);
    const BYTE *root = nullptr; size_t root_size = 0;
    for (unsigned i = 0; i < chunks; ++i) {
        const unsigned offset = word(data, size, 32 + i * 4);
        const unsigned tag = word(data, size, offset), bytes = word(data, size, size_t(offset) + 4);
        check(range(size_t(offset) + 8, bytes, size));
        if (tag == 0x30535452) { check(!root); root = data + offset + 8; root_size = bytes; }
    }
    check(root && word(root, root_size, 0) == 1 &&
          word(root, root_size, 12) == 0 &&
          (word(root, root_size, 20) == 0 || (word(root, root_size, 4) == 3 && word(root, root_size, 20) == 1)));
    auto r = std::make_unique<Root>(as<Device>(self));
    if (word(root, root_size, 4) == 0) {
        r->graphics_empty = true;
        return publish(std::move(r), out);
    }
    if (word(root, root_size, 4) == 2 || word(root, root_size, 4) == 3) {
        r->texture.table4 = word(root, root_size, 4) == 3;
        const size_t parameters = word(root, root_size, 8);
        for (unsigned i = 0; i < 2; ++i) {
            const size_t parameter = parameters + i * 12;
            check(word(root, root_size, parameter) == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE &&
                  word(root, root_size, parameter + 4) == (r->texture.table4 ? D3D12_SHADER_VISIBILITY_ALL : D3D12_SHADER_VISIBILITY_PIXEL));
            const size_t table = word(root, root_size, parameter + 8);
            check(word(root, root_size, table) == 1);
            const size_t entry = word(root, root_size, table + 4);
            check(word(root, root_size, entry) == (i ? D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER : D3D12_DESCRIPTOR_RANGE_TYPE_SRV) &&
                  word(root, root_size, entry + 4) == ((!i && r->texture.table4) ? 4u : 1u) &&
                  (word(root, root_size, entry + 16) == 0 || word(root, root_size, entry + 16) == UINT32_MAX));
            if (!i) {
                r->texture.srv_reg = word(root, root_size, entry + 8);
                r->texture.srv_space = word(root, root_size, entry + 12);
            } else {
                r->texture.sampler_reg = word(root, root_size, entry + 8);
                r->texture.sampler_space = word(root, root_size, entry + 12);
            }
        }
        if (r->texture.table4) {
            const size_t parameter = parameters + 24;
            check(word(root, root_size, parameter) == D3D12_ROOT_PARAMETER_TYPE_CBV &&
                  word(root, root_size, parameter + 4) == D3D12_SHADER_VISIBILITY_ALL);
            const size_t cbv = word(root, root_size, parameter + 8);
            check(word(root, root_size, cbv) == 0 && word(root, root_size, cbv + 4) == 0 &&
                  r->texture.srv_reg == 0 && r->texture.srv_space == 0 &&
                  r->texture.sampler_reg == 0 && r->texture.sampler_space == 0);
        }
        r->graphics_texture = true;
        return publish(std::move(r), out);
    }
    check(word(root, root_size, 4) == 1);
    const size_t parameter = word(root, root_size, 8);
    check(word(root, root_size, parameter) == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE &&
          word(root, root_size, parameter + 4) == D3D12_SHADER_VISIBILITY_ALL);
    const size_t table = word(root, root_size, parameter + 8);
    check(word(root, root_size, table) == 1);
    const size_t entry = word(root, root_size, table + 4);
    check(word(root, root_size, entry) == D3D12_DESCRIPTOR_RANGE_TYPE_UAV &&
          word(root, root_size, entry + 4) == 1 &&
          (word(root, root_size, entry + 16) == 0 || word(root, root_size, entry + 16) == UINT32_MAX));
    r->reg = word(root, root_size, entry + 8); r->space = word(root, root_size, entry + 12);
    return publish(std::move(r), out);
}
HRESULT create_pipeline(ID3D12Device *self, const D3D12_COMPUTE_PIPELINE_STATE_DESC *desc, REFIID iid, void **out)
{
    output_for<Pipeline>(iid, IID_ID3D12PipelineState, out);
    auto *d = as<Device>(self);
    check(desc && !desc->NodeMask && desc->Flags == D3D12_PIPELINE_STATE_FLAG_NONE &&
          !desc->CachedPSO.CachedBlobSizeInBytes && !desc->CachedPSO.pCachedBlob);
    auto *r = owned<Root>(d, desc->pRootSignature);
    check(!r->graphics_empty && !r->graphics_texture);
    auto p = std::make_unique<Pipeline>(d); p->root = Ref<Root>(r);
    p->shader = ndx_shader_create(d->backend, desc->CS.pShaderBytecode, desc->CS.BytecodeLength, r->space, r->reg);
    check(p->shader, E_INVALIDARG); ++d->stats.shader_compiles;
    return publish(std::move(p), out);
}
HRESULT create_heap(ID3D12Device *self, const D3D12_DESCRIPTOR_HEAP_DESC *desc, REFIID iid, void **out)
{
    output_for<Heap>(iid, IID_ID3D12DescriptorHeap, out);
    check(desc && desc->NumDescriptors >= 1 && desc->NumDescriptors <= 8 && !desc->NodeMask &&
          (((desc->Type == D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || desc->Type == D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER) &&
            desc->Flags == D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE) ||
           ((desc->Type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV || desc->Type == D3D12_DESCRIPTOR_HEAP_TYPE_DSV) &&
            desc->Flags == D3D12_DESCRIPTOR_HEAP_FLAG_NONE)));
    auto h = std::make_unique<Heap>(as<Device>(self)); h->desc = *desc;
    h->start = next_handle.fetch_add((desc->NumDescriptors + 1) * descriptor_stride);
    h->descriptors.resize(desc->NumDescriptors); h->owner->heaps.push_back(h.get());
    return publish(std::move(h), out);
}
UINT descriptor_size(ID3D12Device *, D3D12_DESCRIPTOR_HEAP_TYPE type)
{
    check(type == D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV ||
          type == D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER || type == D3D12_DESCRIPTOR_HEAP_TYPE_DSV); return descriptor_stride;
}
D3D12_DESCRIPTOR_HEAP_DESC heap_desc(ID3D12DescriptorHeap *self) { return as<Heap>(self)->desc; }
D3D12_CPU_DESCRIPTOR_HANDLE cpu_start(ID3D12DescriptorHeap *self) { return {static_cast<SIZE_T>(as<Heap>(self)->start)}; }
D3D12_GPU_DESCRIPTOR_HANDLE gpu_start(ID3D12DescriptorHeap *self) {
    auto *h = as<Heap>(self); check(h->desc.Flags == D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE); return {h->start};
}
void create_uav(ID3D12Device *self, ID3D12Resource *resource, ID3D12Resource *counter,
                const D3D12_UNORDERED_ACCESS_VIEW_DESC *desc, D3D12_CPU_DESCRIPTOR_HANDLE handle)
{
    auto *d = as<Device>(self); auto *r = owned<Resource>(d, resource);
    check(!counter && desc && desc->ViewDimension == D3D12_UAV_DIMENSION_BUFFER &&
          desc->Format == DXGI_FORMAT_UNKNOWN && desc->Buffer.StructureByteStride == 4 &&
          desc->Buffer.CounterOffsetInBytes == 0 && desc->Buffer.Flags == D3D12_BUFFER_UAV_FLAG_NONE &&
          desc->Buffer.NumElements && (r->desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS));
    check(desc->Buffer.FirstElement <= r->desc.Width / 4 &&
          desc->Buffer.NumElements <= r->desc.Width / 4 - desc->Buffer.FirstElement);
    for (auto *h : d->heaps) {
        if (handle.ptr >= h->start && handle.ptr - h->start < h->descriptors.size() * descriptor_stride) {
            check(h->desc.Type == D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            auto &v = descriptor(h, handle.ptr);
            v = {}; v.kind = DescriptorKind::uav;
            v.resource = Ref<Resource>(r); v.offset = static_cast<unsigned>(desc->Buffer.FirstElement * 4);
            v.bytes = desc->Buffer.NumElements * 4; return;
        }
    }
    throw ApiError{E_INVALIDARG};
}
Descriptor &cpu_descriptor(Device *d, D3D12_CPU_DESCRIPTOR_HANDLE handle, D3D12_DESCRIPTOR_HEAP_TYPE type)
{
    for (auto *h : d->heaps) {
        if (handle.ptr >= h->start && handle.ptr - h->start < h->descriptors.size() * descriptor_stride) {
            check(h->desc.Type == type);
            return descriptor(h, handle.ptr);
        }
    }
    throw ApiError{E_INVALIDARG};
}
Descriptor &rtv(Device *d, D3D12_CPU_DESCRIPTOR_HANDLE handle)
{
    return cpu_descriptor(d, handle, D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
}
void create_srv(ID3D12Device *self, ID3D12Resource *resource,
                const D3D12_SHADER_RESOURCE_VIEW_DESC *desc, D3D12_CPU_DESCRIPTOR_HANDLE handle)
{
    auto *d = as<Device>(self); auto *r = owned<Resource>(d, resource);
    check(r->desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
          r->desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM && desc &&
          desc->Format == DXGI_FORMAT_R8G8B8A8_UNORM && desc->ViewDimension == D3D12_SRV_DIMENSION_TEXTURE2D &&
          desc->Shader4ComponentMapping == D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING &&
          !desc->Texture2D.MostDetailedMip && desc->Texture2D.MipLevels == 1 &&
          !desc->Texture2D.PlaneSlice && desc->Texture2D.ResourceMinLODClamp == 0);
    auto &v = cpu_descriptor(d, handle, D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    v = {}; v.kind = DescriptorKind::srv; v.resource = Ref<Resource>(r);
}
void create_sampler(ID3D12Device *self, const D3D12_SAMPLER_DESC *desc, D3D12_CPU_DESCRIPTOR_HANDLE handle)
{
    auto address = [](D3D12_TEXTURE_ADDRESS_MODE mode) {
        return mode == D3D12_TEXTURE_ADDRESS_MODE_CLAMP || mode == D3D12_TEXTURE_ADDRESS_MODE_WRAP;
    };
    check(desc && desc->Filter == D3D12_FILTER_MIN_MAG_MIP_POINT && address(desc->AddressU) &&
          address(desc->AddressV) && desc->AddressW == D3D12_TEXTURE_ADDRESS_MODE_CLAMP &&
          desc->MipLODBias == 0 && desc->MinLOD == 0 && desc->MaxLOD == 0 &&
          desc->MaxAnisotropy == 1 && desc->ComparisonFunc == D3D12_COMPARISON_FUNC_NEVER);
    auto &v = cpu_descriptor(as<Device>(self), handle, D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER);
    v = {}; v.kind = DescriptorKind::sampler;
    v.repeat_u = desc->AddressU == D3D12_TEXTURE_ADDRESS_MODE_WRAP;
    v.repeat_v = desc->AddressV == D3D12_TEXTURE_ADDRESS_MODE_WRAP;
}
void create_rtv(ID3D12Device *self, ID3D12Resource *resource,
                const D3D12_RENDER_TARGET_VIEW_DESC *desc, D3D12_CPU_DESCRIPTOR_HANDLE handle)
{
    auto *d = as<Device>(self); auto *r = owned<Resource>(d, resource);
    check(r->desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
          (r->desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET));
    check(!desc || (desc->Format == DXGI_FORMAT_R8G8B8A8_UNORM &&
          desc->ViewDimension == D3D12_RTV_DIMENSION_TEXTURE2D &&
          !desc->Texture2D.MipSlice && !desc->Texture2D.PlaneSlice));
    auto &v = rtv(d, handle); v = {}; v.kind = DescriptorKind::rtv; v.resource = Ref<Resource>(r);
}
void create_dsv(ID3D12Device *self, ID3D12Resource *resource,
                const D3D12_DEPTH_STENCIL_VIEW_DESC *desc, D3D12_CPU_DESCRIPTOR_HANDLE handle)
{
    auto *d = as<Device>(self); auto *r = owned<Resource>(d, resource);
    check(r->desc.Format == DXGI_FORMAT_D32_FLOAT &&
          r->desc.Flags == D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL);
    check(!desc || (desc->Format == DXGI_FORMAT_D32_FLOAT &&
          desc->ViewDimension == D3D12_DSV_DIMENSION_TEXTURE2D &&
          desc->Flags == D3D12_DSV_FLAG_NONE && !desc->Texture2D.MipSlice));
    auto &v = cpu_descriptor(d, handle, D3D12_DESCRIPTOR_HEAP_TYPE_DSV);
    v = {}; v.kind = DescriptorKind::dsv; v.resource = Ref<Resource>(r);
}
HRESULT create_graphics_pipeline(ID3D12Device *self, const D3D12_GRAPHICS_PIPELINE_STATE_DESC *desc,
                                  REFIID iid, void **out)
{
    output_for<Pipeline>(iid, IID_ID3D12PipelineState, out);
    auto *d = as<Device>(self);
    check(desc && !desc->NodeMask && desc->Flags == D3D12_PIPELINE_STATE_FLAG_NONE &&
          !desc->CachedPSO.CachedBlobSizeInBytes && !desc->CachedPSO.pCachedBlob &&
          !desc->DS.BytecodeLength && !desc->HS.BytecodeLength && !desc->GS.BytecodeLength &&
          !desc->StreamOutput.NumEntries && !desc->StreamOutput.NumStrides &&
          !desc->StreamOutput.RasterizedStream && !desc->InputLayout.NumElements &&
          desc->IBStripCutValue == D3D12_INDEX_BUFFER_STRIP_CUT_VALUE_DISABLED &&
          desc->PrimitiveTopologyType == D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE &&
          desc->NumRenderTargets == 1 && desc->RTVFormats[0] == DXGI_FORMAT_R8G8B8A8_UNORM &&
          (desc->DSVFormat == DXGI_FORMAT_UNKNOWN || desc->DSVFormat == DXGI_FORMAT_D32_FLOAT) &&
          desc->SampleDesc.Count == 1 &&
          !desc->SampleDesc.Quality && desc->SampleMask == UINT32_MAX);
    const auto &blend = desc->BlendState; const auto &raster = desc->RasterizerState;
    check(!blend.AlphaToCoverageEnable && !blend.IndependentBlendEnable &&
          !blend.RenderTarget[0].BlendEnable && !blend.RenderTarget[0].LogicOpEnable &&
          blend.RenderTarget[0].RenderTargetWriteMask == D3D12_COLOR_WRITE_ENABLE_ALL &&
          raster.FillMode == D3D12_FILL_MODE_SOLID && raster.CullMode == D3D12_CULL_MODE_NONE &&
          !raster.DepthBias && !raster.DepthBiasClamp && !raster.SlopeScaledDepthBias &&
          raster.DepthClipEnable && !raster.MultisampleEnable && !raster.AntialiasedLineEnable &&
          !raster.ForcedSampleCount && raster.ConservativeRaster == D3D12_CONSERVATIVE_RASTERIZATION_MODE_OFF &&
          !desc->DepthStencilState.StencilEnable);
    const auto &z = desc->DepthStencilState;
    check(!z.DepthEnable || (desc->DSVFormat == DXGI_FORMAT_D32_FLOAT &&
          (z.DepthWriteMask == D3D12_DEPTH_WRITE_MASK_ZERO || z.DepthWriteMask == D3D12_DEPTH_WRITE_MASK_ALL) &&
          (z.DepthFunc == D3D12_COMPARISON_FUNC_LESS || z.DepthFunc == D3D12_COMPARISON_FUNC_LESS_EQUAL)));
    for (unsigned i = 1; i < 8; ++i) check(desc->RTVFormats[i] == DXGI_FORMAT_UNKNOWN);
    auto *r = owned<Root>(d, desc->pRootSignature); check(r->graphics_empty || r->graphics_texture);
    auto p = std::make_unique<Pipeline>(d); p->root = Ref<Root>(r); p->graphics = true;
    p->depth_target = desc->DSVFormat == DXGI_FORMAT_D32_FLOAT;
    const ndx_depth_state depth{bool(z.DepthEnable), z.DepthWriteMask == D3D12_DEPTH_WRITE_MASK_ALL,
                                 z.DepthFunc == D3D12_COMPARISON_FUNC_LESS_EQUAL ? NDX_DEPTH_LEQUAL : NDX_DEPTH_LESS};
    p->shader = ndx_graphics_create(d->backend, desc->VS.pShaderBytecode, desc->VS.BytecodeLength,
                                    desc->PS.pShaderBytecode, desc->PS.BytecodeLength,
                                    r->graphics_texture ? &r->texture : nullptr, &depth);
    check(p->shader, E_INVALIDARG); d->stats.shader_compiles += 2;
    return publish(std::move(p), out);
}
List *direct_recording(ID3D12GraphicsCommandList *self)
{
    auto *l = recording(self); check(l->type == D3D12_COMMAND_LIST_TYPE_DIRECT); return l;
}
void set_graphics_root(ID3D12GraphicsCommandList *self, ID3D12RootSignature *root)
{
    auto *l = direct_recording(self); auto *r = owned<Root>(l->owner, root); check(r->graphics_empty || r->graphics_texture);
    if (l->graphics_root.get() != r) {
        l->graphics_handle = l->sampler_handle = 0;
        l->constants = {}; l->constants_offset = 0;
    }
    l->graphics_root = Ref<Root>(r);
}
void set_graphics_table(ID3D12GraphicsCommandList *self, UINT index, D3D12_GPU_DESCRIPTOR_HANDLE handle)
{
    auto *l = direct_recording(self);
    check(index < 2 && l->graphics_root && l->graphics_root->graphics_texture);
    auto *h = index ? l->sampler_heap.get() : l->heap.get(); check(h);
    descriptor(h, handle.ptr);
    if (!index && l->graphics_root->texture.table4) {
        check(handle.ptr <= UINT64_MAX - 3 * descriptor_stride);
        descriptor(h, handle.ptr + 3 * descriptor_stride);
    }
    (index ? l->sampler_handle : l->graphics_handle) = handle.ptr;
}
void set_graphics_cbv(ID3D12GraphicsCommandList *self, UINT index, D3D12_GPU_VIRTUAL_ADDRESS location)
{
    auto *l = direct_recording(self);
    check(index == 2 && l->graphics_root && l->graphics_root->texture.table4 &&
          location && location % D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT == 0);
    for (auto *r : l->owner->resources) {
        if (r->desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER || r->heap.Type == D3D12_HEAP_TYPE_READBACK) continue;
        const auto address = ndx_buffer_address(l->owner->backend, r->buffer);
        if (location < address || !range(location - address, 16, r->desc.Width)) continue;
        l->constants = Ref<Resource>(r);
        l->constants_offset = static_cast<unsigned>(location - address);
        return;
    }
    throw ApiError{E_INVALIDARG};
}
void set_topology(ID3D12GraphicsCommandList *self, D3D12_PRIMITIVE_TOPOLOGY topology)
{
    auto *l = direct_recording(self); check(topology == D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST); l->triangles = true;
}
void set_viewports(ID3D12GraphicsCommandList *self, UINT count, const D3D12_VIEWPORT *vp)
{
    auto *l = direct_recording(self); check(count == 1 && vp);
    const std::array<float, 6> v{vp->TopLeftX, vp->TopLeftY, vp->Width, vp->Height, vp->MinDepth, vp->MaxDepth};
    check(std::all_of(v.begin(), v.end(), [](float x) { return std::isfinite(x); }) &&
          v[0] >= 0 && v[1] >= 0 && v[2] > 0 && v[3] > 0 &&
          v[0] + v[2] <= 4096 && v[1] + v[3] <= 4096 && v[4] >= 0 && v[5] <= 1 && v[4] <= v[5]);
    l->viewport = v; l->have_viewport = true;
}
void set_scissors(ID3D12GraphicsCommandList *self, UINT count, const D3D12_RECT *rect)
{
    auto *l = direct_recording(self); check(count == 1 && rect && rect->left >= 0 && rect->top >= 0 &&
          rect->right >= rect->left && rect->bottom >= rect->top && rect->right <= 4096 && rect->bottom <= 4096);
    l->scissor = {unsigned(rect->left), unsigned(rect->top), unsigned(rect->right), unsigned(rect->bottom)};
    l->have_scissor = true;
}
void set_targets(ID3D12GraphicsCommandList *self, UINT count, const D3D12_CPU_DESCRIPTOR_HANDLE *handles,
                 BOOL, const D3D12_CPU_DESCRIPTOR_HANDLE *depth)
{
    auto *l = direct_recording(self); check(count == 1 && handles);
    auto &view = rtv(l->owner, handles[0]); check(view.kind == DescriptorKind::rtv && view.resource);
    Ref<Resource> z;
    if (depth) {
        auto &v = cpu_descriptor(l->owner, *depth, D3D12_DESCRIPTOR_HEAP_TYPE_DSV);
        check(v.kind == DescriptorKind::dsv && v.resource); z = v.resource;
        check(z->desc.Width == view.resource->desc.Width && z->desc.Height == view.resource->desc.Height);
    }
    l->target = view.resource; l->depth = z;
}
void clear_target(ID3D12GraphicsCommandList *self, D3D12_CPU_DESCRIPTOR_HANDLE handle,
                  const FLOAT color[4], UINT count, const D3D12_RECT *)
{
    auto *l = direct_recording(self); check(color && !count);
    auto &view = rtv(l->owner, handle); check(bool(view.resource));
    Command c; c.op = Op::clear; c.dst = view.resource;
    for (unsigned i = 0; i < 4; ++i) { check(std::isfinite(color[i])); c.color[i] = color[i]; }
    l->commands.push_back(std::move(c));
}
void clear_depth(ID3D12GraphicsCommandList *self, D3D12_CPU_DESCRIPTOR_HANDLE handle,
                 D3D12_CLEAR_FLAGS flags, FLOAT depth, UINT8 stencil, UINT count, const D3D12_RECT *)
{
    auto *l = direct_recording(self);
    check(flags == D3D12_CLEAR_FLAG_DEPTH && !stencil && !count &&
          std::isfinite(depth) && depth >= 0 && depth <= 1);
    auto &v = cpu_descriptor(l->owner, handle, D3D12_DESCRIPTOR_HEAP_TYPE_DSV);
    check(v.kind == DescriptorKind::dsv && v.resource);
    Command c; c.op = Op::clear_depth; c.dst = v.resource; c.clear_depth = depth;
    l->commands.push_back(std::move(c));
}
void set_index_buffer(ID3D12GraphicsCommandList *self, const D3D12_INDEX_BUFFER_VIEW *view)
{
    auto *l = direct_recording(self);
    if (!view) { l->index = {}; l->index_size = l->index_offset = l->index_bytes = 0; return; }
    check(view->Format == DXGI_FORMAT_R16_UINT || view->Format == DXGI_FORMAT_R32_UINT);
    const unsigned size = view->Format == DXGI_FORMAT_R16_UINT ? 2 : 4;
    check(view->BufferLocation && view->BufferLocation % size == 0 &&
          view->SizeInBytes && view->SizeInBytes % size == 0);
    for (auto *r : l->owner->resources) {
        if (r->desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER || r->heap.Type == D3D12_HEAP_TYPE_READBACK) continue;
        const auto address = ndx_buffer_address(l->owner->backend, r->buffer);
        if (view->BufferLocation < address || !range(view->BufferLocation - address, view->SizeInBytes, r->desc.Width)) continue;
        l->index = Ref<Resource>(r); l->index_size = size;
        l->index_offset = static_cast<unsigned>(view->BufferLocation - address); l->index_bytes = view->SizeInBytes;
        return;
    }
    throw ApiError{E_INVALIDARG};
}
Command draw_command(List *l, UINT vertices)
{
    check((vertices == 3 || vertices == 6) && l->pipeline &&
          l->pipeline->graphics && l->graphics_root && l->pipeline->root.get() == l->graphics_root.get() &&
          l->target && l->have_viewport && l->have_scissor && l->triangles);
    check(l->pipeline->depth_target == bool(l->depth));
    Command c; c.op = Op::draw; c.pipeline = l->pipeline; c.dst = l->target;
    c.vertices = vertices; c.depth = l->depth;
    if (l->graphics_root->graphics_texture) {
        check(l->heap && l->sampler_heap && l->graphics_handle && l->sampler_handle);
        c.heap = l->heap; c.handle = l->graphics_handle;
        c.sampler_heap = l->sampler_heap; c.sampler_handle = l->sampler_handle;
        if (l->graphics_root->texture.table4) {
            check(bool(l->constants));
            c.constants = l->constants; c.constants_offset = l->constants_offset;
        }
    }
    c.viewport = l->viewport; c.scissor = l->scissor;
    return c;
}
void draw(ID3D12GraphicsCommandList *self, UINT vertices, UINT instances, UINT first, UINT first_instance)
{
    auto *l = direct_recording(self); check(instances == 1 && !first && !first_instance);
    l->commands.push_back(draw_command(l, vertices));
}
void draw_indexed(ID3D12GraphicsCommandList *self, UINT count, UINT instances, UINT first, INT base, UINT first_instance)
{
    auto *l = direct_recording(self); check(instances == 1 && !first_instance && l->index);
    check(range(UINT64(first) * l->index_size, UINT64(count) * l->index_size, l->index_bytes));
    auto c = draw_command(l, count);
    c.index = l->index; c.index_size = l->index_size; c.index_offset = l->index_offset;
    c.first_index = first; c.base_vertex = base;
    l->commands.push_back(std::move(c));
}
void copy_texture(ID3D12GraphicsCommandList *self, const D3D12_TEXTURE_COPY_LOCATION *dst,
                  UINT x, UINT y, UINT z, const D3D12_TEXTURE_COPY_LOCATION *src, const D3D12_BOX *box)
{
    auto *l = direct_recording(self);
    check(dst && src && !x && !y && !z && !box);
    const bool upload = dst->Type == D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    const auto &tex = upload ? *dst : *src;
    const auto &buf = upload ? *src : *dst;
    check(tex.Type == D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX && !tex.SubresourceIndex &&
          buf.Type == D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT);
    auto *d = owned<Resource>(l->owner, dst->pResource); auto *s = owned<Resource>(l->owner, src->pResource);
    const auto *t = upload ? d : s; const auto *b = upload ? s : d;
    const auto &placed = buf.PlacedFootprint; const auto &fp = placed.Footprint;
    check(b->desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER &&
          b->heap.Type == (upload ? D3D12_HEAP_TYPE_UPLOAD : D3D12_HEAP_TYPE_READBACK) &&
          t->desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
          t->desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM && fp.Format == t->desc.Format &&
          fp.Width == t->desc.Width && fp.Height == t->desc.Height && fp.Depth == 1 &&
          fp.RowPitch >= fp.Width * 4 && fp.RowPitch % D3D12_TEXTURE_DATA_PITCH_ALIGNMENT == 0 &&
          placed.Offset % D3D12_TEXTURE_DATA_PLACEMENT_ALIGNMENT == 0 &&
          range(placed.Offset, UINT64(fp.RowPitch) * fp.Height, b->desc.Width));
    Command c; c.op = Op::texture_copy; c.src = Ref<Resource>(s); c.dst = Ref<Resource>(d);
    c.upload = upload;
    c.dst_offset = unsigned(placed.Offset); c.bytes = fp.RowPitch; l->commands.push_back(std::move(c));
}
UINT node_count(ID3D12Device *) { return 1; }
HRESULT removed_reason(ID3D12Device *self) { return as<Device>(self)->error; }
D3D12_COMMAND_LIST_TYPE list_type(ID3D12GraphicsCommandList *self) { return as<List>(self)->type; }

template<class T> void base_table()
{
    using I = typename T::Interface;
    T::table = defaults<typename T::VTable>();
    T::table.QueryInterface = protected_call<query<I>>::call;
    T::table.AddRef = add_ref<I>;
    T::table.Release = release<I>;
    if constexpr (!std::is_same_v<T, Device>)
        T::table.GetDevice = protected_call<get_device<I>>::call;
}
void initialize_tables()
{
    static const bool initialized = [] {
        base_table<Device>(); base_table<Resource>(); base_table<Allocator>();
        base_table<List>(); base_table<Queue>(); base_table<Fence>();
        base_table<Root>(); base_table<Heap>(); base_table<Pipeline>();
#define BIND(type, method, function) type::table.method = protected_call<function>::call
        BIND(Device, GetNodeCount, node_count);
        BIND(Device, GetDeviceRemovedReason, removed_reason);
        BIND(Device, CreateCommittedResource, create_resource);
        BIND(Device, CreateCommandAllocator, create_allocator);
        BIND(Device, CreateCommandList, create_list);
        BIND(Device, CreateCommandQueue, create_queue);
        BIND(Device, CreateFence, create_fence);
        BIND(Device, CreateRootSignature, create_root);
        BIND(Device, CreateComputePipelineState, create_pipeline);
        BIND(Device, CreateGraphicsPipelineState, create_graphics_pipeline);
        BIND(Device, CreateDescriptorHeap, create_heap);
        BIND(Device, GetDescriptorHandleIncrementSize, descriptor_size);
        BIND(Device, CreateUnorderedAccessView, create_uav);
        BIND(Device, CreateShaderResourceView, create_srv);
        BIND(Device, CreateSampler, create_sampler);
        BIND(Device, CreateRenderTargetView, create_rtv);
        BIND(Device, CreateDepthStencilView, create_dsv);
        BIND(Resource, Map, resource_map); BIND(Resource, Unmap, resource_unmap);
        BIND(Resource, GetDesc, resource_desc); BIND(Resource, GetGPUVirtualAddress, resource_address);
        BIND(Resource, GetHeapProperties, heap_properties);
        BIND(Allocator, Reset, allocator_reset);
        BIND(List, Reset, list_reset); BIND(List, Close, close_list);
        BIND(List, GetType, list_type); BIND(List, CopyBufferRegion, copy_buffer);
        BIND(List, ResourceBarrier, barriers); BIND(List, SetPipelineState, set_pipeline);
        BIND(List, SetComputeRootSignature, set_root); BIND(List, SetDescriptorHeaps, set_heaps);
        BIND(List, SetComputeRootDescriptorTable, set_table); BIND(List, Dispatch, dispatch);
        BIND(List, SetGraphicsRootSignature, set_graphics_root);
        BIND(List, SetGraphicsRootDescriptorTable, set_graphics_table);
        BIND(List, SetGraphicsRootConstantBufferView, set_graphics_cbv);
        BIND(List, IASetPrimitiveTopology, set_topology);
        BIND(List, IASetIndexBuffer, set_index_buffer);
        BIND(List, RSSetViewports, set_viewports); BIND(List, RSSetScissorRects, set_scissors);
        BIND(List, OMSetRenderTargets, set_targets); BIND(List, ClearRenderTargetView, clear_target);
        BIND(List, ClearDepthStencilView, clear_depth); BIND(List, DrawIndexedInstanced, draw_indexed);
        BIND(List, DrawInstanced, draw); BIND(List, CopyTextureRegion, copy_texture);
        BIND(Queue, ExecuteCommandLists, execute); BIND(Queue, Signal, queue_signal);
        BIND(Queue, GetDesc, queue_desc); BIND(Fence, GetCompletedValue, completed_value);
        BIND(Heap, GetDesc, heap_desc); BIND(Heap, GetCPUDescriptorHandleForHeapStart, cpu_start);
        BIND(Heap, GetGPUDescriptorHandleForHeapStart, gpu_start);
#undef BIND
        return true;
    }();
    (void)initialized;
}
}
extern "C" HRESULT WINAPI D3D12CreateDevice(IUnknown *, D3D_FEATURE_LEVEL, REFIID, void **out)
{
    if (out) *out = nullptr;
    return unsupported_hr;
}
extern "C" HRESULT Ndx12CreateExperimentalDevice(const char *node, REFIID iid, void **out)
{
    if (!out) return E_POINTER;
    *out = nullptr;
    try {
        check(node && iid_equal(iid, IID_ID3D12Device), E_NOINTERFACE);
        initialize_tables();
        auto d = std::make_unique<Device>(); d->backend = ndx_backend_create(node);
        check(d->backend, unsupported_hr); return publish(std::move(d), out);
    } catch (const ApiError &e) { return e.hr; }
      catch (const std::bad_alloc &) { return E_OUTOFMEMORY; }
      catch (...) { return E_FAIL; }
}
extern "C" HRESULT Ndx12GetStats(ID3D12Device *device, Ndx12Stats *stats)
{
    try {
        auto *d = as<Device>(device); check_thread(d); check(stats, E_POINTER);
        d->stats.context_reset_status = ndx_reset_status(d->backend); *stats = d->stats; return S_OK;
    } catch (const ApiError &e) { return e.hr; } catch (...) { return E_FAIL; }
}
extern "C" UINT64 Ndx12LiveObjects(void) { return live_objects.load(); }
extern "C" HRESULT Ndx12GetGraphicsStats(ID3D12Device *device, Ndx12GraphicsStats *stats)
{
    try {
        auto *d = as<Device>(device); check_thread(d); check(stats, E_POINTER);
        *stats = d->graphics; return S_OK;
    } catch (const ApiError &e) { return e.hr; } catch (...) { return E_FAIL; }
}
extern "C" HRESULT Ndx12CreatePresentResource(ID3D12Device *device, UINT width, UINT height, ID3D12Resource **out)
{
    if (!out) return E_POINTER;
    *out = nullptr;
    try {
        auto *d = as<Device>(device); check_thread(d);
        check(SUCCEEDED(d->error) && width && height && width <= 4096 && height <= 4096);
        auto r = std::make_unique<Resource>(d);
        r->desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        r->desc.Width = width; r->desc.Height = height;
        r->desc.DepthOrArraySize = r->desc.MipLevels = r->desc.SampleDesc.Count = 1;
        r->desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        r->desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        r->heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        r->heap.CreationNodeMask = r->heap.VisibleNodeMask = 1;
        r->state = D3D12_RESOURCE_STATE_PRESENT;
        r->buffer = ndx_present_create(d->backend, width, height);
        check(r->buffer, E_OUTOFMEMORY);
        r->presentable = true;
        ++d->present.created; ++d->graphics.live_render_targets;
        d->resources.push_back(r.get());
        *out = &r->box.iface; r.release(); return S_OK;
    } catch (const ApiError &e) { return e.hr; }
      catch (const std::bad_alloc &) { return E_OUTOFMEMORY; }
      catch (...) { return E_FAIL; }
}
extern "C" HRESULT Ndx12ExportPresentResource(ID3D12Resource *resource, Ndx12DmaBuf *buffer)
{
    if (!buffer) return E_POINTER;
    *buffer = {}; buffer->fd = -1;
    try {
        auto *r = as<Resource>(resource); check_thread(r);
        check(r->presentable && !r->exported && !r->present_busy && SUCCEEDED(r->owner->error));
        unsigned stride = 0, offset = 0;
        const int fd = ndx_present_export(r->owner->backend, r->buffer, &stride, &offset);
        check(fd >= 0, E_FAIL);
        *buffer = {fd, static_cast<UINT>(r->desc.Width), r->desc.Height, stride, offset, 0x34324241u, 0};
        r->exported = true; ++r->owner->present.exports; return S_OK;
    } catch (const ApiError &e) { return e.hr; } catch (...) { return E_FAIL; }
}
extern "C" HRESULT Ndx12AcquireForPresent(ID3D12Resource *resource)
{
    try {
        auto *r = as<Resource>(resource); check_thread(r);
        check(r->presentable && r->exported && r->present_ready && !r->present_busy &&
              r->state == D3D12_RESOURCE_STATE_PRESENT && SUCCEEDED(r->owner->error));
        r->present_busy = true; r->present_ready = false;
        r->add(); ++r->owner->present.acquired; return S_OK;
    } catch (const ApiError &e) { return e.hr; } catch (...) { return E_FAIL; }
}
extern "C" HRESULT Ndx12ReleaseFromPresent(ID3D12Resource *resource)
{
    try {
        auto *r = as<Resource>(resource); check_thread(r);
        check(r->presentable && r->present_busy);
        r->present_busy = false; ++r->owner->present.released; r->release(); return S_OK;
    } catch (const ApiError &e) { return e.hr; } catch (...) { return E_FAIL; }
}
extern "C" HRESULT Ndx12GetPresentStats(ID3D12Device *device, Ndx12PresentStats *stats)
{
    try {
        auto *d = as<Device>(device); check_thread(d); check(stats, E_POINTER);
        *stats = d->present; return S_OK;
    } catch (const ApiError &e) { return e.hr; } catch (...) { return E_FAIL; }
}
