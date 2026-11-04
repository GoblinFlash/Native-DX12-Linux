#include "ndx12.h"
#include "evidence_outputs.h"
#include <algorithm>
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
constexpr unsigned tw = 8, th = 4, upload_pitch = 256, upload_offset = 1024;
constexpr unsigned upload_bytes = upload_offset + upload_pitch * th + 512;
using Pixel = std::array<unsigned char, 4>;
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
Com<ID3D12Resource> resource(ID3D12Device *d, unsigned w, unsigned h, bool texture,
                            D3D12_HEAP_TYPE type, bool target = false) {
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = type; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = texture ? D3D12_RESOURCE_DIMENSION_TEXTURE2D : D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = w; desc.Height = h; desc.DepthOrArraySize = desc.MipLevels = desc.SampleDesc.Count = 1;
    desc.Format = texture ? DXGI_FORMAT_R8G8B8A8_UNORM : DXGI_FORMAT_UNKNOWN;
    desc.Layout = texture ? D3D12_TEXTURE_LAYOUT_UNKNOWN : D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    desc.Flags = target ? D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET : D3D12_RESOURCE_FLAG_NONE;
    const auto state = target ? D3D12_RESOURCE_STATE_COPY_SOURCE : type == D3D12_HEAP_TYPE_UPLOAD ?
        D3D12_RESOURCE_STATE_GENERIC_READ : D3D12_RESOURCE_STATE_COPY_DEST;
    ID3D12Resource *r = nullptr;
    hr(ID3D12Device_CreateCommittedResource(d, &heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr,
                                           IID_ID3D12Resource, reinterpret_cast<void **>(&r)), "CreateCommittedResource");
    return Com<ID3D12Resource>(r);
}
Com<ID3D12DescriptorHeap> heap(ID3D12Device *d, D3D12_DESCRIPTOR_HEAP_TYPE type) {
    D3D12_DESCRIPTOR_HEAP_DESC desc{}; desc.Type = type; desc.NumDescriptors = 8;
    desc.Flags = type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV ? D3D12_DESCRIPTOR_HEAP_FLAG_NONE : D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ID3D12DescriptorHeap *h = nullptr;
    hr(ID3D12Device_CreateDescriptorHeap(d, &desc, IID_ID3D12DescriptorHeap, reinterpret_cast<void **>(&h)), "CreateDescriptorHeap");
    return Com<ID3D12DescriptorHeap>(h);
}
D3D12_CPU_DESCRIPTOR_HANDLE cpu(ID3D12Device *d, ID3D12DescriptorHeap *h, unsigned slot) {
    auto v = ID3D12DescriptorHeap_GetCPUDescriptorHandleForHeapStart(h);
    v.ptr += slot * ID3D12Device_GetDescriptorHandleIncrementSize(d, ID3D12DescriptorHeap_GetDesc(h).Type); return v;
}
D3D12_GPU_DESCRIPTOR_HANDLE gpu(ID3D12Device *d, ID3D12DescriptorHeap *h, unsigned slot) {
    auto v = ID3D12DescriptorHeap_GetGPUDescriptorHandleForHeapStart(h);
    v.ptr += slot * ID3D12Device_GetDescriptorHandleIncrementSize(d, ID3D12DescriptorHeap_GetDesc(h).Type); return v;
}
void transition(ID3D12GraphicsCommandList *l, ID3D12Resource *r, D3D12_RESOURCE_STATES from, D3D12_RESOURCE_STATES to) {
    D3D12_RESOURCE_BARRIER b{}; b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, from, to};
    ID3D12GraphicsCommandList_ResourceBarrier(l, 1, &b);
}
D3D12_TEXTURE_COPY_LOCATION subresource(ID3D12Resource *r) {
    D3D12_TEXTURE_COPY_LOCATION v{}; v.pResource = r; v.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; return v;
}
D3D12_TEXTURE_COPY_LOCATION footprint(ID3D12Resource *r, unsigned w, unsigned h, unsigned row, unsigned at) {
    D3D12_TEXTURE_COPY_LOCATION v{}; v.pResource = r; v.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    v.PlacedFootprint.Offset = at; v.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, w, h, 1, row}; return v;
}
Pixel texel(unsigned texture, unsigned frame, unsigned x, unsigned y) {
    return {static_cast<unsigned char>(17 + x * 23 + frame * 7),
            static_cast<unsigned char>(31 + y * 47 + frame * 11),
            static_cast<unsigned char>(texture ? 211 - frame * 13 : 19 + frame * 13), 255};
}
Pixel reference(unsigned frame, unsigned x, unsigned y, bool wrong_texture, bool wrong_sampler, bool no_draw) {
    if (no_draw || x < 16 || x >= 80 || y < 16 || y >= 64) return {0, 0, 0, 255};
    double u = (x + .5 - 16) / 64.0, v = (y + .5 - 16) / 48.0;
    if (frame) { u = u * 2 - .5; v = v * 2 - .5; }
    const bool repeat = (frame == 1) != wrong_sampler;
    if (repeat) { u -= std::floor(u); v -= std::floor(v); }
    const auto ix = static_cast<unsigned>(std::clamp(int(std::floor(u * tw)), 0, int(tw - 1)));
    const auto iy = static_cast<unsigned>(std::clamp(int(std::floor(v * th)), 0, int(th - 1)));
    return texel((frame % 2) ^ unsigned(wrong_texture), frame, ix, iy);
}
void rejected_without_work(ID3D12Device *d, const std::string &prefix) {
    Ndx12Stats s{}; Ndx12GraphicsStats g{};
    hr(Ndx12GetStats(d, &s), "GetStats"); hr(Ndx12GetGraphicsStats(d, &g), "GetGraphicsStats");
    require(!s.submissions && !s.copies && !g.draws && !g.clears && !g.texture_copies && !s.context_reset_status,
            "invalid input partially executed");
    snapshot(prefix, "after-rejection"); puts("context_reset_status=0\nresult=EXPECTED_REJECTION");
}
void exercise(const std::string &mode, const std::string &fixtures, const std::string &prefix) {
    evidence.reserve(prefix, "frame", 3);
    ID3D12Device *d = nullptr;
    require(FAILED(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_ID3D12Device,
                                    reinterpret_cast<void **>(&d))) && !d, "feature level overclaim");
    puts("standard_feature_level_rejected=1");
    hr(Ndx12CreateExperimentalDevice("/dev/dri/renderD128", IID_ID3D12Device, reinterpret_cast<void **>(&d)), "Create device");
    Com<ID3D12Device> device(d);
    auto root_blob = read(fixtures + (mode == "bad-root-srv" ? "/wrong-srv.bin" :
                                     mode == "bad-root-sampler" ? "/wrong-sampler.bin" : "/root.bin"));
    ID3D12RootSignature *r = nullptr;
    hr(ID3D12Device_CreateRootSignature(d, 0, root_blob.data(), root_blob.size(), IID_ID3D12RootSignature,
                                       reinterpret_cast<void **>(&r)), "CreateRootSignature");
    Com<ID3D12RootSignature> root(r);
    std::array<Com<ID3D12PipelineState>, 2> pipelines;
    for (unsigned i = 0; i < 2; ++i) {
        auto vs = read(fixtures + "/quad.vs.dxil"), ps = read(fixtures + (i ? "/b.ps.dxil" : "/a.ps.dxil"));
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
        if (mode == "bad-root-srv" || mode == "bad-root-sampler") {
            require(FAILED(result) && !out, "mismatched register accepted"); rejected_without_work(d, prefix); return;
        }
        hr(result, "CreateGraphicsPipelineState"); pipelines[i].reset(out);
    }
    D3D12_COMMAND_QUEUE_DESC qd{}; qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ID3D12CommandQueue *q = nullptr; ID3D12CommandAllocator *a = nullptr; ID3D12GraphicsCommandList *l = nullptr; ID3D12Fence *f = nullptr;
    hr(ID3D12Device_CreateCommandQueue(d, &qd, IID_ID3D12CommandQueue, reinterpret_cast<void **>(&q)), "CreateCommandQueue");
    Com<ID3D12CommandQueue> queue(q);
    hr(ID3D12Device_CreateCommandAllocator(d, qd.Type, IID_ID3D12CommandAllocator, reinterpret_cast<void **>(&a)), "CreateCommandAllocator");
    Com<ID3D12CommandAllocator> allocator(a);
    hr(ID3D12Device_CreateCommandList(d, 0, qd.Type, a, nullptr, IID_ID3D12GraphicsCommandList,
                                     reinterpret_cast<void **>(&l)), "CreateCommandList");
    Com<ID3D12GraphicsCommandList> list(l);
    hr(ID3D12Device_CreateFence(d, 0, D3D12_FENCE_FLAG_NONE, IID_ID3D12Fence, reinterpret_cast<void **>(&f)), "CreateFence");
    Com<ID3D12Fence> fence(f);
    auto target = resource(d, width, height, true, D3D12_HEAP_TYPE_DEFAULT, true);
    std::array<Com<ID3D12Resource>, 2> textures{resource(d, tw, th, true, D3D12_HEAP_TYPE_DEFAULT),
                                             resource(d, tw, th, true, D3D12_HEAP_TYPE_DEFAULT)};
    std::array<Com<ID3D12Resource>, 2> uploads{resource(d, upload_bytes, 1, false, D3D12_HEAP_TYPE_UPLOAD),
                                            resource(d, upload_bytes, 1, false, D3D12_HEAP_TYPE_UPLOAD)};
    auto guard_upload = resource(d, bytes, 1, false, D3D12_HEAP_TYPE_UPLOAD);
    auto readback = resource(d, bytes, 1, false, D3D12_HEAP_TYPE_READBACK);
    auto rtv = heap(d, D3D12_DESCRIPTOR_HEAP_TYPE_RTV), srv = heap(d, D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV),
         samplers = heap(d, D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER);
    const auto rt = cpu(d, rtv.get(), 3); ID3D12Device_CreateRenderTargetView(d, target.get(), nullptr, rt);
    hr(ID3D12Device_GetDeviceRemovedReason(d), "setup"); snapshot(prefix, "before-dispatch");
    unsigned all_mismatches = 0;
    for (unsigned frame = 0; frame < 3; ++frame) {
        if (frame) {
            hr(ID3D12CommandAllocator_Reset(a), "Reset allocator"); hr(ID3D12GraphicsCommandList_Reset(l, a, nullptr), "Reset list");
        }
        const auto guard = static_cast<unsigned char>(0xa1 + frame * 13);
        D3D12_RANGE empty{0, 0}, full{0, bytes}; void *mapped = nullptr;
        hr(ID3D12Resource_Map(guard_upload.get(), 0, &empty, &mapped), "Map guards");
        std::memset(mapped, guard, bytes); ID3D12Resource_Unmap(guard_upload.get(), 0, &full);
        ID3D12GraphicsCommandList_CopyBufferRegion(l, readback.get(), 0, guard_upload.get(), 0, bytes);
        const unsigned srv_slot = 1 + frame * 2, sampler_slot = 6 - frame * 2;
        for (unsigned t = 0; t < 2; ++t) {
            D3D12_RANGE written{0, upload_bytes};
            hr(ID3D12Resource_Map(uploads[t].get(), 0, &empty, &mapped), "Map texture upload");
            auto *p = static_cast<unsigned char *>(mapped); std::memset(p, 0xd7, upload_bytes);
            for (unsigned y = 0; y < th; ++y) for (unsigned x = 0; x < tw; ++x) {
                const auto c = texel(t, frame, x, y); std::memcpy(p + upload_offset + y * upload_pitch + x * 4, c.data(), 4);
            }
            ID3D12Resource_Unmap(uploads[t].get(), 0, &written);
            if (frame) transition(l, textures[t].get(), D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
            auto src = footprint(uploads[t].get(), tw, th, mode == "bad-upload-pitch" ? 32 : upload_pitch,
                                 mode == "bad-upload-offset" ? 1 : upload_offset);
            auto dst = subresource(textures[t].get()); ID3D12GraphicsCommandList_CopyTextureRegion(l, &dst, 0, 0, 0, &src, nullptr);
            if (mode != "bad-state") transition(l, textures[t].get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
            D3D12_SHADER_RESOURCE_VIEW_DESC view{}; view.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
            view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            view.Texture2D.MipLevels = mode == "bad-srv" ? 2 : 1;
            if (mode != "missing-srv") ID3D12Device_CreateShaderResourceView(d, textures[t].get(), &view, cpu(d, srv.get(), srv_slot + t));
            D3D12_SAMPLER_DESC sampler{}; sampler.Filter = mode == "bad-filter" ? D3D12_FILTER_MIN_MAG_MIP_LINEAR : D3D12_FILTER_MIN_MAG_MIP_POINT;
            sampler.AddressU = sampler.AddressV = t ? D3D12_TEXTURE_ADDRESS_MODE_WRAP : D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
            sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP; sampler.MaxAnisotropy = 1; sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_NEVER;
            if (mode != "missing-sampler") ID3D12Device_CreateSampler(d, &sampler, cpu(d, samplers.get(), sampler_slot + t));
        }
        transition(l, target.get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        const float clear[4]{0, 0, 0, 1}; ID3D12GraphicsCommandList_ClearRenderTargetView(l, rt, clear, 0, nullptr);
        ID3D12GraphicsCommandList_SetPipelineState(l, pipelines[frame ? 1 : 0].get());
        ID3D12GraphicsCommandList_SetGraphicsRootSignature(l, r);
        ID3D12DescriptorHeap *heaps[]{srv.get(), samplers.get()}; ID3D12GraphicsCommandList_SetDescriptorHeaps(l, 2, heaps);
        const unsigned selected_texture = (frame % 2) ^ unsigned(mode == "wrong-srv");
        const unsigned selected_sampler = unsigned(frame == 1) ^ unsigned(mode == "wrong-sampler");
        ID3D12GraphicsCommandList_SetGraphicsRootDescriptorTable(l, 0, gpu(d, srv.get(), srv_slot + selected_texture));
        if (mode != "unset-sampler") ID3D12GraphicsCommandList_SetGraphicsRootDescriptorTable(l, 1, gpu(d, samplers.get(), sampler_slot + selected_sampler));
        if (mode == "heap-switch") ID3D12GraphicsCommandList_SetDescriptorHeaps(l, 1, heaps);
        ID3D12GraphicsCommandList_IASetPrimitiveTopology(l, D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        const D3D12_VIEWPORT vp{0, 0, float(width), float(height), 0, 1}; const D3D12_RECT sc{0, 0, width, height};
        ID3D12GraphicsCommandList_RSSetViewports(l, 1, &vp); ID3D12GraphicsCommandList_RSSetScissorRects(l, 1, &sc);
        ID3D12GraphicsCommandList_OMSetRenderTargets(l, 1, &rt, TRUE, nullptr);
        if (mode != "no-draw") ID3D12GraphicsCommandList_DrawInstanced(l, 6, 1, 0, 0);
        transition(l, target.get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
        auto source = subresource(target.get()), dest = footprint(readback.get(), width, height, pitch, offset);
        ID3D12GraphicsCommandList_CopyTextureRegion(l, &dest, 0, 0, 0, &source, nullptr);
        const auto closed = ID3D12GraphicsCommandList_Close(l);
        if (mode == "bad-upload-pitch" || mode == "bad-upload-offset" || mode == "bad-srv" || mode == "bad-filter" ||
            mode == "unset-sampler" || mode == "heap-switch") {
            require(FAILED(closed), "invalid recorded command accepted"); rejected_without_work(d, prefix); return;
        }
        hr(closed, "Close");
        auto *base = reinterpret_cast<ID3D12CommandList *>(l); ID3D12CommandQueue_ExecuteCommandLists(q, 1, &base);
        if (mode == "bad-state" || mode == "missing-srv" || mode == "missing-sampler") {
            require(FAILED(ID3D12Device_GetDeviceRemovedReason(d)), "invalid execution accepted"); rejected_without_work(d, prefix); return;
        }
        hr(ID3D12Device_GetDeviceRemovedReason(d), "ExecuteCommandLists"); hr(ID3D12CommandQueue_Signal(q, f, frame + 1), "Signal");
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
        while (ID3D12Fence_GetCompletedValue(f) != frame + 1) {
            require(std::chrono::steady_clock::now() < deadline, "GPU fence timeout"); std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        hr(ID3D12Resource_Map(readback.get(), 0, &full, &mapped), "Map readback");
        const auto *data = static_cast<const unsigned char *>(mapped);
        evidence.write(2 + frame, data, bytes);
        unsigned guards = 0, mismatch = 0, actual_mismatch = 0;
        for (unsigned i = 0; i < bytes; ++i) {
            const bool pixel = i >= offset && i < offset + pitch * height && (i - offset) % pitch < width * 4;
            if (!pixel && data[i] != guard) ++guards;
        }
        for (unsigned y = 0; y < height; ++y) for (unsigned x = 0; x < width; ++x) {
            const auto expected = reference(frame, x, y, false, false, false);
            const auto actual = reference(frame, x, y, mode == "wrong-srv", mode == "wrong-sampler", mode == "no-draw");
            mismatch += std::memcmp(data + offset + y * pitch + x * 4, expected.data(), 4) != 0;
            actual_mismatch += std::memcmp(data + offset + y * pitch + x * 4, actual.data(), 4) != 0;
        }
        ID3D12Resource_Unmap(readback.get(), 0, &empty);
        printf("frame%u_mismatched_pixels=%u\nframe%u_actual_mismatches=%u\nframe%u_checked_pixels=%u\n"
               "frame%u_guard_mismatches=%u\nframe%u_fence=%u\nframe%u_srv_slot=%u\nframe%u_sampler_slot=%u\n",
               frame, mismatch, frame, actual_mismatch, frame, width * height, frame, guards, frame, frame + 1,
               frame, srv_slot + selected_texture, frame, sampler_slot + selected_sampler);
        require(!guards && !actual_mismatch, "GPU image/guards differ from reference");
        all_mismatches += mismatch;
    }
    snapshot(prefix, "after-readback"); Ndx12Stats s{}; Ndx12GraphicsStats g{};
    hr(Ndx12GetStats(d, &s), "GetStats"); hr(Ndx12GetGraphicsStats(d, &g), "GetGraphicsStats");
    require(!s.context_reset_status && s.submissions == 3 && s.copies == 3 && !s.dispatches && s.shader_compiles == 4 &&
            g.draws == (mode == "no-draw" ? 0u : 3u) && g.clears == 3 && g.texture_copies == 9, "execution counters/reset");
    require(mode == "quad" ? !all_mismatches : all_mismatches > 0, "negative control did not detect corruption");
    printf("context_reset_status=%u\ndraws=%llu\ntexture_copies=%llu\nshader_compiles=%llu\n",
           s.context_reset_status, (unsigned long long)g.draws, (unsigned long long)g.texture_copies, (unsigned long long)s.shader_compiles);
    puts(mode == "quad" ? "result=PASS" : "result=EXPECTED_RESULT_MISMATCH");
}
}
int main(int argc, char **argv) {
    int result = 0;
    try { require(argc == 4, "usage: ndx12-m3-texture mode fixtures prefix"); exercise(argv[1], argv[2], argv[3]); evidence.finish(); }
    catch (const std::exception &e) { std::fprintf(stderr, "FAIL=%s\n", e.what()); result = 1; }
    printf("live_objects_after_release=%llu\n", (unsigned long long)Ndx12LiveObjects());
    return Ndx12LiveObjects() ? 1 : result;
}
