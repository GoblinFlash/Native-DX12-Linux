#include "ndx12.h"
#include "evidence_outputs.h"
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
EvidenceOutputs evidence;
constexpr unsigned width = 96, height = 80, pitch = 512, offset = 512;
constexpr unsigned bytes = offset + pitch * height + 512;
template<class T> struct Release { void operator()(T *p) const { if (p) p->lpVtbl->Release(p); } };
template<class T> using Com = std::unique_ptr<T, Release<T>>;
void require(bool ok, const char *text) { if (!ok) throw std::runtime_error(text); }
void hr(HRESULT value, const char *text) {
    if (FAILED(value)) { std::fprintf(stderr, "HRESULT=%08x %s\n", unsigned(value), text); throw std::runtime_error(text); }
}
std::vector<char> read(const std::string &path) {
    std::ifstream f(path, std::ios::binary); require(bool(f), "shader input unavailable");
    return {std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
}
void snapshot(const std::string &prefix, const char *phase) {
    std::ostringstream maps, fds;
    maps << "PHASE=" << phase << '\n'; std::ifstream input("/proc/self/maps"); maps << input.rdbuf();
    fds << "PHASE=" << phase << '\n';
    for (const auto &entry : std::filesystem::directory_iterator("/proc/self/fd")) {
        std::error_code ec; auto target = std::filesystem::read_symlink(entry.path(), ec).string();
        if (ec || target.find("/dev/dri/") == std::string::npos) continue;
        fds << "FD=" << entry.path().filename().string() << " TARGET=" << target << '\n';
        std::ifstream info("/proc/self/fdinfo/" + entry.path().filename().string()); fds << info.rdbuf();
    }
    require(bool(maps) && bool(fds), "evidence write failed");
    evidence.text(0, maps.str());
    evidence.text(1, fds.str());
}
Com<ID3D12Resource> resource(ID3D12Device *d, bool texture, D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = type; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
    D3D12_RESOURCE_DESC desc{}; desc.Dimension = texture ? D3D12_RESOURCE_DIMENSION_TEXTURE2D : D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = texture ? width : bytes; desc.Height = texture ? height : 1;
    desc.DepthOrArraySize = desc.MipLevels = desc.SampleDesc.Count = 1;
    desc.Format = texture ? DXGI_FORMAT_R8G8B8A8_UNORM : DXGI_FORMAT_UNKNOWN;
    desc.Layout = texture ? D3D12_TEXTURE_LAYOUT_UNKNOWN : D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    desc.Flags = texture ? D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET : D3D12_RESOURCE_FLAG_NONE;
    auto state = texture ? D3D12_RESOURCE_STATE_COPY_SOURCE : type == D3D12_HEAP_TYPE_UPLOAD ?
        D3D12_RESOURCE_STATE_GENERIC_READ : D3D12_RESOURCE_STATE_COPY_DEST;
    ID3D12Resource *r = nullptr;
    hr(ID3D12Device_CreateCommittedResource(d, &heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr,
                                           IID_ID3D12Resource, reinterpret_cast<void **>(&r)), "CreateCommittedResource");
    require(texture ? ID3D12Resource_GetGPUVirtualAddress(r) == 0 : ID3D12Resource_GetGPUVirtualAddress(r) != 0,
            "resource GPU address contract");
    return Com<ID3D12Resource>(r);
}
void transition(ID3D12GraphicsCommandList *l, ID3D12Resource *r, D3D12_RESOURCE_STATES from, D3D12_RESOURCE_STATES to) {
    D3D12_RESOURCE_BARRIER b{}; b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, from, to};
    ID3D12GraphicsCommandList_ResourceBarrier(l, 1, &b);
}
void exercise(const std::string &mode, const std::string &fixtures, const std::string &prefix) {
    evidence.reserve(prefix, "frame", 3);
    ID3D12Device *d = nullptr;
    require(FAILED(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_ID3D12Device,
                                    reinterpret_cast<void **>(&d))) && !d, "feature level overclaim");
    puts("standard_feature_level_rejected=1");
    hr(Ndx12CreateExperimentalDevice("/dev/dri/renderD128", IID_ID3D12Device, reinterpret_cast<void **>(&d)), "Create device");
    Com<ID3D12Device> device(d);
    auto root_blob = read(fixtures + "/root.bin"); ID3D12RootSignature *r = nullptr;
    hr(ID3D12Device_CreateRootSignature(d, 0, root_blob.data(), root_blob.size(), IID_ID3D12RootSignature,
                                       reinterpret_cast<void **>(&r)), "CreateRootSignature");
    Com<ID3D12RootSignature> root(r);
    std::array<Com<ID3D12PipelineState>, 2> pipelines;
    for (unsigned i = 0; i < 2; ++i) {
        const std::string variant = i ? "b" : "a";
        auto vs = read(fixtures + "/" + variant + ".vs.dxil"), ps = read(fixtures + "/" + variant + ".ps.dxil");
        if (mode == "bad-vs") vs = ps;
        if (mode == "bad-ps") ps = vs;
        if (mode == "truncated-dxil") vs.resize(24);
        D3D12_GRAPHICS_PIPELINE_STATE_DESC p{}; p.pRootSignature = r;
        p.VS = {vs.data(), vs.size()}; p.PS = {ps.data(), ps.size()};
        p.BlendState.RenderTarget[0].RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        p.SampleMask = UINT32_MAX; p.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        p.RasterizerState.CullMode = D3D12_CULL_MODE_NONE; p.RasterizerState.DepthClipEnable = TRUE;
        p.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        p.NumRenderTargets = 1; p.RTVFormats[0] = DXGI_FORMAT_R8G8B8A8_UNORM; p.SampleDesc.Count = 1;
        ID3D12PipelineState *out = nullptr;
        const auto result = ID3D12Device_CreateGraphicsPipelineState(d, &p, IID_ID3D12PipelineState,
                                                                    reinterpret_cast<void **>(&out));
        if (mode == "bad-vs" || mode == "bad-ps" || mode == "truncated-dxil") {
            require(FAILED(result) && !out, "bad graphics shader accepted"); puts("result=EXPECTED_SHADER_REJECTION"); return;
        }
        hr(result, "CreateGraphicsPipelineState"); pipelines[i].reset(out);
    }
    D3D12_COMMAND_QUEUE_DESC qd{}; qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ID3D12CommandQueue *q = nullptr;
    hr(ID3D12Device_CreateCommandQueue(d, &qd, IID_ID3D12CommandQueue, reinterpret_cast<void **>(&q)), "CreateCommandQueue");
    Com<ID3D12CommandQueue> queue(q);
    ID3D12CommandAllocator *a = nullptr;
    hr(ID3D12Device_CreateCommandAllocator(d, qd.Type, IID_ID3D12CommandAllocator, reinterpret_cast<void **>(&a)), "CreateCommandAllocator");
    Com<ID3D12CommandAllocator> allocator(a);
    ID3D12GraphicsCommandList *l = nullptr;
    hr(ID3D12Device_CreateCommandList(d, 0, qd.Type, a, nullptr, IID_ID3D12GraphicsCommandList,
                                     reinterpret_cast<void **>(&l)), "CreateCommandList");
    Com<ID3D12GraphicsCommandList> list(l);
    require(ID3D12GraphicsCommandList_GetType(l) == qd.Type, "list type mismatch");
    ID3D12Fence *f = nullptr;
    hr(ID3D12Device_CreateFence(d, 0, D3D12_FENCE_FLAG_NONE, IID_ID3D12Fence, reinterpret_cast<void **>(&f)), "CreateFence");
    Com<ID3D12Fence> fence(f);
    std::array<Com<ID3D12Resource>, 2> targets{resource(d, true, D3D12_HEAP_TYPE_DEFAULT), resource(d, true, D3D12_HEAP_TYPE_DEFAULT)};
    auto upload = resource(d, false, D3D12_HEAP_TYPE_UPLOAD), readback = resource(d, false, D3D12_HEAP_TYPE_READBACK);
    D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV; hd.NumDescriptors = 4;
    ID3D12DescriptorHeap *h = nullptr;
    hr(ID3D12Device_CreateDescriptorHeap(d, &hd, IID_ID3D12DescriptorHeap, reinterpret_cast<void **>(&h)), "CreateDescriptorHeap RTV");
    Com<ID3D12DescriptorHeap> heap(h);
    std::array<D3D12_CPU_DESCRIPTOR_HANDLE, 2> handles{};
    const auto start = ID3D12DescriptorHeap_GetCPUDescriptorHandleForHeapStart(h);
    const auto stride = ID3D12Device_GetDescriptorHandleIncrementSize(d, hd.Type);
    for (unsigned i = 0; i < 2; ++i) {
        handles[i].ptr = start.ptr + (i * 2 + 1) * stride;
        ID3D12Device_CreateRenderTargetView(d, targets[i].get(), nullptr, handles[i]);
    }
    hr(ID3D12Device_GetDeviceRemovedReason(d), "setup API error"); snapshot(prefix, "before-draw");
    unsigned all_mismatches = 0;
    for (unsigned frame = 0; frame < 3; ++frame) {
        if (frame) {
            hr(ID3D12CommandAllocator_Reset(a), "Reset allocator");
            hr(ID3D12GraphicsCommandList_Reset(l, a, nullptr), "Reset list");
        }
        const unsigned target = frame % 2, shader = frame % 2;
        const unsigned char guard = static_cast<unsigned char>(0x93 + frame * 17);
        void *mapped = nullptr; D3D12_RANGE empty{0, 0}, full{0, bytes};
        hr(ID3D12Resource_Map(upload.get(), 0, &empty, &mapped), "Map upload");
        std::memset(mapped, guard, bytes); ID3D12Resource_Unmap(upload.get(), 0, &full);
        ID3D12GraphicsCommandList_CopyBufferRegion(l, readback.get(), 0, upload.get(), 0, bytes);
        const std::array<float, 4> clear{frame == 2 ? 1.f : 0.f, frame ? 1.f : 0.f, 0.f, 1.f};
        for (unsigned i = 0; i < 2; ++i) {
            transition(l, targets[i].get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
            ID3D12GraphicsCommandList_ClearRenderTargetView(l, handles[i], clear.data(), 0, nullptr);
        }
        ID3D12GraphicsCommandList_SetPipelineState(l, pipelines[shader].get());
        ID3D12GraphicsCommandList_SetGraphicsRootSignature(l, r);
        ID3D12GraphicsCommandList_IASetPrimitiveTopology(l, D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        const D3D12_VIEWPORT vp{frame == 2 ? 8.f : 0.f, frame == 2 ? 6.f : 0.f,
                                frame == 2 ? 80.f : float(width), frame == 2 ? 68.f : float(height), 0.f, 1.f};
        const D3D12_RECT sc{0, 0, frame == 2 ? LONG(width / 2) : LONG(width), LONG(height)};
        ID3D12GraphicsCommandList_RSSetViewports(l, 1, &vp); ID3D12GraphicsCommandList_RSSetScissorRects(l, 1, &sc);
        const auto draw_handle = handles[mode == "wrong-target" ? 1 - target : target];
        ID3D12GraphicsCommandList_OMSetRenderTargets(l, 1, &draw_handle, TRUE, nullptr);
        if (mode != "no-draw") ID3D12GraphicsCommandList_DrawInstanced(l, 3, 1, 0, 0);
        for (unsigned i = 0; i < 2; ++i)
            transition(l, targets[i].get(), mode == "bad-state" ? D3D12_RESOURCE_STATE_COPY_DEST : D3D12_RESOURCE_STATE_RENDER_TARGET,
                       D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION src{}, dst{};
        src.pResource = targets[target].get(); src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource = readback.get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dst.PlacedFootprint.Offset = mode == "bad-offset" ? 1 : offset;
        dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, width, height, 1, mode == "bad-pitch" ? width * 4 : pitch};
        ID3D12GraphicsCommandList_CopyTextureRegion(l, &dst, 0, 0, 0, &src, nullptr);
        const auto closed = ID3D12GraphicsCommandList_Close(l);
        if (mode == "bad-pitch" || mode == "bad-offset") {
            require(FAILED(closed), "invalid footprint accepted"); puts("result=EXPECTED_FOOTPRINT_REJECTION"); return;
        }
        hr(closed, "Close");
        auto *base = reinterpret_cast<ID3D12CommandList *>(l); ID3D12CommandQueue_ExecuteCommandLists(q, 1, &base);
        if (mode == "bad-state") {
            require(FAILED(ID3D12Device_GetDeviceRemovedReason(d)), "invalid state accepted");
            Ndx12Stats stats{}; Ndx12GraphicsStats graphics{};
            hr(Ndx12GetStats(d, &stats), "GetStats"); hr(Ndx12GetGraphicsStats(d, &graphics), "GetGraphicsStats");
            require(!stats.copies && !stats.submissions && !graphics.clears && !graphics.draws && !graphics.texture_copies,
                    "invalid list partially executed");
            snapshot(prefix, "after-rejection"); puts("result=EXPECTED_STATE_REJECTION"); return;
        }
        hr(ID3D12Device_GetDeviceRemovedReason(d), "ExecuteCommandLists");
        hr(ID3D12CommandQueue_Signal(q, f, frame + 1), "Signal");
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
        while (ID3D12Fence_GetCompletedValue(f) != frame + 1) {
            require(std::chrono::steady_clock::now() < deadline, "GPU fence timeout");
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        hr(ID3D12Resource_Map(readback.get(), 0, &full, &mapped), "Map readback");
        const auto *data = static_cast<const unsigned char *>(mapped);
        evidence.write(2 + frame, data, bytes);
        unsigned guard_mismatches = 0, mismatch = 0, checked = 0, edge = 0, inside_count = 0;
        for (unsigned i = 0; i < bytes; ++i) {
            const bool pixel = i >= offset && i < offset + pitch * height && (i - offset) % pitch < width * 4;
            if (!pixel && data[i] != guard) ++guard_mismatches;
        }
        const double shift = shader ? .25 : 0;
        const std::array<double, 3> px{vp.TopLeftX + (1 - .75 + shift) * vp.Width / 2,
            vp.TopLeftX + (1 + .75 + shift) * vp.Width / 2, vp.TopLeftX + (1 + shift) * vp.Width / 2};
        const std::array<double, 3> py{vp.TopLeftY + .25 * vp.Height / 2,
            vp.TopLeftY + .25 * vp.Height / 2, vp.TopLeftY + 1.75 * vp.Height / 2};
        for (unsigned y = 0; y < height; ++y) for (unsigned x = 0; x < width; ++x) {
            bool inside = true, near_edge = false;
            for (unsigned e = 0; e < 3; ++e) {
                const unsigned n = (e + 1) % 3; const double dx = px[n] - px[e], dy = py[n] - py[e];
                const double cross = dx * (y + .5 - py[e]) - dy * (x + .5 - px[e]);
                inside &= cross > 0; near_edge |= std::abs(cross) / std::hypot(dx, dy) < 1;
            }
            inside &= x < unsigned(sc.right);
            if (near_edge) { ++edge; continue; }
            const std::array<unsigned char, 4> expected = inside ?
                std::array<unsigned char, 4>{static_cast<unsigned char>(shader ? 0 : 255), 0,
                                            static_cast<unsigned char>(shader ? 255 : 0), 255} :
                std::array<unsigned char, 4>{static_cast<unsigned char>(clear[0] * 255),
                                            static_cast<unsigned char>(clear[1] * 255), 0, 255};
            ++checked; inside_count += inside;
            mismatch += std::memcmp(data + offset + y * pitch + x * 4, expected.data(), 4) != 0;
        }
        ID3D12Resource_Unmap(readback.get(), 0, &empty);
        require(!guard_mismatches && inside_count > 300 && checked > 6500, "readback guards or comparison coverage failed");
        printf("frame%u_mismatched_pixels=%u\nframe%u_checked_pixels=%u\nframe%u_edge_pixels=%u\n"
               "frame%u_interior_pixels=%u\nframe%u_guard_mismatches=%u\nframe%u_fence=%u\n",
               frame, mismatch, frame, checked, frame, edge, frame, inside_count, frame, guard_mismatches, frame, frame + 1);
        all_mismatches += mismatch;
        require((mode == "no-draw" || mode == "wrong-target") ? mismatch == inside_count : mismatch == 0,
                "GPU pixel comparison failed");
    }
    snapshot(prefix, "after-draw");
    Ndx12Stats stats{}; Ndx12GraphicsStats g{};
    hr(Ndx12GetStats(d, &stats), "GetStats"); hr(Ndx12GetGraphicsStats(d, &g), "GetGraphicsStats");
    require(stats.context_reset_status == 0 && stats.submissions == 3 && stats.copies == 3 && stats.dispatches == 0 &&
            stats.shader_compiles == 4 && g.draws == (mode == "no-draw" ? 0u : 3u) && g.clears == 6 && g.texture_copies == 3,
            "execution counters or reset check failed");
    printf("context_reset_status=%u\ndraws=%llu\nclears=%llu\ntexture_copies=%llu\nshader_compiles=%llu\n",
           stats.context_reset_status, (unsigned long long)g.draws, (unsigned long long)g.clears,
           (unsigned long long)g.texture_copies, (unsigned long long)stats.shader_compiles);
    puts(all_mismatches ? "result=EXPECTED_RESULT_MISMATCH" : "result=PASS");
}
}
int main(int argc, char **argv) {
    int result = 0;
    try { require(argc == 4, "usage: ndx12-m3 mode fixtures prefix"); exercise(argv[1], argv[2], argv[3]); evidence.finish(); }
    catch (const std::exception &e) { std::fprintf(stderr, "FAIL=%s\n", e.what()); result = 1; }
    printf("live_objects_after_release=%llu\n", (unsigned long long)Ndx12LiveObjects());
    return Ndx12LiveObjects() ? 1 : result;
}
