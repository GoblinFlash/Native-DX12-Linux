#include "ndx12.h"
#include "evidence_outputs.h"
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
EvidenceOutputs evidence;
constexpr unsigned width = 96, height = 80, pitch = 512, offset = 512;
constexpr unsigned bytes = offset + pitch * height + 512, index_bytes = 4096, frames = 6;
constexpr std::array<unsigned, frames> first_indices{3, 5, 1, 7, 3, 1};
constexpr std::array<unsigned, frames> raw_bias{8, 0, 4, 2, 0, 0};
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
Com<ID3D12Resource> resource(ID3D12Device *d, unsigned w, unsigned h, DXGI_FORMAT format,
                            D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES state) {
    const bool texture = format != DXGI_FORMAT_UNKNOWN;
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = type; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = texture ? D3D12_RESOURCE_DIMENSION_TEXTURE2D : D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = w; desc.Height = h; desc.DepthOrArraySize = desc.MipLevels = desc.SampleDesc.Count = 1;
    desc.Format = format; desc.Layout = texture ? D3D12_TEXTURE_LAYOUT_UNKNOWN : D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    desc.Flags = format == DXGI_FORMAT_D32_FLOAT ? D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL :
                 texture ? D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET : D3D12_RESOURCE_FLAG_NONE;
    D3D12_CLEAR_VALUE clear{}; clear.Format = format; clear.DepthStencil.Depth = 1;
    ID3D12Resource *r = nullptr;
    hr(ID3D12Device_CreateCommittedResource(d, &heap, D3D12_HEAP_FLAG_NONE, &desc, state,
                                           format == DXGI_FORMAT_D32_FLOAT ? &clear : nullptr,
                                           IID_ID3D12Resource, reinterpret_cast<void **>(&r)), "CreateCommittedResource");
    return Com<ID3D12Resource>(r);
}
Com<ID3D12DescriptorHeap> heap(ID3D12Device *d, D3D12_DESCRIPTOR_HEAP_TYPE type) {
    D3D12_DESCRIPTOR_HEAP_DESC desc{}; desc.Type = type; desc.NumDescriptors = 4;
    ID3D12DescriptorHeap *h = nullptr;
    hr(ID3D12Device_CreateDescriptorHeap(d, &desc, IID_ID3D12DescriptorHeap, reinterpret_cast<void **>(&h)), "CreateDescriptorHeap");
    return Com<ID3D12DescriptorHeap>(h);
}
D3D12_CPU_DESCRIPTOR_HANDLE cpu(ID3D12Device *d, ID3D12DescriptorHeap *h, unsigned slot) {
    auto v = ID3D12DescriptorHeap_GetCPUDescriptorHandleForHeapStart(h);
    v.ptr += slot * ID3D12Device_GetDescriptorHandleIncrementSize(d, ID3D12DescriptorHeap_GetDesc(h).Type); return v;
}
void transition(ID3D12GraphicsCommandList *l, ID3D12Resource *r, D3D12_RESOURCE_STATES from, D3D12_RESOURCE_STATES to) {
    D3D12_RESOURCE_BARRIER b{}; b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, from, to};
    ID3D12GraphicsCommandList_ResourceBarrier(l, 1, &b);
}
Pixel reference(unsigned frame, unsigned x, unsigned y, const std::string &mode) {
    Pixel color{0, 0, 0, 255};
    float depth = mode == "wrong-depth" ? 0.f : frame == 5 ? .5f : 1.f;
    for (unsigned draw = 0; draw < 2; ++draw) {
        const unsigned layer = frame == 1 ? 1 - draw : draw;
        if (mode == "no-draw" || mode == "wrong-base" || (mode == "wrong-indices" && !layer)) continue;
        const float px = x + .5f, py = y + .5f;
        if (px < 16 + layer * 16 || px >= 64 + layer * 16 || py < 12 + layer * 16 || py >= 56 + layer * 16) continue;
        const float z = layer && frame != 2 && frame != 3 ? .75f : .25f;
        if (mode == "no-depth" || (frame == 3 ? z <= depth : z < depth)) {
            color = layer ? Pixel{0, 0, 255, 255} : Pixel{255, 0, 0, 255};
            if (mode != "no-depth" && frame != 4) depth = z;
        }
    }
    return color;
}
void rejected_without_work(ID3D12Device *d, const std::string &prefix) {
    Ndx12Stats s{}; Ndx12GraphicsStats g{};
    hr(Ndx12GetStats(d, &s), "GetStats"); hr(Ndx12GetGraphicsStats(d, &g), "GetGraphicsStats");
    require(!s.submissions && !s.copies && !g.draws && !g.clears && !g.texture_copies && !s.context_reset_status,
            "invalid input partially executed");
    snapshot(prefix, "after-rejection"); puts("context_reset_status=0\nresult=EXPECTED_REJECTION");
}
void exercise(const std::string &mode, const std::string &fixtures, const std::string &prefix) {
    evidence.reserve(prefix, "frame", frames);
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
    auto target = resource(d, width, height, DXGI_FORMAT_R8G8B8A8_UNORM, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_SOURCE);
    std::array<Com<ID3D12Resource>, 2> depth;
    for (auto &z : depth) z = resource(d, mode == "bad-dsv-size" ? width - 1 : width, height, DXGI_FORMAT_D32_FLOAT,
                                      D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto guard_upload = resource(d, bytes, 1, DXGI_FORMAT_UNKNOWN, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto readback = resource(d, bytes, 1, DXGI_FORMAT_UNKNOWN, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    auto index_upload = resource(d, index_bytes, 1, DXGI_FORMAT_UNKNOWN, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto indices = resource(d, index_bytes, 1, DXGI_FORMAT_UNKNOWN, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto rtv = heap(d, D3D12_DESCRIPTOR_HEAP_TYPE_RTV), dsv = heap(d, D3D12_DESCRIPTOR_HEAP_TYPE_DSV);
    const auto rt = cpu(d, rtv.get(), 2); ID3D12Device_CreateRenderTargetView(d, target.get(), nullptr, rt);
    std::array<D3D12_CPU_DESCRIPTOR_HANDLE, 2> ds{cpu(d, dsv.get(), 1), cpu(d, dsv.get(), 3)};
    for (unsigned i = 0; i < 2; ++i) {
        D3D12_DEPTH_STENCIL_VIEW_DESC view{};
        view.Format = mode == "bad-dsv-format" ? DXGI_FORMAT_D24_UNORM_S8_UINT : DXGI_FORMAT_D32_FLOAT;
        view.ViewDimension = D3D12_DSV_DIMENSION_TEXTURE2D;
        ID3D12Device_CreateDepthStencilView(d, depth[i].get(), &view, ds[i]);
    }
    if (mode == "bad-dsv-format") {
        require(FAILED(ID3D12Device_GetDeviceRemovedReason(d)), "bad DSV accepted"); rejected_without_work(d, prefix); return;
    }
    hr(ID3D12Device_GetDeviceRemovedReason(d), "setup"); snapshot(prefix, "before-dispatch");
    unsigned all_mismatches = 0;
    for (unsigned frame = 0; frame < frames; ++frame) {
        if (frame) {
            hr(ID3D12CommandAllocator_Reset(a), "Reset allocator"); hr(ID3D12GraphicsCommandList_Reset(l, a, nullptr), "Reset list");
        }
        std::array<Com<ID3D12PipelineState>, 2> pipelines;
        for (unsigned layer = 0; layer < 2; ++layer) {
            auto vs = read(fixtures + (frame == 2 || frame == 3 ? "/equal.vs.dxil" : "/normal.vs.dxil"));
            auto ps = read(fixtures + (layer ? "/blue.ps.dxil" : "/red.ps.dxil"));
            D3D12_GRAPHICS_PIPELINE_STATE_DESC p{}; p.pRootSignature = r;
            p.VS = {vs.data(), vs.size()}; p.PS = {ps.data(), ps.size()};
            p.BlendState.RenderTarget[0].RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
            p.SampleMask = UINT32_MAX; p.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
            p.RasterizerState.CullMode = D3D12_CULL_MODE_NONE; p.RasterizerState.DepthClipEnable = TRUE;
            p.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
            p.NumRenderTargets = 1; p.RTVFormats[0] = DXGI_FORMAT_R8G8B8A8_UNORM; p.SampleDesc.Count = 1;
            p.DSVFormat = mode == "bad-depth-format" ? DXGI_FORMAT_UNKNOWN : DXGI_FORMAT_D32_FLOAT;
            p.DepthStencilState.DepthEnable = mode != "no-depth";
            p.DepthStencilState.DepthWriteMask = frame == 4 ? D3D12_DEPTH_WRITE_MASK_ZERO : D3D12_DEPTH_WRITE_MASK_ALL;
            p.DepthStencilState.DepthFunc = mode == "bad-depth-func" ? D3D12_COMPARISON_FUNC_GREATER :
                                           frame == 3 ? D3D12_COMPARISON_FUNC_LESS_EQUAL : D3D12_COMPARISON_FUNC_LESS;
            p.DepthStencilState.StencilEnable = mode == "bad-stencil";
            ID3D12PipelineState *out = nullptr;
            const auto result = ID3D12Device_CreateGraphicsPipelineState(d, &p, IID_ID3D12PipelineState,
                                                                        reinterpret_cast<void **>(&out));
            if (mode == "bad-depth-format" || mode == "bad-depth-func" || mode == "bad-stencil") {
                require(FAILED(result) && !out, "unsupported depth PSO accepted"); rejected_without_work(d, prefix); return;
            }
            hr(result, "CreateGraphicsPipelineState"); pipelines[layer].reset(out);
        }
        const unsigned size = frame % 2 ? 4 : 2, first = first_indices[frame], ib_offset = 64 * (frame + 1);
        const auto guard = static_cast<unsigned char>(0xa1 + frame * 13);
        D3D12_RANGE empty{0, 0}, full{0, bytes}, all_indices{0, index_bytes}; void *mapped = nullptr;
        hr(ID3D12Resource_Map(guard_upload.get(), 0, &empty, &mapped), "Map guards");
        std::memset(mapped, guard, bytes); ID3D12Resource_Unmap(guard_upload.get(), 0, &full);
        ID3D12GraphicsCommandList_CopyBufferRegion(l, readback.get(), 0, guard_upload.get(), 0, bytes);
        hr(ID3D12Resource_Map(index_upload.get(), 0, &empty, &mapped), "Map indices");
        auto *index_data = static_cast<unsigned char *>(mapped); std::memset(index_data, 0xfc, index_bytes);
        const std::array<unsigned, 6> pattern = frame % 2 ? std::array<unsigned, 6>{0, 1, 2, 0, 2, 3} :
                                                          std::array<unsigned, 6>{2, 0, 1, 2, 3, 0};
        for (unsigned layer = 0; layer < 2; ++layer) for (unsigned i = 0; i < 6; ++i) {
            const uint32_t value = raw_bias[frame] + (mode == "wrong-indices" && !layer ? 0 : pattern[i]);
            const uint16_t small = static_cast<uint16_t>(value);
            auto *dest = index_data + ib_offset + layer * 512 + (first + i) * size;
            if (size == 2) std::memcpy(dest, &small, 2); else std::memcpy(dest, &value, 4);
        }
        if (mode != "mapped-index") ID3D12Resource_Unmap(index_upload.get(), 0, &all_indices);
        const bool direct_upload = frame == 5 || mode == "mapped-index";
        if (!direct_upload) {
            if (frame) transition(l, indices.get(), D3D12_RESOURCE_STATE_INDEX_BUFFER, D3D12_RESOURCE_STATE_COPY_DEST);
            ID3D12GraphicsCommandList_CopyBufferRegion(l, indices.get(), 0, index_upload.get(), 0, index_bytes);
            if (mode != "bad-index-state") transition(l, indices.get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_INDEX_BUFFER);
        }
        transition(l, target.get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        const float clear[4]{0, 0, 0, 1}; ID3D12GraphicsCommandList_ClearRenderTargetView(l, rt, clear, 0, nullptr);
        for (unsigned i = 0; i < 2; ++i) {
            if (!frame && mode != "bad-depth-state") transition(l, depth[i].get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_DEPTH_WRITE);
            const float clear_z = mode == "bad-clear-value" ? std::numeric_limits<float>::quiet_NaN() :
                                  i == frame % 2 ? (frame == 5 ? .5f : 1.f) : 0.f;
            ID3D12GraphicsCommandList_ClearDepthStencilView(l, ds[i], mode == "bad-clear" ? D3D12_CLEAR_FLAG_STENCIL : D3D12_CLEAR_FLAG_DEPTH,
                                                            clear_z, 0, 0, nullptr);
        }
        ID3D12GraphicsCommandList_SetGraphicsRootSignature(l, r);
        ID3D12GraphicsCommandList_IASetPrimitiveTopology(l, D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        const D3D12_VIEWPORT vp{0, 0, float(width), float(height), 0, 1}; const D3D12_RECT sc{0, 0, width, height};
        ID3D12GraphicsCommandList_RSSetViewports(l, 1, &vp); ID3D12GraphicsCommandList_RSSetScissorRects(l, 1, &sc);
        const unsigned selected_depth = (frame % 2) ^ unsigned(mode == "wrong-depth");
        ID3D12GraphicsCommandList_OMSetRenderTargets(l, 1, &rt, TRUE, mode == "missing-depth" ? nullptr : &ds[selected_depth]);
        for (unsigned draw = 0; draw < 2; ++draw) {
            const unsigned layer = frame == 1 ? 1 - draw : draw;
            ID3D12GraphicsCommandList_SetPipelineState(l, pipelines[layer].get());
            D3D12_INDEX_BUFFER_VIEW view{};
            view.BufferLocation = ID3D12Resource_GetGPUVirtualAddress(direct_upload ? index_upload.get() : indices.get()) + ib_offset + layer * 512;
            view.SizeInBytes = (first + 6) * size; view.Format = size == 2 ? DXGI_FORMAT_R16_UINT : DXGI_FORMAT_R32_UINT;
            if (mode == "bad-index-format") view.Format = DXGI_FORMAT_R8_UINT;
            if (mode == "bad-index-align") ++view.BufferLocation;
            if (mode == "bad-index-address") view.BufferLocation = 0x1000;
            if (mode == "bad-index-view-range") view.SizeInBytes = index_bytes;
            if (mode != "missing-index") ID3D12GraphicsCommandList_IASetIndexBuffer(l, &view);
            if (mode == "unbound-index") ID3D12GraphicsCommandList_IASetIndexBuffer(l, nullptr);
            const int base_vertex = static_cast<int>(layer * 4) - static_cast<int>(raw_bias[frame]) + (mode == "wrong-base" ? 16 : 0);
            if (mode != "no-draw") ID3D12GraphicsCommandList_DrawIndexedInstanced(l, 6, 1,
                mode == "bad-index-draw-range" ? first + 1 : first, base_vertex, 0);
        }
        transition(l, target.get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION src{}, dst{};
        src.pResource = target.get(); src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource = readback.get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dst.PlacedFootprint.Offset = offset; dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, width, height, 1, pitch};
        ID3D12GraphicsCommandList_CopyTextureRegion(l, &dst, 0, 0, 0, &src, nullptr);
        const bool bad_state = mode == "bad-index-state" || mode == "bad-depth-state" || mode == "mapped-index";
        const bool rejected = mode == "missing-index" || mode == "unbound-index" || mode == "missing-depth" ||
            (mode.rfind("bad-", 0) == 0 && !bad_state);
        const auto closed = ID3D12GraphicsCommandList_Close(l);
        if (rejected) { require(FAILED(closed), "invalid recorded command accepted"); rejected_without_work(d, prefix); return; }
        hr(closed, "Close");
        auto *base = reinterpret_cast<ID3D12CommandList *>(l); ID3D12CommandQueue_ExecuteCommandLists(q, 1, &base);
        if (bad_state) {
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
            const auto expected = reference(frame, x, y, "depth"), actual = reference(frame, x, y, mode);
            mismatch += std::memcmp(data + offset + y * pitch + x * 4, expected.data(), 4) != 0;
            actual_mismatch += std::memcmp(data + offset + y * pitch + x * 4, actual.data(), 4) != 0;
        }
        ID3D12Resource_Unmap(readback.get(), 0, &empty);
        printf("frame%u_mismatched_pixels=%u\nframe%u_actual_mismatches=%u\nframe%u_checked_pixels=%u\n"
               "frame%u_guard_mismatches=%u\nframe%u_fence=%u\nframe%u_index_size=%u\nframe%u_index_offset=%u\n"
               "frame%u_first_index=%u\nframe%u_base_vertex_near=%d\nframe%u_depth_slot=%u\n",
               frame, mismatch, frame, actual_mismatch, frame, width * height, frame, guards, frame, frame + 1,
               frame, size, frame, ib_offset, frame, first, frame, -static_cast<int>(raw_bias[frame]) + (mode == "wrong-base" ? 16 : 0),
               frame, selected_depth * 2 + 1);
        require(!guards && !actual_mismatch, "GPU image/guards differ from reference"); all_mismatches += mismatch;
    }
    snapshot(prefix, "after-readback"); Ndx12Stats s{}; Ndx12GraphicsStats g{};
    hr(Ndx12GetStats(d, &s), "GetStats"); hr(Ndx12GetGraphicsStats(d, &g), "GetGraphicsStats");
    require(!s.context_reset_status && s.submissions == frames && s.copies == frames * 2 - 1 && !s.dispatches && s.shader_compiles == frames * 4 &&
            g.draws == (mode == "no-draw" ? 0u : frames * 2) && g.clears == frames * 3 && g.texture_copies == frames, "execution counters/reset");
    require(mode == "depth" ? !all_mismatches : all_mismatches > 0, "negative control did not detect corruption");
    printf("context_reset_status=%u\ndraws=%llu\ntexture_copies=%llu\nshader_compiles=%llu\n",
           s.context_reset_status, (unsigned long long)g.draws, (unsigned long long)g.texture_copies, (unsigned long long)s.shader_compiles);
    puts(mode == "depth" ? "result=PASS" : "result=EXPECTED_RESULT_MISMATCH");
}
}
int main(int argc, char **argv) {
    int result = 0;
    try { require(argc == 4, "usage: ndx12-m3-depth mode fixtures prefix"); exercise(argv[1], argv[2], argv[3]); evidence.finish(); }
    catch (const std::exception &e) { std::fprintf(stderr, "FAIL=%s\n", e.what()); result = 1; }
    printf("live_objects_after_release=%llu\n", (unsigned long long)Ndx12LiveObjects());
    return Ndx12LiveObjects() ? 1 : result;
}
