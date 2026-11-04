#include "ndx12.h"
#include "evidence_outputs.h"
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
EvidenceOutputs evidence;
constexpr uint32_t sentinel = 0xdeadbeef, guard = 0xa5c39e71;
template<class T> struct ComRelease { void operator()(T *p) const { if (p) p->lpVtbl->Release(p); } };
template<class T> using Com = std::unique_ptr<T, ComRelease<T>>;
void require(bool ok, const char *what) { if (!ok) throw std::runtime_error(what); }
void hr(HRESULT h, const char *what) { if (FAILED(h)) { std::fprintf(stderr, "HRESULT=%08x %s\n", unsigned(h), what); throw std::runtime_error(what); } }
unsigned number(const char *p)
{
    size_t used = 0; auto n = std::stoul(p, &used, 0);
    require(used == std::strlen(p) && n <= UINT32_MAX, "argument out of range");
    return static_cast<unsigned>(n);
}
std::vector<char> read(const std::string &path)
{
    std::ifstream f(path, std::ios::binary);
    require(bool(f), "input file unavailable");
    return {std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
}
void snapshot(const std::string &prefix, const char *phase)
{
    std::ostringstream maps;
    maps << "PHASE=" << phase << '\n';
    std::ifstream input("/proc/self/maps"); maps << input.rdbuf();
    std::ostringstream fds;
    fds << "PHASE=" << phase << '\n';
    for (const auto &entry : std::filesystem::directory_iterator("/proc/self/fd")) {
        std::error_code ec;
        const auto target = std::filesystem::read_symlink(entry.path(), ec).string();
        if (ec || target.find("/dev/dri/") == std::string::npos) continue;
        fds << "FD=" << entry.path().filename().string() << " TARGET=" << target << '\n';
        std::ifstream info("/proc/self/fdinfo/" + entry.path().filename().string());
        fds << info.rdbuf();
    }
    require(bool(maps) && bool(fds), "cannot write runtime evidence");
    evidence.text(0, maps.str());
    evidence.text(1, fds.str());
}
Com<ID3D12Resource> buffer(ID3D12Device *d, unsigned bytes, D3D12_HEAP_TYPE type,
                          D3D12_RESOURCE_STATES state, bool uav = false)
{
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = type; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
    D3D12_RESOURCE_DESC desc{}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = bytes; desc.Height = 1; desc.DepthOrArraySize = desc.MipLevels = 1;
    desc.SampleDesc.Count = 1; desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    if (uav) desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    ID3D12Resource *out = nullptr;
    hr(ID3D12Device_CreateCommittedResource(d, &heap, D3D12_HEAP_FLAG_NONE, &desc, state,
                                            nullptr, IID_ID3D12Resource, reinterpret_cast<void **>(&out)), "CreateCommittedResource");
    return Com<ID3D12Resource>(out);
}
void transition(ID3D12GraphicsCommandList *list, ID3D12Resource *r,
                D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after)
{
    D3D12_RESOURCE_BARRIER b{}; b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition.pResource = r; b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    b.Transition.StateBefore = before; b.Transition.StateAfter = after;
    ID3D12GraphicsCommandList_ResourceBarrier(list, 1, &b);
}
int exercise(const std::string &mode, const std::string &dxil_path, const std::string &root_path,
             const std::string &prefix, unsigned seed, unsigned multiplier, unsigned bias,
             unsigned work, unsigned descriptor_index)
{
    const bool copy_only = mode == "copy";
    const unsigned payload = copy_only ? work : (2048 + 16) * 4;
    require(payload && payload <= 4 * 1024 * 1024 && descriptor_index < 8 &&
            (copy_only || (work >= 1 && work <= 1024 / 64)), "test workload outside range");
    evidence.reserve(prefix, "phase", 3);
    ID3D12Device *raw = nullptr;
    require(FAILED(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_ID3D12Device,
                                    reinterpret_cast<void **>(&raw))) && !raw, "standard feature level falsely advertised");
    printf("standard_feature_level_rejected=1\n");
    const HRESULT created = Ndx12CreateExperimentalDevice(mode == "no-device" ? "/dev/null" : "/dev/dri/renderD128",
                                                          IID_ID3D12Device, reinterpret_cast<void **>(&raw));
    if (mode == "no-device") { require(FAILED(created) && !raw, "missing GPU accepted"); puts("result=EXPECTED_DEVICE_REJECTION"); return 0; }
    hr(created, "Ndx12CreateExperimentalDevice"); Com<ID3D12Device> device(raw);
    const unsigned offset = 64, bytes = payload + 128;
    auto upload = buffer(raw, bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto gpu = buffer(raw, bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_SOURCE, !copy_only);
    auto decoy = buffer(raw, bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_SOURCE, !copy_only);
    auto readback = buffer(raw, bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    ID3D12Device *parent = nullptr;
    hr(ID3D12Resource_GetDevice(gpu.get(), IID_ID3D12Device, reinterpret_cast<void **>(&parent)), "GetDevice");
    require(parent == raw, "device identity mismatch"); ID3D12Device_Release(parent);
    IUnknown *identity = nullptr;
    hr(ID3D12Resource_QueryInterface(gpu.get(), IID_IUnknown, reinterpret_cast<void **>(&identity)), "QueryInterface");
    require(static_cast<void *>(identity) == static_cast<void *>(gpu.get()), "IUnknown identity mismatch");
    IUnknown_Release(identity);
    void *unsupported = reinterpret_cast<void *>(1);
    require(ID3D12Resource_QueryInterface(gpu.get(), IID_ID3D12Device, &unsupported) == E_NOINTERFACE && !unsupported,
            "unsupported interface accepted");
    const auto n = ID3D12Resource_AddRef(gpu.get());
    require(ID3D12Resource_Release(gpu.get()) == n - 1, "reference counting mismatch");
    void *bad_map = nullptr;
    require(FAILED(ID3D12Resource_Map(gpu.get(), 0, nullptr, &bad_map)) && !bad_map, "DEFAULT resource mapped");
    require(ID3D12Resource_GetGPUVirtualAddress(gpu.get()) != 0, "missing GPU VA");
    puts("com_identity_and_lifetime_checks=PASS");
    const UINT64 baseline_objects = Ndx12LiveObjects();
    for (unsigned cycle = 0; cycle < 8; ++cycle) {
        {
            auto temporary = buffer(raw, 4096 + cycle * 256, D3D12_HEAP_TYPE_UPLOAD,
                                    D3D12_RESOURCE_STATE_GENERIC_READ);
            void *p = nullptr; const D3D12_RANGE no_read{0, 0};
            hr(ID3D12Resource_Map(temporary.get(), 0, &no_read, &p), "temporary Map");
            std::memset(p, int(cycle), 4096 + cycle * 256);
            ID3D12Resource_Unmap(temporary.get(), 0, nullptr);
        }
        Ndx12Stats stats{}; hr(Ndx12GetStats(raw, &stats), "lifetime stats");
        require(stats.live_buffers == 4 && Ndx12LiveObjects() == baseline_objects,
                "resource lifetime count did not return to baseline");
    }
    puts("resource_lifetime_cycles=8");
    ID3D12CommandQueue *q = nullptr;
    D3D12_COMMAND_QUEUE_DESC qdesc{}; qdesc.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    hr(ID3D12Device_CreateCommandQueue(raw, &qdesc, IID_ID3D12CommandQueue, reinterpret_cast<void **>(&q)), "CreateCommandQueue");
    Com<ID3D12CommandQueue> queue(q);
    ID3D12CommandAllocator *a = nullptr;
    hr(ID3D12Device_CreateCommandAllocator(raw, D3D12_COMMAND_LIST_TYPE_COMPUTE, IID_ID3D12CommandAllocator,
                                          reinterpret_cast<void **>(&a)), "CreateCommandAllocator");
    Com<ID3D12CommandAllocator> allocator(a);
    ID3D12GraphicsCommandList *l = nullptr;
    hr(ID3D12Device_CreateCommandList(raw, 0, D3D12_COMMAND_LIST_TYPE_COMPUTE, a, nullptr,
                                     IID_ID3D12GraphicsCommandList, reinterpret_cast<void **>(&l)), "CreateCommandList");
    Com<ID3D12GraphicsCommandList> list(l);
    require(FAILED(ID3D12CommandAllocator_Reset(a)), "allocator reset while recording accepted");
    ID3D12Fence *f = nullptr;
    hr(ID3D12Device_CreateFence(raw, 0, D3D12_FENCE_FLAG_NONE, IID_ID3D12Fence, reinterpret_cast<void **>(&f)), "CreateFence");
    Com<ID3D12Fence> fence(f);
    Com<ID3D12RootSignature> root;
    Com<ID3D12PipelineState> pipeline;
    Com<ID3D12DescriptorHeap> heap;
    if (!copy_only) {
        auto rootsig = read(root_path);
        if (mode == "bad-root") rootsig.resize(24);
        ID3D12RootSignature *r = nullptr;
        const auto result = ID3D12Device_CreateRootSignature(raw, 0, rootsig.data(), rootsig.size(),
                                                             IID_ID3D12RootSignature, reinterpret_cast<void **>(&r));
        if (mode == "bad-root") { require(FAILED(result) && !r, "bad root accepted"); puts("result=EXPECTED_ROOT_REJECTION"); return 0; }
        hr(result, "CreateRootSignature"); root.reset(r);
        auto dxil = read(dxil_path);
        if (mode == "bad-dxil") dxil.resize(24);
        D3D12_COMPUTE_PIPELINE_STATE_DESC p{}; p.pRootSignature = r; p.CS = {dxil.data(), dxil.size()};
        ID3D12PipelineState *pso = nullptr;
        const auto compiled = ID3D12Device_CreateComputePipelineState(raw, &p, IID_ID3D12PipelineState,
                                                                      reinterpret_cast<void **>(&pso));
        if (mode == "bad-dxil" || mode == "wrong-root") {
            require(FAILED(compiled) && !pso, "bad shader or mismatched root accepted");
            puts("result=EXPECTED_SHADER_REJECTION"); return 0;
        }
        hr(compiled, "CreateComputePipelineState"); pipeline.reset(pso);
        D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        hd.NumDescriptors = 8; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        ID3D12DescriptorHeap *h = nullptr;
        hr(ID3D12Device_CreateDescriptorHeap(raw, &hd, IID_ID3D12DescriptorHeap, reinterpret_cast<void **>(&h)), "CreateDescriptorHeap");
        heap.reset(h);
        auto cpu = ID3D12DescriptorHeap_GetCPUDescriptorHandleForHeapStart(h);
        cpu.ptr += descriptor_index * ID3D12Device_GetDescriptorHandleIncrementSize(raw, hd.Type);
        D3D12_UNORDERED_ACCESS_VIEW_DESC view{}; view.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        view.Buffer.FirstElement = offset / 4; view.Buffer.NumElements = payload / 4; view.Buffer.StructureByteStride = 4;
        ID3D12Device_CreateUnorderedAccessView(raw, mode == "wrong-buffer" ? decoy.get() : gpu.get(), nullptr, &view, cpu);
    }
    auto record = [&] {
        transition(l, gpu.get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
        transition(l, decoy.get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
        ID3D12GraphicsCommandList_CopyBufferRegion(l, gpu.get(), 0, upload.get(), 0,
                                                   mode == "bad-range" ? bytes + 1 : bytes);
        ID3D12GraphicsCommandList_CopyBufferRegion(l, decoy.get(), 0, upload.get(), 0, bytes);
        if (copy_only) ID3D12GraphicsCommandList_CopyBufferRegion(l, gpu.get(), 96, upload.get(), 64, payload);
        if (!copy_only) {
            transition(l, gpu.get(), mode == "bad-state" ? D3D12_RESOURCE_STATE_COPY_SOURCE : D3D12_RESOURCE_STATE_COPY_DEST,
                        D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            transition(l, decoy.get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            ID3D12GraphicsCommandList_SetPipelineState(l, pipeline.get());
            ID3D12GraphicsCommandList_SetComputeRootSignature(l, root.get());
            auto *h = heap.get(); ID3D12GraphicsCommandList_SetDescriptorHeaps(l, 1, &h);
            auto handle = ID3D12DescriptorHeap_GetGPUDescriptorHandleForHeapStart(h);
            handle.ptr += descriptor_index * ID3D12Device_GetDescriptorHandleIncrementSize(raw, D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            ID3D12GraphicsCommandList_SetComputeRootDescriptorTable(l, 0, handle);
            if (mode != "no-dispatch") ID3D12GraphicsCommandList_Dispatch(l, work, 1, 1);
            transition(l, gpu.get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
            transition(l, decoy.get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
        } else {
            transition(l, gpu.get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COPY_SOURCE);
            transition(l, decoy.get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COPY_SOURCE);
        }
        ID3D12GraphicsCommandList_CopyBufferRegion(l, readback.get(), 0, gpu.get(), 0, bytes);
    };
    if (mode == "bad-range") {
        ID3D12GraphicsCommandList_CopyBufferRegion(l, gpu.get(), 0, upload.get(), 0, bytes + 1);
        require(FAILED(ID3D12GraphicsCommandList_Close(l)), "out of range copy accepted");
        puts("result=EXPECTED_RANGE_REJECTION"); return 0;
    }
    record();
    if (mode != "open-list") hr(ID3D12GraphicsCommandList_Close(l), "Close");
    if (mode == "stale-allocator") hr(ID3D12CommandAllocator_Reset(a), "Reset allocator for negative control");
    unsigned total_mismatches = 0;
    snapshot(prefix, "before-dispatch");
    for (unsigned phase = 0; phase < 3; ++phase) {
        std::vector<uint32_t> initial((bytes + 3) / 4, guard);
        if (copy_only) {
            for (unsigned i = 0; i < initial.size(); ++i) initial[i] = ((i * 17u + seed + phase * 101u) ^ (i >> 2));
        } else {
            for (unsigned i = 0; i < 1024; ++i) {
                initial[offset / 4 + i] = (i * 17u + seed + phase * 101u) ^ (i >> 2);
                initial[offset / 4 + 1024 + i] = sentinel;
            }
        }
        void *mapped = nullptr; const D3D12_RANGE no_read{0, 0};
        hr(ID3D12Resource_Map(upload.get(), 0, &no_read, &mapped), "Map upload");
        std::memcpy(mapped, initial.data(), bytes);
        const D3D12_RANGE written{0, bytes}; ID3D12Resource_Unmap(upload.get(), 0, &written);
        if (phase == 2) {
            hr(ID3D12CommandAllocator_Reset(a), "Reset allocator after completion");
            hr(ID3D12GraphicsCommandList_Reset(l, a, nullptr), "Reset list after completion");
            record(); hr(ID3D12GraphicsCommandList_Close(l), "Close reset list");
        }
        auto *base = reinterpret_cast<ID3D12CommandList *>(l);
        ID3D12CommandQueue_ExecuteCommandLists(q, 1, &base);
        if (mode == "open-list" || mode == "bad-state" || mode == "stale-allocator") {
            require(FAILED(ID3D12Device_GetDeviceRemovedReason(raw)), "invalid command submission accepted");
            Ndx12Stats s{}; hr(Ndx12GetStats(raw, &s), "stats");
            require(!s.copies && !s.dispatches && !s.submissions, "invalid list partly executed");
            printf("copies=%llu\ndispatches=%llu\nresult=EXPECTED_SUBMISSION_REJECTION\n",
                   static_cast<unsigned long long>(s.copies), static_cast<unsigned long long>(s.dispatches));
            snapshot(prefix, "after-readback"); return 0;
        }
        hr(ID3D12Device_GetDeviceRemovedReason(raw), "ExecuteCommandLists");
        hr(ID3D12CommandQueue_Signal(q, f, phase + 1), "Queue Signal");
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
        while (ID3D12Fence_GetCompletedValue(f) < phase + 1) {
            require(std::chrono::steady_clock::now() < deadline, "fence timeout");
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        require(ID3D12Fence_GetCompletedValue(f) == phase + 1, "wrong completed fence value");
        const D3D12_RANGE read_range{0, bytes};
        hr(ID3D12Resource_Map(readback.get(), 0, &read_range, &mapped), "Map readback");
        std::vector<uint32_t> actual(initial.size());
        std::memcpy(actual.data(), mapped, bytes);
        ID3D12Resource_Unmap(readback.get(), 0, &no_read);
        evidence.write(2 + phase, actual.data(), bytes);
        auto expected = initial;
        if (copy_only) std::copy_n(reinterpret_cast<const BYTE *>(initial.data()) + 64, payload,
                                   reinterpret_cast<BYTE *>(expected.data()) + 96);
        if (!copy_only) for (unsigned i = 0; i < work * 64; ++i)
            expected[offset / 4 + 1024 + i] = (initial[offset / 4 + i] * multiplier + bias) ^ (i * 0x9e3779b9u);
        unsigned mismatches = 0;
        for (unsigned i = 0; i < bytes; ++i)
            mismatches += reinterpret_cast<const BYTE *>(actual.data())[i] != reinterpret_cast<const BYTE *>(expected.data())[i];
        total_mismatches += mismatches;
        if (mode == "no-dispatch" || mode == "wrong-buffer") {
            require(actual == initial && mismatches, "negative result control failed");
        } else require(!mismatches, "GPU readback mismatch");
        printf("phase%u_checked_bytes=%u\nphase%u_byte_mismatches=%u\nphase%u_fence=%u\n",
               phase, bytes, phase, mismatches, phase, phase + 1);
    }
    snapshot(prefix, "after-readback");
    Ndx12Stats stats{}; hr(Ndx12GetStats(raw, &stats), "GetStats");
    require(stats.context_reset_status == 0 && stats.live_buffers == 4, "reset or buffer count mismatch");
    printf("copies=%llu\ndispatches=%llu\nsubmissions=%llu\nshader_compiles=%llu\ncontext_reset_status=%u\n"
           "command_list_replayed=1\nallocator_and_list_reset=1\ntotal_byte_mismatches=%u\nresult=%s\n",
           static_cast<unsigned long long>(stats.copies), static_cast<unsigned long long>(stats.dispatches),
           static_cast<unsigned long long>(stats.submissions), static_cast<unsigned long long>(stats.shader_compiles),
           stats.context_reset_status, total_mismatches, total_mismatches ? "EXPECTED_RESULT_MISMATCH" : "PASS");
    return 0;
}
}
int main(int argc, char **argv)
{
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    try {
        require(argc == 10, "usage: ndx12-m1 mode dxil rootsig prefix seed multiplier bias groups-or-copy-bytes descriptor-index");
        const int result = exercise(argv[1], argv[2], argv[3], argv[4], number(argv[5]),
                                     number(argv[6]), number(argv[7]), number(argv[8]), number(argv[9]));
        evidence.finish();
        require(Ndx12LiveObjects() == 0, "COM objects leaked");
        puts("live_objects_after_release=0");
        return result;
    } catch (const std::exception &e) {
        std::fprintf(stderr, "FAIL=%s\n", e.what());
        std::fprintf(stderr, "live_objects_after_failure=%llu\n", static_cast<unsigned long long>(Ndx12LiveObjects()));
        return 2;
    }
}
